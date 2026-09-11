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

## Nummernkreise A-F

Die Formate `A`, `B`, `C`, `D`, `E` und `F` besitzen getrennte fortlaufende Nummernkreise.

Ein neuer Vorschlag für `A` wird nur aus vorhandenen `A`-Signaturen berechnet. Werte aus `B` bis `F` beeinflussen diesen Vorschlag nicht.

Im Pilot wird die nächste Nummer aus vorhandenen lokalen Test- und Bestandsdaten berechnet. Das ist noch keine transaktionssichere Mehrbenutzer-Reservierung.

## Datierungsmodell

Die interne Datierung wird strukturiert geführt:

```yaml
datierung:
  jahr: 1980
  monat: 7
  tag: null
  original: "00.07.1980"
  original_typ: "importierte_arbeitsdaten"
```

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
