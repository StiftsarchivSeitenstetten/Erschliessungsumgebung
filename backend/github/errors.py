"""Repository errors translated away from GitHub-specific details."""

from __future__ import annotations


class RepositoryError(RuntimeError):
    pass


class RepositoryNotFoundError(RepositoryError):
    pass


class RepositoryConflictError(RepositoryError):
    pass


class RepositoryAuthError(RepositoryError):
    pass
