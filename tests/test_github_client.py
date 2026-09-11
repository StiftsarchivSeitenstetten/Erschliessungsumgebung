import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from backend.github.client import GitHubClient
from backend.github.errors import RepositoryConflictError, RepositoryEmptyError


def http_error(status: int, body: str) -> HTTPError:
    return HTTPError(
        url="https://api.github.com/repos/example/repo/git/ref/heads/main",
        code=status,
        msg="error",
        hdrs={},
        fp=io.BytesIO(body.encode("utf-8")),
    )


class GitHubClientTest(unittest.TestCase):
    def test_empty_repository_409_is_not_ref_conflict(self):
        client = GitHubClient("token")
        with patch("backend.github.client.urlopen", side_effect=http_error(409, '{"message":"Git Repository is empty."}')):
            with self.assertRaises(RepositoryEmptyError):
                client.request("GET", "/repos/example/repo/git/ref/heads/main")

    def test_other_409_remains_conflict(self):
        client = GitHubClient("token")
        with patch("backend.github.client.urlopen", side_effect=http_error(409, '{"message":"Reference update failed"}')):
            with self.assertRaises(RepositoryConflictError):
                client.request("PATCH", "/repos/example/repo/git/refs/heads/main", {"sha": "x"})


if __name__ == "__main__":
    unittest.main()
