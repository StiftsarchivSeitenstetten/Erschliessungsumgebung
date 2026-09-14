import io
import base64
import unittest
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from http.client import IncompleteRead
from unittest.mock import patch

from backend.github.client import GitHubClient
from backend.github.github_repository import GitHubDataRepository
from backend.github.errors import RepositoryAuthError, RepositoryConflictError, RepositoryEmptyError, RepositoryError


def http_error(status: int, body: str) -> HTTPError:
    return HTTPError(
        url="https://api.github.com/repos/example/repo/git/ref/heads/main",
        code=status,
        msg="error",
        hdrs={},
        fp=io.BytesIO(body.encode("utf-8")),
    )


class GitHubClientTest(unittest.TestCase):
    def test_incomplete_download_is_a_repository_error(self):
        with patch("backend.github.client.urlopen", side_effect=IncompleteRead(b"partial", 20)):
            with self.assertRaises(RepositoryError):
                GitHubClient("test").request("GET", "/test")

    def test_large_blob_cache_checks_fresh_revision_and_never_masks_errors(self):
        repository = GitHubDataRepository.__new__(GitHubDataRepository)
        repository.settings = type("Settings", (), {"github_data_owner":"example", "github_data_repo":"repo", "github_data_branch":"integration-test"})()
        first = "a" * 1_000_000
        second = "b" * 1_000_000
        def metadata(sha):
            return {"type":"file", "sha":sha, "git_url":f"https://api.github.com/repos/example/repo/git/blobs/{sha}"}
        with patch.object(repository, "request", side_effect=[metadata("a"), {"content":base64.b64encode(first.encode()).decode()}, metadata("a"), metadata("b"), {"content":base64.b64encode(second.encode()).decode()}, RepositoryError("network")]) as request:
            self.assertEqual(repository.read_file("index.json").content, first)
            self.assertEqual(repository.read_file("index.json").content, first)
            self.assertEqual(repository.read_file("index.json").content, second)
            with self.assertRaises(RepositoryError):
                repository.read_file("index.json")
            self.assertEqual(request.call_count, 6)
        self.assertEqual(repository._large_file_cache.revision, "b")

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
        repository.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        file = repository.read_file("indexes/fotos.json")
        self.assertEqual(file.content, '{"schema_version":1}')
        self.assertEqual(repository.client.paths[-1], "/repos/example/repo/git/blobs/blob-sha")

    def test_valid_installation_token_is_reused(self):
        repository = token_repository(expires_in=timedelta(hours=1))
        response = repository.request("GET", "/ok")
        self.assertEqual(response, {"ok": True})
        self.assertEqual(repository.refresh_count, 0)
        self.assertEqual(repository.client.calls, [("GET", "/ok", None)])

    def test_token_near_expiry_is_refreshed_before_request(self):
        repository = token_repository(expires_in=timedelta(minutes=4, seconds=59))
        response = repository.request("GET", "/ok")
        self.assertEqual(response, {"ok": True})
        self.assertEqual(repository.refresh_count, 1)
        self.assertEqual(repository.client.token_label, "refreshed-1")

    def test_expired_token_is_refreshed_before_request(self):
        repository = token_repository(expires_in=timedelta(seconds=-1))
        response = repository.request("GET", "/ok")
        self.assertEqual(response, {"ok": True})
        self.assertEqual(repository.refresh_count, 1)
        self.assertEqual(repository.client.token_label, "refreshed-1")

    def test_auth_error_refreshes_and_retries_once(self):
        first_client = StaticClient([RepositoryAuthError("abgelaufen")], token_label="old")
        repository = token_repository(client=first_client, refresh_responses=[{"ok": True}])
        response = repository.request("GET", "/needs-token")
        self.assertEqual(response, {"ok": True})
        self.assertEqual(repository.refresh_count, 1)
        self.assertEqual(first_client.calls, [("GET", "/needs-token", None)])
        self.assertEqual(repository.client.calls, [("GET", "/needs-token", None)])

    def test_auth_error_after_retry_is_raised(self):
        first_client = StaticClient([RepositoryAuthError("abgelaufen")], token_label="old")
        repository = token_repository(client=first_client, refresh_responses=[RepositoryAuthError("immer noch falsch")])
        with self.assertRaises(RepositoryAuthError):
            repository.request("GET", "/needs-token")
        self.assertEqual(repository.refresh_count, 1)

    def test_repository_read_and_write_operations_still_work(self):
        repository = GitHubDataRepository.__new__(GitHubDataRepository)
        repository.settings = type("Settings", (), {
            "github_data_owner": "example",
            "github_data_repo": "repo",
            "github_data_branch": "main",
        })()
        repository.client = GitDataClient()
        repository.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        self.assertEqual(repository.get_branch_head(), "base")
        self.assertEqual(repository.read_file("data/fotos/foto-000001.md").content, "hello")
        new_head = repository.commit_files(expected_head="base", files={"data/fotos/foto-000002.md": "new"}, message="Test")
        self.assertEqual(new_head, "commit-new")
        self.assertIn(("PATCH", "/repos/example/repo/git/refs/heads/main", {"sha": "commit-new", "force": False}), repository.client.calls)


class StaticClient:
    api_base = "https://api.github.com"

    def __init__(self, responses, token_label="token"):
        self.responses = list(responses)
        self.calls = []
        self.token_label = token_label

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if not self.responses:
            return {"ok": True}
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TokenRepository(GitHubDataRepository):
    def __init__(self, *, client, expires_at, refresh_responses):
        self.settings = type("Settings", (), {
            "github_data_owner": "example",
            "github_data_repo": "repo",
            "github_data_branch": "main",
        })()
        self.client = client
        self.token_expires_at = expires_at
        self.refresh_count = 0
        self.refresh_responses = list(refresh_responses)
        self.fixed_now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

    def now(self):
        return self.fixed_now

    def refresh_installation_token(self):
        self.refresh_count += 1
        responses = self.refresh_responses.pop(0) if self.refresh_responses else [{"ok": True}]
        if isinstance(responses, (dict, Exception)):
            responses = [responses]
        self.client = StaticClient(responses, token_label=f"refreshed-{self.refresh_count}")
        self.token_expires_at = self.fixed_now + timedelta(hours=1)


def token_repository(*, expires_in=timedelta(hours=1), client=None, refresh_responses=None):
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    return TokenRepository(
        client=client or StaticClient([{"ok": True}]),
        expires_at=now + expires_in,
        refresh_responses=refresh_responses or [[{"ok": True}]],
    )


class GitDataClient:
    api_base = "https://api.github.com"

    def __init__(self):
        self.calls = []
        self.head = "base"

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/repos/example/repo/git/ref/heads/main":
            return {"object": {"sha": self.head}}
        if method == "GET" and path == "/repos/example/repo/contents/data/fotos/foto-000001.md?ref=main":
            return {"type": "file", "content": base64.b64encode(b"hello").decode("ascii"), "sha": "file-sha"}
        if method == "GET" and path == "/repos/example/repo/git/commits/base":
            return {"tree": {"sha": "tree-base"}}
        if method == "POST" and path == "/repos/example/repo/git/blobs":
            return {"sha": "blob-new"}
        if method == "POST" and path == "/repos/example/repo/git/trees":
            return {"sha": "tree-new"}
        if method == "POST" and path == "/repos/example/repo/git/commits":
            return {"sha": "commit-new"}
        if method == "PATCH" and path == "/repos/example/repo/git/refs/heads/main":
            self.head = payload["sha"]
            return {}
        raise AssertionError((method, path, payload))


if __name__ == "__main__":
    unittest.main()
