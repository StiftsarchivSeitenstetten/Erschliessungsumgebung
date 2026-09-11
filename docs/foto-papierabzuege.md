# Foto-Pilot: Einzelne Papierabzüge

## Bereich 9.4.2

Der Pilot bearbeitet ausschließlich einzelne Papierabzüge im Bereich `9.4.2`.

Der Gesamtbereich `9.4` bezeichnet Fotos. Für den aktuellen Arbeitsstand gilt:

- `9.4.1`: Fotoalben
- `9.4.2`: einzelne Papierabzüge
- `9.4.3`: möglicherweise Negative, noch nicht verbindlich festgelegt
- `9.4.4`: möglicherweise Diapositive, noch nicht verbindlich festgelegt

Ehrenamtliche entscheiden in diesem Modul nicht, ob ein Objekt Album, Papierabzug, Negativ oder Dia ist. Diese Entscheidung liegt im gewählten Arbeitsmodul. Im Modul `Einzelne Papierabzüge - 9.4.2` wählen sie nur das Format.

## Signaturbildung

Für Papierabzüge gilt:

```text
9.4.2.<FORMAT>.<NUMMER>
```

Beispiele:

```text
9.4.2.A.8468
9.4.2.B.1025
9.4.2.C.500
```

Die Signatur wird strukturiert gespeichert:

```yaml
signatur:
  bestand: "9.4"
  objektgruppe: "2"
  format: "A"
  nummer: 8468
  anzeige: "9.4.2.A.8468"
  status: vergeben
```

Nach der ersten verbindlichen Speicherung gelten Format, Nummer und Signatur als stabil. Eine spätere Umsignierung ist ein eigener redaktioneller Vorgang.

Die Fachwerte für Modulkennung, Bestand, Objektgruppe, Formate, Signaturmuster und Vokabulare sind zentral in `config/foto-papierabzuege.json` definiert. Python-Validierung und Browser-Pilot verwenden diese gemeinsame Konfiguration.

Die etablierten Erschließungsfelder werden kanonisch im YAML-Frontmatter gespeichert. Der Markdown-Body bleibt für zusätzliche Freitexte reserviert, die nicht bereits strukturiert erfasst sind.

`Titel` bleibt im Datenmodell erhalten, ist aber ein redaktionelles Feld. Ehrenamtliche Erfassungsmasken zeigen kein bearbeitbares Titelfeld.

`Beschriftung` und `Beschreibung` bleiben fachlich getrennt. In Erfassungsmasken werden sie als gleichwertige große Textfelder mit gleicher Eingabekomponente, gleicher Breite und gleicher sichtbarer Höhe dargestellt.

Dargestellte Personen werden in der Ehrenamtsmaske als wiederholbare Personenzeilen erfasst. Jede Zeile besitzt ein Feld `Name` und ein Feld `Hinweis`, zum Beispiel `vermutlich`, `2. von links`, `stehend rechts` oder `Identifizierung laut Beschriftung`.

Das Fotofeld `korrespondenzstueck` wird als boolescher Wert geführt. Neue Datensätze erhalten standardmäßig `korrespondenzstueck: false`; eine gesetzte Checkbox erzeugt `korrespondenzstueck: true`. In der Ehrenamtsmaske steht diese Checkbox zwischen Erschließung und Datierung und ist vorerst nicht Teil der Vorbelegungsfunktion.

## Nummernkreise A-F

Die Formate `A`, `B`, `C`, `D`, `E` und `F` besitzen getrennte fortlaufende Nummernkreise.

Ein neuer Vorschlag für `A` wird nur aus vorhandenen `A`-Signaturen berechnet. Werte aus `B` bis `F` beeinflussen diesen Vorschlag nicht.

Im Pilot wird die nächste Nummer aus vorhandenen lokalen Test- und Bestandsdaten berechnet. Das ist noch keine transaktionssichere Mehrbenutzer-Reservierung.

Der Browser merkt sich zusätzlich lokal gespeicherte, noch nicht nach GitHub geschriebene Datensätze in `localStorage`. In Ehrenamtsprofilen gibt es keinen sichtbaren YAML-Vorschau-Schritt. `Datensatz speichern` validiert die Eingaben, setzt die Signatur auf `vergeben`, erzeugt im Hintergrund die kanonische Markdown-Datei und nimmt den Datensatz in die lokale Sitzungsinventur auf.

Nach erfolgreichem Speichern kann derselbe Datensatz nicht erneut gespeichert werden. Mit `Neuer Datensatz` beginnt der nächste lokale Draft; dann werden technische ID und Nummer des gewählten Formats fortgeführt.

Die Funktion `Lokale Sitzungsdaten zurücksetzen` löscht nur diese lokale Sitzungsinventur. Aktive Vorbelegungen und das gewählte UI-Profil bleiben erhalten.

## Datierungsmodell

Die interne Datierung wird strukturiert geführt:

```yaml
datierung:
  jahr: 1980
  monat: 7
  tag: null
  anmerkung: "Datierung auf der Rückseite notiert."
  original: "00.07.1980"
  original_typ: "importierte_arbeitsdaten"
```

In Ehrenamtsprofilen wird diese Struktur nicht technisch angezeigt. Dort gibt es nur:

- `Datierung`
- `Anmerkung zur Datierung`

Das Feld `Datierung` akzeptiert einfache Eingaben:

- `1966`
- `07.1980`
- `25.12.1980`

Diese Eingaben werden intern in `jahr`, `monat` und `tag` umgesetzt. Importbezogene Felder wie `original` und `original_typ` bleiben für Altdaten im Modell erhalten, werden in Ehrenamtsmasken aber nicht angezeigt.

Bei neu erfassten Ehrenamtsdatensätzen werden `datierung.original` und `datierung.original_typ` nicht leer ausgegeben. Sie bleiben optionale Felder für importierte oder ältere Daten. Die Bezeichnungen werden vorerst beibehalten, weil eine Umbenennung in `altwert` o. Ä. eine Migration vorhandener Importdaten und Validierungsregeln auslösen würde.

Mindestens möglich sind:

- genaues Datum
- Jahr und Monat
- nur Jahr
- keine Datierung

Komplexere Angaben wie `um`, `vor`, `nach` und Zeiträume sollen perspektivisch möglich bleiben, werden im ersten Pilot aber bewusst zurückhaltend behandelt.

## Archivis-Datumsexport

Für Archivis/Excel werden aus der strukturierten Datierung Textwerte erzeugt:

- Jahr, Monat und Tag: `YYYYMMDD`
- Jahr und Monat: `YYYYMM99`
- nur Jahr: `YYYY9999`
- kein Jahr: leer

Beispiele:

```text
1966       -> 19669999
Juli 1980  -> 19800799
25.12.1980 -> 19801225
```

Diese Exportwerte sind Textwerte und sollen später in Excel nicht automatisch in Excel-Datumswerte umgewandelt werden.

Der Pilot-CSV-Export gibt `korrespondenzstueck` zusätzlich als eigene Spalte `Korrespondenzstueck` mit den Werten `Ja` oder `Nein` aus. Eine endgültige Archivis-Zuordnung kann später noch präzisiert werden.

## Redaktionsstufen

Die Redaktionsstufe beschreibt die Redaktionshoheit:

- `ehrenamtlich`: Ehrenamtliche und Redaktion dürfen lesen und bearbeiten
- `redaktionell`: Ehrenamtliche dürfen lesen, aber nicht mehr bearbeiten; die Redaktion darf bearbeiten

Bearbeitungsstatus und Publikationsstatus sind eigene Dimensionen und dürfen nicht mit der Redaktionsstufe vermischt werden.

## Vorbelegungslogik

Aktive persönliche Vorbelegungen sind Bedienzustand, nicht Bestandteil eines einzelnen Archivdatensatzes.

Eine Vorbelegung bleibt aktiv, bis sie geändert, deaktiviert oder gelöscht wird. Änderungen in einem einzelnen Datensatz ändern die aktive Vorbelegung nicht automatisch.

Nicht vorbelegbar sind insbesondere:

- technische ID
- Format
- Nummer
- Signatur
- Redaktionsstufe
- technische Bearbeitungsprovenienz

Im Webpilot kann die aktive Vorbelegung in `localStorage` gespeichert werden.

In der Ehrenamtsmaske steht die Vorbelegung am Ende der Arbeitsmaske. Der normale Arbeitsfluss bleibt: Signatur/Format, Erfassungsfelder, Datensatz speichern, neuer Datensatz, Vorbelegung und Pilot-/Wartungsfunktionen.

Vorbelegbar sind nur fachliche Erschließungsfelder, darunter Herkunft, Titel, Beschriftung, Beschreibung, Datierung, dargestellte Personen, Sammler, Fotograf, Rechteinhaber, Orte, Schlagworte, Altsignaturen und interne Bemerkung.

Technische ID, Format, Nummer, Signatur, Redaktionsstufe und technische Provenienz sind nicht vorbelegbar.

## Validierung

Die Markdown-Dateien werden mit `PyYAML` gelesen. Das YAML-Frontmatter wird gegen `schemas/foto.schema.json` validiert. Fachprüfungen, die über JSON Schema hinausgehen, bleiben in Python:

- Signaturkonsistenz
- eindeutige technische IDs
- eindeutige Signaturen
- reale Kalenderdaten
- getrennte Nummernkreise

## UI-Profile

Für den Pilot werden vorbereitet:

- Redaktion
- Ehrenamt - Standard
- Ehrenamt - sehbehindert/barrierearm

Die barrierearme Maske verwendet große Schrift, große Bedienelemente, hohe Kontraste, semantisches HTML, echte Labels, sichtbaren Fokus und eine sinnvolle Tab-Reihenfolge.

## Bewusst noch offen

Noch nicht umgesetzt werden:

- produktives Schreiben nach GitHub aus dem Browser
- GitHub-Tokens im Frontend
- OAuth
- produktive Benutzerrollen
- transaktionssichere Mehrbenutzer-Signaturreservierung
- Verbindung zum Repository `Findmittel`
- produktive Module für Negative oder Diapositive
