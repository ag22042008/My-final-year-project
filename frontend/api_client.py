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

# Fallback to localhost if not provided in .env
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

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


def check_health():
    """Verify backend is reachable.
    
    Returns True if healthy, False if down.
    """
    try:
        res = requests.get(f"{BACKEND_URL}/api/health", timeout=5)
        return res.status_code == 200
    except requests.exceptions.RequestException as e:
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
    try:
        files = {"file": (filename, file_bytes, "application/pdf")}
        res = requests.post(f"{BACKEND_URL}/api/upload-resume", files=files, timeout=60)
        return _handle_response(res)
    except requests.exceptions.ConnectionError:
        raise BackendError("Could not connect to backend. Is uvicorn running?")
    except requests.exceptions.RequestException as e:
        raise BackendError(f"Network error during upload: {str(e)}")


def transcribe_audio(file_bytes, filename):
    """Send recorded audio to backend for transcription.
    
    Args:
        file_bytes: Raw bytes of the audio.
        filename: Name of the audio file.
        
    Returns:
        dict: The TranscribeResponse dict containing 'text'.
    """
    try:
        files = {"file": (filename, file_bytes, "audio/wav")}
        res = requests.post(f"{BACKEND_URL}/api/transcribe", files=files, timeout=60)
        return _handle_response(res)
    except requests.exceptions.ConnectionError:
        raise BackendError("Could not connect to backend.")
    except requests.exceptions.RequestException as e:
        raise BackendError(f"Network error during transcription: {str(e)}")


def research_questions(profile):
    """Fetch interview questions based on the candidate's profile.
    
    Args:
        profile (dict): The ProfileResponse dict.
        
    Returns:
        list: List of QuestionItem dicts.
    """
    try:
        res = requests.post(f"{BACKEND_URL}/api/research", json=profile, timeout=120)
        return _handle_response(res)
    except requests.exceptions.ConnectionError:
        raise BackendError("Could not connect to backend.")
    except requests.exceptions.RequestException as e:
        raise BackendError(f"Network error during research: {str(e)}")


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
        "profile": profile
    }
    try:
        res = requests.post(f"{BACKEND_URL}/api/evaluate", json=payload, timeout=60)
        return _handle_response(res)
    except requests.exceptions.ConnectionError:
        raise BackendError("Could not connect to backend.")
    except requests.exceptions.RequestException as e:
        raise BackendError(f"Network error during evaluation: {str(e)}")
