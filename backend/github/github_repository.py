"""GitHub App backed repository adapter.

This adapter is intentionally small and isolated. It is configured only through
environment variables and can be replaced by InMemoryGitRepository in tests.
"""

from __future__ import annotations

import base64

from ..config import Settings
from .app_auth import create_app_jwt
from .client import GitHubClient
from .errors import RepositoryConflictError, RepositoryNotFoundError
from .repository import RepositoryFile


class GitHubDataRepository:
    def __init__(self, settings: Settings) -> None:
        if not settings.github_app_id or not settings.github_installation_id or not settings.github_private_key_path:
            raise RuntimeError("GitHub-App-Konfiguration ist unvollstaendig.")
        self.settings = settings
        app_jwt = create_app_jwt(settings.github_app_id, settings.github_private_key_path)
        app_client = GitHubClient(app_jwt)
        response = app_client.request(
            "POST",
            f"/app/installations/{settings.github_installation_id}/access_tokens",
        )
        self.client = GitHubClient(response["token"])

    @property
    def repo_path(self) -> str:
        return f"/repos/{self.settings.github_data_owner}/{self.settings.github_data_repo}"

    def get_branch_head(self) -> str:
        response = self.client.request("GET", f"{self.repo_path}/git/ref/heads/{self.settings.github_data_branch}")
        return response["object"]["sha"]

    def read_file(self, path: str) -> RepositoryFile:
        response = self.client.request(
            "GET",
            f"{self.repo_path}/contents/{path}?ref={self.settings.github_data_branch}",
        )
        if response.get("type") != "file":
            raise RepositoryNotFoundError(path)
        encoded = response.get("content") or ""
        if not encoded and response.get("git_url"):
            blob_response = self.client.request("GET", response["git_url"].removeprefix(self.client.api_base))
            encoded = blob_response["content"]
        content = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        return RepositoryFile(path=path, content=content, revision=response["sha"])

    def list_directory(self, path: str) -> list[RepositoryFile]:
        response = self.client.request(
            "GET",
            f"{self.repo_path}/contents/{path}?ref={self.settings.github_data_branch}",
        )
        if not isinstance(response, list):
            raise RepositoryNotFoundError(path)
        files: list[RepositoryFile] = []
        for item in response:
            if item.get("type") != "file":
                continue
            file_response = self.client.request("GET", item["url"].removeprefix(self.client.api_base))
            content = base64.b64decode(file_response["content"].encode("ascii")).decode("utf-8")
            files.append(RepositoryFile(path=item["path"], content=content, revision=item["sha"]))
        return files

    def commit_files(self, *, expected_head: str, files: dict[str, str], message: str) -> str:
        current_head = self.get_branch_head()
        if current_head != expected_head:
            raise RepositoryConflictError("Branch wurde parallel aktualisiert.")

        base_commit = self.client.request("GET", f"{self.repo_path}/git/commits/{expected_head}")
        tree_items = []
        for path, content in files.items():
            blob = self.client.request(
                "POST",
                f"{self.repo_path}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self.client.request(
            "POST",
            f"{self.repo_path}/git/trees",
            {"base_tree": base_commit["tree"]["sha"], "tree": tree_items},
        )
        commit = self.client.request(
            "POST",
            f"{self.repo_path}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [expected_head]},
        )
        self.client.request(
            "PATCH",
            f"{self.repo_path}/git/refs/heads/{self.settings.github_data_branch}",
            {"sha": commit["sha"], "force": False},
        )
        return commit["sha"]
