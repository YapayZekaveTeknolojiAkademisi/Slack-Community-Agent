from typing import Dict, Optional
import time

from .models import Session


class SessionManager:
    def __init__(self, timeout: int = 900):
        self.sessions: Dict[str, Session] = {}
        self.timeout = timeout

    def create_or_get(self, user_id: str) -> Session:
        if user_id not in self.sessions:
            self.sessions[user_id] = Session(user_id)
        return self.sessions[user_id]

    def get(self, user_id: str) -> Optional[Session]:
        return self.sessions.get(user_id)

    def delete(self, user_id: str):
        if user_id in self.sessions:
            del self.sessions[user_id]

    def cleanup(self):
        now = time.time()
        expired = [
            uid for uid, session in self.sessions.items()
            if now - session.last_activity > self.timeout
        ]
        for uid in expired:
            del self.sessions[uid]