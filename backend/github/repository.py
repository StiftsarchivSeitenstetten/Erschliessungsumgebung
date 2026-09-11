"""Repository interfaces and a deterministic in-memory adapter for tests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
from typing import Protocol

from .errors import RepositoryConflictError, RepositoryNotFoundError


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    content: str
    revision: str


class DataRepository(Protocol):
    def get_branch_head(self) -> str:
        ...

    def read_file(self, path: str) -> RepositoryFile:
        ...

    def list_directory(self, path: str) -> list[RepositoryFile]:
        ...

    def commit_files(self, *, expected_head: str, files: dict[str, str], message: str) -> str:
        ...


class InMemoryGitRepository:
    """Small optimistic Git-like repository for unit tests and local dry runs."""

    def __init__(self, files: dict[str, str] | None = None, conflict_failures: int = 0) -> None:
        self.files = dict(files or {})
        self.head = "commit-0"
        self.commits: list[dict[str, object]] = []
        self.read_file_calls: list[str] = []
        self.list_directory_calls: list[str] = []
        self._counter = itertools.count(1)
        self._conflict_failures = conflict_failures

    def get_branch_head(self) -> str:
        return self.head

    def _revision(self, path: str, content: str) -> str:
        return hashlib.sha1(f"{self.head}:{path}:{content}".encode("utf-8")).hexdigest()

    def read_file(self, path: str) -> RepositoryFile:
        self.read_file_calls.append(path)
        if path not in self.files:
            raise RepositoryNotFoundError(path)
        content = self.files[path]
        return RepositoryFile(path=path, content=content, revision=self._revision(path, content))

    def list_directory(self, path: str) -> list[RepositoryFile]:
        self.list_directory_calls.append(path)
        prefix = path.rstrip("/") + "/"
        files = [
            self.read_file(file_path)
            for file_path in sorted(self.files)
            if file_path.startswith(prefix) and "/" not in file_path[len(prefix) :]
        ]
        return files

    def commit_files(self, *, expected_head: str, files: dict[str, str], message: str) -> str:
        if self._conflict_failures > 0:
            self._conflict_failures -= 1
            self.head = f"external-{next(self._counter)}"
            raise RepositoryConflictError("Branch wurde parallel aktualisiert.")
        if expected_head != self.head:
            raise RepositoryConflictError("Branch wurde parallel aktualisiert.")
        self.files.update(files)
        self.head = f"commit-{next(self._counter)}"
        self.commits.append({"head": self.head, "message": message, "files": sorted(files)})
        return self.head
