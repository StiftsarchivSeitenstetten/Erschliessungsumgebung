"""Read-only browser harness for both generic modules; no data commits allowed."""

import argparse
import os
from pathlib import Path
import tempfile
from dataclasses import replace
from unittest.mock import patch

from backend.config import get_settings
from backend.github.github_repository import GitHubDataRepository
from backend.modules import get_module
from backend.github.repository import RepositoryFile
from backend.records.module_index import build_module_index, dump_index, blob_revision, index_path
from .generic_github import check_target, check
from .index_github import make_indexed_test_module


class ReadOnlyRepository(GitHubDataRepository):
    local_index = None

    def read_file(self, path):
        if self.local_index and path == self.local_index.path:
            return self.local_index
        return super().read_file(path)

    def main_head(self):
        return self.request("GET", f"{self.repo_path}/git/ref/heads/main")["object"]["sha"]

    def request(self, method, path, payload=None, **kwargs):
        check(method == "GET", "Nur lesende GitHub-Abfragen erlaubt.")
        return super().request(method, path, payload, **kwargs)

    def commit_files(self, **kwargs):
        raise RuntimeError("Browserpruefung darf nicht schreiben.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--alternate-config", action="store_true", help="Rebuild only the test-module index in memory with different lookup and sort fields")
    args = parser.parse_args()
    settings = get_settings()
    check_target(settings)
    repository = ReadOnlyRepository(settings)
    main_before = repository.main_head()
    integration_before = repository.get_branch_head()
    print({"main_before": main_before, "integration_before": integration_before}, flush=True)
    with tempfile.TemporaryDirectory(prefix="navigation-browser-") as directory:
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{directory}/auth.sqlite3", "COOKIE_SECURE": "false"}):
            from backend.auth.service import create_user
            from backend.database import SessionLocal
            from backend.main import create_app
            from backend.models import ModuleAccess
            from fastapi.responses import JSONResponse
            import uvicorn

            photo = get_module("foto_papierabzuege")
            other = make_indexed_test_module(Path(directory))
            if args.alternate_config:
                other = replace(other, search_config={"fulltext":["daten.personen", "daten.text", "daten.intern"], "lookup":["daten.text"]},
                                list_config={"columns":[{"path":"daten.text"}, {"path":"daten.zeitraum"}, {"path":"daten.intern"}],
                                             "default_sort":{"path":"daten.text", "direction":"desc"}})
                content = dump_index(build_module_index(other, repository.list_directory(other.storage["data_dir"])))
                repository.local_index = RepositoryFile(index_path(other), content, blob_revision(content))
            modules = {module.access_key: module for module in (photo, other)}
            app = create_app()
            app.state.data_repository = repository
            with SessionLocal() as db:
                for role in ("redaktion", "ehrenamtlich"):
                    user = create_user(db, username=f"navigation-{role}", display_name=f"Navigation {role}",
                                       email=f"{role}@navigation.invalid", role=role,
                                       ui_profile="redaktion" if role == "redaktion" else "ehrenamt-standard",
                                       modules=[photo.access_key], password="NavigationTest123!")
                    user.module_access.append(ModuleAccess(module_key=other.access_key))
                db.commit()

            @app.middleware("http")
            async def block_writes(request, call_next):
                if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(("/api/modules/", "/api/records/")):
                    return JSONResponse({"detail": "Rein lesender Browsertest"}, status_code=403)
                return await call_next(request)

            with patch("backend.routes.modules.get_module", side_effect=modules.__getitem__), patch("backend.routes.modules.list_modules", return_value=list(modules.values())):
                try:
                    uvicorn.run(app, host="127.0.0.1", port=args.port)
                finally:
                    check(repository.main_head() == main_before, "main wurde veraendert.")
                    check(repository.get_branch_head() == integration_before, "integration-test wurde veraendert.")
                    print("Beide Daten-Heads unveraendert.", flush=True)


if __name__ == "__main__":
    main()
