from typing import Dict

from services.english_service.models import Session


class FlowEngine:

    _TRANSIENT_KEYS = (
        "quiz_questions",
        "current_index",
        "writing_type",
        "topic",
        "source_text",
        "min_words",
        "last_writing_feedback",
    )

    def start(self, session: Session) -> Dict:
        """Yeni /english oturumu: seçim adımına dön; eski level/mode ve ara görev durumunu temizle."""
        session.step = "select_level"
        session.level = None
        session.mode = None
        session.context = []
        if hasattr(session, "data") and session.data is not None:
            for key in self._TRANSIENT_KEYS:
                session.data.pop(key, None)
        return {
            "type": "level_selection",
            "message": "Select your level"
        }

    def set_level(self, session: Session, level: str) -> Dict:
        session.level = level
        session.step = "select_mode"

        return {
            "type": "mode_selection",
            "message": f"Level set to {level}. Select mode."
        }

    def set_mode(self, session: Session, mode: str) -> Dict:
        session.mode = mode

        if mode == "writing":
            session.step = "select_writing_type"
            return {
                "type": "writing_type_selection",
                "message": "Select writing type: topic_writing or translation_writing"
            }

        session.step = "active"
        return {
            "type": "mode_started",
            "message": f"{mode} mode started"
        }