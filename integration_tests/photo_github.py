"""Explicit real-photo compatibility test, only on integration-test."""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from backend.config import get_settings
from backend.github.errors import RepositoryNotFoundError
from backend.github.github_repository import GitHubDataRepository
from backend.modules import get_module
from backend.records.generic_read import parse_record_content
from backend.records.runtime import RecordRuntime
from backend.records.module_index import blob_revision, dump_index, index_path, make_index
from .generic_github import GuardedRepository, check, check_target, git
from .photo_fixture import INDEX_PATH, MODULE_KEY, PASSWORD, STATE_PATH, legacy_payload, sample_payload, server_defaults


class PhotoRepository(GuardedRepository):
    allowed_record_path = None

    def guard(self):
        check(os.getenv("GENERIC_PHOTO_INTEGRATION") == "1", "Foto-Integrationstest nicht freigegeben.")
        super().guard()

    def check_files(self, files):
        check(self.allowed_record_path is not None, "Neue Foto-Testdatei noch nicht bestimmt.")
        generic_index = index_path(get_module(MODULE_KEY))
        check(set(files) in ({self.allowed_record_path}, {self.allowed_record_path, STATE_PATH},
                            {self.allowed_record_path, generic_index}, {self.allowed_record_path, STATE_PATH, generic_index}),
              "Nur neue Foto-Testdatei und gemeinsamer Record/State-Commit erlaubt.")


def configure_app(repository, *, readonly=False):
    from backend.auth.service import create_user
    from backend.database import SessionLocal
    from backend.main import create_app
    from fastapi.responses import JSONResponse

    app = create_app()
    app.state.data_repository = repository
    app.state.generic_server_values_provider = server_defaults
    with SessionLocal() as db:
        for role in ("redaktion", "ehrenamtlich"):
            create_user(db, username=f"foto-test-{role}", display_name=f"Foto-Test {role}",
                        email=f"{role}@foto-test.invalid", role=role,
                        ui_profile="redaktion" if role == "redaktion" else "ehrenamt-standard",
                        modules=[MODULE_KEY], password=PASSWORD)
        db.commit()

    @app.middleware("http")
    async def restrict_record_writes(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(("/api/records/", "/api/modules/")):
            allowed = request.url.path.startswith(f"/api/modules/{MODULE_KEY}/records")
            if readonly or not allowed:
                return JSONResponse({"detail": "Schreiben in diesem Testserver gesperrt."}, status_code=403)
        return await call_next(request)

    return app


def compare_legacy(repository, path, payload, state):
    from backend.records.photos import (
        allocate_photo_identity,
        build_new_record,
        normalize_state,
        read_photo_record,
        validate_canonical_record,
    )
    from scripts.foto_core import render_photo_markdown

    file = repository.read_file(path)
    record = parse_record_content(file.content)
    validate_canonical_record(record)
    legacy_read = read_photo_record(repository, record["id"])
    check(legacy_read.data == record and legacy_read.revision == file.revision, "Legacy-Lesen weicht ab.")
    check(parse_record_content(render_photo_markdown(record)) == record, "Legacy-Serialisierung veraendert kanonische Werte.")
    user = SimpleNamespace(username="foto-test-redaktion")
    record_id, signature = allocate_photo_identity(normalize_state(state), payload["signatur"]["format"])
    with patch("backend.records.photos.utc_iso", return_value=record["technik"]["erstellt_am"]):
        legacy = build_new_record(legacy_payload(payload), user, record_id, signature)
    comparison = deepcopy(legacy)
    comparison["technik"]["geaendert_am"] = None
    comparison["technik"]["geaendert_von"] = None
    check(comparison == record, "Unerwartete Struktur-/Werteabweichung gegen Legacy-Create.")
    return record


def exercise(repository, report, partition="A"):
    from fastapi.testclient import TestClient
    from backend.records.photos import read_photo_record, validate_canonical_record
    from backend.records.photo_index import parse_photo_index

    module = get_module(MODULE_KEY)
    state_file = repository.read_file(STATE_PATH)
    state = json.loads(state_file.content)
    index_file = repository.read_file(INDEX_PATH)
    index = parse_photo_index(json.loads(index_file.content))
    record_id = f"foto-{state['next_record_id']:06d}"
    signature = f"9.4.2.{partition}.{state['next_signature_number'][partition]}"
    path = f"data/fotos/{record_id}.md"
    check(index.by_id(record_id) is None and index.by_signature(signature) is None, "ID oder Signatur bereits indexiert.")
    try:
        repository.read_file(path)
    except RepositoryNotFoundError:
        pass
    else:
        raise RuntimeError("Erwartete neue Foto-ID bereits vorhanden.")
    repository.allowed_record_path = path
    report.update({"state_before": state, "record_id": record_id, "signature": signature,
                   "partition": partition, "record_path": path, "index_count": len(index.records)})
    print(json.dumps({"planned_photo": report}, indent=2), flush=True)
    app = configure_app(repository)

    def ok(response, expected=200):
        check(response.status_code == expected, f"HTTP {response.status_code}, erwartet {expected}: {response.text}")
        return response.json()

    with TestClient(app) as client:
        def login(role):
            ok(client.post("/api/auth/login", json={"login": f"foto-test-{role}", "password": PASSWORD}))
            me = ok(client.get("/api/auth/me"))
            return {"X-CSRF-Token": client.cookies.get(me["csrf_cookie_name"])}

        headers = login("redaktion")
        url = f"/api/modules/{MODULE_KEY}/records"
        payload = sample_payload(partition)
        ok(client.post(url, json={"operation_id": f"photo-write-disabled-{record_id}", "record": payload}, headers=headers), 503)
        app.state.generic_write_modules = {MODULE_KEY}
        created = ok(client.post(url, json={"operation_id": f"photo-live-create-{record_id}", "record": payload}, headers=headers), 201)
        check(created["record_id"] == record_id, "Falsche ID.")
        check(set(repository.commits[-1]["files"]) == {path, STATE_PATH, index_path(module)}, "Record, State und Index nicht gemeinsam committed.")
        record = compare_legacy(repository, path, payload, state)
        check(record["signatur"]["anzeige"] == signature and record["signatur"]["status"] == "vergeben", "Falsche Signatur.")
        check(record["technik"]["erstellt_am"] and record["technik"]["erstellt_von"] == "foto-test-redaktion", "Erstellungsmetadaten fehlen.")
        expected_state = deepcopy(state)
        expected_state["next_record_id"] += 1
        expected_state["next_signature_number"][partition] += 1
        expected_state.setdefault("create_operations", {})[f"photo-live-create-{record_id}"] = {
            "request": {"record": deepcopy(payload), "identity": None},
            "record_id": record_id,
        }
        check(json.loads(repository.read_file(STATE_PATH).content) == expected_state, "Foto-State falsch fortgeschrieben.")
        report["legacy_create_difference"] = "Only geaendert_am/von: generic null at create, legacy already populated. YAML key order has no semantic effect."

        record_url = f"{url}/{record_id}"
        for role in ("redaktion", "ehrenamtlich"):
            headers = login(role)
            readback = ok(client.get(record_url))
            check(readback["record"] == RecordRuntime(module).filter_for_view(record, role), "Rollen-Read-back falsch.")
            check(readback["meta"]["revision"] == repository.read_file(path).revision, "Falsche Git-Revision.")
            check(("titel" in readback["record"]["erschliessung"]) == (role == "redaktion"), "Titelsichtbarkeit falsch.")
            check("technik" not in readback["record"], "Technische Metadaten entgegen Moduldefinition sichtbar.")
            legacy = ok(client.get(f"/api/records/photos/{record_id}"))
            check(legacy["record"] == record, "Legacy-API akzeptiert neuen Datensatz nicht.")
        report["readback"] = "generic + legacy, redaktion + ehrenamtlich passed; technik verified in YAML/legacy, hidden by generic field catalog"
        headers = login("redaktion")
        state_after_create = repository.read_file(STATE_PATH)
        updated_payload = deepcopy(payload)
        updated_payload["erschliessung"]["fotograf"] = "Testfotograf aktualisiert"
        updated_payload["erschliessung"]["beschreibung"] = "INTEGRATIONSTEST - nach generischem Update"
        updated_payload["erschliessung"]["dargestellte_personen"][0]["hinweis"] = "Mitte"
        updated_payload["erschliessung"]["dargestellte_personen"].append({"name": "Testperson Drei", "hinweis": "hinzugefuegt"})
        updated_payload["datierung"].update({"jahr": 1967, "monat": 6, "tag": 13})
        updated = ok(client.put(record_url, json={"record": updated_payload, "base_revision": created["meta"]["revision"]}, headers=headers))
        current_file = repository.read_file(path)
        current = parse_record_content(current_file.content)
        validate_canonical_record(current)
        check(current["id"] == record["id"] and current["signatur"] == record["signatur"], "ID/Signatur beim Update geaendert.")
        for key in ("erstellt_am", "erstellt_von"):
            check(current["technik"][key] == record["technik"][key], "Erstellungsmetadaten beim Update geaendert.")
        check(current["technik"]["geaendert_am"] and current["technik"]["geaendert_von"] == "foto-test-redaktion", "Aenderungsmetadaten fehlen.")
        check(current["erschliessung"] == updated_payload["erschliessung"] and current["datierung"] == updated_payload["datierung"], "Update-Fachwerte falsch.")
        check(updated["meta"]["revision"] != created["meta"]["revision"], "Keine neue Dateirevision.")
        check(repository.read_file(STATE_PATH) == state_after_create, "Update hat State geaendert.")
        check(set(repository.commits[-1]["files"]) == {path, index_path(module)}, "Update muss Record und Index aendern.")
        check(read_photo_record(repository, record_id).data == current, "Legacy-Lesen nach Update falsch.")
        check(ok(client.get(record_url)) == updated, "Generisches Lesen nach Update falsch.")
        head = repository.get_branch_head()
        ok(client.put(record_url, json={"record": payload, "base_revision": created["meta"]["revision"]}, headers=headers), 409)
        check(repository.get_branch_head() == head and repository.read_file(path) == current_file and
              repository.read_file(STATE_PATH) == state_after_create, "Veraltete Revision hat Daten veraendert.")
        report["update_conflict"] = {"revision_a": created["meta"]["revision"], "revision_b": updated["meta"]["revision"], "stale_status": 409}
        check(repository.read_file(INDEX_PATH) == index_file, "Fotoindex unerwartet veraendert.")
        listing = ok(client.get("/api/records/photos"))["records"]
        check(not any(item["id"] == record_id for item in listing), "Neuer Datensatz unerwartet in Indexliste.")
        ok(client.get(f"/api/records/photos/signatures/{signature}"), 404)
        report["index"] = "unchanged; new record absent; legacy list/search/navigation omit it; signature lookup 404; direct ID read 200"
        report["state_after"] = expected_state
        app.state.generic_write_modules = set()


def run_live(report_path):
    settings = get_settings()
    check_target(settings)
    check(git("branch", "--show-current") == "generic-module-architecture-v1", "Falscher Anwendungsbranch.")
    repository = PhotoRepository(settings)
    report = {"code_head": git("rev-parse", "HEAD"), "effective_branch": settings.github_data_branch,
              "main_before": repository.main_head(), "integration_before": repository.get_branch_head()}
    repository.main_before = report["main_before"]
    print(json.dumps(report, indent=2), flush=True)
    # Read one actual imported reference without modifying it.
    reference = repository.read_file("data/fotos/foto-000002.md")
    report["reference_id"] = "foto-000002"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix="photo-generic-live-") as directory:
            with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{directory}/auth.sqlite3", "COOKIE_SECURE": "false"}):
                repository.writes_enabled = True
                exercise(repository, report)
        report["reference_unchanged"] = repository.read_file(reference.path) == reference
        check(report["reference_unchanged"], "Referenzfoto wurde veraendert.")
        check(set(parse_record_content(reference.content)) == set(parse_record_content(repository.read_file(report["record_path"]).content)), "Abweichende Wurzelstruktur gegen importiertes Foto.")
        report["result"] = "passed"
    finally:
        repository.writes_enabled = False
        report.update({"main_after": repository.main_head(), "integration_after": repository.get_branch_head(), "commits": repository.commits})
        if report["integration_before"] != report["integration_after"]:
            comparison = repository.request("GET", f"{repository.repo_path}/compare/{report['integration_before']}...{report['integration_after']}")
            report["changed_files"] = [item["filename"] for item in comparison["files"]]
            report["history_matches"] = [item["sha"] for item in comparison["commits"]] == [item["head"] for item in repository.commits]
        else:
            report["changed_files"] = []
            report["history_matches"] = not repository.commits
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        check(report["main_after"] == report["main_before"] and report["history_matches"], "Unerwartete Branch-Aenderungen.")
        check(set(report["changed_files"]) <= {STATE_PATH, repository.allowed_record_path, index_path(get_module(MODULE_KEY))}, "Unerwartete geaenderte Dateien.")


def run_offline(report_path):
    from backend.github.repository import InMemoryGitRepository

    class OfflineRepository(InMemoryGitRepository):
        def _revision(self, path, content):
            return blob_revision(content)

    repository = OfflineRepository({
        STATE_PATH: json.dumps({"next_record_id": 10332, "next_signature_number": {"A": 8610, "B": 1046, "C": 579, "D": 81, "E": 36, "F": 1}}),
        INDEX_PATH: json.dumps({"schema_version": 1, "records": []}),
    })
    report = {}
    module = get_module(MODULE_KEY)
    repository.files[index_path(module)] = dump_index(make_index(module, []))
    with tempfile.TemporaryDirectory(prefix="photo-generic-offline-") as directory:
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{directory}/auth.sqlite3", "COOKIE_SECURE": "false"}):
            exercise(repository, report)
    report["result"] = "passed"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def serve_readonly(port):
    import uvicorn

    class ReadOnlyRepository(GitHubDataRepository):
        def request(self, method, path, payload=None, **kwargs):
            check(method == "GET", "Browser-Testrepository ist nur lesbar.")
            return super().request(method, path, payload, **kwargs)

        def commit_files(self, **kwargs):
            raise RuntimeError("Browser-Testrepository ist nur lesbar.")

    settings = get_settings()
    check_target(settings)
    with tempfile.TemporaryDirectory(prefix="photo-browser-") as directory:
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{directory}/auth.sqlite3", "COOKIE_SECURE": "false"}):
            app = configure_app(ReadOnlyRepository(settings), readonly=True)
            uvicorn.run(app, host="127.0.0.1", port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--offline", action="store_true")
    modes.add_argument("--serve-readonly", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    if args.serve_readonly:
        serve_readonly(args.port)
        return
    check(args.report is not None, "Berichtspfad fehlt.")
    if args.offline:
        run_offline(args.report)
    else:
        check(os.getenv("GENERIC_GITHUB_INTEGRATION") == "1" and os.getenv("GENERIC_PHOTO_INTEGRATION") == "1",
              "Live-Fototest erfordert GENERIC_GITHUB_INTEGRATION=1 und GENERIC_PHOTO_INTEGRATION=1.")
        run_live(args.report)


if __name__ == "__main__":
    main()
