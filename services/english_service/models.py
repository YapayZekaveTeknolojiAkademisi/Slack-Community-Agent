from typing import Optional, List
import time

class Session:
    def __init__(self, user_id: str):
        self.user_id = user_id

        # state
        self.level: Optional[str] = None
        self.mode: Optional[str] = None
        self.step: Optional[str] = "start"

        # data
        self.context: List[str] = []

        # Bütün 'ensure' mantıkları artık burada merkezileşti.
        self.data: dict = {
            "recent_writing_topics": [],
            "recent_translation_sources": [],
            "previous_quiz_questions": [],
            "used_quiz_question_types": []
        }

        # timeout
        self.last_activity = time.time()

    def touch(self):
        self.last_activity = time.time()