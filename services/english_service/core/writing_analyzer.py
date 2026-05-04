import logging
from typing import Any

from services.english_service.models import Session
from services.english_service.core.metrics import Metrics
from services.english_service.core.prompt_builder import (
    build_topic_writing_prompt,
    build_translation_writing_prompt,
)
from services.english_service.llm.client import BaseLLMClient, GroqLLMClient

logger = logging.getLogger(__name__)


class WritingAnalyzer:
    def __init__(self, llm_client: BaseLLMClient | None = None):
        self.llm = llm_client or GroqLLMClient(
            temperature=0.2,
            system_message=(
                "You are a careful English writing evaluator. "
                "Return consistent numeric feedback as valid JSON only."
            ),
        )

    def analyze(self, session: Session, user_text: str):
        writing_type = session.data.get("writing_type")

        if writing_type == "topic_writing":
            return self.analyze_topic_writing(session, user_text)

        if writing_type == "translation_writing":
            return self.analyze_translation_writing(session, user_text)

        return {
            "type": "writing_feedback",
            "message": "Unknown writing task type.",
        }

    def analyze_topic_writing(self, session: Session, user_text: str):
        cleaned_text = user_text.strip()
        validation_error = self._validate_min_words(
            cleaned_text,
            session.data.get("min_words", 0),
            empty_message="Your text is empty. Please write something first.",
        )
        if validation_error:
            return validation_error

        prompt = build_topic_writing_prompt(
            level=session.level,
            topic=session.data.get("topic", ""),
            user_text=cleaned_text,
        )

        llm_response = self.llm.generate(prompt)
        feedback = self._parse_feedback(llm_response)
        session.data["last_writing_feedback"] = feedback

        return {
            "type": "writing_feedback",
            "message": self._format_feedback(feedback),
            "raw_feedback": feedback,
        }

    def analyze_translation_writing(self, session: Session, user_text: str):
        cleaned_text = user_text.strip()
        validation_error = self._validate_min_words(
            cleaned_text,
            session.data.get("min_words", 0),
            empty_message="Your translation is empty. Please write something first.",
        )
        if validation_error:
            return validation_error

        prompt = build_translation_writing_prompt(
            level=session.level,
            source_text=session.data.get("source_text", ""),
            user_text=cleaned_text,
        )

        llm_response = self.llm.generate(prompt)
        feedback = self._parse_feedback(llm_response)
        session.data["last_writing_feedback"] = feedback

        return {
            "type": "writing_feedback",
            "message": self._format_feedback(feedback),
            "raw_feedback": feedback,
        }

    def _validate_min_words(
        self,
        text: str,
        min_words: int,
        empty_message: str,
    ) -> dict | None:
        if not text:
            return {
                "type": "writing_feedback",
                "message": empty_message,
            }

        word_count = len(text.split())
        if word_count < min_words:
            return {
                "type": "writing_feedback",
                "message": f"Too short. You wrote {word_count} words. Minimum is {min_words}.",
            }

        return None

    def _parse_feedback(self, raw_response: str):
        import re
        import json

        cleaned = raw_response.strip()

        # direct parse first
        try:
            data = json.loads(cleaned)
            return self._normalize_feedback(data, raw_response)
        except Exception:
            pass

        # markdown json block extraction
        fenced = re.search(
                r"```(?:json)?\s*(\{.*\})\s*```",
                cleaned,
                re.DOTALL
        )
        if fenced:
                try:
                        data = json.loads(fenced.group(1))
                        return self._normalize_feedback(data, raw_response)
                except Exception:
                        pass

        # first json object extraction
        obj = re.search(
                r"\{.*\}",
                cleaned,
                re.DOTALL
        )
        if obj:
                try:
                        data = json.loads(obj.group(0))
                        return self._normalize_feedback(data, raw_response)
                except Exception:
                        pass

        Metrics.inc("json_parse_failures")
        logger.warning(
                "Writing feedback JSON parsing failed. Raw response: %s",
                raw_response
        )

        return self._fallback_feedback(raw_response)

    def _normalize_feedback(self, data: dict[str, Any], raw_response: str) -> dict[str, Any]:
        return {
            "overall_score": self._score(data.get("overall_score")),
            "grammar_score": self._score(data.get("grammar_score")),
            "vocabulary_score": self._score(data.get("vocabulary_score")),
            "clarity_score": self._score(data.get("clarity_score")),
            "strengths": self._clean_list(data.get("strengths"), limit=2),
            "improvements": self._clean_list(data.get("improvements"), limit=2),
            "next_focus": self._clean_text(data.get("next_focus")) or "Practice one clear improvement in your next answer.",
            "raw_response": raw_response,
        }

    def _score(self, value: Any) -> int:
        try:
            score = int(value)
        except (TypeError, ValueError):
            return 5

        return max(1, min(score, 10))

    def _clean_list(self, value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []

        cleaned = []
        for item in value:
            text = self._clean_text(item)
            if text:
                cleaned.append(text)
            if len(cleaned) == limit:
                break

        return cleaned

    def _clean_text(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    def _fallback_feedback(self, raw_response: str) -> dict[str, Any]:
        Metrics.inc("writing_fallback_used")

        return {
            "overall_score": 5,
            "grammar_score": 5,
            "vocabulary_score": 5,
            "clarity_score": 5,
            "strengths": ["You completed the task."],
            "improvements": ["Review grammar and sentence clarity."],
            "next_focus": "Write a short corrected version and focus on clear sentence structure.",
            "raw_response": raw_response,
        }

    def _format_feedback(self, feedback: dict[str, Any]) -> str:
        strengths = feedback.get("strengths") or ["You completed the task."]
        improvements = feedback.get("improvements") or ["Review grammar and sentence clarity."]

        strengths_text = "\n".join(f"- {item}" for item in strengths)
        improvements_text = "\n".join(f"- {item}" for item in improvements)

        return (
            "Scores\n"
            f"Overall: {feedback['overall_score']}/10\n"
            f"Grammar: {feedback['grammar_score']}/10\n"
            f"Vocabulary: {feedback['vocabulary_score']}/10\n"
            f"Clarity: {feedback['clarity_score']}/10\n\n"
            "Strengths\n"
            f"{strengths_text}\n\n"
            "Improvements\n"
            f"{improvements_text}\n\n"
            f"Next focus: {feedback['next_focus']}"
        )
