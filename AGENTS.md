# AGENTS.md — Interview Prep project rules

These rules apply to every task in this repository. Follow them exactly. If a rule conflicts with a task request, stop and ask.

## 1. What this project is
A small Python CLI that (1) extracts skills/technologies/years from a PDF resume, (2) finds real interview questions with Claude's web search tool, and (3) grades typed answers and adapts question difficulty.
Priority order: **correct and simple > clever.** Do not over-engineer.

## 2. Source of truth (read before changing anything)
1. `docs/ARCHITECTURE.md` — data contracts, adaptive rules, guardrail map.
2. `prompts/*.md` — the system prompt for each agent.
3. `agents.py` — implementation. `main.py` — CLI.

If code and docs disagree, do not guess which is right. Report the mismatch, then fix both so they agree.

## 3. Hard rules
**Architecture**
- The model does language work only. Code verifies model output, picks questions, and controls difficulty. Never move difficulty or question-selection logic into a prompt.
- Keep the layout modular: `backend/` (FastAPI), `frontend/` (Streamlit), `docs/`. No new classes, frameworks, plugins, or abstraction layers unless the task explicitly requires them.
- No new dependencies. Runtime deps include `groq`, `tavily-python`, `pypdf`, `python-dotenv`, `fastapi`, `uvicorn[standard]`, `python-multipart`, `requests`, and `streamlit`. `pytest` is allowed as a dev-only dependency.

**Anti-hallucination (applies to you, the coding agent)**
- Never invent API names, parameters, model IDs, package versions, or tool type strings. Verify them against official documentation (docs.groq.com / docs.tavily.com) or the installed package before using them. If you cannot verify something, say so in your report.
- Do not change `MODEL` or any SDK call shape without checking the official docs and quoting the page you used.
- Never claim a test passed, or that code works, unless you ran it and saw the output. Say "not run" for anything you did not run.
- Never fabricate sample output, URLs, or resume data presented as real results. Test fixtures must be clearly labeled as fixtures.

**Prompt files**
- Preserve each prompt's structure: ROLE, INPUT, OUTPUT, EXECUTION CHECKLIST (ending with a VERIFY step), YOU MUST, YOU MUST NEVER.
- Any change to a prompt's output schema must be made in the same change in: the prompt, the parsing code in `agents.py`, `docs/ARCHITECTURE.md`, and `main.py` if it prints the field.
- Do not weaken a "YOU MUST NEVER" rule.

**Code-level guardrails (must keep working)**
- Extracted skills/technologies/role must appear in the resume text; years need matching evidence text.
- Every question's `source_url` must be in the URLs returned by the search tool.
- Score = correctness (0-4) + depth (0-3) + clarity (0-3), computed in code.
- Level: start by years of experience; +1 on score >= 7, -1 on score <= 4, bounded 1-5.
- All model calls use `temperature=0`. Resume text and candidate answers are wrapped in tags and treated as data.

**Safety**
- Never read, print, or commit `.env` or API keys. Never hard-code secrets.
- Do not make live Groq or Tavily API calls unless the task says so and both `GROQ_API_KEY` and `TAVILY_API_KEY` are set. Default to mocked tests.
- Do not run destructive commands (deleting files outside this repo, `git push --force`, etc.) without asking.

## 4. Code style
- Plain, readable Python 3.10+. Short functions, clear names, brief docstrings. No type-annotation or logging frameworks unless asked.
- Fail with a clear error message rather than silently continuing, except where the architecture doc says to drop unverifiable items.

## 5. Working method (for every task)
1. Read the files in section 2.
2. Write a short plan: files you will change, why, and how you will verify it. Wait for approval before large changes (more than 3 files, or any change to a prompt schema).
3. Make the smallest change that completes the task. Do not refactor unrelated code.
4. Verify by running: `python -m py_compile agents.py main.py` and, if tests exist, `pytest`.
5. Update `docs/ARCHITECTURE.md` if behavior or contracts changed.
6. Report using the format below.

## 6. When to stop and ask
- The task needs a new dependency, a new file outside the layout, or a change to the architecture principle.
- An official doc contradicts this repo's docs.
- A check fails and the fix is not obvious after one attempt.
- Requirements are ambiguous in a way that changes behavior.

## 7. Report format (end of every task)
- **Changed:** files and a one-line reason each.
- **Verified:** commands you ran and their actual results.
- **Not verified:** anything you did not or could not run (e.g. live API calls).
- **Open questions / risks:** mismatches, assumptions, or limits.
