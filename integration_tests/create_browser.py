"""One guarded browser POST for the generic photo create workflow on integration-test."""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from backend.config import get_settings
from backend.modules import get_module
from backend.records.generic_read import parse_record_content
from backend.records.module_index import index_path, read_module_index
from .generic_github import check, check_target, git
from .photo_fixture import MODULE_KEY, PASSWORD, STATE_PATH
from .photo_github import PhotoRepository, configure_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--write", action="store_true", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    settings = get_settings()
    check_target(settings)
    check(os.getenv("GENERIC_GITHUB_INTEGRATION") == "1", "Allgemeine Schreibfreigabe fehlt.")
    check(os.getenv("GENERIC_PHOTO_INTEGRATION") == "1", "Foto-Schreibfreigabe fehlt.")
    check(git("branch", "--show-current") == "generic-module-architecture-v1", "Falscher Anwendungsbranch.")
    check(not git("ls-files", ".env"), ".env ist versioniert.")

    repository = PhotoRepository(settings)
    module = get_module(MODULE_KEY)
    state_before = json.loads(repository.read_file(STATE_PATH).content)
    record_id = f"foto-{state_before['next_record_id']:06d}"
    partition = "B"
    signature = f"9.4.2.{partition}.{state_before['next_signature_number'][partition]}"
    record_path = f"data/fotos/{record_id}.md"
    repository.allowed_record_path = record_path
    report = {
        "effective_branch": settings.github_data_branch,
        "code_head": git("rev-parse", "HEAD"),
        "main_before": repository.main_head(),
        "integration_before": repository.get_branch_head(),
        "planned_record_id": record_id,
        "planned_signature": signature,
        "partition": partition,
        "record_path": record_path,
    }
    repository.main_before = report["main_before"]
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "login": "foto-test-redaktion", "password": PASSWORD}, indent=2), flush=True)

    with tempfile.TemporaryDirectory(prefix="create-browser-") as directory:
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{directory}/auth.sqlite3", "COOKIE_SECURE": "false"}):
            from fastapi.responses import JSONResponse
            import uvicorn

            app = configure_app(repository)
            app.state.generic_write_modules = {MODULE_KEY}

            @app.middleware("http")
            async def allow_one_create(request, call_next):
                if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(("/api/modules/", "/api/records/")):
                    allowed = request.method == "POST" and request.url.path == f"/api/modules/{MODULE_KEY}/records"
                    if not allowed or repository.commits:
                        return JSONResponse({"detail": "Nur ein gezielter Foto-POST ist erlaubt."}, status_code=403)
                return await call_next(request)

            repository.writes_enabled = True
            try:
                uvicorn.run(app, host="127.0.0.1", port=args.port)
            finally:
                repository.writes_enabled = False

    report["main_after"] = repository.main_head()
    report["integration_after"] = repository.get_branch_head()
    report["commits"] = repository.commits
    check(report["main_after"] == report["main_before"], "Daten-main wurde veraendert.")
    check(len(repository.commits) == 1, "Erwartet wurde genau ein erfolgreicher Create-Commit.")
    expected_files = {record_path, STATE_PATH, index_path(module)}
    check(set(repository.commits[0]["files"]) == expected_files, "Create-Commit enthaelt unerwartete Dateien.")

    file = repository.read_file(record_path)
    record = parse_record_content(file.content)
    check(record["id"] == record_id, "Server-ID weicht vom State ab.")
    check(record["signatur"]["anzeige"] == signature, "Server-Signatur oder Partition falsch.")
    check(record["technik"]["erstellt_am"] and record["technik"]["erstellt_von"] == "foto-test-redaktion", "Erstellungsmetadaten fehlen.")
    check(record["technik"]["geaendert_am"] is None and record["technik"]["geaendert_von"] is None, "Aenderungsmetadaten bei Create falsch.")
    expected_state = deepcopy(state_before)
    expected_state["next_record_id"] += 1
    expected_state["next_signature_number"][partition] += 1
    check(json.loads(repository.read_file(STATE_PATH).content) == expected_state, "State wurde nicht korrekt fortgeschrieben.")

    index = read_module_index(repository, module)
    entry = next((item for item in index["records"] if item["record_id"] == record_id), None)
    check(entry is not None and entry["revision"] == file.revision, "Generischer Index enthaelt den neuen Record nicht korrekt.")
    from backend.records.photos import read_photo_record
    check(read_photo_record(repository, record_id).data == record, "Legacy-Lesen des neuen Fotos fehlgeschlagen.")

    comparison = repository.request("GET", f"{repository.repo_path}/compare/{report['integration_before']}...{report['integration_after']}")
    check([item["sha"] for item in comparison["commits"]] == [repository.commits[0]["head"]], "Unerwartete Commits im Testzeitraum.")
    check({item["filename"] for item in comparison["files"]} == expected_files, "Unerwartete Dateien im Testzeitraum.")
    report.update({
        "record_id": record_id,
        "signature": signature,
        "revision": file.revision,
        "state_after": expected_state,
        "index_entry": True,
        "legacy_read": True,
        "technical_metadata": record["technik"],
        "result": "passed",
    })
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
