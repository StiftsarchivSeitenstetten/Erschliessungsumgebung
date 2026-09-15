"""Explicit browser PUT test: two existing test records, integration-test only."""

import argparse
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from backend.config import get_settings
from backend.modules import get_module
from backend.records.generic_read import parse_record_content
from backend.records.module_index import read_module_index
from .generic_github import GuardedRepository, check, check_target
from .index_github import make_indexed_test_module


TARGETS = {
    "foto_papierabzuege": ("data/fotos/foto-010332.md", "indexes/generic/fotos.json"),
    "generic_integration_test": ("data/integration-test/integration-0003.md", "indexes/generic/integration-test.json"),
}


class UpdateRepository(GuardedRepository):
    def check_files(self, files):
        check(set(files) in [set(paths) for paths in TARGETS.values()], "Nur vorhandene Testrecords plus Index erlaubt.")
        record_path = next(path for path in files if path.startswith("data/"))
        check(not any(record_path in commit["files"] for commit in self.commits), "Nur ein erfolgreicher Update-Test je Record erlaubt.")
        before = parse_record_content(self.before[record_path].content)
        after = parse_record_content(files[record_path])
        check(before["id"] == after["id"] and before["signatur"] == after["signatur"], "ID und Signatur muessen unveraendert bleiben.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--write", action="store_true", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    check_target(settings)
    check(os.getenv("GENERIC_GITHUB_INTEGRATION") == "1", "Explizite Schreibfreigabe fehlt.")
    repository = UpdateRepository(settings)
    repository.main_before = repository.main_head()
    head_before = repository.get_branch_head()
    protected = ["state/foto-papierabzuege.json", "state/integration-test.json", "indexes/fotos.json"]
    repository.before = {path: repository.read_file(path) for path in protected + [paths[0] for paths in TARGETS.values()]}
    report = {"main_before":repository.main_before,"integration_before":head_before,
              "revisions_before":{path:file.revision for path,file in repository.before.items()}}
    print(json.dumps(report), flush=True)
    with tempfile.TemporaryDirectory(prefix="update-browser-") as directory:
        with patch.dict(os.environ, {"DATABASE_URL":f"sqlite:///{directory}/auth.sqlite3", "COOKIE_SECURE":"false"}):
            from backend.auth.service import create_user
            from backend.database import SessionLocal
            from backend.main import create_app
            from backend.models import ModuleAccess
            from backend.records.photos import read_photo_record
            from fastapi.responses import JSONResponse
            import uvicorn

            modules = {"foto_papierabzuege":get_module("foto_papierabzuege"),
                       "generic_integration_test":make_indexed_test_module(Path(directory))}
            app = create_app()
            app.state.data_repository = repository
            app.state.generic_write_modules = set(TARGETS)
            with SessionLocal() as db:
                for role in ("ehrenamtlich", "redaktion"):
                    user = create_user(db, username=f"update-{role}", display_name=f"Update-Test {role}",
                                       email=f"{role}@update.invalid", role=role,
                                       ui_profile="redaktion" if role == "redaktion" else "ehrenamt-standard",
                                       modules=["foto_papierabzuege"], password="UpdateTest123!")
                    user.module_access.append(ModuleAccess(module_key="generic_integration_test"))
                db.commit()
            allowed_urls = {f"/api/modules/{key}/records/{Path(paths[0]).stem}" for key,paths in TARGETS.items()}

            @app.middleware("http")
            async def restrict_writes(request, call_next):
                if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(("/api/modules/", "/api/records/")):
                    if request.method != "PUT" or request.url.path not in allowed_urls:
                        return JSONResponse({"detail":"Nur erlaubte Test-PUTs"}, status_code=403)
                response = await call_next(request)
                if request.method == "PUT":
                    report.setdefault("put_statuses", []).append(response.status_code)
                return response

            repository.writes_enabled = True
            with patch("backend.routes.modules.get_module", side_effect=modules.__getitem__), patch("backend.routes.modules.list_modules", return_value=list(modules.values())):
                try:
                    uvicorn.run(app, host="127.0.0.1", port=args.port)
                finally:
                    repository.writes_enabled = False
                    report["main_after"] = repository.main_head()
                    report["integration_after"] = repository.get_branch_head()
                    check(report["main_after"] == repository.main_before, "main veraendert.")
                    for path in protected:
                        check(repository.read_file(path).content == repository.before[path].content, f"Geschuetzte Datei veraendert: {path}")
                    report["records"] = {}
                    for key,(path,index_path) in TARGETS.items():
                        file = repository.read_file(path)
                        record = parse_record_content(file.content)
                        index = read_module_index(repository, modules[key])
                        entry = next(item for item in index["records"] if item["record_id"] == record["id"])
                        check(entry["revision"] == file.revision, "Indexrevision stimmt nicht mit Record ueberein.")
                        report["records"][key] = {"id":record["id"],"signature":record["signatur"]["anzeige"],"revision":file.revision}
                    check(read_photo_record(repository,"foto-010332").data["id"] == "foto-010332", "Legacy-Lesen fehlgeschlagen.")
                    comparison = repository.request("GET",f"{repository.repo_path}/compare/{head_before}...{report['integration_after']}")
                    report["commits"] = repository.commits
                    check([commit["sha"] for commit in comparison["commits"]] == [commit["head"] for commit in repository.commits], "Unerwartete Commits.")
                    check({file["filename"] for file in comparison["files"]} == {path for commit in repository.commits for path in commit["files"]}, "Unerwartete Dateien.")
                    report["protected_unchanged"] = True
                    args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
                    print(json.dumps(report),flush=True)


if __name__ == "__main__":
    main()
