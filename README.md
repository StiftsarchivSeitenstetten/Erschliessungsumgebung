# Erschliessungsumgebung

Schema-gesteuerte Erschließungsumgebung des Stiftsarchivs Seitenstetten für strukturierte YAML/Markdown-Daten.

## Ziel

Dieses Repository dient als Arbeits-, Redaktions- und Datenhaltungsebene für Erschließungsdaten des Stiftsarchivs Seitenstetten.

Der kanonische Datenbestand soll nicht in einer klassischen Datenbank entstehen, sondern in versionierten Markdown-Dateien mit YAML-Frontmatter. Diese Dateien sollen sowohl in GitHub als auch in Obsidian gut lesbar und bearbeitbar bleiben.

Das bestehende Repository `StiftsarchivSeitenstetten/Findmittel` bleibt vorerst unverändert. Eine spätere Anbindung oder ein Export dorthin wird erst entwickelt, wenn der erste Pilot stabil ist.

## Grundprinzip

```text
Erfassungsformular
        ↓
strukturierte YAML/Markdown-Datei
        ↓
Validierung
        ↓
GitHub / Versionsgeschichte
        ↓
redaktionell kontrollierter Datenbestand
        ↓
später: Export / Findmittel / weitere Systeme
```

GitHub übernimmt dabei insbesondere:

- Versionsverwaltung
- Änderungsgeschichte
- Review
- Validierung über GitHub Actions
- spätere Publikations- und Exportprozesse

## Erster Pilot: Fotoerschließung

Der erste Datentyp ist die Fotoerschließung. Ein Foto soll grundsätzlich einen eigenen Datensatz erhalten.

Die stabile technische ID eines Datensatzes wird von der archivischen Signatur getrennt. Der Dateiname orientiert sich an der stabilen ID, nicht an der Signatur.

Beispiel:

```text
data/fotos/foto-000001.md
```

Der erste Pilotbereich ist `9.4.2 - Einzelne Papierabzüge`. Albumseiten, Negative und Diapositive werden in diesem Pilot noch nicht produktiv umgesetzt.

Innerhalb von `9.4.2` wählen Bearbeiterinnen und Bearbeiter nur das Format `A` bis `F`. Jedes Format besitzt einen eigenen fortlaufenden Nummernkreis. Die Signatur wird nach dem Muster `9.4.2.<FORMAT>.<NUMMER>` gebildet, zum Beispiel `9.4.2.C.500`.

Die ersten realen Papierabzug-Testdaten liegen unter `data/fotos/` und dienen als Grundlage für Schema, Validierung und Formularlogik.

## Datenmodell

Strukturierte Erschließungsdaten stehen im YAML-Frontmatter. Für den Foto-Pilot gehören auch die etablierten Erschließungsfelder aus der bisherigen Excel-Praxis kanonisch ins YAML, darunter `titel`, `beschriftung`, `beschreibung`, `dargestellte_personen`, `herkunft`, `orte`, `schlagworte`, `altsignaturen` und `interne_bemerkung`.

Der Markdown-Body ist nur für zusätzliche Freitexte vorgesehen, die nicht bereits strukturiert gespeichert werden. Inhalte aus kanonischen YAML-Feldern sollen dort nicht redundant wiederholt werden.

Das Datenmodell wird nicht vom HTML-Formular definiert. Für den Pilot existiert ein zentrales JSON Schema in `schemas/foto.schema.json`, an dem sich Validierung und weitere Verarbeitung orientieren.

## Redaktionsmodell

Redaktionsstufe, Bearbeitungsstatus und späterer Publikationsstatus werden getrennt geführt.

Die Redaktionsstufe beschreibt die Redaktionshoheit:

- `ehrenamtlich`: berechtigte Ehrenamtliche und Redaktion können bearbeiten
- `redaktionell`: Ehrenamtliche können lesen, aber nicht mehr bearbeiten; Bearbeitung nur durch Redaktion

Der Bearbeitungsstatus beschreibt unabhängig davon den inhaltlichen Arbeitsstand.

Berechtigungen dürfen nicht nur in der Benutzeroberfläche abgesichert werden. Spätere Schreibvorgänge müssen zusätzlich serverseitig beziehungsweise in GitHub-Workflows prüfen, welche Redaktionsstufe der vorhandene kanonische Datensatz besitzt.

## Signaturen

Signaturen bleiben von stabilen technischen IDs getrennt. Die Signatur soll später strukturiert gespeichert und nach definierten Regeln vorgeschlagen oder vergeben werden können.

Eine verbindliche automatische Signaturvergabe darf nicht ausschließlich im Browser erfolgen, sondern muss zentral gegen den Gesamtbestand geprüft werden, damit Eindeutigkeit gewährleistet ist.

Einmal vergebene Signaturen sollen stabil bleiben. Änderungen an Signaturen sind ein eigener redaktioneller Vorgang.

Der aktuelle Pilot berechnet Signaturvorschläge aus vorhandenen Test- und Bestandsdaten. Das ist noch keine transaktionssichere Mehrbenutzer-Reservierung.

Die zentrale Fachkonfiguration für das Papierabzug-Modul liegt in `config/foto-papierabzuege.json`. Python-Validierung und Browser-Pilot verwenden diese Datei gemeinsam für Modulkennung, Bestand, Objektgruppe, Formate, Signaturmuster, Vokabulare und vorbelegbare Felder.

## Digitalisate

Hochauflösende Masterdateien, insbesondere TIFFs, sollen voraussichtlich nicht dauerhaft in diesem Git-Repository liegen.

Das Repository speichert in erster Linie Erschließungsdaten und Verweise auf Digitalisate, zum Beispiel Dateinamen, Vorschaubilder, spätere URLs oder IIIF-Referenzen.

## Bedienprofile

Datenmodell und Benutzeroberflächen bleiben getrennt. Für den Pilot werden mindestens diese Profile vorbereitet:

- Redaktion
- Ehrenamt - Standard
- Ehrenamt - sehbehindert/barrierearm

Die barrierearme Maske soll große Schrift, hohe Kontraste, große Bedienelemente, echte HTML-Labels, sichtbaren Fokus und vollständige Tastaturbedienung unterstützen.

Für gegenwärtige und künftige Erfassungsmasken gelten diese allgemeinen UI-Regeln:

- `Titel` ist ein redaktionelles Feld. Ehrenamtliche erfassen keinen Titel; in ehrenamtlichen Erfassungsmasken wird das Eingabefeld nicht angezeigt.
- `Beschriftung` und `Beschreibung` sind fachlich verschiedene, aber ergonomisch gleichwertige große Textfelder mit gleicher Eingabekomponente, gleicher Breite und gleicher sichtbarer Höhe.
- Dargestellte Personen werden in Erfassungsmasken als wiederholbare Personenzeilen erfasst. Jede Person kann einen Namen und optional einen Hinweis erhalten, zum Beispiel `vermutlich`, `2. von links` oder `Identifizierung laut Beschriftung`.
- Ehrenamtliche erfassen Datierungen über ein einfaches Feld `Datierung` mit Eingaben wie `1966`, `07.1980` oder `25.12.1980` sowie ein Feld `Anmerkung zur Datierung`. Intern wird daraus weiterhin die strukturierte Datierung für Validierung und Archivis-Export erzeugt.
- Der Benutzerbegriff für die verbindliche lokale Abschlussaktion lautet `Datensatz speichern`. Technisch setzt diese Aktion die Signatur auf `vergeben`, aktualisiert die lokale Sitzungsinventur und schaltet den Download frei.

## Vorläufige Repository-Struktur

```text
Erschliessungsumgebung/
├── README.md
├── app/
├── data/
│   └── fotos/
├── config/
├── schemas/
├── vocabularies/
├── presets/
├── ui/
├── exports/
├── docs/
├── scripts/
├── tests/
└── .github/
    └── workflows/
```

Die Struktur ist bewusst vorläufig. Sie darf angepasst werden, wenn sich beim Aufbau des Foto-Piloten eine bessere Lösung ergibt.

## Aktueller Stand und nächste Schritte

Der Pilot `9.4.2 - Einzelne Papierabzüge` ist als statische lokale Anwendung implementiert. Er umfasst Testdaten, zentrales Schema, Fachkonfiguration, Validierung, Archivis-Datumsexport, getrennte Nummernkreise A-F, lokale Vorbelegungen, Standardmaske und barrierearme Maske.

Als nächstes vorgesehen:

1. Praktischer Arbeitstest mit realen Papierabzügen.
2. Fachliche Nachschärfung von Pflichtfeldern, Formaten A-F und Eingabemasken.
3. Aufbau eines produktiven Bestandsinventars.
4. GitHub-Schreibworkflow ohne unsichere Tokens im Browser.
5. Benutzer- und Rollenmodell für Ehrenamtliche und Redaktion.
6. Kollisionssichere zentrale Signaturvergabe.
7. Spätere Export- und Publikationsschnittstelle zum Repository `Findmittel`.

## Lokaler Pilot

Der statische Pilot im Verzeichnis `app/` darf keine GitHub-Tokens speichern oder verlangen. Ehrenamtliche speichern direkt über `Datensatz speichern`; YAML/Markdown-Erzeugung und Validierung laufen dabei im Hintergrund. Eine technische YAML-Vorschau bleibt nur für das Redaktions-/Entwicklungsprofil verfügbar. Produktives Schreiben nach GitHub, Benutzerrollen und kollisionssichere Signaturvergabe bleiben spätere Arbeitsschritte.

Innerhalb einer lokalen Arbeitssitzung merkt sich der Browser gespeicherte, noch nicht nach GitHub geschriebene Datensätze in `localStorage`. Das reine Erzeugen oder Aktualisieren der Vorschau verbraucht noch keine technische ID und keine Signaturnummer. Erst die Aktion `Datensatz speichern` setzt die Signatur auf `vergeben`, erzeugt die herunterladbare kanonische Fassung und nimmt den Datensatz in die lokale Sitzungsinventur auf. Diese lokale Fortschreibung ist weiterhin keine produktive Mehrbenutzer-Reservierung.

Die Funktion `Lokale Sitzungsdaten zurücksetzen` entfernt nur lokal gespeicherte Pilot-Datensätze. Aktive Vorbelegungen und das gewählte UI-Profil bleiben erhalten.

Lokal starten:

```bash
python3 -m http.server 8765
```

Danach im Browser öffnen:

```text
http://127.0.0.1:8765/app/
```

Tests und Validierung:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests
python3 scripts/validate.py
python3 exports/archivis/export.py
```
