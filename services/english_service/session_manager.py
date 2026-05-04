from typing import Dict, Optional
import time

from .models import Session
from .core.level_config import (
    PREVIOUS_QUIZ_LIMIT,
    RECENT_TOPIC_LIMIT,
    RECENT_TRANSLATION_LIMIT,
)


class SessionManager:
    def __init__(self, timeout: int = 900):
        self.sessions: Dict[str, Session] = {}
        self.timeout = timeout

    def create_or_get(self, user_id: str) -> Session:
        session = self.sessions.get(user_id)

        if session and self._is_expired(session):
            self.delete(user_id)
            session = None

        if not session:
            session = Session(user_id)
            self.sessions[user_id] = session

        self._ensure_english_state(session)
        session.touch()
        return session

    def get(self, user_id: str) -> Optional[Session]:
        session = self.sessions.get(user_id)

        if not session:
            return None

        if self._is_expired(session):
            self.delete(user_id)
            return None

        self._ensure_english_state(session)
        session.touch()
        return session

    def delete(self, user_id: str):
        if user_id in self.sessions:
            del self.sessions[user_id]

    def cleanup(self):
        expired = [
            uid for uid, session in self.sessions.items()
            if self._is_expired(session)
        ]

        for uid in expired:
            self.delete(uid)

    def add_recent_writing_topic(self, session: Session, topic: str):
        self._append_unique_limited(
            session=session,
            key="recent_writing_topics",
            value=topic,
            limit=RECENT_TOPIC_LIMIT,
        )

    def add_recent_translation_source(self, session: Session, source_text: str):
        self._append_unique_limited(
            session=session,
            key="recent_translation_sources",
            value=source_text,
            limit=RECENT_TRANSLATION_LIMIT,
        )

    def add_previous_quiz_questions(self, session: Session, questions: list[str]):
        if not isinstance(questions, list):
            return

        for question in questions:
            self._append_unique_limited(
                session=session,
                key="previous_quiz_questions",
                value=question,
                limit=PREVIOUS_QUIZ_LIMIT,
            )

    def _is_expired(self, session: Session) -> bool:
        return time.time() - session.last_activity > self.timeout

    def _ensure_english_state(self, session: Session):
        """Initialize deterministic history fields used by the English service."""
        if not hasattr(session, "data") or session.data is None:
            session.data = {}

        session.data.setdefault("recent_writing_topics", [])
        session.data.setdefault("recent_translation_sources", [])
        session.data.setdefault("previous_quiz_questions", [])
        session.data.setdefault("used_quiz_question_types", [])

    def _append_unique_limited(
        self,
        session: Session,
        key: str,
        value: str,
        limit: int,
    ):
        self._ensure_english_state(session)

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