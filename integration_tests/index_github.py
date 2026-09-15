"""Explicit index rebuild/incremental integration test on integration-test only."""

import argparse
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from urllib.request import Request, urlopen
from unittest.mock import patch

from backend.config import get_settings
from backend.github.client import GitHubClient
from backend.github.errors import RepositoryConflictError, RepositoryNotFoundError
from backend.github.repository import RepositoryFile
from backend.modules import get_module
from backend.records.module_index import (
    blob_revision, build_module_index, dump_index, index_path, read_module_index, rebuild_module_index,
)
from .generic_github import GuardedRepository, check, check_target, git
from .generic_fixture import MODULE_KEY, STATE_PATH, make_module, sample_payload


class IndexRepository(GuardedRepository):
    allowed_indexes = set()
    new_record_path = None

    def check_files(self, files):
        paths = set(files)
        check(paths in [{path} for path in self.allowed_indexes] or
              paths in ({self.new_record_path, "indexes/generic/integration-test.json", STATE_PATH},
                        {self.new_record_path, "indexes/generic/integration-test.json"}),
              "Index-Testcommit ausserhalb der freigegebenen Dateien.")


class SnapshotRepository:
    """One immutable archive for rebuild input, with optimistic live commits."""

    def __init__(self, repository, head, prefixes):
        self.repository = repository
        self.head = head
        self.files = {}
        repository.ensure_installation_token()
        request = Request(f"{GitHubClient.api_base}{repository.repo_path}/tarball/{head}",
                          headers={"Authorization": f"Bearer {repository.client.token}", "Accept": "application/vnd.github+json"})
        with urlopen(request, timeout=120) as response:
            archive = response.read()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for member in tar:
                if not member.isfile() or "/" not in member.name:
                    continue
                path = member.name.split("/", 1)[1]
                if not any(path.startswith(prefix + "/") for prefix in prefixes):
                    continue
                content = tar.extractfile(member).read().decode("utf-8")
                self.files[path] = RepositoryFile(path, content, blob_revision(content))

    def get_branch_head(self):
        if self.repository.get_branch_head() != self.head:
            raise RepositoryConflictError("Snapshot-Head wurde zwischenzeitlich veraendert.")
        return self.head

    def read_file(self, path):
        return self.files[path] if path in self.files else self.repository.read_file(path)

    def list_directory(self, path):
        prefix = path.rstrip("/") + "/"
        return [file for key, file in sorted(self.files.items()) if key.startswith(prefix) and "/" not in key[len(prefix):]]

    def commit_files(self, *, expected_head, files, message):
        self.head = self.repository.commit_files(expected_head=expected_head, files=files, message=message)
        self.files.update({path: RepositoryFile(path, content, blob_revision(content)) for path, content in files.items()})
        return self.head


def make_indexed_test_module(directory):
    module = make_module(directory)
    return replace(module, storage={**module.storage, "index": {"path": "indexes/generic/integration-test.json"}},
                   search_config={"fulltext": ["daten.text", "daten.personen", "daten.zeitraum", "daten.intern"],
                                  "lookup": ["signatur.anzeige"]},
                   list_config={"columns": [{"path": "signatur.anzeige"}, {"path": "daten.text"}, {"path": "daten.intern"}],
                                "default_sort": {"path": "signatur.anzeige", "direction": "asc"}})


def api_checks(repository, photo_module, test_module, report):
    from fastapi.testclient import TestClient
    from backend.auth.service import create_user
    from backend.database import SessionLocal
    from backend.main import create_app
    from backend.models import ModuleAccess

    app = create_app()
    app.state.data_repository = repository
    with SessionLocal() as db:
        for role in ("redaktion", "ehrenamtlich"):
            user = create_user(db, username=f"index-test-{role}", display_name=f"Index-Test {role}",
                               email=f"{role}@index.invalid", role=role,
                               ui_profile="redaktion" if role == "redaktion" else "ehrenamt-standard",
                               modules=[photo_module.access_key], password="IsolierterIndex123!")
            user.module_access.append(ModuleAccess(module_key=MODULE_KEY))
        db.commit()
    def module_lookup(key):
        if key == MODULE_KEY:
            return test_module
        if key == photo_module.access_key:
            return photo_module
        raise KeyError(key)

    def ok(response, expected=200):
        check(response.status_code == expected, f"HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    with patch("backend.routes.modules.get_module", side_effect=module_lookup), TestClient(app) as client:
        def login(role):
            ok(client.post("/api/auth/login", json={"login": f"index-test-{role}", "password": "IsolierterIndex123!"}))
            me = ok(client.get("/api/auth/me"))
            return {"X-CSRF-Token": client.cookies.get(me["csrf_cookie_name"])}
        headers = login("redaktion")
        url = f"/api/modules/{photo_module.access_key}/records"
        detail = ok(client.get(url + "/foto-010332"))
        check(detail["record"]["signatur"]["anzeige"] == "9.4.2.A.8610", "Foto-ID-Zugriff falsch.")
        lookup = ok(client.get(url, params={"lookup_field": "signatur.anzeige", "lookup_value": "9.4.2.A.8610"}))["records"]
        check([item["record_id"] for item in lookup] == ["foto-010332"], "Foto-Lookup falsch.")
        fulltext = ok(client.get(url, params={"q": "INTEGRATIONSTEST nach generischem Update"}))["records"]
        check(any(item["record_id"] == "foto-010332" for item in fulltext), "Foto-Volltext fehlt.")
        listing = ok(client.get(url))["records"]
        ordered_ids = [item["record_id"] for item in listing]
        position = ordered_ids.index("foto-010332")
        report["photo_api"] = {"count": len(listing), "lookup": lookup[0]["record_id"],
                               "fulltext_hit": True, "position": position,
                               "previous": ordered_ids[position - 1] if position else None,
                               "next": ordered_ids[position + 1] if position + 1 < len(ordered_ids) else None}
        check(lookup[0]["meta"]["revision"] == detail["meta"]["revision"], "Indexrevision falsch.")
        print(json.dumps({"photo_api": report["photo_api"]}), flush=True)

        url = f"/api/modules/{MODULE_KEY}/records"
        payload = sample_payload()
        payload["daten"]["intern"] = "IndexGeheimNurRedaktion"
        initial_state = json.loads(repository.read_file(STATE_PATH).content)
        new_id = f"integration-{initial_state['next_record_id']:04d}"
        repository.new_record_path = f"data/integration-test/{new_id}.md"
        try:
            repository.read_file(repository.new_record_path)
        except RepositoryNotFoundError:
            pass
        else:
            raise RuntimeError("Test-ID bereits vorhanden.")
        app.state.generic_writes_enabled = True
        created = ok(client.post(url, json={"operation_id": f"index-live-create-{new_id}", "record": payload}, headers=headers), 201)
        check(created["record_id"] == new_id, "Falsche Test-ID.")
        check(set(repository.commits[-1]["files"]) == {repository.new_record_path, STATE_PATH, index_path(test_module)}, "Create nicht atomar mit State/Index.")
        after_create_state = repository.read_file(STATE_PATH)
        expected_state = deepcopy(initial_state)
        expected_state["next_record_id"] += 1
        expected_state["next_signature_number"]["T"] += 1
        expected_state.setdefault("create_operations", {})[f"index-live-create-{new_id}"] = {
            "request": {"record": deepcopy(payload), "identity": None},
            "record_id": new_id,
        }
        check(json.loads(after_create_state.content) == expected_state, "State-Zaehler falsch.")
        payload["daten"]["text"] = "Indexintegration aktualisiert"
        updated = ok(client.put(url + "/" + new_id, json={"record": payload, "base_revision": created["meta"]["revision"]}, headers=headers))
        check(set(repository.commits[-1]["files"]) == {repository.new_record_path, index_path(test_module)}, "Update nicht atomar mit Index.")
        check(repository.read_file(STATE_PATH) == after_create_state, "Update hat State veraendert.")
        index = read_module_index(repository, test_module)
        entry = next(item for item in index["records"] if item["record_id"] == new_id)
        check(entry["revision"] == updated["meta"]["revision"], "Update-Indexrevision falsch.")
        head = repository.get_branch_head()
        index_before = repository.read_file(index_path(test_module))
        ok(client.put(url + "/" + new_id, json={"record": payload, "base_revision": created["meta"]["revision"]}, headers=headers), 409)
        check(repository.get_branch_head() == head and repository.read_file(index_path(test_module)) == index_before, "Konflikt hat Index veraendert.")
        check(repository.read_file(STATE_PATH) == after_create_state, "Konflikt hat State veraendert.")
        headers = login("ehrenamtlich")
        check(ok(client.get(url, params={"q": "IndexGeheimNurRedaktion"}))["records"] == [], "Verstecktes Feld erzeugt Ehrenamtstreffer.")
        check(all("daten.intern" not in item["values"] for item in ok(client.get(url))["records"]), "Verstecktes Feld ausgegeben.")
        headers = login("redaktion")
        check([item["record_id"] for item in ok(client.get(url, params={"q": "IndexGeheimNurRedaktion"}))["records"]] == [new_id], "Redaktionssuche falsch.")
        report["second_module"] = {"created_id": new_id, "signature": created["record"]["signatur"]["anzeige"],
                                   "state_after": expected_state, "atomic_create_update": True, "stale_revision": 409,
                                   "hidden_field_no_hit_or_output": True}
        app.state.generic_writes_enabled = False


def run(report_path):
    settings = get_settings()
    check_target(settings)
    check(git("branch", "--show-current") == "generic-module-architecture-v1", "Falscher Anwendungsbranch.")
    check(not git("ls-files", ".env"), ".env darf nicht versioniert sein.")
    repository = IndexRepository(settings)
    report = {"code_head": git("rev-parse", "HEAD"), "main_before": repository.main_head(),
              "integration_before": repository.get_branch_head(), "effective_branch": settings.github_data_branch}
    repository.main_before = report["main_before"]
    photo = get_module("foto_papierabzuege")
    photo_state = repository.read_file("state/foto-papierabzuege.json")
    legacy_index = repository.read_file("indexes/fotos.json")
    print(json.dumps(report, indent=2), flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="generic-index-integration-") as directory:
            other = make_indexed_test_module(Path(directory))
            repository.allowed_indexes = {index_path(photo), index_path(other)}
            snapshot = SnapshotRepository(repository, report["integration_before"], [photo.storage["data_dir"], other.storage["data_dir"]])
            print("Git-Snapshot geladen; validiere alle kanonischen Datensaetze.", flush=True)
            for module in (photo, other):
                built = build_module_index(module, snapshot.list_directory(module.storage["data_dir"]))
                if module is photo:
                    check(len(built["records"]) == 10331, "Unerwartete Fotoanzahl.")
                    check(any(item["record_id"] == "foto-010332" for item in built["records"]), "Testfoto fehlt.")
                    check(not any(item["record_id"] == "foto-008117" for item in built["records"]), "Zurueckgestelltes Foto unerwartet enthalten.")
                print(json.dumps({"validated_module": module.id, "records": len(built["records"]), "bytes": len(dump_index(built).encode())}), flush=True)
            repository.writes_enabled = True
            for module in (photo, other):
                built = rebuild_module_index(snapshot, module)
                count = len(repository.commits)
                rebuilt = rebuild_module_index(snapshot, module)
                check(built == rebuilt and len(repository.commits) == count, "Rebuild nicht idempotent.")
                report.setdefault("indexes", {})[module.id] = {"path": index_path(module), "records": len(built["records"]), "bytes": len(dump_index(built).encode())}
            with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{directory}/auth.sqlite3", "COOKIE_SECURE": "false"}):
                api_checks(repository, photo, other, report)
            check(repository.read_file("state/foto-papierabzuege.json") == photo_state, "Foto-State veraendert.")
            check(repository.read_file("indexes/fotos.json") == legacy_index, "Legacy-Fotoindex veraendert.")
            report["result"] = "passed"
    finally:
        repository.writes_enabled = False
        report.update({"main_after": repository.main_head(), "integration_after": repository.get_branch_head(), "commits": repository.commits})
        comparison = repository.request("GET", f"{repository.repo_path}/compare/{report['integration_before']}...{report['integration_after']}")
        report["changed_files"] = [item["filename"] for item in comparison.get("files", [])]
        report["history_matches"] = [item["sha"] for item in comparison["commits"]] == [item["head"] for item in repository.commits]
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        check(report["main_before"] == report["main_after"] and report["history_matches"], "Unerwartete Branch-Aenderung.")
        check(set(report["changed_files"]) <= repository.allowed_indexes | {repository.new_record_path, STATE_PATH}, "Unerwartete Dateiaenderung.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    check(args.write and os.getenv("GENERIC_GITHUB_INTEGRATION") == "1", "Live-Lauf nur mit --write und GENERIC_GITHUB_INTEGRATION=1.")
    run(args.report)
