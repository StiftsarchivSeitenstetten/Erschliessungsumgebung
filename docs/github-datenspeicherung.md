# GitHub-Datenspeicherung

Phase 2B führt das private Repository `StiftsarchivSeitenstetten/Erschliessungsdaten` als kanonischen Speicher für produktive Erschließungsdaten ein. Die Weboberfläche kommuniziert niemals direkt mit diesem Repository. Alle GitHub-Zugriffe laufen ausschließlich über das FastAPI-Backend der `Erschliessungsumgebung`.

## Trennung der Repositories

`Erschliessungsumgebung`

- Anwendungscode
- Backend
- Schemata
- Tests
- Dokumentation

`Erschliessungsdaten`

- kanonische produktive YAML/Markdown-Datensätze
- technische Vergabestände
- keine Anwendungscodes
- keine Benutzerpasswörter

## GitHub-App-Prinzip

Für den Produktivbetrieb ist eine GitHub App vorgesehen, die nur auf `StiftsarchivSeitenstetten/Erschliessungsdaten` installiert wird.

Der Browser erhält niemals:

- GitHub Personal Access Tokens
- GitHub-App-Private-Keys
- Installation Tokens

Das Backend erzeugt serverseitig ein GitHub-App-JWT, tauscht es gegen ein Installation Token und führt damit die benötigten Repository-Operationen aus.

## Benötigte Environment-Variablen

```text
GITHUB_APP_ID=
GITHUB_INSTALLATION_ID=
GITHUB_PRIVATE_KEY_PATH=
GITHUB_DATA_OWNER=StiftsarchivSeitenstetten
GITHUB_DATA_REPO=Erschliessungsdaten
GITHUB_DATA_BRANCH=main
```

Private Keys und echte Tokens werden nicht ins Repository committed.

## Repository-Struktur

```text
Erschliessungsdaten/
  data/
    fotos/
      foto-000001.md
      foto-000002.md
  state/
    foto-papierabzuege.json
```

`data/fotos/` enthält die kanonischen Foto-Datensätze.

`state/foto-papierabzuege.json` enthält den technischen Vergabestand:

```json
{
  "next_id": 4,
  "formats": {
    "A": 8471,
    "B": 1026,
    "C": 505,
    "D": 1,
    "E": 1,
    "F": 1
  }
}
```

Diese Werte werden nicht blind gesetzt. Fehlt die State-Datei, bootstrapped das Backend den Stand aus den tatsächlich vorhandenen Datensätzen in `data/fotos/`.

## Transaktions- und Signaturverfahren

Beim Erstellen eines neuen Fotodatensatzes bestimmt das Backend verbindlich:

- technische ID
- Nummer im Formatkreis A-F
- vollständige Signatur
- technische Provenienz

Der Ablauf ist optimistisch Git-basiert:

1. aktuellen Head-Commit des Branches lesen
2. State lesen oder aus vorhandenen Datensätzen bootstrappen
3. nächste ID und nächste Formatnummer bestimmen
4. kanonischen YAML/Markdown-Datensatz serverseitig erzeugen
5. Datensatz und aktualisierten State gemeinsam in einem Git-Tree/Commit schreiben
6. Branch-Ref nur aktualisieren, wenn sie noch auf dem erwarteten Head steht
7. bei Ref-Konflikt begrenzt neu laden und wiederholen

Datensatz und State werden niemals in getrennten Commits geschrieben.

## Verbindliche Reservierung für neue Foto-Datensätze

Die kommende persistente Speicherwarteschlange kann vor dem vollständigen Create mit
`POST /api/records/photos/reservations` eine Record-ID und Signatur verbindlich reservieren.
Der Request enthält ausschließlich eine clientseitig erzeugte UUID als `operation_id` und
die Signaturpartition A–F. Die Antwort liefert `operation_id`, `record_id`, `signature`,
`partition` und `reserved_at`; eine Record-Revision gibt es zu diesem Zeitpunkt noch nicht.

Die Reservierung wird unter `reservations` im bestehenden
`state/foto-papierabzuege.json` gespeichert. Ein Eintrag enthält zusätzlich die vollständigen
Signaturdaten für den späteren Create:

```json
{
  "operation_id": "11111111-1111-4111-8111-111111111111",
  "record_id": "foto-010334",
  "signature": "9.4.2.B.1047",
  "partition": "B",
  "reserved_at": "2026-09-15T09:42:00Z",
  "signature_data": {
    "bestand": "9.4",
    "objektgruppe": "2",
    "format": "B",
    "nummer": 1047,
    "anzeige": "9.4.2.B.1047",
    "status": "vergeben"
  }
}
```

Eine `operation_id` bezeichnet genau einen Create-Vorgang. Wiederholte Requests liefern
die persistierte Reservierung und erhöhen den State nicht erneut. ID-Zähler,
Partitionszähler und Reservation werden gemeinsam in einem atomaren State-Commit
geschrieben. Dadurch liefert auch ein Retry nach verlorener HTTP-Antwort dieselbe Identität.

Reservierungen werden nicht freigegeben; Signaturlücken sind ausdrücklich zulässig. Der
spätere vollständige Create muss `operation_id`, `record_id` und `signature` mitsenden,
verwendet exakt die reservierte Identität und erhöht die Zähler nicht nochmals. Der bisherige
direkte Create ohne Reservation bleibt während dieses Zwischenschritts verfügbar.

## Konflikterkennung bei Bearbeitung

Beim Lesen eines bestehenden Datensatzes liefert die API eine `base_revision` mit. Beim Speichern per `PUT` muss der Client diese Revision mitsenden.
Der Dirty State bezieht sich auf den zuletzt vom Backend bestätigten Datensatzstand und wird nach jedem erfolgreichen Save neu berechnet.

Der Foto-Pilot unterscheidet zentral folgende Speicherzustände:

- `clean`: Der aktuelle Arbeitsstand entspricht ausschließlich dem zuletzt vom Backend bestätigten Stand.
- `dirty`: Es liegen ungespeicherte Änderungen vor.
- `saving`: Der festgehaltene Snapshot wird gerade übertragen.
- `auth_error`, `conflict`, `validation_error`, `error`: Der Save ist fehlgeschlagen; die lokalen Änderungen bleiben erhalten.

`queued` ist als künftiger Zustand vorgesehen und wird später durch die persistente Speicherwarteschlange ergänzt. Der Foto-Pilot wechselt derzeit noch nicht in diesen Zustand.

Ist die gespeicherte Fassung nicht mehr dieselbe, antwortet das Backend mit `409 Conflict`:

```text
Dieser Datensatz wurde inzwischen von einer anderen Person geändert.
Bitte laden Sie die aktuelle Fassung neu.
```

Es gibt kein `last write wins`.

## Provenienz

Neue Datensätze erhalten serverseitig:

```yaml
technik:
  quelle: webapp
  erstellt_am: "2026-09-11T12:00:00Z"
  erstellt_von: "anna"
  geaendert_am: null
  geaendert_von: null
```

Bei Änderungen bleiben `erstellt_am` und `erstellt_von` erhalten. `geaendert_am` und `geaendert_von` werden durch das Backend gesetzt. Der Browser darf diese Werte nicht frei vorgeben.

## API-Endpunkte

Alle Endpunkte verlangen eine gültige Session und Modulzugriff auf `foto_papierabzuege`.

```text
GET  /api/records/photos
GET  /api/records/photos/{id}
POST /api/records/photos
PUT  /api/records/photos/{id}
```

Schreibende Endpunkte verlangen zusätzlich CSRF-Prüfung, Schema-Validierung, fachliche Validierung und Rollenprüfung.

## Lokaler Fake-Modus

Die Repository-Schicht ist austauschbar. Tests verwenden `InMemoryGitRepository`; dadurch entstehen keine echten GitHub-Commits.

Ohne vollständige GitHub-App-Konfiguration verwendet die Anwendung für lokale Entwicklung ebenfalls einen In-Memory-Adapter. Dieser Modus ist nur für Entwicklung und Tests gedacht.

## Manuelle GitHub-App-Schritte

Für den echten Produktivbetrieb muss eine GitHub App manuell eingerichtet werden:

1. GitHub Organization `StiftsarchivSeitenstetten` öffnen.
2. `Settings` → `Developer settings` → `GitHub Apps` → `New GitHub App`.
3. Namen vergeben, z. B. `Erschliessungsumgebung Datenspeicher`.
4. Webhook deaktivieren oder ohne Secret belassen, solange keine Webhooks verwendet werden.
5. Repository permissions setzen:
   - `Contents`: `Read and write`
   - `Metadata`: automatisch `Read-only`
6. Keine weiteren Berechtigungen vergeben.
7. App erstellen.
8. Private Key erzeugen und sicher auf dem Server ablegen.
9. App nur auf `StiftsarchivSeitenstetten/Erschliessungsdaten` installieren.
10. `App ID`, `Installation ID` und Private-Key-Pfad in der Server-Umgebung setzen.

Bis diese Schritte erledigt sind, bleibt der echte GitHub-Adapter konfigurierbar, aber nicht produktiv nutzbar.
