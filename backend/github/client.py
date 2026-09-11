"""Minimal GitHub HTTP client for the production repository adapter."""

from __future__ import annotations

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import (
    RepositoryAuthError,
    RepositoryConflictError,
    RepositoryEmptyError,
    RepositoryError,
    RepositoryNotFoundError,
)


class GitHubClient:
    api_base = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.api_base}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                content = response.read().decode("utf-8")
                return json.loads(content) if content else {}
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            exc.close()
            try:
                error_payload = json.loads(error_body) if error_body else {}
            except json.JSONDecodeError:
                error_payload = {}
            message = str(error_payload.get("message", ""))
            if exc.code == 401 or exc.code == 403:
                raise RepositoryAuthError("GitHub-Zugriff nicht autorisiert.") from exc
            if exc.code == 404:
                raise RepositoryNotFoundError(path) from exc
            if exc.code == 409 and message == "Git Repository is empty.":
                raise RepositoryEmptyError("Git-Repository ist leer.") from exc
            if exc.code == 409 or exc.code == 422:
                raise RepositoryConflictError("GitHub-Ref wurde parallel aktualisiert.") from exc
            raise RepositoryError(f"GitHub-Fehler {exc.code}") from exc
        except URLError as exc:
            raise RepositoryError("GitHub ist nicht erreichbar.") from exc

    @staticmethod
    def decode_content(encoded: str) -> str:
        return base64.b64decode(encoded.encode("ascii")).decode("utf-8")

    @staticmethod
    def encode_content(content: str) -> str:
        return base64.b64encode(content.encode("utf-8")).decode("ascii")
