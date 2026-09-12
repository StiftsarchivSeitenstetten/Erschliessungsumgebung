"""GitHub App backed repository adapter.

This adapter is intentionally small and isolated. It is configured only through
environment variables and can be replaced by InMemoryGitRepository in tests.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from .app_auth import create_app_jwt
from .client import GitHubClient
from .errors import RepositoryAuthError, RepositoryConflictError, RepositoryNotFoundError
from .repository import RepositoryFile


class GitHubDataRepository:
    TOKEN_REFRESH_SKEW = timedelta(minutes=5)

    def __init__(self, settings: Settings) -> None:
        if not settings.github_app_id or not settings.github_installation_id or not settings.github_private_key_path:
            raise RuntimeError("GitHub-App-Konfiguration ist unvollstaendig.")
        self.settings = settings
        self.client: GitHubClient | None = None
        self.token_expires_at: datetime | None = None
        self.refresh_installation_token()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def refresh_installation_token(self) -> None:
        app_jwt = create_app_jwt(self.settings.github_app_id, self.settings.github_private_key_path)
        app_client = GitHubClient(app_jwt)
        response = app_client.request(
            "POST",
            f"/app/installations/{self.settings.github_installation_id}/access_tokens",
        )
        self.client = GitHubClient(response["token"])
        self.token_expires_at = self.parse_expires_at(response["expires_at"])

    @staticmethod
    def parse_expires_at(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    def ensure_installation_token(self) -> None:
        if self.client is None or self.token_expires_at is None:
            self.refresh_installation_token()
            return
        if self.now() + self.TOKEN_REFRESH_SKEW >= self.token_expires_at:
            self.refresh_installation_token()

    def request(self, method: str, path: str, payload: dict | None = None, *, retry_auth: bool = True) -> dict[str, Any]:
        self.ensure_installation_token()
        assert self.client is not None
        try:
            return self.client.request(method, path, payload)
        except RepositoryAuthError:
            if not retry_auth:
                raise
            self.refresh_installation_token()
            assert self.client is not None
            return self.client.request(method, path, payload)

    @property
    def repo_path(self) -> str:
        return f"/repos/{self.settings.github_data_owner}/{self.settings.github_data_repo}"

    def get_branch_head(self) -> str:
        response = self.request("GET", f"{self.repo_path}/git/ref/heads/{self.settings.github_data_branch}")
        return response["object"]["sha"]

    def read_file(self, path: str) -> RepositoryFile:
        response = self.request(
            "GET",
            f"{self.repo_path}/contents/{path}?ref={self.settings.github_data_branch}",
        )
        if response.get("type") != "file":
            raise RepositoryNotFoundError(path)
        encoded = response.get("content") or ""
        if not encoded and response.get("git_url"):
            blob_response = self.request("GET", response["git_url"].removeprefix(GitHubClient.api_base))
            encoded = blob_response["content"]
        content = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        return RepositoryFile(path=path, content=content, revision=response["sha"])

    def list_directory(self, path: str) -> list[RepositoryFile]:
        response = self.request(
            "GET",
            f"{self.repo_path}/contents/{path}?ref={self.settings.github_data_branch}",
        )
        if not isinstance(response, list):
            raise RepositoryNotFoundError(path)
        files: list[RepositoryFile] = []
        for item in response:
            if item.get("type") != "file":
                continue
            file_response = self.request("GET", item["url"].removeprefix(GitHubClient.api_base))
            content = base64.b64decode(file_response["content"].encode("ascii")).decode("utf-8")
            files.append(RepositoryFile(path=item["path"], content=content, revision=item["sha"]))
        return files

    def commit_files(self, *, expected_head: str, files: dict[str, str], message: str) -> str:
        current_head = self.get_branch_head()
        if current_head != expected_head:
            raise RepositoryConflictError("Branch wurde parallel aktualisiert.")

        base_commit = self.request("GET", f"{self.repo_path}/git/commits/{expected_head}")
        tree_items = []
        for path, content in files.items():
            blob = self.request(
                "POST",
                f"{self.repo_path}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self.request(
            "POST",
            f"{self.repo_path}/git/trees",
            {"base_tree": base_commit["tree"]["sha"], "tree": tree_items},
        )
        commit = self.request(
            "POST",
            f"{self.repo_path}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [expected_head]},
        )
        self.request(
            "PATCH",
            f"{self.repo_path}/git/refs/heads/{self.settings.github_data_branch}",
            {"sha": commit["sha"], "force": False},
        )
        return commit["sha"]
