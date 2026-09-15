"""Local browser-acceptance server for Autographs, backed only by memory."""

import argparse
import json
import os
from pathlib import Path


os.environ["COOKIE_SECURE"] = "false"
os.environ.setdefault("DATABASE_URL", "sqlite:////private/tmp/autograph-browser.sqlite3")

from backend.auth.service import create_user  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.github.repository import InMemoryGitRepository  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.modules import get_module, list_modules  # noqa: E402
from backend.records.generic_read import parse_record_content  # noqa: E402
from backend.records.module_index import dump_index, make_index  # noqa: E402


PASSWORD = "LokalerAutographTest123!"


def make_repository(module):
    files = {
        module.storage["state"]["path"]: json.dumps({
            "next_record_id": 1,
            "next_signature_number": {"A": 1},
        }),
        module.storage["index"]["path"]: dump_index(make_index(module, [])),
    }
    for reference in module.vocabularies.values():
        files[reference["repository_path"]] = Path(reference["path"]).read_text(encoding="utf-8")
    return InMemoryGitRepository(files)


def make_app():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    list_modules.cache_clear()
    module = get_module("autographen_9_6")
    repository = make_repository(module)
    app = create_app()
    app.state.data_repository = repository
    app.state.generic_write_modules = {"autographen_9_6"}
    with SessionLocal() as db:
        for role in ("redaktion", "ehrenamtlich"):
            create_user(
                db,
                username=f"autograph-test-{role}",
                display_name=f"Autograph-Test {role}",
                email=f"{role}@autograph-test.invalid",
                role=role,
                ui_profile="redaktion" if role == "redaktion" else "ehrenamt-standard",
                modules=["autographen_9_6"],
                password=PASSWORD,
            )
        db.commit()

    @app.get("/test-state")
    def test_state():
        records = {
            path: parse_record_content(content)
            for path, content in repository.files.items()
            if path.startswith("data/autographen/")
        }
        return {
            "repository": "in-memory",
            "commits": repository.commits,
            "state": json.loads(repository.files[module.storage["state"]["path"]]),
            "records": records,
        }

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    import uvicorn

    print(json.dumps({
        "url": f"http://127.0.0.1:{args.port}/login/",
        "users": ["autograph-test-redaktion", "autograph-test-ehrenamtlich"],
        "password": PASSWORD,
        "repository": "in-memory",
    }), flush=True)
    uvicorn.run(make_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
