"""Opt-in live test: python -m integration_tests.generic_github --write --report PATH.

Requires GENERIC_GITHUB_INTEGRATION=1. Never imported by unittest discovery.
Only the test process enables generic writes; no production flag is changed.
"""

from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from unittest.mock import patch

from backend.config import ROOT, get_settings
from backend.github.errors import RepositoryConflictError, RepositoryNotFoundError
from backend.github.github_repository import GitHubDataRepository
from backend.records.generic_read import parse_record_content
from backend.records.runtime import RecordRuntime
from .generic_fixture import DATA_DIR, MODULE_KEY, STATE_PATH, make_module, sample_payload


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def check_target(settings):
    check((settings.github_data_owner, settings.github_data_repo, settings.github_data_branch) ==
          ("StiftsarchivSeitenstetten", "Erschliessungsdaten", "integration-test"),
          "Abbruch: wirksames Datenziel ist nicht Erschliessungsdaten/integration-test.")


def check_paths(files):
    check(bool(files), "Leerer Testcommit.")
    for path in files:
        check(path == STATE_PATH or re.fullmatch(r"data/integration-test/integration-[0-9]{4,}\.md", path),
              f"Schreibpfad ausserhalb der Testflaeche: {path}")


class GuardedRepository(GitHubDataRepository):
    """Use the real adapter with a test-only allowlist around every mutation."""

    def __init__(self, settings):
        check_target(settings)
        self.main_before = None
        self.writes_enabled = False
        self.commits = []
        super().__init__(settings)

    def main_head(self):
        return super().request("GET", f"{self.repo_path}/git/ref/heads/main")["object"]["sha"]

    def guard(self):
        check_target(self.settings)
        check_target(get_settings())
        check(git("branch", "--show-current") == "generic-module-architecture-v1", "Falscher Anwendungsbranch.")
        check(self.writes_enabled and os.getenv("GENERIC_GITHUB_INTEGRATION") == "1", "Testschreiben nicht aktiviert.")
        check(self.main_before is not None and self.main_head() == self.main_before, "Daten-main wurde veraendert; Abbruch.")

    def request(self, method, path, payload=None, **kwargs):
        if method != "GET":
            self.guard()
            allowed = {
                ("POST", f"{self.repo_path}/git/blobs"),
                ("POST", f"{self.repo_path}/git/trees"),
                ("POST", f"{self.repo_path}/git/commits"),
                ("PATCH", f"{self.repo_path}/git/refs/heads/integration-test"),
            }
            check((method, path) in allowed, "GitHub-Mutation nicht erlaubt.")
            if method == "PATCH":
                check(payload.get("force") is False, "Force-Update ist verboten.")
        return super().request(method, path, payload, **kwargs)

    def commit_files(self, *, expected_head, files, message):
        self.guard()
        self.check_files(files)
        head = super().commit_files(expected_head=expected_head, files=files, message=message)
        details = self.request("GET", f"{self.repo_path}/commits/{head}")
        check({item["filename"] for item in details["files"]} == set(files), "Unerwartete Dateien im Commit.")
        check([parent["sha"] for parent in details["parents"]] == [expected_head], "Unerwarteter Commit-Elternstand.")
        self.commits.append({"head": head, "files": sorted(files)})
        print(json.dumps({"successful_commit": self.commits[-1]}), flush=True)
        return head

    def check_files(self, files):
        check_paths(files)


def protected_tree(repository, head):
    """Compare all sibling trees/blobs, without enumerating 10,330 photos."""
    def tree(sha):
        result = repository.request("GET", f"{repository.repo_path}/git/trees/{sha}")
        check(not result.get("truncated"), "Git-Baum ist unvollstaendig.")
        return {entry["path"]: entry["sha"] for entry in result["tree"]}
    root = tree(head)
    data = tree(root["data"]) if "data" in root else {}
    state = tree(root["state"]) if "state" in root else {}
    return {
        "root": {key: value for key, value in root.items() if key not in {"data", "state"}},
        "data": {key: value for key, value in data.items() if key != "integration-test"},
        "state": {key: value for key, value in state.items() if key != "integration-test.json"},
    }


def exercise(repository, module, report):
    # Imports happen only after the CLI has selected a temporary SQLite database.
    from fastapi.testclient import TestClient
    from backend.auth.service import create_user
    from backend.database import SessionLocal
    from backend.main import create_app
    from backend.models import ModuleAccess

    app = create_app()
    app.state.data_repository = repository
    password = "IsolierterTest123!"
    with SessionLocal() as db:
        for role in ("redaktion", "ehrenamtlich"):
            user = create_user(db, username=f"integration-{role}", display_name=f"Integration {role}",
                               email=f"{role}@integration.invalid", role=role,
                               ui_profile="redaktion" if role == "redaktion" else "ehrenamt-standard",
                               modules=[], password=password)
            user.module_access.append(ModuleAccess(module_key=MODULE_KEY))
        db.commit()

    def module_lookup(key):
        if key != MODULE_KEY:
            raise KeyError(key)
        return module

    def ok(response, status=200):
        check(response.status_code == status, f"HTTP {response.status_code}, erwartet {status}: {response.text}")
        return response.json()

    with patch("backend.routes.modules.get_module", side_effect=module_lookup), TestClient(app) as client:
        def login(role):
            ok(client.post("/api/auth/login", json={"login": f"integration-{role}", "password": password}))
            me = ok(client.get("/api/auth/me"))
            return {"X-CSRF-Token": client.cookies.get(me["csrf_cookie_name"])}

        headers = login("redaktion")
        url = f"/api/modules/{MODULE_KEY}/records"
        payload = sample_payload()
        ok(client.post(url, json={"operation_id": "generic-write-disabled-check", "record": payload}, headers=headers), 503)
        app.state.generic_write_modules = {MODULE_KEY}

        try:
            state_file = repository.read_file(STATE_PATH)
        except RepositoryNotFoundError:
            # Only this isolated test module may bootstrap counters at one.
            try:
                repository.list_directory(DATA_DIR)
            except RepositoryNotFoundError:
                pass
            else:
                raise RuntimeError("Testverzeichnis existiert ohne State; keine Zaehler schaetzen.")
            repository.commit_files(expected_head=repository.get_branch_head(),
                                    files={STATE_PATH: json.dumps({"next_record_id": 1, "next_signature_number": {"T": 1}}) + "\n"},
                                    message="Initialisiere isolierten generischen Integrationstest-State")
            state_file = repository.read_file(STATE_PATH)
        initial_state = json.loads(state_file.content)
        next_id = initial_state["next_record_id"]
        next_number = initial_state["next_signature_number"]["T"]

        def create(offset):
            result = ok(client.post(url, json={"operation_id": f"generic-live-create-{next_id + offset}", "record": payload}, headers=headers), 201)
            record_id = f"integration-{next_id + offset:04d}"
            path = f"{DATA_DIR}/{record_id}.md"
            check(result["record_id"] == record_id, "Falsche serverseitige ID.")
            file = repository.read_file(path)
            record = parse_record_content(file.content)
            RecordRuntime(module).validate(record)
            check(file.content.startswith("---\n"), "YAML-Frontmatter fehlt.")
            check(record["signatur"]["anzeige"] == f"INTEGRATION.T.{next_number + offset}", "Falsche Signatur.")
            check(record["daten"] == payload["daten"], "Fachliche Daten weichen ab.")
            check(record["technik"]["erstellt_am"] and record["technik"]["erstellt_von"] == "integration-redaktion", "Erstellungsmetadaten fehlen.")
            check(record["technik"]["geaendert_am"] is None and record["technik"]["geaendert_von"] is None, "Falsche Aenderungsmetadaten bei Create.")
            state = json.loads(repository.read_file(STATE_PATH).content)
            expected = deepcopy(initial_state)
            expected["next_record_id"] += offset + 1
            expected["next_signature_number"]["T"] += offset + 1
            operations = expected.setdefault("create_operations", {})
            for operation_offset in range(offset + 1):
                operation_record_id = f"integration-{next_id + operation_offset:04d}"
                operations[f"generic-live-create-{next_id + operation_offset}"] = {
                    "request": {"record": deepcopy(payload), "identity": None},
                    "record_id": operation_record_id,
                }
            check(state == expected, "State nach Create falsch.")
            check(set(repository.commits[-1]["files"]) == {path, STATE_PATH}, "Record/State nicht gemeinsam committed.")
            report.setdefault("records", []).append({"id": record_id, "signatur": record["signatur"]["anzeige"], "path": path})
            return result, record, path

        created, original, path = create(0)
        record_url = f"{url}/{created['record_id']}"
        readback = ok(client.get(record_url))
        check({key: value for key, value in created.items() if key != "operation_id"} == readback,
              "Read-back stimmt nicht mit Create-Response ueberein.")
        check(readback["record"] == RecordRuntime(module).filter_for_view(original, "redaktion"), "Read-back stimmt nicht mit YAML ueberein.")
        check(readback["meta"]["revision"] == repository.read_file(path).revision, "Revision stimmt nicht mit Git-Blob ueberein.")
        headers = login("ehrenamtlich")
        volunteer = ok(client.get(record_url))
        check("intern" not in volunteer["record"]["daten"], "Redaktionswert ist fuer Ehrenamt sichtbar.")
        check(volunteer["record"] == RecordRuntime(module).filter_for_view(original, "ehrenamtlich"), "Falscher Ehrenamts-Read-back.")
        headers = login("redaktion")
        report["readback_roles"] = ["redaktion", "ehrenamtlich"]

        state_before_update = repository.read_file(STATE_PATH)
        changed = deepcopy(payload)
        changed["daten"]["text"] = "GENERIC INTEGRATION TEST - aktualisiert"
        changed["daten"]["personen"] = [{"name": "Testperson Geaendert"}, {"name": "Testperson Drei"}]
        changed["daten"]["zeitraum"]["to"]["year"] = 1902
        updated = ok(client.put(record_url, json={"record": changed, "base_revision": readback["meta"]["revision"]}, headers=headers))
        current = parse_record_content(repository.read_file(path).content)
        check(current["daten"] == changed["daten"], "Update nicht gespeichert.")
        check(current["id"] == original["id"] and current["signatur"] == original["signatur"], "ID/Signatur bei Update veraendert.")
        for key in ("erstellt_am", "erstellt_von"):
            check(current["technik"][key] == original["technik"][key], "Erstellungsmetadaten veraendert.")
        check(current["technik"]["geaendert_am"] and current["technik"]["geaendert_von"] == "integration-redaktion", "Aenderungsmetadaten fehlen.")
        check(updated["meta"]["revision"] != readback["meta"]["revision"], "Revision nicht geaendert.")
        check(repository.read_file(STATE_PATH) == state_before_update, "Update hat State geaendert.")
        check(repository.commits[-1]["files"] == [path], "Update hat weitere Dateien geaendert.")
        check(ok(client.get(record_url)) == updated, "Update-Read-back falsch.")
        report["update"] = {"revision_a": readback["meta"]["revision"], "revision_b": updated["meta"]["revision"]}

        def reject(label, method, target, body, expected):
            before_head = repository.get_branch_head()
            before_state = repository.read_file(STATE_PATH)
            before_record = repository.read_file(path)
            if method == "POST":
                body = {"operation_id": f"generic-rejected-{label}", **body}
            ok(client.request(method, target, json=body, headers=headers), expected)
            check(repository.get_branch_head() == before_head, f"Commit bei Fehlerfall {label}.")
            check(repository.read_file(STATE_PATH) == before_state, f"State bei Fehlerfall {label}.")
            check(repository.read_file(path) == before_record, f"Record bei Fehlerfall {label}.")
            check(repository.main_head() == repository.main_before, "main wurde veraendert.")
            report.setdefault("rejected", {})[label] = expected

        reject("stale_revision", "PUT", record_url, {"record": changed, "base_revision": readback["meta"]["revision"]}, 409)
        reject("missing_revision", "PUT", record_url, {"record": changed}, 422)
        bad = deepcopy(payload)
        bad["daten"]["text"] = None
        reject("schema", "POST", url, {"record": bad}, 422)
        bad = deepcopy(payload)
        bad["daten"]["unknown"] = "x"
        reject("unknown_field", "POST", url, {"record": bad}, 422)
        reject("readonly", "POST", url, {"record": {**payload, "signatur": {"anzeige": "forged"}}}, 403)
        reject("server_metadata", "POST", url, {"record": {**payload, "technik": {"erstellt_von": "forged"}}}, 403)
        reject("client_id", "POST", url, {"record": {**payload, "id": "integration-9999"}}, 403)
        headers = login("ehrenamtlich")
        reject("hidden_field", "POST", url, {"record": payload}, 403)
        headers = login("redaktion")

        stale_head = repository.get_branch_head()
        create(1)
        before_head = repository.get_branch_head()
        before_state = repository.read_file(STATE_PATH)
        try:
            repository.commit_files(expected_head=stale_head, files={STATE_PATH: before_state.content}, message="Muss als Ref-Konflikt abgewiesen werden")
        except RepositoryConflictError:
            pass
        else:
            raise RuntimeError("Veralteter Branch-Head wurde nicht abgewiesen.")
        check(repository.get_branch_head() == before_head and repository.read_file(STATE_PATH) == before_state, "Ref-Konflikt hat Branch veraendert.")
        report["ref_conflict"] = "rejected before blob/tree/commit creation"
        report["final_state"] = json.loads(before_state.content)
        report["list_count"] = len(ok(client.get(url))["records"])
        app.state.generic_write_modules = set()


def run(report_path):
    settings = get_settings()
    check_target(settings)
    check(git("branch", "--show-current") == "generic-module-architecture-v1", "Falscher Anwendungsbranch.")
    check(not git("ls-files", ".env"), ".env ist versioniert.")
    report = {"code_head": git("rev-parse", "HEAD"), "effective_branch": settings.github_data_branch}
    repository = GuardedRepository(settings)
    report["main_before"] = repository.main_head()
    report["integration_before"] = repository.get_branch_head()
    repository.main_before = report["main_before"]
    protected_before = protected_tree(repository, report["integration_before"])
    print(json.dumps(report, indent=2), flush=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix="generic-github-integration-") as directory:
            temporary = Path(directory)
            module = make_module(temporary)
            with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{temporary / 'auth.sqlite3'}", "COOKIE_SECURE": "false"}):
                repository.writes_enabled = True
                exercise(repository, module, report)
        report["result"] = "passed"
    finally:
        repository.writes_enabled = False
        report["commits"] = repository.commits
        report["main_after"] = repository.main_head()
        report["integration_after"] = repository.get_branch_head()
        report["protected_trees_unchanged"] = protected_before == protected_tree(repository, report["integration_after"])
        if report["integration_before"] != report["integration_after"]:
            comparison = repository.request("GET", f"{repository.repo_path}/compare/{report['integration_before']}...{report['integration_after']}")
            report["changed_files"] = [item["filename"] for item in comparison["files"]]
            report["history_matches_test_commits"] = [item["sha"] for item in comparison["commits"]] == [item["head"] for item in repository.commits]
        else:
            report["changed_files"] = []
            report["history_matches_test_commits"] = not repository.commits
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        check(report["main_before"] == report["main_after"], "main-Head nicht unveraendert.")
        check(report["protected_trees_unchanged"], "Dateien ausserhalb Testflaeche geaendert.")
        check(report["history_matches_test_commits"], "Fremde oder unerwartete Commits im Testzeitraum.")
        if report["changed_files"]:
            check_paths(report["changed_files"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Explizit nur integration-test beschreiben")
    mode.add_argument("--offline", action="store_true", help="Nur In-Memory; kein GitHub-Zugriff")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.offline:
        run_offline(args.report)
        return
    check(args.write and os.getenv("GENERIC_GITHUB_INTEGRATION") == "1", "Erfordert --write und GENERIC_GITHUB_INTEGRATION=1.")
    run(args.report)


def run_offline(report_path):
    from backend.github.repository import InMemoryGitRepository

    class OfflineRepository(InMemoryGitRepository):
        main_before = "unchanged-main"

        def main_head(self):
            return self.main_before

        def _revision(self, path, content):
            # GitHub file revisions are blob SHAs, independent of the branch head.
            return hashlib.sha1(content.encode("utf-8")).hexdigest()

        def list_directory(self, path):
            result = super().list_directory(path)
            if not result:
                raise RepositoryNotFoundError(path)
            return result

    report = {}
    with tempfile.TemporaryDirectory(prefix="generic-offline-") as directory:
        temporary = Path(directory)
        module = make_module(temporary)
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{temporary / 'auth.sqlite3'}", "COOKIE_SECURE": "false"}):
            exercise(OfflineRepository(), module, report)
    report["result"] = "passed"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
