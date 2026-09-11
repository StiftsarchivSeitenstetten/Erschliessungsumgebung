import io
import base64
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from backend.github.client import GitHubClient
from backend.github.github_repository import GitHubDataRepository
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

    def test_repository_read_file_follows_git_blob_for_large_content(self):
        class FakeClient:
            api_base = "https://api.github.com"

            def __init__(self):
                self.paths = []

            def request(self, method, path, payload=None):
                self.paths.append(path)
                if path.startswith("/repos/example/repo/contents/indexes/fotos.json"):
                    return {
                        "type": "file",
                        "content": "",
                        "sha": "contents-sha",
                        "git_url": "https://api.github.com/repos/example/repo/git/blobs/blob-sha",
                    }
                if path == "/repos/example/repo/git/blobs/blob-sha":
                    return {"content": base64.b64encode(b'{"schema_version":1}').decode("ascii")}
                raise AssertionError(path)

        repository = GitHubDataRepository.__new__(GitHubDataRepository)
        repository.settings = type("Settings", (), {
            "github_data_owner": "example",
            "github_data_repo": "repo",
            "github_data_branch": "main",
        })()
        repository.client = FakeClient()

        file = repository.read_file("indexes/fotos.json")
        self.assertEqual(file.content, '{"schema_version":1}')
        self.assertEqual(repository.client.paths[-1], "/repos/example/repo/git/blobs/blob-sha")


if __name__ == "__main__":
    unittest.main()
