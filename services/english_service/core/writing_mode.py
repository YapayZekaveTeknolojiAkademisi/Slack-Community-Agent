from services.english_service.models import Session
from services.english_service.core.level_config import (
    RECENT_TOPIC_LIMIT,
    RECENT_TRANSLATION_LIMIT,
)
from services.english_service.core.writing_analyzer import WritingAnalyzer
from services.english_service.core.writing_task_generator import WritingTaskGenerator


class WritingMode:
    def __init__(self):
        self.analyzer = WritingAnalyzer()
        self.task_generator = WritingTaskGenerator()

    def start_topic_writing(self, session: Session):
        self._ensure_writing_state(session)

        level = session.level
        last_topic = session.data.get("last_topic")
        recent_topics = session.data.get("recent_writing_topics", [])

        task = self.task_generator.generate_topic_task(
            level=level,
            last_topic=last_topic,
            recent_topics=recent_topics,
        )

        topic = task["topic"]

        session.data["writing_type"] = "topic_writing"
        session.data["topic"] = topic
        session.data["last_topic"] = topic
        session.data["min_words"] = task["min_words"]
        self._append_unique_limited(
            session=session,
            key="recent_writing_topics",
            value=topic,
            limit=RECENT_TOPIC_LIMIT,
        )

        session.step = "waiting_writing"

        return {
            "type": "writing_task",
            "message": f"Write about: {topic}\nMinimum {task['min_words']} words.",
        }

    def start_translation_writing(self, session: Session):
        self._ensure_writing_state(session)

        level = session.level
        last_source_text = session.data.get("last_source_text")
        recent_source_texts = session.data.get("recent_translation_sources", [])

        task = self.task_generator.generate_translation_task(
            level=level,
            last_source_text=last_source_text,
            recent_source_texts=recent_source_texts,
        )

        source_text = task["source_text"]

        session.data["writing_type"] = "translation_writing"
        session.data["source_text"] = source_text
        session.data["last_source_text"] = source_text
        session.data["min_words"] = task["min_words"]
        self._append_unique_limited(
            session=session,
            key="recent_translation_sources",
            value=source_text,
            limit=RECENT_TRANSLATION_LIMIT,
        )

        session.step = "waiting_writing"

        return {
            "type": "writing_task",
            "message": (
                "Translate this Turkish text into English:\n"
                f"{source_text}\n"
                f"Minimum {task['min_words']} words."
            ),
        }

    def evaluate(self, session: Session, user_text: str):
        result = self.analyzer.analyze(session, user_text)
        # Yalnızca gerçek LLM geri bildirimi başarılıysa yazı beklemeyi kapat; "çok kısa/boş" için beklemeye devam.
        if (
            result.get("type") == "writing_feedback"
            and result.get("raw_feedback") is not None
        ):
            session.step = "writing_completed"
        return result

    def _ensure_writing_state(self, session: Session):
        if not hasattr(session, "data") or session.data is None:
            session.data = {}

        session.data.setdefault("recent_writing_topics", [])
        session.data.setdefault("recent_translation_sources", [])

    def _append_unique_limited(
        self,
        session: Session,
        key: str,
        value: str,
        limit: int,
    ):
        self._ensure_writing_state(session)

        if not isinstance(value, str) or not value.strip():
            return

        cleaned_value = value.strip()
        values = session.data.get(key, [])

        if not isinstance(values, list):
            values = []

        values = [
            item.strip()
            for item in values
            if isinstance(item, str)
            and item.strip()
            and item.strip().lower() != cleaned_value.lower()
        ]

        values.append(cleaned_value)
        session.data[key] = values[-limit:]