"""FastAPI backend for the Interview Prep application.

WHY THIS FILE EXISTS:
This is the HTTP API layer — it maps REST endpoints to the business logic
in agents.py. It contains NO business logic itself; it only:
  1. Validates and parses incoming HTTP requests.
  2. Calls the appropriate function in agents.py.
  3. Returns the result as JSON or an appropriate HTTP error.

WHY FastAPI over Flask/Django:
  - Automatic request validation via Pydantic models.
  - Built-in OpenAPI docs at /docs (useful for debugging).
  - Async-capable, though we use sync handlers here because Groq and
    Tavily SDKs are synchronous.
  - Lightweight — no ORM, template engine, or admin panel needed.

ERROR STRATEGY:
  - 400: Bad input (missing file, empty profile, etc.).
  - 502: Upstream failure (Groq or Tavily API error).
  - 500: Unexpected internal error.
  This mapping lets the frontend distinguish user mistakes from server
  problems and show appropriate messages.
"""

import os
import tempfile
import traceback

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# WHY relative import is NOT used: backend/ is not a package with __init__.py.
# We import agents as a module from the same directory. When running with
# `uvicorn backend.app:app` from the project root, Python's path includes
# the project root, so `backend.agents` resolves correctly.
import agents

# ---------------------------------------------------------------------------
# Pydantic models for request/response validation
# ---------------------------------------------------------------------------
# WHY Pydantic models: FastAPI uses them for automatic request parsing,
# validation, and OpenAPI schema generation. They also serve as documentation
# for the API contract.

class SkillItem(BaseModel):
    """A single skill or technology extracted from a resume."""
    name: str
    category: str


class ProfileResponse(BaseModel):
    """The structured profile extracted from a resume.
    Matches the Profile data contract in ARCHITECTURE.md."""
    name: str = ""
    role: str | None = None
    years_of_experience: int | None = None
    years_evidence: str | None = None
    skills: list[SkillItem] = Field(default_factory=list)
    technologies: list[SkillItem] = Field(default_factory=list)


class ResearchRequest(BaseModel):
    """Request body for the /api/research endpoint.
    Contains the profile to research questions for."""
    name: str = ""
    role: str | None = None
    years_of_experience: int | None = None
    years_evidence: str | None = None
    skills: list[SkillItem] = Field(default_factory=list)
    technologies: list[SkillItem] = Field(default_factory=list)


class QuestionItem(BaseModel):
    """A single interview question from the research phase."""
    question: str
    difficulty: int
    skill: str
    source_url: str
    source_title: str = ""


class EvaluateRequest(BaseModel):
    """Request body for the /api/evaluate endpoint."""
    question: QuestionItem
    answer: str
    # Profile is included so the evaluator has candidate context,
    # though currently the interviewer prompt doesn't use it.
    profile: ResearchRequest


class EvaluationResponse(BaseModel):
    """The evaluation result for a candidate's answer."""
    correctness: int
    depth: int
    clarity: int
    score: int
    feedback: str
    model_answer: str = ""


class TranscribeResponse(BaseModel):
    """The transcribed text from the voice input."""
    text: str


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# WHY metadata: FastAPI uses these for the auto-generated /docs page.
app = FastAPI(
    title="Interview Prep API",
    description="Extracts profiles from resumes, researches interview questions via Tavily, and evaluates answers using Groq LLM.",
    version="1.0.0",
)

# WHY CORS: The Streamlit frontend runs on a different port (typically 8501)
# than the backend (8000). Without CORS, the browser blocks cross-origin
# requests. We allow all origins in development; in production you'd
# restrict this to the Streamlit URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to the Streamlit URL.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    """Health check endpoint.

    WHY: Lets the frontend verify the backend is running before making
    real requests. Also useful for monitoring/load-balancer health probes.
    """
    return {"status": "ok"}


@app.post("/api/upload-resume", response_model=ProfileResponse)
def upload_resume(file: UploadFile = File(...)):
    """Upload a PDF resume and extract a structured profile.

    WHY UploadFile + temp file approach:
      - UploadFile gives us streaming access to the uploaded bytes.
      - We write to a temp file because pypdf's PdfReader expects a file
        path, not a file-like object (it could accept one, but the path
        API is simpler and avoids seek/tell issues).
      - The temp file is deleted in the finally block to avoid leaking
        disk space, especially important on free-tier hosting.

    Returns:
        ProfileResponse: The validated profile JSON.

    Raises:
        400: If the file is not a PDF or no text can be extracted.
        502: If the Groq API call fails.
    """
    # Validate file type before doing any work.
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    tmp_path = None
    try:
        # Write uploaded bytes to a temp file so pypdf can read it.
        # WHY suffix=".pdf": Some PDF libraries check the extension.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name

        profile = agents.extract_profile(tmp_path)
        return profile

    except ValueError as e:
        # ValueError from our code (e.g. "No text could be extracted").
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Groq API errors, network issues, etc.
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail=f"Failed to extract profile: {str(e)}",
        )
    finally:
        # Always clean up the temp file.
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/transcribe", response_model=TranscribeResponse)
def transcribe(file: UploadFile = File(...)):
    """Transcribe an uploaded audio clip into text.
    
    WHY UploadFile + temp file:
      - We need to pass a File object to the Groq SDK.
      - Saving it temporarily ensures we can read the binary payload reliably 
        and provide a filename/path to the transcription agent.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")
        
    tmp_path = None
    try:
        # Suffix must match audio types if Groq validates extensions, .wav is safe.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name
            
        text = agents.transcribe_audio(tmp_path)
        return TranscribeResponse(text=text)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail=f"Failed to transcribe audio: {str(e)}",
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/research", response_model=list[QuestionItem])
def research(req: ResearchRequest):
    """Research interview questions for a given profile.

    WHY profile as input (not just skills list):
      - The researcher needs the role to tailor search queries
        (e.g. "Python interview questions for data engineer").
      - Passing the full profile avoids a second data contract.

    Returns:
        List of validated QuestionItem objects.

    Raises:
        400: If no skills/technologies provided.
        502: If Tavily or Groq API calls fail.
    """
    # Convert Pydantic model to plain dict for agents.py.
    # WHY .model_dump(): agents.py expects plain dicts with "name" keys,
    # not Pydantic model instances.
    profile_dict = req.model_dump()

    try:
        questions = agents.research_questions(profile_dict)
        return questions

    except ValueError as e:
        # "No skills or technologies to research", "No valid questions", etc.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail=f"Failed to research questions: {str(e)}",
        )


@app.post("/api/evaluate", response_model=EvaluationResponse)
def evaluate(req: EvaluateRequest):
    """Evaluate a candidate's answer to an interview question.

    WHY question + answer + profile in one request:
      - The evaluator needs the question to know what's being asked.
      - The profile provides skill context for evaluation quality.
      - Bundling them avoids stateful session management on the backend.
        The backend stays stateless; all state lives in the frontend's
        session_state.

    Returns:
        EvaluationResponse with scores and feedback.

    Raises:
        502: If the Groq API call fails.
    """
    question_dict = req.question.model_dump()
    profile_dict = req.profile.model_dump()

    try:
        evaluation = agents.evaluate_answer(
            question_dict, req.answer, profile_dict
        )
        return evaluation

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail=f"Failed to evaluate answer: {str(e)}",
        )
