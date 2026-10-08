"""Tests for code-level guardrails.

All test data is FIXTURE data — not real personal information.
No live API calls are made; agents.ask is mocked throughout.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from backend import agents


# ══════════════════════════════════════════════════════════════════════════
# FIXTURE DATA — clearly labeled, not real personal info
# ══════════════════════════════════════════════════════════════════════════

FIXTURE_RESUME_TEXT = (
    "Jane Doe\n"
    "Software Engineer\n"
    "5 years of experience in software development\n"
    "Skills: Python, JavaScript, React, PostgreSQL, Docker\n"
    "Experience with machine learning and data analysis\n"
    "Worked at Acme Corp from 2019 to 2024\n"
)

FIXTURE_PROFILE = {
    "name": "Jane Doe",
    "role": "Software Engineer",
    "years_of_experience": 5,
    "years_evidence": "5 years of experience",
    "skills": [
        {"name": "Python", "category": "language"},
        {"name": "JavaScript", "category": "language"},
    ],
    "technologies": [
        {"name": "React", "category": "framework"},
        {"name": "PostgreSQL", "category": "database"},
        {"name": "Docker", "category": "tool"},
    ],
}

FIXTURE_QUESTIONS = [
    {
        "question": "What is a Python decorator?",
        "difficulty": 2,
        "skill": "Python",
        "source_url": "https://example.com/python-questions",
        "source_title": "Python Interview Questions",
    },
    {
        "question": "Explain closures in JavaScript.",
        "difficulty": 3,
        "skill": "JavaScript",
        "source_url": "https://example.com/js-questions",
        "source_title": "JS Interview Questions",
    },
    {
        "question": "What is virtual DOM in React?",
        "difficulty": 1,
        "skill": "React",
        "source_url": "https://example.com/react-questions",
        "source_title": "React Interview Questions",
    },
    {
        "question": "Explain ACID properties in databases.",
        "difficulty": 4,
        "skill": "PostgreSQL",
        "source_url": "https://example.com/db-questions",
        "source_title": "Database Interview Questions",
    },
    {
        "question": "What is container orchestration?",
        "difficulty": 5,
        "skill": "Docker",
        "source_url": "https://example.com/docker-questions",
        "source_title": "Docker Interview Questions",
    },
]

FIXTURE_RETRIEVED_URLS = {
    "https://example.com/python-questions",
    "https://example.com/js-questions",
    "https://example.com/react-questions",
    "https://example.com/db-questions",
    "https://example.com/docker-questions",
}


# ══════════════════════════════════════════════════════════════════════════
# EXTRACTOR GUARDRAIL TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestExtractorDropsInvalidSkills:
    """G1: Skills/technologies not in resume text are dropped."""

    def test_drops_skill_not_in_resume(self):
        """Fixture: 'Rust' is NOT in the resume, should be dropped."""
        profile = {
            "skills": [
                {"name": "Python", "category": "language"},
                {"name": "Rust", "category": "language"},
            ],
            "technologies": [],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        names = [s["name"] for s in result["skills"]]
        assert "Python" in names
        assert "Rust" not in names

    def test_drops_technology_not_in_resume(self):
        """Fixture: 'Kubernetes' is NOT in the resume, should be dropped."""
        profile = {
            "skills": [],
            "technologies": [
                {"name": "React", "category": "framework"},
                {"name": "Kubernetes", "category": "tool"},
            ],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        names = [t["name"] for t in result["technologies"]]
        assert "React" in names
        assert "Kubernetes" not in names

    def test_keeps_all_valid_skills(self):
        """Fixture: all names present in resume are kept."""
        profile = {
            "skills": [
                {"name": "Python", "category": "language"},
                {"name": "JavaScript", "category": "language"},
            ],
            "technologies": [
                {"name": "Docker", "category": "tool"},
            ],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        assert len(result["skills"]) == 2
        assert len(result["technologies"]) == 1


class TestExtractorYearsEvidence:
    """G3/G4: years_of_experience tied to years_evidence in resume."""

    def test_years_none_when_evidence_not_in_resume(self):
        """Fixture: evidence text not found in resume → years = None."""
        profile = {
            "years_of_experience": 10,
            "years_evidence": "10 years of professional experience",
            "skills": [],
            "technologies": [],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        assert result["years_of_experience"] is None
        assert result["years_evidence"] is None

    def test_years_kept_when_evidence_in_resume(self):
        """Fixture: evidence text found in resume → years kept."""
        profile = {
            "years_of_experience": 5,
            "years_evidence": "5 years of experience",
            "skills": [],
            "technologies": [],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        assert result["years_of_experience"] == 5
        assert result["years_evidence"] == "5 years of experience"

    def test_years_none_when_no_evidence_provided(self):
        """Fixture: no evidence at all → years = None."""
        profile = {
            "years_of_experience": 3,
            "years_evidence": None,
            "skills": [],
            "technologies": [],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        assert result["years_of_experience"] is None

    def test_years_none_when_evidence_is_empty_string(self):
        """Fixture: empty-string evidence → years = None."""
        profile = {
            "years_of_experience": 3,
            "years_evidence": "",
            "skills": [],
            "technologies": [],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        assert result["years_of_experience"] is None


class TestExtractorRole:
    """G2: Role must appear in resume text."""

    def test_role_dropped_when_not_in_resume(self):
        """Fixture: 'Data Scientist' is NOT in the resume."""
        profile = {
            "role": "Data Scientist",
            "skills": [],
            "technologies": [],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        assert result["role"] is None

    def test_role_kept_when_in_resume(self):
        """Fixture: 'Software Engineer' IS in the resume."""
        profile = {
            "role": "Software Engineer",
            "skills": [],
            "technologies": [],
        }
        result = agents.validate_profile(profile, FIXTURE_RESUME_TEXT)
        assert result["role"] == "Software Engineer"


# ══════════════════════════════════════════════════════════════════════════
# RESEARCHER GUARDRAIL TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestResearcherDropsBadUrl:
    """G5: Questions with source_url not in retrieved URLs are dropped."""

    def test_drops_question_with_unretrieved_url(self):
        """Fixture: source_url not in retrieved set → dropped."""
        questions = [
            {
                "question": "What is Python?",
                "difficulty": 1,
                "skill": "Python",
                "source_url": "https://example.com/python-questions",
            },
            {
                "question": "What is Java?",
                "difficulty": 2,
                "skill": "Java",
                "source_url": "https://fake-url.com/not-retrieved",
            },
        ]
        retrieved = {"https://example.com/python-questions"}
        result = agents.validate_questions(questions, retrieved)
        assert len(result) == 1
        assert result[0]["question"] == "What is Python?"


class TestResearcherDropsDuplicates:
    """G7: Duplicate questions (same text, case-insensitive) are dropped."""

    def test_drops_duplicate_questions(self):
        """Fixture: identical question text → second is dropped."""
        questions = [
            {
                "question": "What is Python?",
                "difficulty": 1,
                "skill": "Python",
                "source_url": "https://example.com/a",
            },
            {
                "question": "What is Python?",
                "difficulty": 2,
                "skill": "Python",
                "source_url": "https://example.com/a",
            },
        ]
        retrieved = {"https://example.com/a"}
        result = agents.validate_questions(questions, retrieved)
        assert len(result) == 1

    def test_drops_case_insensitive_duplicates(self):
        """Fixture: same text different case → duplicate dropped."""
        questions = [
            {
                "question": "What is Python?",
                "difficulty": 1,
                "skill": "Python",
                "source_url": "https://example.com/a",
            },
            {
                "question": "what is python?",
                "difficulty": 2,
                "skill": "Python",
                "source_url": "https://example.com/a",
            },
        ]
        retrieved = {"https://example.com/a"}
        result = agents.validate_questions(questions, retrieved)
        assert len(result) == 1


class TestResearcherDropsInvalidDifficulty:
    """G6: Questions with difficulty outside 1-5 are dropped."""

    def test_drops_difficulty_0(self):
        """Fixture: difficulty 0 → dropped."""
        questions = [
            {"question": "Q0", "difficulty": 0, "skill": "X",
             "source_url": "https://example.com/a"},
        ]
        retrieved = {"https://example.com/a"}
        with pytest.raises(ValueError, match="No valid questions"):
            agents.validate_questions(questions, retrieved)

    def test_drops_difficulty_6(self):
        """Fixture: difficulty 6 → dropped."""
        questions = [
            {"question": "Q6", "difficulty": 6, "skill": "X",
             "source_url": "https://example.com/a"},
        ]
        retrieved = {"https://example.com/a"}
        with pytest.raises(ValueError, match="No valid questions"):
            agents.validate_questions(questions, retrieved)

    def test_drops_non_integer_difficulty(self):
        """Fixture: non-integer difficulty → dropped."""
        questions = [
            {"question": "Q", "difficulty": "hard", "skill": "X",
             "source_url": "https://example.com/a"},
        ]
        retrieved = {"https://example.com/a"}
        with pytest.raises(ValueError, match="No valid questions"):
            agents.validate_questions(questions, retrieved)

    def test_keeps_valid_among_invalid_difficulties(self):
        """Fixture: only the valid-difficulty question survives."""
        questions = [
            {"question": "Q0", "difficulty": 0, "skill": "X",
             "source_url": "https://example.com/a"},
            {"question": "Q3", "difficulty": 3, "skill": "X",
             "source_url": "https://example.com/a"},
            {"question": "Q6", "difficulty": 6, "skill": "X",
             "source_url": "https://example.com/a"},
        ]
        retrieved = {"https://example.com/a"}
        result = agents.validate_questions(questions, retrieved)
        assert len(result) == 1
        assert result[0]["question"] == "Q3"


class TestResearcherRaisesWhenEmpty:
    """G8: ValueError when no question survives filtering."""

    def test_raises_on_all_invalid(self):
        """Fixture: every question is invalid → ValueError."""
        questions = [
            {"question": "Q", "difficulty": 0, "skill": "X",
             "source_url": "https://example.com/a"},
        ]
        retrieved = {"https://example.com/a"}
        with pytest.raises(ValueError, match="No valid questions"):
            agents.validate_questions(questions, retrieved)

    def test_raises_on_empty_list(self):
        """Fixture: empty question list → ValueError."""
        with pytest.raises(ValueError, match="No valid questions"):
            agents.validate_questions([], set())


# ══════════════════════════════════════════════════════════════════════════
# INTEGRATED RESEARCH PIPELINE TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestResearchQuestionsPipeline:
    """Tests the full research_questions pipeline mocking Tavily and Groq.
    
    WHY THIS TEST: To ensure the two-step search-and-extract pipeline
    works correctly together without making real API calls.
    """

    @patch("backend.agents.tavily_search")
    @patch("backend.agents.ask")
    def test_research_questions_golden_path(self, mock_ask, mock_tavily):
        """Fixture: Mock Tavily returns URLs, Mock Groq returns JSON questions."""
        # 1. Setup Tavily mock
        mock_tavily.return_value = (
            [
                {"url": "https://example.com/mock-python", "title": "Mock", "content": "mock text"}
            ],
            {"https://example.com/mock-python"}
        )

        # 2. Setup Groq mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '```json\n[{"question": "What is Python?", "difficulty": 3, "skill": "Python", "source_url": "https://example.com/mock-python"}]\n```'
        mock_ask.return_value = mock_response

        # 3. Call actual function
        result = agents.research_questions(FIXTURE_PROFILE)

        # 4. Assertions
        assert len(result) == 1
        assert result[0]["question"] == "What is Python?"
        assert result[0]["source_url"] == "https://example.com/mock-python"


# ══════════════════════════════════════════════════════════════════════════
# INTERVIEWER GUARDRAIL TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestStartingLevel:
    """Starting level = clamp(years, 1, 5); None → 1."""

    def test_0_years(self):
        """Fixture: 0 years → level 1."""
        assert agents.starting_level(0) == 1

    def test_3_years(self):
        """Fixture: 3 years → level 3."""
        assert agents.starting_level(3) == 3

    def test_6_years(self):
        """Fixture: 6 years → clamped to level 5."""
        assert agents.starting_level(6) == 5

    def test_none_years(self):
        """Fixture: None → level 1 (default)."""
        assert agents.starting_level(None) == 1

    def test_1_year(self):
        """Fixture: 1 year → level 1."""
        assert agents.starting_level(1) == 1

    def test_negative_years(self):
        """Fixture: negative → clamped to level 1."""
        assert agents.starting_level(-2) == 1


class TestLevelAdjustment:
    """Level adjustment: +1 on >=7, -1 on <=4, unchanged 5-6, bounded 1-5."""

    def test_level_up_on_score_7(self):
        assert agents.adjust_level(3, 7) == 4

    def test_level_up_on_score_10(self):
        assert agents.adjust_level(3, 10) == 4

    def test_level_down_on_score_4(self):
        assert agents.adjust_level(3, 4) == 2

    def test_level_down_on_score_0(self):
        assert agents.adjust_level(3, 0) == 2

    def test_level_unchanged_on_score_5(self):
        assert agents.adjust_level(3, 5) == 3

    def test_level_unchanged_on_score_6(self):
        assert agents.adjust_level(3, 6) == 3

    def test_level_cannot_go_below_1(self):
        """Fixture: level 1 + low score → stays at 1."""
        assert agents.adjust_level(1, 0) == 1

    def test_level_cannot_go_above_5(self):
        """Fixture: level 5 + high score → stays at 5."""
        assert agents.adjust_level(5, 10) == 5


class TestScoreComputation:
    """Score = clamped(correctness) + clamped(depth) + clamped(clarity)."""

    def test_perfect_score(self):
        assert agents.compute_score({"correctness": 4, "depth": 3, "clarity": 3}) == 10

    def test_zero_score(self):
        assert agents.compute_score({"correctness": 0, "depth": 0, "clarity": 0}) == 0

    def test_mixed_score(self):
        assert agents.compute_score({"correctness": 2, "depth": 1, "clarity": 2}) == 5

    def test_clamps_over_max(self):
        """Fixture: sub-scores above max are clamped before summing."""
        # correctness max=4, depth max=3, clarity max=3
        assert agents.compute_score({"correctness": 5, "depth": 4, "clarity": 4}) == 10

    def test_clamps_negative(self):
        """Fixture: negative sub-scores are clamped to 0."""
        assert agents.compute_score({"correctness": -1, "depth": -2, "clarity": -1}) == 0

    def test_missing_keys_default_to_zero(self):
        """Fixture: missing keys → treated as 0."""
        assert agents.compute_score({}) == 0


class TestEmptyAnswer:
    """G10: Empty answer → score 0 without calling ask."""

    def test_empty_string_scores_zero(self):
        """Fixture: empty answer → all zeros, no API call."""
        with patch("backend.agents.ask") as mock_ask:
            result = agents.evaluate_answer(FIXTURE_QUESTIONS[0], "", FIXTURE_PROFILE)
            assert result["score"] == 0
            assert result["correctness"] == 0
            assert result["depth"] == 0
            assert result["clarity"] == 0
            mock_ask.assert_not_called()

    def test_whitespace_only_scores_zero(self):
        """Fixture: whitespace-only answer → all zeros, no API call."""
        with patch("backend.agents.ask") as mock_ask:
            result = agents.evaluate_answer(FIXTURE_QUESTIONS[0], "   \n\t  ", FIXTURE_PROFILE)
            assert result["score"] == 0
            mock_ask.assert_not_called()

    def test_none_answer_scores_zero(self):
        """Fixture: None answer → all zeros, no API call."""
        with patch("backend.agents.ask") as mock_ask:
            result = agents.evaluate_answer(FIXTURE_QUESTIONS[0], None, FIXTURE_PROFILE)
            assert result["score"] == 0
            mock_ask.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# NEXT_QUESTION SELECTION TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestNextQuestion:
    """next_question picks closest difficulty, breaks ties by pool order."""

    def test_exact_match(self):
        """Fixture: question at exact level is picked."""
        questions = [
            {"question": "Q1", "difficulty": 1, "skill": "A"},
            {"question": "Q3", "difficulty": 3, "skill": "B"},
            {"question": "Q5", "difficulty": 5, "skill": "C"},
        ]
        idx, q = agents.next_question(questions, 3)
        assert idx == 1
        assert q["question"] == "Q3"

    def test_closest_difficulty(self):
        """Fixture: picks the question nearest to current level."""
        questions = [
            {"question": "Q1", "difficulty": 1, "skill": "A"},
            {"question": "Q4", "difficulty": 4, "skill": "B"},
        ]
        idx, q = agents.next_question(questions, 3)
        assert idx == 1  # distance 1 vs distance 2
        assert q["question"] == "Q4"

    def test_ties_broken_by_pool_order(self):
        """Fixture: equal distance → first in list wins."""
        questions = [
            {"question": "Q2", "difficulty": 2, "skill": "A"},  # dist=1 from level 3
            {"question": "Q4", "difficulty": 4, "skill": "B"},  # dist=1 from level 3
        ]
        idx, q = agents.next_question(questions, 3)
        assert idx == 0
        assert q["question"] == "Q2"

    def test_skips_asked_questions(self):
        """Fixture: already-asked indices are skipped."""
        questions = [
            {"question": "Q3a", "difficulty": 3, "skill": "A"},
            {"question": "Q3b", "difficulty": 3, "skill": "B"},
        ]
        idx, q = agents.next_question(questions, 3, asked_indices={0})
        assert idx == 1
        assert q["question"] == "Q3b"

    def test_returns_none_when_exhausted(self):
        """Fixture: all asked → returns (None, None)."""
        questions = [
            {"question": "Q1", "difficulty": 1, "skill": "A"},
        ]
        idx, q = agents.next_question(questions, 1, asked_indices={0})
        assert idx is None
        assert q is None

    def test_with_full_question_pool(self):
        """Fixture: with the full fixture pool, level 3 picks Q3 (difficulty 3)."""
        idx, q = agents.next_question(FIXTURE_QUESTIONS, 3)
        assert q["difficulty"] == 3
        assert q["question"] == "Explain closures in JavaScript."

    def test_progressive_selection(self):
        """Fixture: as level rises, successively harder questions are picked."""
        questions = [
            {"question": "Q1", "difficulty": 1, "skill": "A"},
            {"question": "Q2", "difficulty": 2, "skill": "B"},
            {"question": "Q3", "difficulty": 3, "skill": "C"},
            {"question": "Q4", "difficulty": 4, "skill": "D"},
            {"question": "Q5", "difficulty": 5, "skill": "E"},
        ]
        asked = set()
        for expected_level in [1, 2, 3, 4, 5]:
            idx, q = agents.next_question(questions, expected_level, asked)
            assert q["difficulty"] == expected_level
            asked.add(idx)


# ══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTION TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestClamp:
    """clamp(value, low, high) utility."""

    def test_within_range(self):
        assert agents.clamp(3, 1, 5) == 3

    def test_below_range(self):
        assert agents.clamp(0, 1, 5) == 1

    def test_above_range(self):
        assert agents.clamp(7, 1, 5) == 5

    def test_at_boundaries(self):
        assert agents.clamp(1, 1, 5) == 1
        assert agents.clamp(5, 1, 5) == 5


class TestExtractJson:
    """extract_json from various text formats."""

    def test_plain_json(self):
        result = agents.extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = agents.extract_json(text)
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        text = 'Here is the result: {"key": "value"} that is all.'
        result = agents.extract_json(text)
        assert result == {"key": "value"}

    def test_json_array(self):
        text = '[{"a": 1}, {"a": 2}]'
        result = agents.extract_json(text)
        assert len(result) == 2

    def test_raises_on_empty(self):
        with pytest.raises(ValueError, match="Empty text"):
            agents.extract_json("")

    def test_raises_on_no_json(self):
        with pytest.raises(json.JSONDecodeError):
            agents.extract_json("no json here at all")
