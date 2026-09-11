"""GitHub App authentication helpers.

The real production path needs a GitHub App private key configured through
environment variables. Tests use the in-memory repository and do not touch
GitHub.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .errors import RepositoryAuthError


def create_app_jwt(app_id: str, private_key_path: Path) -> str:
    try:
        import jwt
    except ImportError as exc:
        raise RepositoryAuthError("PyJWT ist fuer echte GitHub-App-Authentifizierung erforderlich.") from exc
    now = datetime.now(timezone.utc)
    payload = {
        "iat": int((now - timedelta(seconds=60)).timestamp()),
        "exp": int((now + timedelta(minutes=9)).timestamp()),
        "iss": app_id,
    }
    private_key = private_key_path.read_text(encoding="utf-8")
    return jwt.encode(payload, private_key, algorithm="RS256")
