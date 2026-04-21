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
        self.data: dict = {}

        # timeout
        self.last_activity = time.time()

    def touch(self):
        self.last_activity = time.time()