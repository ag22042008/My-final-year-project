# Architecture

## Overview
A Python CLI that (1) extracts a structured profile from a PDF resume,
(2) researches real interview questions using Claude's web search tool, and
(3) runs an adaptive interview loop that grades answers and adjusts difficulty.

**Core principle:** the model does language work only. Code verifies model
output, picks questions, and controls difficulty.

---

## File Layout
```
project/
  backend/
    app.py              # FastAPI app: routes only, no business logic
    agents.py           # Core logic moved here (Tavily search + Groq calls + guardrails)
    prompts/
      extractor.md      # System prompt for extraction
      researcher.md     # Updated: LLM receives search results as context
      interviewer.md    # System prompt for interviewer
    tests/
      test_guardrails.py  # Guardrail tests (mocked, no API calls)
    requirements.txt    # Backend dependencies
  frontend/
    app.py              # Streamlit UI
    api_client.py       # HTTP client connecting to FastAPI backend
    requirements.txt    # Frontend dependencies
  docs/
    ARCHITECTURE.md     # This file
    CHANGES.md          # Refactoring logs
  .env.example          # Environment variables template
  README.md             # How to run backend and frontend
```

---

## Data Contracts

### Profile (Extractor → code)
```json
{
  "name": "string",
  "role": "string | null",
  "years_of_experience": "int | null",
  "years_evidence": "string | null",
  "skills": [
    { "name": "string", "category": "string" }
  ],
  "technologies": [
    { "name": "string", "category": "string" }
  ]
}
```

### Question (Researcher → code)
```json
{
  "question": "string",
  "difficulty": "int (1-5)",
  "skill": "string",
  "source_url": "string",
  "source_title": "string"
}
```

### Evaluation (Interviewer → code)
```json
{
  "correctness": "int (0-4)",
  "depth": "int (0-3)",
  "clarity": "int (0-3)",
  "feedback": "string",
  "model_answer": "string"
}
```

---

## Adaptive Rules (implemented in code, NOT in prompts)

### Starting Level
```
level = clamp(years_of_experience, 1, 5)
if years_of_experience is None → level = 1
```

### Question Selection (`next_question`)
- Pick the question whose `difficulty` is closest to the current `level`.
- Break ties by pool order (first match in the list wins).
- Skip already-asked questions.

### Score Computation (`compute_score`)
```
score = clamp(correctness, 0, 4) + clamp(depth, 0, 3) + clamp(clarity, 0, 3)
```
Total range: 0–10. Computed in code **after** clamping sub-scores.

### Level Adjustment (`adjust_level`)
```
score >= 7  →  level += 1
score <= 4  →  level -= 1
5 <= score <= 6  →  level unchanged
level always bounded [1, 5]
```

### Empty Answers
An empty or whitespace-only answer scores 0 across all sub-scores
**without** calling the model.

---

## Guardrail Map

| # | Guardrail | Where enforced | What happens on violation |
|---|-----------|----------------|--------------------------|
| G1 | Extracted skill/technology name must appear in resume text | `validate_profile()` in `agents.py` | Item silently dropped |
| G2 | Extracted role must appear in resume text | `validate_profile()` | Role set to `None` |
| G3 | `years_evidence` must appear in resume text | `validate_profile()` | `years_of_experience` and `years_evidence` both set to `None` |
| G4 | No `years_evidence` provided at all | `validate_profile()` | `years_of_experience` set to `None` |
| G5 | Question `source_url` must be in retrieved URLs | `validate_questions()` | Question dropped |
| G6 | Question `difficulty` must be integer 1-5 | `validate_questions()` | Question dropped |
| G7 | No duplicate questions (by text, case-insensitive) | `validate_questions()` | Duplicate dropped |
| G8 | No valid questions survive filtering | `validate_questions()` | `ValueError` raised |
| G9 | Sub-scores out of valid range | `compute_score()`, `evaluate_answer()` | Clamped to valid range |
| G10 | Empty/whitespace answer | `evaluate_answer()` | Score 0, no API call |
| G11 | Level exceeds bounds after adjustment | `adjust_level()` | Clamped to [1, 5] |

---

## API Details

| Setting | Value | Source |
|---------|-------|--------|
| Model | `openai/gpt-oss-120b` | [docs.groq.com/models](https://console.groq.com/docs/models) |
| Temperature | `0` | Fixed in `ask()` |
| Web search tool | `Tavily Search API` | [docs.tavily.com](https://docs.tavily.com/docs/welcome) |

### Search Flow (Tavily + Groq)
The application now separates finding content from extracting questions:
1. **Search**: `tavily_search()` queries the Tavily API and retrieves a structured list of internet results containing `url`, `title`, and `content`.
2. **Contextualize**: These results are formatted into `<search_results>` XML-like blocks.
3. **Extract**: Groq LLM `openai/gpt-oss-120b` processes the results as context to extract structured mock questions, strictly matching the source URLs.

---

## Tag Wrapping
All user-supplied data is wrapped in XML-style tags and treated as data:
- Resume text: `<resume>...</resume>`
- Candidate answer: `<answer>...</answer>`
- Question: `<question>...</question>`
- Skill context: `<skill>...</skill>`
- Profile: `<profile>...</profile>`
