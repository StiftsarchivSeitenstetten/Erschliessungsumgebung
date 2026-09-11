import importlib
import os
from pathlib import Path
import tempfile
import unittest
from wsgiref.util import setup_testing_defaults


TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP_DIR.name) / 'deployment-test.sqlite3'}"
os.environ["COOKIE_SECURE"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from backend.auth.service import create_user  # noqa: E402
from backend.database import Base, SessionLocal, engine, engine_kwargs  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.permissions import MODULE_FOTO_PAPIERABZUEGE  # noqa: E402


class DomainFactoryDeploymentTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def test_health_is_public_and_minimal(self):
        client = TestClient(create_app())
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_passenger_wsgi_import_and_login_page(self):
        passenger_wsgi = importlib.import_module("passenger_wsgi")
        self.assertTrue(callable(passenger_wsgi.application))
        status_headers = {}
        body = b"".join(passenger_wsgi.application(self.environ_for("/login/"), self.start_response(status_headers)))
        self.assertTrue(status_headers["status"].startswith("200"))
        self.assertIn(b"<!", body[:100].lower())

    def test_passenger_wsgi_health(self):
        passenger_wsgi = importlib.import_module("passenger_wsgi")
        status_headers = {}
        body = b"".join(passenger_wsgi.application(self.environ_for("/health"), self.start_response(status_headers)))
        self.assertTrue(status_headers["status"].startswith("200"))
        self.assertEqual(body, b'{"status":"ok"}')

    def test_secure_cookie_configuration_for_production(self):
        previous = os.environ.get("COOKIE_SECURE")
        os.environ["COOKIE_SECURE"] = "true"
        try:
            with SessionLocal() as db:
                create_user(
                    db,
                    username="anna",
                    display_name="Anna",
                    email="anna@example.test",
                    role="ehrenamtlich",
                    ui_profile="ehrenamt-standard",
                    modules=[MODULE_FOTO_PAPIERABZUEGE],
                    password="SehrGeheim123",
                )
                db.commit()
            client = TestClient(create_app(), base_url="https://tauruslektorat.at")
            response = client.post("/api/auth/login", json={"login": "anna", "password": "SehrGeheim123"})
            self.assertEqual(response.status_code, 200)
            cookie_headers = response.headers.get_list("set-cookie")
            normalized = [header.lower() for header in cookie_headers]
            self.assertTrue(any("httponly" in header and "secure" in header and "samesite=lax" in header for header in normalized))
            self.assertTrue(any("erschliessung_csrf" in header and "secure" in header and "samesite=lax" in header for header in normalized))
        finally:
            if previous is None:
                os.environ.pop("COOKIE_SECURE", None)
            else:
                os.environ["COOKIE_SECURE"] = previous

    def test_mysql_database_url_syntax_is_supported_by_sqlalchemy(self):
        url = "mysql+pymysql://user:password@localhost:3306/erschliessung?charset=utf8mb4"
        self.assertEqual(engine_kwargs(url), {})
        parsed = make_url(url)
        self.assertEqual(parsed.drivername, "mysql+pymysql")
        self.assertEqual(parsed.database, "erschliessung")

    def environ_for(self, path: str) -> dict:
        environ = {}
        setup_testing_defaults(environ)
        environ.update({
            "REQUEST_METHOD": "GET",
            "SCRIPT_NAME": "",
            "PATH_INFO": path,
            "SERVER_NAME": "tauruslektorat.at",
            "SERVER_PORT": "443",
            "wsgi.url_scheme": "https",
        })
        return environ

    @staticmethod
    def start_response(target: dict):
        def _start_response(status, headers, exc_info=None):
            target["status"] = status
            target["headers"] = headers

        return _start_response


if __name__ == "__main__":
    unittest.main()
