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

Die Datei `foto-000001.md` wird aus realen Papierabzug-Testdaten entwickelt und dient als Grundlage für Schema, Validierung und Formularlogik.

## Datenmodell

Strukturierte Erschließungsdaten sollen im YAML-Frontmatter stehen. Freie, quellennahe oder erläuternde Texte sollen im Markdown-Teil der Datei stehen.

Das Datenmodell soll nicht vom HTML-Formular definiert werden. Stattdessen wird später ein zentrales Schema entstehen, an dem sich Formular, Validierung und weitere Verarbeitung orientieren.

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

## Digitalisate

Hochauflösende Masterdateien, insbesondere TIFFs, sollen voraussichtlich nicht dauerhaft in diesem Git-Repository liegen.

Das Repository speichert in erster Linie Erschließungsdaten und Verweise auf Digitalisate, zum Beispiel Dateinamen, Vorschaubilder, spätere URLs oder IIIF-Referenzen.

## Bedienprofile

Datenmodell und Benutzeroberflächen bleiben getrennt. Für den Pilot werden mindestens diese Profile vorbereitet:

- Redaktion
- Ehrenamt - Standard
- Ehrenamt - sehbehindert/barrierearm

Die barrierearme Maske soll große Schrift, hohe Kontraste, große Bedienelemente, echte HTML-Labels, sichtbaren Fokus und vollständige Tastaturbedienung unterstützen.

## Vorläufige Repository-Struktur

```text
Erschliessungsumgebung/
├── README.md
├── app/
├── data/
│   └── fotos/
├── schemas/
├── vocabularies/
├── signatures/
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

## Nächste Schritte

1. Grundstruktur und README anlegen.
2. Gemeinsam ein reales typisches Foto auswählen.
3. Daraus `data/fotos/foto-000001.md` als ersten fachlichen Beispieldatensatz entwickeln.
4. An diesem Datensatz klären:
   - welche Felder Ehrenamtliche brauchen;
   - welche Felder nur die Redaktion braucht;
   - welche Werte kontrollierte Vokabulare werden;
   - welche Felder automatisch erzeugt werden;
   - welche Angaben ins YAML gehören;
   - welche Angaben als Markdown-Freitext geführt werden;
   - wie Digitalisat, physisches Foto, Aufnahme, Personen, Ort und Datierung modelliert werden;
   - wie die Signatur tatsächlich aufgebaut ist.
5. Erst danach `schemas/foto.schema.json` entwickeln.
6. Erst danach das erste Erfassungsformular bauen.

## Lokaler Pilot

Der statische Pilot im Verzeichnis `app/` darf keine GitHub-Tokens speichern oder verlangen. Er erzeugt lokal YAML/Markdown, zeigt eine Vorschau und kann Datensätze herunterladen. Produktives Schreiben nach GitHub, Benutzerrollen und kollisionssichere Signaturvergabe bleiben spätere Arbeitsschritte.
