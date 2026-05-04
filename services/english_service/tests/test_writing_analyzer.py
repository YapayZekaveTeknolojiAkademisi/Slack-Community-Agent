import json

from services.english_service.core.writing_analyzer import (
    WritingAnalyzer
)


class MockFeedbackLLM:
    def generate(self,prompt):
        return json.dumps(
          {
            "overall_score":8,
            "grammar_score":7,
            "vocabulary_score":8,
            "clarity_score":8,
            "strengths":["Good grammar","Clear ideas"],
            "improvements":["Use richer vocab","Check articles"],
            "next_focus":"Practice articles"
          }
        )


def test_feedback_schema():
    analyzer=WritingAnalyzer(
       llm_client=MockFeedbackLLM()
    )

    parsed=analyzer._parse_feedback(
      MockFeedbackLLM().generate("")
    )

    assert parsed["overall_score"]==8
    assert len(parsed["strengths"])==2
    assert "next_focus" in parsed


def test_score_clamped():
    analyzer = WritingAnalyzer(
    llm_client=MockFeedbackLLM()
)

    assert analyzer._score(25)==10
    assert analyzer._score(-1)==1