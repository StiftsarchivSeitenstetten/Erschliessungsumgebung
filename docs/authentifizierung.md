# Authentifizierung und Rollenmodell

Phase 2A ergänzt eine eigene Anmeldung für die Erschließungsumgebung. Ehrenamtliche benötigen kein GitHub-Konto; GitHub-Schreibzugriff und produktive Speicherung folgen erst in Phase 2B.

## Architektur

Das Backend liegt unter `backend/` und verwendet FastAPI, SQLAlchemy, Alembic und Argon2id.

```text
backend/
  main.py              FastAPI-App, statische App-Auslieferung
  config.py            Umgebungsvariablen und Cookie-Konfiguration
  database.py          SQLAlchemy-Engine und Sessions
  models/              User, ModuleAccess, SessionToken
  auth/                Passwort-Hashing, Login-Service, Sessions
  permissions/         zentrale Rollen- und Modulregeln
  routes/              Auth- und Modul-API
  cli.py               administrative Benutzerverwaltung
```

Die bestehenden statischen Dateien aus `app/` werden durch das Backend unter derselben Origin ausgeliefert. Die Foto-Maske prüft beim Laden `/api/auth/me` und den Modulzugriff auf `foto_papierabzuege`.

## Datenbankschema

`users`

- `id`
- `username`
- `display_name`
- `email`
- `password_hash`
- `role`
- `active`
- `ui_profile`
- `created_at`
- `last_login`

`module_access`

- mehrere Arbeitsbereiche pro Benutzer
- Phase 2A produktiv: `foto_papierabzuege`

`sessions`

- opake Session-ID im HttpOnly-Cookie
- serverseitig gespeicherter Hash der Session-ID
- CSRF-Token
- Ablaufzeit und Invalidierungszeit

## Rollen und Arbeitsbereiche

Benutzerrollen:

- `ehrenamtlich`
- `redaktion`
- `admin`

Datensatz-Redaktionsstufen bleiben davon getrennt:

- `ehrenamtlich`
- `redaktionell`

Berechtigungsregel:

| Benutzerrolle | ehrenamtlichen Datensatz bearbeiten | redaktionellen Datensatz bearbeiten | Benutzerverwaltung |
| --- | --- | --- | --- |
| `ehrenamtlich` | ja | nein | nein |
| `redaktion` | ja | ja | nein |
| `admin` | ja | ja | ja |

Zusätzlich muss der Benutzer für den jeweiligen Arbeitsbereich freigeschaltet sein.

## Lokale Einrichtung

1. Abhängigkeiten installieren:

   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   ```

2. Lokale Konfiguration aus Beispiel ableiten:

   ```bash
   cp .env.example .env
   ```

   Für lokale Entwicklung kann `COOKIE_SECURE=false` gesetzt werden. Für Produktion soll `COOKIE_SECURE=true` bleiben.

3. Datenbankmigration ausführen:

   ```bash
   .venv/bin/python -m alembic upgrade head
   ```

4. Admin-Benutzer anlegen:

   ```bash
   .venv/bin/python -m backend.cli create-user
   ```

5. Server starten:

   ```bash
   COOKIE_SECURE=false .venv/bin/python -m uvicorn backend.main:app --reload
   ```

6. Im Browser öffnen:

   ```text
   http://127.0.0.1:8000/login/
   ```

## CLI

Benutzer werden ausschließlich administrativ angelegt:

```bash
.venv/bin/python -m backend.cli create-user
.venv/bin/python -m backend.cli list-users
.venv/bin/python -m backend.cli disable-user anna
.venv/bin/python -m backend.cli enable-user anna
.venv/bin/python -m backend.cli reset-password anna
```

Das Passwort wird interaktiv über `getpass` abgefragt und nicht sichtbar eingegeben.

## Sicherheitsentscheidungen

- Passwörter werden mit Argon2id über `argon2-cffi` gehasht.
- Login-Fehler melden nicht, ob Benutzername oder Passwort falsch war.
- Deaktivierte Benutzer können sich nicht anmelden.
- Sessions sind opak und serverseitig invalidierbar.
- Session-Cookies sind `HttpOnly`, `SameSite=Lax` und produktiv `Secure`.
- Schreibende API-Endpunkte verwenden einen CSRF-Header gegen ein serverseitig gespeichertes Token.
- `.env` und lokale SQLite-Datenbanken werden nicht versioniert.
- Keine Registrierungsfunktion und keine Benutzerverwaltung im Browser.

## Bewusst offen für Phase 2B

- GitHub-App und Schreiben nach `Erschliessungsdaten`
- produktives Lesen vorhandener Erschließungsdaten
- zentrale kollisionssichere Signaturvergabe
- redaktionelle Datensatzbearbeitung über Backend
- grafische Benutzerverwaltung
- E-Mail-Einladung oder Passwort-Reset
