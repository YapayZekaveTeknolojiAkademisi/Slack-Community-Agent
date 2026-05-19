from services.english_service.session_manager import SessionManager
from services.english_service.models import Session
from services.english_service.core.flow_engine import FlowEngine
from services.english_service.core.writing_mode import WritingMode
from services.english_service.core.quiz_mode import QuizMode


def _clear_active_writing_task(session: Session) -> None:
    """Quiz'e veya mod değişimine geçerken yazı görevi + bekleyen metni sıfırla (yanlış step ile sessiz ignore önlenir)."""
    if not hasattr(session, "data") or session.data is None:
        return
    for key in (
        "writing_type",
        "topic",
        "source_text",
        "min_words",
        "last_writing_feedback",
    ):
        session.data.pop(key, None)


class EnglishService:

    def __init__(self):
        self.session_manager = SessionManager()
        self.flow = FlowEngine()
        self.writing = WritingMode()
        self.quiz = QuizMode()

    def start_session(self, user_id: str):
        session = self.session_manager.create_or_get(user_id)
        return self.flow.start(session)

    def select_level(self, user_id: str, level: str):
        session = self.session_manager.get(user_id)
        if not session:
            return {"error": "Session not found"}

        return self.flow.set_level(session, level)

    def select_mode(self, user_id: str, mode: str):
        session = self.session_manager.get(user_id)
        if not session:
            return {"error": "Session not found"}

        if mode == "quiz":
            session.mode = "quiz"
            _clear_active_writing_task(session)
            return self.quiz.start_quiz(session)

        return self.flow.set_mode(session, mode)

    def select_writing_type(self, user_id: str, writing_type: str):
        session = self.session_manager.get(user_id)
        if not session:
            return {"error": "Session not found"}

        if writing_type == "topic_writing":
            return self.writing.start_topic_writing(session)

        if writing_type == "translation_writing":
            return self.writing.start_translation_writing(session)

        return {"error": "Invalid writing type"}

    def submit_writing(self, user_id: str, text: str):
        session = self.session_manager.get(user_id)
        if not session:
            return {"error": "Session not found"}

        return self.writing.evaluate(session, text)

    def submit_quiz_answer(self, user_id: str, answer: str):
        session = self.session_manager.get(user_id)
        if not session:
            return {"error": "Session not found"}

        return self.quiz.submit_answer(session, answer)