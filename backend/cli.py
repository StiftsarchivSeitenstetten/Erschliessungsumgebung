"""Administrative command line tools for user management."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth.passwords import hash_password
from .auth.service import create_user
from .database import SessionLocal, init_db
from .models import User
from .permissions.rules import MODULES, ROLES, UI_PROFILES, validate_module, validate_role, validate_ui_profile


def prompt(value: str | None, label: str) -> str:
    if value:
        return value
    answer = input(f"{label}: ").strip()
    if not answer:
        raise SystemExit(f"{label} darf nicht leer sein.")
    return answer


def prompt_choice(value: str | None, label: str, choices: set[str]) -> str:
    if value:
        answer = value
    else:
        answer = input(f"{label} ({', '.join(sorted(choices))}): ").strip()
    if answer not in choices:
        raise SystemExit(f"Ungueltiger Wert fuer {label}: {answer}")
    return answer


def prompt_modules(value: str | None) -> list[str]:
    raw = value if value is not None else input(f"Arbeitsbereiche ({', '.join(sorted(MODULES))}, Komma-getrennt): ")
    modules = [part.strip() for part in raw.split(",") if part.strip()]
    if not modules:
        raise SystemExit("Mindestens ein Arbeitsbereich ist erforderlich.")
    return [validate_module(module) for module in modules]


def prompt_password(value: str | None = None) -> str:
    if value:
        return value
    password = getpass.getpass("Passwort: ")
    confirm = getpass.getpass("Passwort wiederholen: ")
    if password != confirm:
        raise SystemExit("Passwoerter stimmen nicht ueberein.")
    if len(password) < 10:
        raise SystemExit("Passwort muss mindestens 10 Zeichen haben.")
    return password


def create_user_command(args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        try:
            user = create_user(
                db,
                username=prompt(args.username, "Benutzername"),
                display_name=prompt(args.display_name, "Anzeigename"),
                email=prompt(args.email, "E-Mail"),
                role=validate_role(prompt_choice(args.role, "Rolle", ROLES)),
                ui_profile=validate_ui_profile(prompt_choice(args.ui_profile, "UI-Profil", UI_PROFILES)),
                modules=prompt_modules(args.modules),
                password=prompt_password(args.password),
            )
            db.commit()
            username = user.username
        except IntegrityError as exc:
            db.rollback()
            raise SystemExit("Benutzername oder E-Mail existiert bereits.") from exc
    print(f"Benutzer angelegt: {username}")
    return 0


def list_users_command(args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
        for user in users:
            status = "aktiv" if user.active else "deaktiviert"
            print(f"{user.username}\t{user.display_name}\t{user.email}\t{user.role}\t{user.ui_profile}\t{','.join(user.modules)}\t{status}")
    return 0


def set_active_command(args: argparse.Namespace, active: bool) -> int:
    init_db()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if not user:
            raise SystemExit("Benutzer nicht gefunden.")
        user.active = active
        db.commit()
    print(f"Benutzer {'aktiviert' if active else 'deaktiviert'}: {args.username}")
    return 0


def reset_password_command(args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if not user:
            raise SystemExit("Benutzer nicht gefunden.")
        user.password_hash = hash_password(prompt_password(args.password))
        db.commit()
    print(f"Passwort aktualisiert: {args.username}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-user")
    create.add_argument("--username")
    create.add_argument("--display-name")
    create.add_argument("--email")
    create.add_argument("--role")
    create.add_argument("--ui-profile")
    create.add_argument("--modules")
    create.add_argument("--password", help=argparse.SUPPRESS)
    create.set_defaults(func=create_user_command)

    list_users = subparsers.add_parser("list-users")
    list_users.set_defaults(func=list_users_command)

    disable = subparsers.add_parser("disable-user")
    disable.add_argument("username")
    disable.set_defaults(func=lambda args: set_active_command(args, False))

    enable = subparsers.add_parser("enable-user")
    enable.add_argument("username")
    enable.set_defaults(func=lambda args: set_active_command(args, True))

    reset = subparsers.add_parser("reset-password")
    reset.add_argument("username")
    reset.add_argument("--password", help=argparse.SUPPRESS)
    reset.set_defaults(func=reset_password_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
