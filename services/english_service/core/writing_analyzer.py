from services.english_service.models import Session
from services.english_service.core.prompt_builder import (
    build_topic_writing_prompt,
    build_translation_writing_prompt,
)
from services.english_service.llm.client import BaseLLMClient, GroqLLMClient


class WritingAnalyzer:
    def __init__(self, llm_client: BaseLLMClient | None = None):
        self.llm = llm_client or GroqLLMClient(
            temperature=0.3,
            system_message="You are a careful and encouraging English teacher who gives consistent feedback."
        )

    def analyze(self, session: Session, user_text: str):
        writing_type = session.data.get("writing_type")

        if writing_type == "topic_writing":
            return self.analyze_topic_writing(session, user_text)

        if writing_type == "translation_writing":
            return self.analyze_translation_writing(session, user_text)

        return {
            "type": "writing_feedback",
            "message": "Unknown writing task type."
        }

    def analyze_topic_writing(self, session: Session, user_text: str):
        cleaned_text = user_text.strip()
        word_count = len(cleaned_text.split())
        min_words = session.data.get("min_words", 0)
        topic = session.data.get("topic", "")

        if not cleaned_text:
            return {
                "type": "writing_feedback",
                "message": "Your text is empty. Please write something first."
            }

        if word_count < min_words:
            return {
                "type": "writing_feedback",
                "message": f"Too short. You wrote {word_count} words. Minimum is {min_words}."
            }

        prompt = build_topic_writing_prompt(
            level=session.level,
            topic=topic,
            user_text=cleaned_text,
        )

        llm_response = self.llm.generate(prompt)

        return {
            "type": "writing_feedback",
            "message": llm_response
        }

    def analyze_translation_writing(self, session: Session, user_text: str):
        cleaned_text = user_text.strip()
        word_count = len(cleaned_text.split())
        min_words = session.data.get("min_words", 0)
        source_text = session.data.get("source_text", "")

        if not cleaned_text:
            return {
                "type": "writing_feedback",
                "message": "Your translation is empty. Please write something first."
            }

        if word_count < min_words:
            return {
                "type": "writing_feedback",
                "message": f"Too short. You wrote {word_count} words. Minimum is {min_words}."
            }

        prompt = build_translation_writing_prompt(
            level=session.level,
            source_text=source_text,
            user_text=cleaned_text,
        )

        llm_response = self.llm.generate(prompt)

        return {
            "type": "writing_feedback",
            "message": llm_response
        }