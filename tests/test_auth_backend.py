from datetime import timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP_DIR.name) / 'auth-test.sqlite3'}"
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from backend.auth.passwords import verify_password  # noqa: E402
from backend.auth.service import create_user  # noqa: E402
from backend.auth.sessions import utcnow  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.github.repository import InMemoryGitRepository  # noqa: E402
from backend.models import ModuleAccess, SessionToken, User  # noqa: E402
from backend.permissions import MODULE_FOTO_PAPIERABZUEGE, can_edit_record, has_module_access  # noqa: E402
from backend.modules import get_module, load_module  # noqa: E402
from tests.test_record_runtime import write_runtime_module, write_runtime_schema  # noqa: E402


def csrf_from_client(client: TestClient) -> str:
    me = client.get("/api/auth/me")
    cookie_name = me.json()["csrf_cookie_name"]
    return client.cookies.get(cookie_name) or ""


class AuthBackendTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.app = create_app()
        self.app.state.data_repository = InMemoryGitRepository()
        self.client = TestClient(self.app)

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

    def test_generic_write_module_configuration_is_fail_closed_and_comma_separated(self):
        with patch.dict(os.environ, {"GENERIC_WRITE_MODULES": ""}):
            self.assertEqual(get_settings().generic_write_modules, frozenset())
            self.assertEqual(create_app().state.generic_write_modules, frozenset())
        with patch.dict(os.environ, {"GENERIC_WRITE_MODULES": " autographen_9_6, runtime_test ,, "}):
            self.assertEqual(
                get_settings().generic_write_modules,
                frozenset({"autographen_9_6", "runtime_test"}),
            )

    def test_login_with_username_and_me(self):
        self.create_user()
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "anna")
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["ui_profile"], "ehrenamt-barrierearm")
        self.assertEqual(me.json()["modules"], [MODULE_FOTO_PAPIERABZUEGE])

    def test_email_is_not_a_login_identifier(self):
        self.create_user()
        response = self.login(login="anna@example.test")
        self.assertEqual(response.status_code, 401)

    def test_multiple_users_without_email_can_login_by_username(self):
        self.create_user(username="user_a", email=None)
        self.create_user(username="user_b", email="  ")

        with SessionLocal() as db:
            users = db.scalars(select(User).where(User.username.in_(["user_a", "user_b"]))).all()
            self.assertEqual([user.email for user in users], [None, None])

        self.assertEqual(self.login("user_a").status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.login("user_b").status_code, 200)

    def test_duplicate_email_addresses_are_allowed_and_login_uses_username(self):
        self.create_user(username="user_c", email=" Test@Example.org ")
        self.create_user(username="user_d", email="test@example.org")

        with SessionLocal() as db:
            users = db.scalars(select(User).where(User.username.in_(["user_c", "user_d"]))).all()
            self.assertEqual([user.email for user in users], ["test@example.org", "test@example.org"])

        self.assertEqual(self.login("user_c").status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.login("user_d").status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.login("test@example.org").status_code, 401)

    def test_username_remains_unique(self):
        self.create_user(username="user_a", email=None)
        with self.assertRaises(IntegrityError), SessionLocal() as db:
            create_user(
                db,
                username="user_a",
                display_name="Noch ein User A",
                email=None,
                role="ehrenamtlich",
                ui_profile="ehrenamt-standard",
                modules=[MODULE_FOTO_PAPIERABZUEGE],
                password="SehrGeheim123",
            )
            db.commit()

    def test_email_remains_unvalidated_metadata(self):
        user_id = self.create_user(email=" Keine-Mailadresse ")
        with SessionLocal() as db:
            self.assertEqual(db.get(User, user_id).email, "keine-mailadresse")

    def test_login_page_only_advertises_username(self):
        html = (Path(__file__).parents[1] / "backend" / "static" / "login" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('<label for="login">Benutzername</label>', html)
        self.assertNotIn("Benutzername oder E-Mail", html)

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

    def test_module_catalog_lists_accessible_module_metadata(self):
        self.create_user()
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get("/api/modules")
        self.assertEqual(response.status_code, 200)
        modules = response.json()
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0]["id"], MODULE_FOTO_PAPIERABZUEGE)
        self.assertEqual(modules[0]["label"], "Fotoerschließung")
        self.assertEqual(modules[0]["icon"], "photo")
        self.assertEqual(modules[0]["order"], 10)

    def test_module_catalog_supports_multiple_modules_without_role_logic(self):
        self.create_user(username="rita", role="redaktion", ui_profile="redaktion")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == "rita"))
            user.module_access.append(ModuleAccess(module_key="runtime_test"))
            db.commit()
        self.assertEqual(self.login("rita").status_code, 200)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_module = load_module(write_runtime_module(root, write_runtime_schema(root)))
            photo_module = get_module(MODULE_FOTO_PAPIERABZUEGE)
            with patch("backend.routes.modules.list_modules", return_value=(runtime_module, photo_module)):
                response = self.client.get("/api/modules")

        self.assertEqual(response.status_code, 200)
        modules = response.json()
        self.assertEqual([module["id"] for module in modules], [MODULE_FOTO_PAPIERABZUEGE, "runtime_test"])

    def test_inaccessible_module_is_not_listed_and_detail_is_forbidden(self):
        self.create_user()
        self.assertEqual(self.login().status_code, 200)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_module = load_module(write_runtime_module(root, write_runtime_schema(root)))
            photo_module = get_module(MODULE_FOTO_PAPIERABZUEGE)
            with patch("backend.routes.modules.list_modules", return_value=(photo_module, runtime_module)), \
                patch("backend.routes.modules.get_module", return_value=runtime_module):
                catalog = self.client.get("/api/modules")
                detail = self.client.get("/api/modules/runtime_test")

        self.assertEqual(catalog.status_code, 200)
        self.assertEqual([module["id"] for module in catalog.json()], [MODULE_FOTO_PAPIERABZUEGE])
        self.assertEqual(detail.status_code, 403)

    def test_roles_do_not_change_module_catalog_membership(self):
        for role in ("ehrenamtlich", "redaktion", "admin"):
            username = f"katalog-{role}"
            self.create_user(username=username, email=f"{username}@example.test", role=role, ui_profile="redaktion" if role != "ehrenamtlich" else "ehrenamt-standard")
            self.assertEqual(self.login(username).status_code, 200)
            response = self.client.get("/api/modules")
            self.assertEqual(response.status_code, 200)
            self.assertEqual([module["id"] for module in response.json()], [MODULE_FOTO_PAPIERABZUEGE])
            self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_from_client(self.client)})

    def test_module_descriptor_resolves_field_rights_for_current_user(self):
        self.create_user()
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get("/api/modules/foto_papierabzuege")
        self.assertEqual(response.status_code, 200)
        descriptor = response.json()
        self.assertEqual(descriptor["module"], MODULE_FOTO_PAPIERABZUEGE)
        self.assertIn("sections", descriptor)
        self.assertIn("fields", descriptor)
        self.assertEqual(descriptor["empty_record"]["signatur"]["format"], "A")
        self.assertEqual(descriptor["empty_record"]["erschliessung"]["orte"], [])
        self.assertEqual(descriptor["empty_record"]["datierung"], {"jahr": None, "monat": None, "tag": None})
        self.assertNotIn("titel", descriptor["empty_record"]["erschliessung"])
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

    def test_vocabulary_endpoint_uses_vocabulary_rights_not_module_membership(self):
        self.create_user(username="rita", role="redaktion", ui_profile="redaktion")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == "rita"))
            user.module_access.append(ModuleAccess(module_key="runtime_test"))
            db.commit()
        self.assertEqual(self.login("rita").status_code, 200)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = load_module(write_runtime_module(root, write_runtime_schema(root)))
            with patch("backend.routes.modules.list_modules", return_value=(module,)):
                response = self.client.get("/api/vocabularies/dokumenttypen")
                unknown = self.client.get("/api/vocabularies/unbekannt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(response.json()["terms"][0]["id"], "brief")
        self.assertTrue(response.json()["terms"][0]["active"])

        self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_from_client(self.client)})
        self.create_user(username="ohne-zugriff", email="ohne@example.test", modules=[])
        self.assertEqual(self.login("ohne-zugriff").status_code, 200)
        with patch("backend.routes.modules.list_modules", return_value=(module,)):
            self.assertEqual(self.client.get("/api/vocabularies/dokumenttypen").status_code, 200)

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
