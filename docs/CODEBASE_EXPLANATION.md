# Codebase Explanation

This document provides a comprehensive overview of the Interview Prep Web App codebase. It breaks down the directory structure, explains the role of every file, and details the reasoning behind the underlying technology choices.

## High-Level Architecture Overview

This project is built around a modern decoupled client-server architecture:
- **Backend**: A REST API powered by **FastAPI** resolving core logic, validations, and integrations with AI models (Groq LLM) and search engines (Tavily).
- **Frontend**: A highly interactive UI built with **Streamlit**, functioning purely as a thin client for presentation and state management.

By enforcing a strict decoupling layer between UI and core AI logic, the system maintains strong security boundaries (no exposed API keys on the frontend), improves scalability, and makes unit testing significantly easier.

---

## Technology Stack and Justifications

### 1. Python (Core Language)
- **Why**: Python has an unmatched ecosystem for AI/ML tooling, SDKs (like `groq`, `tavily-python`), and straightforward backend web frameworks.

### 2. FastAPI (Backend Web Framework)
- **Why**: FastAPI is extremely performant on Python and natively supports asynchronous interactions (`async`/`await`). Since connecting to LLMs and search engines (Groq/Tavily) heavily relies on waiting for I/O bounds, an asynchronous framework is crucial. It also provides automatic Swagger/OpenAPI documentation and type checking via Pydantic.

### 3. Streamlit (Frontend Framework)
- **Why**: Streamlit natively bridges Pythonic logic with interactive web interface elements (buttons, chats, text inputs). It guarantees a fast rapid-prototyping cycle while offering an immediate, responsive UI without needing a separate React/Vue stack.

### 4. Groq + Llama 3.3 (Large Language Model)
- **Why**: Groq's dedicated LPU architecture offers ultra-low latency inference for open-source models like `llama-3.3-70b-versatile`. This provides a conversational and real-time feel to the interview process, which is necessary for the AI interviewer experience. 

### 5. Tavily (Web Search API)
- **Why**: LLMs are restricted by their training dates and tend to hallucinate factual queries. Tavily Search ensures the interview questions asked are authentic and fact-checked against real, modern live-web resources, reducing hallucination entirely.

---

## Directory & File Breakdown

### Root Directory
Files that apply to the whole repository and its ecosystem.

- **`README.md`** 
  - *Purpose*: The starting point for developers. Contains instructions for setting up the virtual environments, putting in `.env` variables, and running both the frontend and backend servers.
- **`AGENTS.md`**
  - *Purpose*: A specialized rulebook guiding autonomous agents (like me) interacting with this repo. Ensures consistency, protects against hallucination, enforces standard rules without breaking modularity.
- **`.env.example`**
  - *Purpose*: A template showing the required environment variables (like `GROQ_API_KEY` and `TAVILY_API_KEY`) ensuring no sensitive data is checked into source control.

### `backend/` 
Responsible for orchestration, prompt generation, guardrails, and third-party API calling.

- **`backend/app.py`**
  - *Purpose*: The main entry point for the FastAPI server. It defines API endpoints (`/upload`, `/research`, `/evaluate`), handling HTTP request/response lifecycles, and acting as the orchestrator for incoming requests rather than housing the raw business logic.
- **`backend/agents.py`**
  - *Purpose*: The core implementation file acting as the "brain". It interacts with the `groq` SDK for model inferences, `tavily-python` for fetching questions, and handles the most critical "Code-level Guardrails" (e.g., adaptive leveling, ensuring skills match the resume). 
- **`backend/requirements.txt`**
  - *Purpose*: Defines the backend-specific pip dependencies (e.g., `fastapi`, `uvicorn`, `groq`, `tavily-python`, `pypdf`).

#### `backend/prompts/`
Contains markdown files used to inject behavior instructions directly into the LLMs.
- **`extractor.md`**: Instructions for extracting a structured skill set/profile from a raw parsed PDF string.
- **`researcher.md`**: Instructions directing the LLM to process Tavily search results into accurately formatted, fact-based mock questions.
- **`interviewer.md`**: Defines the "personality" and evaluation criteria of the synthetic interviewer, driving feedback out of candidate answers.

#### `backend/tests/`
- **`test_guardrails.py`**: Ensures all non-LLM logic in `agents.py` behaves correctly via mocked unit tests without incurring API costs. (e.g., ensuring scoring boundaries like clamping values from 0-4).

### `frontend/`
Focuses entirely on rendering the user interface and bridging the interactions with the backend API.

- **`frontend/app.py`**
  - *Purpose*: The main Streamlit script. Manages user sessions, renders layouts (chatboxes, file uploaders), caches API responses, and constructs the visual flow of the interview. 
- **`frontend/api_client.py`**
  - *Purpose*: Function wrappers utilizing the `requests` library. Provides clean Python functions for `app.py` to communicate dynamically with the REST endpoints from `backend/app.py`.
- **`frontend/requirements.txt`**
  - *Purpose*: Limits frontend specific requirements to UI/HTTP concerns (`streamlit`, `requests`).

### `docs/`
Location for in-depth, living architectural documentation.

- **`docs/ARCHITECTURE.md`**
  - *Purpose*: The foundational blueprint. Defines JSON data contracts for API routing, adaptive grading formulas, and outlines the entire guardrail map across the backend pipeline.
- **`docs/CHANGES.md`**
  - *Purpose*: Historic changelog capturing major refactoring events, pivotal bug fixes, and systemic design decisions. 
  
---

## Summary of Data Flow

1. **Upload Phase**: Frontend sends a resume via UI. Backend reads the PDF, and Groq `extractor` parses into structured details. Back to UI.
2. **Research Phase**: UI requests questions. Backend uses `tavily-python` to scrape the web, then Groq `researcher` creates structured interview queries matching the candidate. It returns matching queries to the UI.
3. **Interview Phase**: Candidate answers over Streamlit text/audio. Answer hits backend to be scored by Groq `interviewer`. Backend modifies difficulty for next loop, returns the adaptive assessment. UI prints feedback.
