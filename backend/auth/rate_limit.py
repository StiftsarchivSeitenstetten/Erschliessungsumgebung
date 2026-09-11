"""Small in-process login rate-limit preparation for Phase 2A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class LoginAttempt:
    count: int
    reset_at: datetime


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 10, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window = timedelta(seconds=window_seconds)
        self._attempts: dict[str, LoginAttempt] = {}

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def is_limited(self, key: str) -> bool:
        attempt = self._attempts.get(key)
        if not attempt:
            return False
        if attempt.reset_at <= self._now():
            self._attempts.pop(key, None)
            return False
        return attempt.count >= self.max_attempts

    def record_failure(self, key: str) -> None:
        now = self._now()
        attempt = self._attempts.get(key)
        if not attempt or attempt.reset_at <= now:
            self._attempts[key] = LoginAttempt(count=1, reset_at=now + self.window)
        else:
            attempt.count += 1

    def record_success(self, key: str) -> None:
        self._attempts.pop(key, None)


login_rate_limiter = LoginRateLimiter()
