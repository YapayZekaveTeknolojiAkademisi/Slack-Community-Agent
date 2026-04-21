from services.english_service.models import Session
from services.english_service.core.writing_analyzer import WritingAnalyzer
from services.english_service.core.writing_task_generator import WritingTaskGenerator


class WritingMode:
    def __init__(self):
        self.analyzer = WritingAnalyzer()
        self.task_generator = WritingTaskGenerator()

    def start_topic_writing(self, session: Session):
        level = session.level
        last_topic = session.data.get("last_topic")
        task = self.task_generator.generate_topic_task(level, last_topic=last_topic)

        session.data["writing_type"] = "topic_writing"
        session.data["topic"] = task["topic"]
        session.data["last_topic"] = task["topic"]
        session.data["min_words"] = task["min_words"]
        session.step = "waiting_writing"

        return {
            "type": "writing_task",
            "message": f"Write about: {task['topic']}\nMinimum {task['min_words']} words."
        }

    def start_translation_writing(self, session: Session):
        level = session.level
        last_source_text = session.data.get("last_source_text")
        task = self.task_generator.generate_translation_task(level, last_source_text=last_source_text)

        session.data["writing_type"] = "translation_writing"
        session.data["source_text"] = task["source_text"]
        session.data["last_source_text"] = task["source_text"]
        session.data["min_words"] = task["min_words"]
        session.step = "waiting_writing"

        return {
            "type": "writing_task",
            "message": (
                "Translate this Turkish text into English:\n"
                f"{task['source_text']}\n"
                f"Minimum {task['min_words']} words."
            )
        }

    def evaluate(self, session: Session, user_text: str):
        return self.analyzer.analyze(session, user_text)