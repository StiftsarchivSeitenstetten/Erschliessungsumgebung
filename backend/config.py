"""Runtime configuration for the authentication backend."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    cookie_secure: bool
    cookie_name: str = "erschliessung_session"
    csrf_cookie_name: str = "erschliessung_csrf"
    session_lifetime_seconds: int = 60 * 60 * 8
    app_dir: Path = ROOT / "app"
    config_dir: Path = ROOT / "config"
    github_app_id: str | None = None
    github_installation_id: str | None = None
    github_private_key_path: Path | None = None
    github_data_owner: str = "StiftsarchivSeitenstetten"
    github_data_repo: str = "Erschliessungsdaten"
    github_data_branch: str = "main"


def get_settings() -> Settings:
    load_env_file()
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'var' / 'auth.sqlite3'}")
    private_key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH")
    return Settings(
        database_url=database_url,
        cookie_secure=_bool_from_env("COOKIE_SECURE", True),
        github_app_id=os.getenv("GITHUB_APP_ID") or None,
        github_installation_id=os.getenv("GITHUB_INSTALLATION_ID") or None,
        github_private_key_path=Path(private_key_path) if private_key_path else None,
        github_data_owner=os.getenv("GITHUB_DATA_OWNER", "StiftsarchivSeitenstetten"),
        github_data_repo=os.getenv("GITHUB_DATA_REPO", "Erschliessungsdaten"),
        github_data_branch=os.getenv("GITHUB_DATA_BRANCH", "main"),
    )
