"""API Client for the frontend to communicate with the FastAPI backend.

WHY THIS FILE EXISTS:
This encapsulates all HTTP communication. Following the strict separation
rule, the frontend must NEVER import from the backend directory. Instead,
it communicates entirely over REST. Centralizing these calls makes error
handling and environment config (like changing BACKEND_URL) easier.

WHY requests:
It's included in the standard library's common ecosystem and specified
in the dependencies. Streamlit is synchronous, so requests is perfect.
"""

import os
import requests

# Defaults to the deployed Render backend. For local development, set
# BACKEND_URL=http://localhost:8000 in your .env file.
# .strip() / .rstrip("/") guard against stray spaces or a trailing slash.
BACKEND_URL = os.environ.get(
    "BACKEND_URL", "https://ai-interview-assistant-pfud.onrender.com"
).strip().rstrip("/")

# Render's free tier sleeps after inactivity; the first request can take
# 30-60 seconds while the service wakes up.
COLD_START_MESSAGE = (
    "Could not connect to the backend. It may be starting up "
    "(this can take up to a minute on the free tier) - please try again shortly."
)


class BackendError(Exception):
    """Custom exception for backend errors to cleanly pass messages to UI.

    WHY: Instead of passing raw requests.exceptions.RequestException to the UI,
    we raise this with the exact error message we want the user to see,
    derived from the backend's HTTP status codes.
    """
    pass


def _handle_response(response):
    """Parse response or raise appropriate BackendError.

    WHY THIS APPROACH:
    We know the backend returns 400 for bad input, 502 for upstream failures
    (like Groq/Tavily), and 500 for generic server errors. Handling them here
    keeps the UI code clean and avoids repeated error-checking logic.
    """
    if response.status_code == 200:
        return response.json()

    try:
        data = response.json()
        detail = data.get("detail", f"Unknown error (HTTP {response.status_code})")
    except Exception:
        detail = f"Server returned HTTP {response.status_code} without JSON."

    # Standardize error message presentation based on status code
    if response.status_code == 400:
        raise BackendError(f"Input Error: {detail}")
    elif response.status_code == 502:
        raise BackendError(f"External API Error: {detail} (Check API keys)")
    elif response.status_code == 500:
        raise BackendError(f"Internal Server Error: {detail}")
    else:
        raise BackendError(f"Error: {detail}")


def _post(path, action, timeout, **kwargs):
    """POST to the backend with consistent error handling.

    WHY: Every endpoint needs the same three handlers (connection error,
    timeout, other network error). Keeping them in one place means the
    messages stay consistent and each public function stays short.

    Args:
        path: Endpoint path, e.g. "/api/research".
        action: Human-readable verb for messages, e.g. "research".
        timeout: Seconds to wait for a response.
        **kwargs: Passed through to requests.post (json=, files=, ...).
    """
    try:
        res = requests.post(f"{BACKEND_URL}{path}", timeout=timeout, **kwargs)
        return _handle_response(res)
    except requests.exceptions.ConnectionError:
        raise BackendError(COLD_START_MESSAGE)
    except requests.exceptions.Timeout:
        raise BackendError(
            f"The {action} request timed out after {timeout} seconds. "
            "The backend may be busy or waking up - please try again."
        )
    except requests.exceptions.RequestException as e:
        raise BackendError(f"Network error during {action}: {str(e)}")


def check_health():
    """Verify backend is reachable.

    Returns True if healthy, False if down.

    The long timeout allows for a Render free-tier cold start.
    """
    try:
        res = requests.get(f"{BACKEND_URL}/api/health", timeout=60)
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False


def upload_resume(file_bytes, filename):
    """Send PDF resume to backend for profile extraction.

    Args:
        file_bytes: Raw bytes of the PDF.
        filename: Name of the uploaded file.

    Returns:
        dict: The extracted Profile response.

    Raises:
        BackendError: If backend fails or unreachable.
    """
    files = {"file": (filename, file_bytes, "application/pdf")}
    return _post("/api/upload-resume", "resume upload", 60, files=files)


def transcribe_audio(file_bytes, filename):
    """Send recorded audio to backend for transcription.

    Args:
        file_bytes: Raw bytes of the audio.
        filename: Name of the audio file.

    Returns:
        dict: The TranscribeResponse dict containing 'text'.
    """
    files = {"file": (filename, file_bytes, "audio/wav")}
    return _post("/api/transcribe", "transcription", 60, files=files)


def research_questions(profile):
    """Fetch interview questions based on the candidate's profile.

    Args:
        profile (dict): The ProfileResponse dict.

    Returns:
        list: List of QuestionItem dicts.
    """
    return _post("/api/research", "research", 120, json=profile)


def evaluate_answer(question, answer, profile):
    """Send candidate's answer for evaluation.

    Args:
        question (dict): The current QuestionItem.
        answer (str): The candidate's typed answer.
        profile (dict): The ProfileResponse dict for context.

    Returns:
        dict: EvaluationResponse dict.
    """
    payload = {
        "question": question,
        "answer": answer,
        "profile": profile,
    }
    return _post("/api/evaluate", "evaluation", 60, json=payload)