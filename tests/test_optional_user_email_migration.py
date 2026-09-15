from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError


ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "20260911_0001"


class OptionalUserEmailMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tmp.name) / "migration.sqlite3"
        self.database_url = f"sqlite:///{self.database_path}"
        self.config = Config(str(ROOT / "alembic.ini"))
        self.config.set_main_option("script_location", str(ROOT / "alembic"))
        self.config.set_main_option("sqlalchemy.url", self.database_url)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": self.database_url})
        self.environment.start()
        self.engine: sa.Engine | None = None

    def tearDown(self):
        if self.engine is not None:
            self.engine.dispose()
        self.environment.stop()
        self.tmp.cleanup()

    @staticmethod
    def user_values(username: str, email: str | None) -> dict[str, object]:
        return {
            "username": username,
            "display_name": username.title(),
            "email": email,
            "password_hash": "existing-password-hash",
            "role": "redaktion",
            "active": True,
            "ui_profile": "redaktion",
            "created_at": datetime.now(timezone.utc),
            "last_login": None,
        }

    def upgrade_legacy_database(self) -> sa.Engine:
        command.upgrade(self.config, BASE_REVISION)
        engine = sa.create_engine(self.database_url)
        self.engine = engine
        metadata = sa.MetaData()
        metadata.reflect(engine)
        with engine.begin() as connection:
            result = connection.execute(
                metadata.tables["users"].insert().values(
                    **self.user_values("bestand", "bestand@example.org")
                )
            )
            connection.execute(
                metadata.tables["module_access"].insert().values(
                    user_id=result.inserted_primary_key[0],
                    module_key="foto_papierabzuege",
                )
            )
        command.upgrade(self.config, "head")
        return engine

    def test_upgrade_preserves_existing_user_and_allows_null_and_duplicate_emails(self):
        engine = self.upgrade_legacy_database()
        inspector = sa.inspect(engine)
        email_column = next(column for column in inspector.get_columns("users") if column["name"] == "email")
        self.assertTrue(email_column["nullable"])
        self.assertNotIn("ix_users_email", {index["name"] for index in inspector.get_indexes("users")})

        metadata = sa.MetaData()
        metadata.reflect(engine)
        users = metadata.tables["users"]
        module_access = metadata.tables["module_access"]
        with engine.begin() as connection:
            existing = connection.execute(
                sa.select(users).where(users.c.username == "bestand")
            ).mappings().one()
            self.assertEqual(existing["email"], "bestand@example.org")
            self.assertEqual(existing["role"], "redaktion")
            self.assertEqual(
                connection.scalar(
                    sa.select(module_access.c.module_key).where(module_access.c.user_id == existing["id"])
                ),
                "foto_papierabzuege",
            )
            connection.execute(users.insert(), [
                self.user_values("user_a", None),
                self.user_values("user_b", None),
                self.user_values("user_c", "test@example.org"),
                self.user_values("user_d", "test@example.org"),
            ])

        with self.assertRaises(IntegrityError), engine.begin() as connection:
            connection.execute(users.insert().values(**self.user_values("user_a", None)))

    def test_downgrade_restores_original_constraint_for_compatible_data(self):
        engine = self.upgrade_legacy_database()
        command.downgrade(self.config, BASE_REVISION)

        inspector = sa.inspect(engine)
        email_column = next(column for column in inspector.get_columns("users") if column["name"] == "email")
        self.assertFalse(email_column["nullable"])
        email_index = next(index for index in inspector.get_indexes("users") if index["name"] == "ix_users_email")
        self.assertTrue(email_index["unique"])

    def test_downgrade_refuses_null_or_duplicate_email_without_cleanup(self):
        engine = self.upgrade_legacy_database()
        metadata = sa.MetaData()
        metadata.reflect(engine)
        with engine.begin() as connection:
            connection.execute(
                metadata.tables["users"].insert().values(**self.user_values("ohne-email", None))
            )

        with self.assertRaisesRegex(RuntimeError, "Downgrade nicht moeglich"):
            command.downgrade(self.config, BASE_REVISION)


if __name__ == "__main__":
    unittest.main()
