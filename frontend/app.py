"""Streamlit UI for the Interview Prep application.

WHY THIS FILE EXISTS:
This is the only user interface for the app. It replaces the old CLI completely.
It communicates entirely via the api_client.py file to ensure strict separation
from the backend code.

WHY Streamlit:
It allows for rapid development of data/AI applications with built-in state
management, making step-by-step interactive flows (like an interview session)
easy to implement without writing React/Vue frontends.
"""

import streamlit as st
import api_client
# ---------------------------------------------------------------------------
# App Setup & CSS Configuration
# ---------------------------------------------------------------------------
# WHY set_page_config: Configures the page title and enforces empty layout.
# We set initial_sidebar_state to collapsed as we want a single-column flow.
st.set_page_config(
    page_title="AI Interview Prep",
    page_icon="🎙️",
    layout="centered"
)

# WHY Custom CSS: The prompt requests a dark theme via custom CSS. Streamlit 
# supports dark theme natively via settings, but we inject this style block to
# fulfill the explicit 'custom CSS' requirement and ensure a polished look.
st.markdown("""
    <style>
    /* Force dark theme aesthetics on primary elements */
    .stApp {
        background-color: #0e1117;
        color: #fafafa;
    }
    .stButton>button {
        background-color: #ff4b4b;
        color: white;
        border-radius: 4px;
        border: none;
    }
    .stButton>button:hover {
        background-color: #ff3333;
    }
    /* Style the question text nicely */
    .question-box {
        background-color: #262730;
        padding: 20px;
        border-radius: 8px;
        border-left: 5px solid #ff4b4b;
        margin-bottom: 20px;
        font-size: 18px;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session State Management
# ---------------------------------------------------------------------------
# WHY session_state: Streamlit reruns the script top-to-bottom on every interaction.
# We must persist the current stage (upload, research, interview, summary) and
# the data (profile, question pool, current index, scores) across these reruns.

if "step" not in st.session_state:
    st.session_state.step = "upload"
if "profile" not in st.session_state:
    st.session_state.profile = None
if "questions" not in st.session_state:
    st.session_state.questions = []
if "current_q_idx" not in st.session_state:
    st.session_state.current_q_idx = 0
if "asked_indices" not in st.session_state:
    st.session_state.asked_indices = []
if "history" not in st.session_state:
    st.session_state.history = []
if "current_level" not in st.session_state:
    st.session_state.current_level = 1


def next_question():
    """Find the next question closest to current_level and update session state."""
    best_idx = None
    best_dist = float("inf")
    
    # Same logic as agents.py: pick closest difficulty, breaking ties by pool order
    for i, q in enumerate(st.session_state.questions):
        if i in st.session_state.asked_indices:
            continue
        dist = abs(q["difficulty"] - st.session_state.current_level)
        if dist < best_dist:
            best_dist = dist
            best_idx = i
            
    if best_idx is not None:
        st.session_state.current_q_idx = best_idx
        st.session_state.asked_indices.append(best_idx)
        return True
    return False

# ---------------------------------------------------------------------------
# UI Views
# ---------------------------------------------------------------------------

st.title("🎙️ AI Technical Interview Prep")

# Display a health warning if backend is unreachable
# WHY do this here: It provides immediate feedback before the user tries to act.
if not api_client.check_health():
    st.error("Backend is unreachable. Please start `uvicorn backend.app:app`.")


if st.session_state.step == "upload":
    # Stage 1: Upload Resume
    st.write("Upload your PDF resume to extract your profile and skills.")
    uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])
    
    if uploaded_file is not None:
        if st.button("Extract Profile"):
            with st.spinner("Analyzing resume..."):
                try:
                    profile = api_client.upload_resume(uploaded_file.getvalue(), uploaded_file.name)
                    st.session_state.profile = profile
                    st.session_state.step = "profile_view"
                    st.rerun()
                except api_client.BackendError as e:
                    st.error(str(e))


elif st.session_state.step == "profile_view":
    # Stage 2: Show Profile & Trigger Research
    p = st.session_state.profile
    st.subheader(f"Profile: {p.get('name', 'Unknown')} - {p.get('role', 'Any Role')}")
    st.write(f"Years of Experience: {p.get('years_of_experience', 'Unknown')}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Skills:**")
        for s in p.get("skills", []):
            st.markdown(f"- {s.get('name')}")
    with col2:
        st.markdown("**Technologies:**")
        for t in p.get("technologies", []):
            st.markdown(f"- {t.get('name')}")
            
    st.write("Ready to research tailored questions for this profile?")
    if st.button("Research Questions"):
        with st.spinner("Searching the web for real interview questions..."):
            try:
                questions = api_client.research_questions(st.session_state.profile)
                st.session_state.questions = questions
                
                # Setup initial interview state exactly as the CLI did
                years = st.session_state.profile.get("years_of_experience")
                # Level = clamp(years, 1, 5). None -> 1
                if years is None:
                    st.session_state.current_level = 1
                else:
                    st.session_state.current_level = max(1, min(years, 5))
                    
                next_question() # Cue up the first question
                st.session_state.step = "interview"
                st.rerun()
            except api_client.BackendError as e:
                st.error(str(e))
                
                
elif st.session_state.step == "interview":
    # Stage 3: Interview Loop
    q_pool_size = len(st.session_state.questions)
    rounds_done = len(st.session_state.history)
    
    # WHY stop at 5? A sane default for the mock interview length, just like the CLI --rounds default.
    if rounds_done >= 5 or rounds_done >= q_pool_size:
        st.session_state.step = "summary"
        st.rerun()
        
    st.progress(rounds_done / 5.0)
    st.subheader(f"Round {rounds_done + 1} / 5 (Level {st.session_state.current_level})")
    
    current_q = st.session_state.questions[st.session_state.current_q_idx]
    
    st.markdown(f'<div class="question-box">{current_q["question"]}</div>', unsafe_allow_html=True)
    st.caption(f"Source: [{current_q.get('source_title', 'Link')}]({current_q['source_url']}) | Difficulty: {current_q['difficulty']} | Skill: {current_q['skill']}")
    
    # WHY audio_input: Provides a realistic, conversational mock interview experience compared to typing.
    audio_bytes = st.audio_input("Record your answer:")
    submitted = st.button("Submit Answer")
    
    if submitted:
        if not audio_bytes:
            st.warning("Please record an audio answer first before submitting!")
        else:
            with st.spinner("Transcribing and evaluating..."):
                try:
                    # Translate audio to text
                    transcript_res = api_client.transcribe_audio(audio_bytes.getvalue(), "answer.wav")
                    answer = transcript_res.get('text', '')
                    
                    # Log the spoken text back to the screen as visual feedback
                    st.info(f"🎙️ You said: {answer}")
                    
                    evalu = api_client.evaluate_answer(
                        question=current_q,
                        answer=answer,
                        profile=st.session_state.profile
                    )
                    
                    # Compute new level based on strict rules: >=7 -> +1; <=4 -> -1
                    score = evalu['score']
                    lvl = st.session_state.current_level
                    if score >= 7:
                        lvl = min(5, lvl + 1)
                    elif score <= 4:
                        lvl = max(1, lvl - 1)
                    st.session_state.current_level = lvl
                    
                    st.session_state.history.append({
                        "question": current_q,
                        "answer": answer,
                        "evaluation": evalu,
                        "level_after": lvl
                    })
                    
                    if next_question():
                        st.session_state.step = "feedback"
                        st.rerun()
                    else:
                        st.session_state.step = "summary"
                        st.rerun()
                        
                except api_client.BackendError as e:
                    st.error(str(e))
                    

elif st.session_state.step == "feedback":
    # Interstitial step to show feedback before next question
    last_round = st.session_state.history[-1]
    st.success(f"Score: {last_round['evaluation']['score']} / 10")
    st.info(f"Feedback: {last_round['evaluation']['feedback']}")
    if last_round['evaluation']['model_answer']:
        with st.expander("See Ideal Answer"):
            st.write(last_round['evaluation']['model_answer'])
            
    if st.button("Next Question"):
        st.session_state.step = "interview"
        st.rerun()
            

elif st.session_state.step == "summary":
    # Stage 4: Summary Report
    st.header("🎉 Interview Complete")
    st.write("Here is your performance summary:")
    
    total_score = sum(h["evaluation"]["score"] for h in st.session_state.history)
    max_score = len(st.session_state.history) * 10
    st.metric("Overall Score", f"{total_score} / {max_score}")
    
    for i, h in enumerate(st.session_state.history):
        with st.expander(f"Q{i+1}: {h['question']['question'][:50]}..."):
            st.write(f"**Your Answer:** {h['answer']}")
            st.write(f"**Score:** {h['evaluation']['score']}/10")
            st.write(f"**Feedback:** {h['evaluation']['feedback']}")
            st.caption(f"Question Level: {h['question']['difficulty']} | Level After: {h['level_after']}")
            
    if st.button("Start New Interview"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
