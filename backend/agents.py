"""Interview-prep agents: extract profile, research questions, evaluate answers.

WHY THIS FILE EXISTS:
This is the core business logic layer for the interview prep application.
It delegates all language work to the Groq LLM (llama-3.3-70b-versatile)
and all web searching to the Tavily Search API. Code here is responsible for:
  - Validating / sanitising model outputs (guardrails G1-G11)
  - Selecting questions and controlling difficulty (adaptive rules)
  - Orchestrating the search-then-extract pipeline for question research

DESIGN CHOICE — Tavily + Groq two-step pipeline:
  The old approach used Groq's built-in `browser_search` tool which was
  unreliable and coupled search + extraction in one model call. The new
  approach separates concerns:
    1. Tavily searches the web (returns structured {url, title, content}).
    2. Groq receives those search snippets as context and extracts
       structured interview questions from them.
  This is more testable, more reliable, and lets us verify source_urls
  against the exact set Tavily returned (guardrail G5).
"""

import json
import os
import re

# groq — free-tier LLM inference (llama-3.3-70b-versatile).
# We use the Groq SDK rather than raw HTTP because it handles retries,
# streaming, and auth header injection automatically.
from groq import Groq

# pypdf — pure-Python PDF text extraction. Chosen over pdfminer/pdfplumber
# because it is lightweight, has no C dependencies, and handles the common
# case (text-based resumes) well enough.
from pypdf import PdfReader

# python-dotenv — loads .env into os.environ so API keys are never hard-coded.
from dotenv import load_dotenv, find_dotenv

# tavily-python — dedicated web search API. Replaces Groq's browser_search.
# Free tier gives 1,000 credits/month which is more than enough for this app.
from tavily import TavilyClient

load_dotenv(find_dotenv())

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The single LLM model used for all language tasks (extraction, question
# formatting, answer evaluation). We do NOT use a separate search model
# anymore — Tavily handles search externally.
MODEL = "openai/gpt-oss-120b"

# Maximum search results per topic from Tavily. 5 gives a good balance
# between coverage and token cost when we feed results to the LLM.
TAVILY_MAX_RESULTS = 5


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _groq_client():
    """Return a Groq client.

    WHY: Lazy construction so the module can be imported without a key
    (e.g. during testing when ask() is mocked). The Groq SDK reads
    GROQ_API_KEY from the environment automatically.
    """
    return Groq()


def _tavily_client():
    """Return a TavilyClient.

    WHY: Same lazy-construction rationale as _groq_client(). The key is
    read from TAVILY_API_KEY env var. We pass it explicitly because the
    Tavily SDK requires it as a constructor argument.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise ValueError(
            "TAVILY_API_KEY is not set. Get a free key at https://app.tavily.com"
        )
    return TavilyClient(api_key=api_key)


def ask(system_prompt, user_content):
    """Send a chat-completion request to Groq and return the response.

    WHY temperature=0: Reproducibility. For extraction and evaluation we want
    deterministic outputs, not creative variation.

    WHY no tools parameter anymore: Tavily handles search externally, so we
    no longer need to pass tool definitions to the LLM.

    Args:
        system_prompt: The system message content.
        user_content: The user message content.

    Returns:
        The Groq ChatCompletion response object.
    """
    client = _groq_client()
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response


def load_prompt(name):
    """Load a prompt file from the prompts/ directory relative to this file.

    WHY relative to __file__: So it works regardless of the working directory
    (e.g. when uvicorn is started from the project root vs backend/).
    """
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "prompts", f"{name}.md"
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_json(text):
    """Extract JSON from model output text.

    WHY multiple strategies: LLMs are inconsistent about wrapping JSON in
    markdown code fences, adding preamble text, etc. We try three approaches
    in order of specificity:
      1. Look for ```json ... ``` code blocks (most explicit).
      2. Find the first { ... } or [ ... ] span (handles bare JSON with
         surrounding commentary).
      3. Parse the whole string (last resort for clean output).

    Args:
        text: Raw model output string.

    Returns:
        Parsed Python object (dict or list).

    Raises:
        ValueError: If text is empty.
        json.JSONDecodeError: If no valid JSON can be found.
    """
    if not text:
        raise ValueError("Empty text, cannot extract JSON")

    # Strategy 1: JSON inside a fenced code block.
    match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    # Strategy 2: First balanced { ... } or [ ... ] span.
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start == -1:
            continue
        end = text.rfind(end_char)
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue

    # Strategy 3: Try the whole string.
    return json.loads(text)


def read_pdf(path):
    """Extract text from a PDF file.

    WHY we raise on empty: A resume with no extractable text is useless and
    indicates either a scanned-image PDF (which we don't support) or a
    corrupt file. Failing early with a clear message is better than passing
    empty text to the LLM and getting garbage back.
    """
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    if not text.strip():
        raise ValueError(f"No text could be extracted from {path}")
    return text


# ---------------------------------------------------------------------------
# Extractor — resume PDF → structured profile
# ---------------------------------------------------------------------------

def extract_profile(pdf_path):
    """Extract a structured profile from a PDF resume.

    Pipeline: read PDF → send to Groq with extractor prompt → parse JSON
    → validate against resume text (guardrails G1-G4).

    Returns:
        A validated profile dict matching the Profile data contract.
    """
    resume_text = read_pdf(pdf_path)
    prompt = load_prompt("extractor")

    # Wrap resume text in XML tags so the LLM treats it as data, not
    # instructions (defense against prompt injection in resumes).
    user_content = f"<resume>\n{resume_text}\n</resume>"
    response = ask(prompt, user_content)

    raw = response.choices[0].message.content
    profile = extract_json(raw)

    # Apply code-level guardrails: every extracted item must have evidence
    # in the actual resume text.
    profile = validate_profile(profile, resume_text)
    return profile


def transcribe_audio(audio_path):
    """Transcribe an audio file using Groq's Whisper API.
    
    WHY THIS FUNCTION:
    Supporting voice recording replaces the need to type answers, making
    the mock interview feel much more realistic. We use whisper-large-v3-turbo 
    because it's optimized for incredibly fast and cheap inference.
    
    Args:
        audio_path: Path to the temporary audio file.
        
    Returns:
        The transcribed text as a string.
    """
    client = _groq_client()
    with open(audio_path, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(os.path.basename(audio_path), file.read()),
            model="whisper-large-v3-turbo",
        )
    return transcription.text


def validate_profile(profile, resume_text):
    """Validate extracted profile against resume text.

    Guardrails enforced here:
      G1: Skills/technologies whose name is not in the resume are dropped.
      G2: Role is set to None if not in resume text.
      G3: years_evidence not in resume → years_of_experience = None.
      G4: No years_evidence provided → years_of_experience = None.

    WHY silent drops instead of errors: A partially-valid profile is still
    useful. If the LLM hallucinates one skill but gets nine right, we want
    those nine. The architecture doc specifies "silently dropped".
    """
    text_lower = resume_text.lower()

    # G1: Filter skills — name must appear in resume text.
    if "skills" in profile:
        profile["skills"] = [
            s for s in profile["skills"]
            if s.get("name", "").lower() in text_lower
        ]

    # G1: Filter technologies — same rule.
    if "technologies" in profile:
        profile["technologies"] = [
            t for t in profile["technologies"]
            if t.get("name", "").lower() in text_lower
        ]

    # G2: Validate role — must appear verbatim (case-insensitive).
    if profile.get("role"):
        if profile["role"].lower() not in text_lower:
            profile["role"] = None

    # G3 & G4: Validate years_of_experience via years_evidence.
    evidence = profile.get("years_evidence")
    if evidence:
        # G3: Evidence text must actually appear in the resume.
        if evidence.lower() not in text_lower:
            profile["years_of_experience"] = None
            profile["years_evidence"] = None
    else:
        # G4: No evidence provided at all → years unknown.
        profile["years_of_experience"] = None

    return profile


# ---------------------------------------------------------------------------
# Researcher — profile → interview questions (Tavily search + Groq extract)
# ---------------------------------------------------------------------------

def tavily_search(query):
    """Search the web using Tavily and return structured results.

    WHY Tavily over Groq browser_search: Tavily returns structured results
    (url, title, content) that we can track for URL verification (G5).
    Groq's built-in search was opaque — we had to regex-scrape URLs from
    the model's prose, which was unreliable.

    Args:
        query: The search query string.

    Returns:
        A list of dicts, each with keys: url, title, content.
        Also returns the set of all URLs found (for guardrail G5).
    """
    client = _tavily_client()
    response = client.search(query=query, max_results=TAVILY_MAX_RESULTS)

    results = []
    urls = set()
    for item in response.get("results", []):
        results.append({
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "content": item.get("content", ""),
        })
        urls.add(item.get("url", ""))

    return results, urls


def research_questions(profile):
    """Find interview questions using Tavily search + Groq extraction.

    Pipeline:
      1. Build search queries from the profile's skills and technologies.
      2. Call Tavily for each topic to get web search results.
      3. Compile all search snippets into a context block.
      4. Send context to Groq with the researcher prompt to extract
         structured questions.
      5. Validate questions with guardrails G5-G8.

    WHY two-step (search then extract) instead of one LLM call:
      - Tavily gives us exact URLs we can verify (G5).
      - Groq doesn't need web access, reducing failure modes.
      - Each step is independently testable and mockable.

    Returns:
        A validated list of question dicts.
    """
    prompt = load_prompt("researcher")

    skills = [s["name"] for s in profile.get("skills", [])]
    technologies = [t["name"] for t in profile.get("technologies", [])]
    all_topics = skills + technologies

    # Limit to top 5 topics to prevent OOM token constraints, excessive latency 
    # and connection timeouts. (An interview is 5 rounds anyway)
    all_topics = all_topics[:5]

    if not all_topics:
        raise ValueError("No skills or technologies to research")

    role = profile.get("role") or "software engineer"

    # Step 1 & 2: Search each topic via Tavily and accumulate results.
    all_search_results = []
    all_retrieved_urls = set()

    for topic in all_topics:
        query = f"{topic} interview questions for {role}"
        results, urls = tavily_search(query)
        all_search_results.extend(results)
        all_retrieved_urls.update(urls)

    if not all_search_results:
        raise ValueError("No search results found for any topic")

    # Step 3: Format search results as context for the LLM.
    # We include the URL, title, and a snippet of content for each result
    # so the LLM can attribute questions to their sources.
    search_context = _format_search_results(all_search_results)

    # Step 4: Ask Groq to extract structured questions from the context.
    user_content = (
        f"<profile>\n"
        f"Role: {role}\n"
        f"Topics: {', '.join(all_topics)}\n"
        f"</profile>\n\n"
        f"<search_results>\n{search_context}\n</search_results>"
    )

    response = ask(prompt, user_content)
    raw = response.choices[0].message.content

    # Parse the model's JSON output.
    questions = []
    if raw:
        try:
            parsed = extract_json(raw)
            if isinstance(parsed, list):
                questions = parsed
            elif isinstance(parsed, dict) and "questions" in parsed:
                questions = parsed["questions"]
        except (json.JSONDecodeError, ValueError):
            raise ValueError("Could not parse questions from model response")

    # Step 5: Validate questions with code-level guardrails.
    questions = validate_questions(questions, all_retrieved_urls)
    return questions


def _format_search_results(results):
    """Format Tavily search results into a text block for the LLM.

    WHY this format: Each result is numbered and clearly delimited with
    URL, title, and content. This makes it easy for the LLM to cite
    source_url accurately. We truncate content to 500 chars to keep the
    prompt within token limits for the free-tier model.
    """
    lines = []
    for i, r in enumerate(results, 1):
        # Truncate content to avoid exceeding token limits on free-tier.
        content = r["content"][:500] if r["content"] else "(no content)"
        lines.append(
            f"[{i}] URL: {r['url']}\n"
            f"    Title: {r['title']}\n"
            f"    Content: {content}\n"
        )
    return "\n".join(lines)


def validate_questions(questions, retrieved_urls):
    """Validate and filter questions.

    Guardrails enforced here:
      G5: Drop if source_url not in the URLs Tavily actually returned.
      G6: Drop if difficulty is not an integer in [1, 5].
      G7: Drop duplicate questions (by question text, case-insensitive).
      G8: Raise ValueError if no questions survive filtering.

    WHY we drop silently for G5-G7: Same rationale as profile validation.
    Partial results are useful; only an empty pool is fatal (G8).
    """
    seen = set()
    valid = []

    for q in questions:
        # G6: Drop if difficulty outside 1-5 or not an integer (coerce strings safely).
        try:
            diff = int(q.get("difficulty"))
            if diff < 1 or diff > 5:
                continue
            q["difficulty"] = diff
        except (ValueError, TypeError):
            continue

        # G5: Drop if source_url not in the set Tavily returned.
        url = q.get("source_url", "")
        if url not in retrieved_urls:
            continue

        # G7: Drop duplicate questions (case-insensitive match).
        q_text = q.get("question", "").strip().lower()
        if not q_text or q_text in seen:
            continue
        seen.add(q_text)

        valid.append(q)

    # G8: No valid questions → fatal error.
    if not valid:
        raise ValueError("No valid questions after filtering")

    return valid


# ---------------------------------------------------------------------------
# Interviewer — question + answer → evaluation (adaptive difficulty)
# ---------------------------------------------------------------------------

def clamp(value, low, high):
    """Clamp a value between low and high (inclusive).

    WHY a helper: Used in multiple places (starting_level, compute_score,
    adjust_level) and the intent is clearer than inline max(low, min(...)).
    """
    return max(low, min(value, high))


def starting_level(years):
    """Calculate starting difficulty level from years of experience.

    Rule: clamp(years, 1, 5). None or <=0 → 1.

    WHY clamp: Years map directly to difficulty levels (1-5 scale).
    Candidates with 0 or unknown experience start at level 1 (basic).
    Candidates with 10+ years still start at 5 (expert) — they can drop
    if they perform poorly.
    """
    if years is None:
        return 1
    return clamp(years, 1, 5)


def compute_score(evaluation):
    """Compute total score from sub-scores, clamping each to its valid range.

    WHY clamp before summing: The model might return out-of-range values
    despite instructions. Clamping here (guardrail G9) ensures the total
    is always in [0, 10] regardless of what the model outputs.

    correctness: 0-4, depth: 0-3, clarity: 0-3.  Total: 0-10.
    """
    correctness = clamp(evaluation.get("correctness", 0), 0, 4)
    depth = clamp(evaluation.get("depth", 0), 0, 3)
    clarity = clamp(evaluation.get("clarity", 0), 0, 3)
    return correctness + depth + clarity


def adjust_level(current_level, score):
    """Adjust difficulty level based on score.

    Rules (implemented in code, NOT in prompts):
      score >= 7 → level + 1 (doing well, increase challenge)
      score <= 4 → level - 1 (struggling, decrease challenge)
      5-6        → unchanged (adequate performance)
      Always bounded [1, 5] (guardrail G11).

    WHY these thresholds: 7/10 = 70% is a reasonable "doing well" bar.
    4/10 = 40% means significant gaps. The 5-6 dead zone prevents
    oscillation when performance is mediocre.
    """
    if score >= 7:
        new_level = current_level + 1
    elif score <= 4:
        new_level = current_level - 1
    else:
        new_level = current_level
    return clamp(new_level, 1, 5)


def next_question(questions, current_level, asked_indices=None):
    """Pick the question closest to current level.

    Ties broken by pool order (first in list wins). Skips already-asked
    indices.

    WHY pool order for ties: Deterministic and simple. No need for
    randomization — the question pool is already diverse across topics.

    Returns:
        (index, question_dict) or (None, None) if exhausted.
    """
    if asked_indices is None:
        asked_indices = set()

    best_idx = None
    best_dist = float("inf")

    for i, q in enumerate(questions):
        if i in asked_indices:
            continue
        dist = abs(q["difficulty"] - current_level)
        if dist < best_dist:
            best_dist = dist
            best_idx = i

    if best_idx is None:
        return None, None

    return best_idx, questions[best_idx]


def evaluate_answer(question, answer, profile):
    """Evaluate a candidate's answer to an interview question.

    Guardrails:
      G10: Empty/whitespace answers score 0 without calling the model.
            This saves an API call and avoids confusing the model with
            empty input.
      G9:  Sub-scores are clamped to their valid ranges after parsing.

    WHY compute score in code: Never trust the model to sum correctly.
    The total score controls difficulty adjustment, so it must be exact.

    Returns:
        Dict with correctness, depth, clarity, score, feedback, model_answer.
    """
    # G10: Empty answer → immediate zero score, no API call.
    if not answer or not answer.strip():
        return {
            "correctness": 0,
            "depth": 0,
            "clarity": 0,
            "score": 0,
            "feedback": "No answer provided.",
            "model_answer": "",
        }

    prompt = load_prompt("interviewer")

    # Wrap inputs in XML tags to prevent prompt injection from user answers.
    user_content = (
        f"<question>\n{question['question']}\n</question>\n"
        f"<answer>\n{answer}\n</answer>\n"
        f"<skill>{question.get('skill', '')}</skill>"
    )

    response = ask(prompt, user_content)
    raw = response.choices[0].message.content
    evaluation = extract_json(raw)

    # G9: Clamp sub-scores to valid ranges (defense against model errors).
    evaluation["correctness"] = clamp(evaluation.get("correctness", 0), 0, 4)
    evaluation["depth"] = clamp(evaluation.get("depth", 0), 0, 3)
    evaluation["clarity"] = clamp(evaluation.get("clarity", 0), 0, 3)

    # Compute total score in code — never trust the model's arithmetic.
    evaluation["score"] = compute_score(evaluation)

    return evaluation
