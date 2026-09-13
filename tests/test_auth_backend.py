from datetime import timedelta
import os
from pathlib import Path
import tempfile
import unittest


TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP_DIR.name) / 'auth-test.sqlite3'}"
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from backend.auth.passwords import verify_password  # noqa: E402
from backend.auth.service import create_user  # noqa: E402
from backend.auth.sessions import utcnow  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.models import SessionToken, User  # noqa: E402
from backend.permissions import MODULE_FOTO_PAPIERABZUEGE, can_edit_record, has_module_access  # noqa: E402


def csrf_from_client(client: TestClient) -> str:
    me = client.get("/api/auth/me")
    cookie_name = me.json()["csrf_cookie_name"]
    return client.cookies.get(cookie_name) or ""


class AuthBackendTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(create_app())

    def create_user(self, **overrides):
        defaults = {
            "username": "anna",
            "display_name": "Anna Müller",
            "email": "anna@example.test",
            "role": "ehrenamtlich",
            "ui_profile": "ehrenamt-barrierearm",
            "modules": [MODULE_FOTO_PAPIERABZUEGE],
            "password": "SehrGeheim123",
        }
        defaults.update(overrides)
        with SessionLocal() as db:
            user = create_user(db, **defaults)
            db.commit()
            db.refresh(user)
            return user.id

    def login(self, login="anna", password="SehrGeheim123"):
        return self.client.post("/api/auth/login", json={"login": login, "password": password})

    def test_create_user_hashes_password(self):
        user_id = self.create_user()
        with SessionLocal() as db:
            user = db.get(User, user_id)
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, "SehrGeheim123")
            self.assertTrue(user.password_hash.startswith("$argon2"))
            self.assertTrue(verify_password("SehrGeheim123", user.password_hash))

    def test_login_with_username_and_me(self):
        self.create_user()
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "anna")
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["ui_profile"], "ehrenamt-barrierearm")
        self.assertEqual(me.json()["modules"], [MODULE_FOTO_PAPIERABZUEGE])

    def test_login_with_email(self):
        self.create_user()
        response = self.login(login="anna@example.test")
        self.assertEqual(response.status_code, 200)

    def test_wrong_password_is_rejected(self):
        self.create_user()
        response = self.login(password="falsch")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Benutzername oder Passwort ist falsch.")

    def test_unknown_user_is_rejected_with_same_message(self):
        response = self.client.post("/api/auth/login", json={"login": "unbekannt", "password": "falsch"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Benutzername oder Passwort ist falsch.")

    def test_repeated_failed_login_is_rate_limited(self):
        login = "rate-limit-user"
        for _ in range(10):
            response = self.client.post("/api/auth/login", json={"login": login, "password": "falsch"})
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/auth/login", json={"login": login, "password": "falsch"})
        self.assertEqual(response.status_code, 429)

    def test_disabled_user_cannot_login(self):
        self.create_user(active=False)
        response = self.login()
        self.assertEqual(response.status_code, 401)

    def test_me_without_login_is_unauthorized(self):
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_logout_invalidates_session(self):
        self.create_user()
        self.assertEqual(self.login().status_code, 200)
        logout = self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_from_client(self.client)})
        self.assertEqual(logout.status_code, 204)
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 401)

    def test_logout_requires_csrf(self):
        self.create_user()
        self.assertEqual(self.login().status_code, 200)
        response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 403)

    def test_invalid_or_expired_session_is_unauthorized(self):
        self.create_user()
        self.assertEqual(self.login().status_code, 200)
        with SessionLocal() as db:
            session = db.scalar(select(SessionToken))
            session.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_roles_are_persisted(self):
        for role in ("ehrenamtlich", "redaktion", "admin"):
            with self.subTest(role=role):
                user_id = self.create_user(
                    username=f"user-{role}",
                    email=f"{role}@example.test",
                    role=role,
                    ui_profile="redaktion" if role != "ehrenamtlich" else "ehrenamt-standard",
                )
                with SessionLocal() as db:
                    self.assertEqual(db.get(User, user_id).role, role)

    def test_module_access_allowed_and_denied(self):
        user_id = self.create_user()
        with SessionLocal() as db:
            user = db.get(User, user_id)
            self.assertTrue(has_module_access(user, MODULE_FOTO_PAPIERABZUEGE))
            self.assertFalse(has_module_access(user, "musikalien"))
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/modules/foto_papierabzuege").status_code, 200)

    def test_module_descriptor_resolves_field_rights_for_current_user(self):
        self.create_user()
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get("/api/modules/foto_papierabzuege")
        self.assertEqual(response.status_code, 200)
        descriptor = response.json()
        self.assertEqual(descriptor["module"], MODULE_FOTO_PAPIERABZUEGE)
        self.assertIn("sections", descriptor)
        self.assertIn("fields", descriptor)
        title = next(field for field in descriptor["fields"] if field["id"] == "titel")
        beschriftung = next(field for field in descriptor["fields"] if field["id"] == "beschriftung")
        self.assertFalse(title["visible"])
        self.assertFalse(title["editable"])
        self.assertTrue(beschriftung["visible"])
        self.assertTrue(beschriftung["editable"])

    def test_module_api_denies_missing_access(self):
        self.create_user(modules=[])
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get("/api/modules/foto_papierabzuege")
        self.assertEqual(response.status_code, 403)

    def test_record_edit_permissions(self):
        ehrenamt_id = self.create_user(username="anna", email="anna@example.test", role="ehrenamtlich")
        redaktion_id = self.create_user(username="rita", email="rita@example.test", role="redaktion", ui_profile="redaktion")
        admin_id = self.create_user(username="admin", email="admin@example.test", role="admin", ui_profile="redaktion")
        redaktionell = {"redaktion": {"stufe": "redaktionell"}}
        ehrenamtlich = {"redaktion": {"stufe": "ehrenamtlich"}}
        with SessionLocal() as db:
            ehrenamt = db.get(User, ehrenamt_id)
            redaktion = db.get(User, redaktion_id)
            admin = db.get(User, admin_id)
            self.assertTrue(can_edit_record(ehrenamt, ehrenamtlich))
            self.assertFalse(can_edit_record(ehrenamt, redaktionell))
            self.assertTrue(can_edit_record(redaktion, redaktionell))
            self.assertTrue(can_edit_record(admin, redaktionell))


if __name__ == "__main__":
    unittest.main()
