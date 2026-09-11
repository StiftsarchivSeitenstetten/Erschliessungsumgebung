# Deployment DomainFactory

Diese Notiz beschreibt die geplante Bereitstellung der Erschliessungsumgebung
auf DomainFactory Webhosting Plus Launch. Sie ersetzt nicht die spaetere
cPanel-Eingabe, sondern haelt die noetigen Werte und Pruefschritte fest.

## cPanel Python App

- Python-Version: `3.11.15`
- Application Root: `erschliessungsumgebung`
- Domain: `tauruslektorat.at`
- Application URL: `tauruslektorat.at` ohne zusaetzlichen Pfad
- Startup File: `passenger_wsgi.py`
- Entry Point: `application`

Die Anwendung selbst ist FastAPI/ASGI. DomainFactory Passenger erwartet WSGI.
`passenger_wsgi.py` importiert deshalb die bestehende App `backend.main:app`
und stellt sie mit `a2wsgi.ASGIMiddleware` als WSGI-Callable `application`
bereit. Die Datei startet keinen Entwicklungsserver und enthaelt keine Secrets.

## Abhaengigkeiten

Im cPanel-Terminal bzw. in der Python-App-Umgebung:

```bash
python -m pip install -r requirements.txt
```

Wichtig fuer den Hostingbetrieb:

- `a2wsgi`: ASGI-zu-WSGI-Adapter fuer Passenger
- `PyMySQL`: SQLAlchemy-Treiber fuer MariaDB/MySQL ohne serverseitige
  Kompilierung
- `cryptography` und `PyJWT`: GitHub-App-Authentifizierung

## Environment Variables

Die produktiven Werte werden in cPanel als Environment Variables gesetzt,
nicht im Repository:

```ini
COOKIE_SECURE=true
DATABASE_URL=mysql+pymysql://DB_USER:DB_PASSWORD@DB_HOST:3306/DB_NAME?charset=utf8mb4

GITHUB_APP_ID=...
GITHUB_INSTALLATION_ID=...
GITHUB_PRIVATE_KEY_PATH=/home/ACCOUNT/private/erschliessungsumgebung/github-app.pem
GITHUB_DATA_OWNER=StiftsarchivSeitenstetten
GITHUB_DATA_REPO=Erschliessungsdaten
GITHUB_DATA_BRANCH=main
```

`DB_USER`, `DB_PASSWORD`, `DB_HOST` und `DB_NAME` sind Platzhalter. Keine
echten Zugangsdaten in Dateien im Webverzeichnis speichern.

## GitHub-App-Private-Key

Der PEM-Schluessel wird auf dem Server ausserhalb oeffentlich erreichbarer
Webverzeichnisse abgelegt, zum Beispiel:

```text
/home/ACCOUNT/private/erschliessungsumgebung/github-app.pem
```

Die Anwendung liest ausschliesslich den Pfad aus `GITHUB_PRIVATE_KEY_PATH`.
Der Inhalt des Schluessels darf nicht in Logs, Commits oder Shell-History
ausgegeben werden.

## Datenbank und Migration

Die lokale Entwicklung kann weiter SQLite verwenden. Fuer DomainFactory ist
MariaDB/MySQL mit SQLAlchemy vorgesehen:

```ini
DATABASE_URL=mysql+pymysql://DB_USER:DB_PASSWORD@DB_HOST:3306/DB_NAME?charset=utf8mb4
```

Vor dem ersten produktiven Login die Migrationen ausfuehren:

```bash
python -m alembic upgrade head
```

Die vorhandenen Migrationen verwenden SQLAlchemy-Typen und enthalten keine
bewussten SQLite-spezifischen Annahmen.

## Passenger-Neustart

Passenger kann ueblicherweise ueber `tmp/restart.txt` neu gestartet werden:

```bash
mkdir -p tmp
touch tmp/restart.txt
```

Das ist nur fuer den Hostingbetrieb gedacht; die lokale Entwicklung bleibt bei
`uvicorn` bzw. den bestehenden Testwerkzeugen.

## Smoke-Test Nach Deployment

Nach dem Neustart pruefen:

```bash
curl -fsS https://tauruslektorat.at/health
```

Erwartet:

```json
{"status":"ok"}
```

Anschliessend im Browser:

- `https://tauruslektorat.at/` oeffnet die Login-Ansicht bzw. leitet dorthin.
- Login setzt Secure/HttpOnly Session-Cookie und Secure CSRF-Cookie.
- Nach Anmeldung ist der Arbeitsbereich Foto-Papierabzuege erreichbar.
- Lesender Zugriff auf das Datenrepository erfolgt serverseitig ueber die
  GitHub-App-Konfiguration.

Der erste Schreibvorgang auf `main` soll ein echter fachlicher
Erfassungsdatensatz ueber die Benutzeroberflaeche sein.
