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

Die Datei `foto-000001.md` wird noch nicht automatisch erzeugt. Sie soll im nächsten Schritt gemeinsam anhand eines realen Fotos entwickelt werden. Erst aus diesem realen Beispieldatensatz werden anschließend Schema, Vokabulare und Formularlogik abgeleitet.

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

## Digitalisate

Hochauflösende Masterdateien, insbesondere TIFFs, sollen voraussichtlich nicht dauerhaft in diesem Git-Repository liegen.

Das Repository speichert in erster Linie Erschließungsdaten und Verweise auf Digitalisate, zum Beispiel Dateinamen, Vorschaubilder, spätere URLs oder IIIF-Referenzen.

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
├── scripts/
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
