"""Teslimat penceresi (10 dk) — kalıcı değil; süre challenge_id → UTC deadline."""

from __future__ import annotations

import threading
from datetime import datetime, timezone


class SubmissionWindowState:
    def __init__(self) -> None:
        self._deadlines: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def is_submission_open(self, challenge_id: str) -> bool:
        with self._lock:
            deadline = self._deadlines.get(challenge_id)
        if deadline is None:
            return False
        return datetime.now(timezone.utc) < deadline

    def set_submission_deadline(self, challenge_id: str, deadline: datetime) -> None:
        with self._lock:
            self._deadlines[challenge_id] = deadline

    def clear_submission_deadline(self, challenge_id: str) -> None:
        with self._lock:
            self._deadlines.pop(challenge_id, None)


active_state = SubmissionWindowState()
