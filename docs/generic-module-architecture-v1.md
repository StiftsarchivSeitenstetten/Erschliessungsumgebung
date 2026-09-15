# Generische Modularchitektur v1

## Bestandsaufnahme

Der Stand vor diesem Branch ist ein stabiler Foto-Pilot. Die fachliche Funktionalität ist aber noch an mehreren Stellen fotospezifisch verdrahtet:

- Frontend: `app/app.js`, `app/index.html` und `app/style.css` bilden direkt das Papierabzug-Formular ab.
- API: `backend/routes/records.py` stellt ausschließlich `/api/records/photos` bereit.
- Persistenz: `backend/records/photos.py` kennt Foto-Pfade, Foto-State, Fotoindex, Signaturvergabe und YAML-Rendering.
- Fachkern: `scripts/foto_core.py` enthält Foto-Schema-Validierung, Signaturbau und Markdown/YAML-Serialisierung.
- Migration: `backend/migration/fotos/analyse.py` ist berechtigt fotospezifisch, weil es die alte Excel-Fotoerfassung migriert.

Es gibt bereits Ansätze, die als Ausgangspunkt für die generische Architektur dienen:

- `ui/modules/papierabzuege.yaml` als Modulbeschreibung.
- `config/foto-papierabzuege.json` als zentrale Fachkonfiguration des Foto-Piloten.
- Vokabular-Dateien unter `vocabularies/`.
- Rollenmodell `ehrenamtlich`, `redaktion`, `admin`.
- Regressionstests für Authentifizierung, Foto-API, Fotoindex, Foto-Core, Migration und statische UI-Regeln.

## Zielbild

Neue Erschließungsmodule sollen langfristig aus JSON-Schema, Modulkonfiguration und Vokabularen bestehen. Zentraler Anwendungscode stellt allgemeine Mechanismen bereit: Authentifizierung, Rollenprüfung, Feldrechte, Laden, Speichern, Konflikte, Suche, Listen, technische Metadaten und GitHub-Persistenz.

Das JSON-Schema beschreibt nur den kanonischen Datensatz. Modul-/UI-Konfiguration beschreibt Formular, Darstellung, Rollen-/Feldrechte, Presets, Such- und Listenfelder, Vokabulare und Signaturstrategie. Vokabulare bleiben eigenständige Ressourcen mit stabilen IDs.

## Modulkonfiguration v1

Die formale Sprache liegt in `schemas/module-config.schema.json`. Moduldateien liegen unter `ui/modules/` und verwenden `config_version: 1`.

Die Modulkonfiguration v1 enthält:

- `module`: ID, Zugriffsschlüssel, Label, Beschreibung und Datensatztyp.
- `schema`: Verweis auf das fachliche JSON-Schema des kanonischen Datensatzes.
- `storage`: Datenverzeichnis, Dateinamenstrategie, optionaler State und Index.
- `id`: deklarative ID-Strategie, zunächst `prefixed_sequence`.
- `signature`: deklarative Signaturstrategie, für den Foto-Piloten `partitioned_sequence` mit den Partitionen A-F.
- `form`: Abschnitte, Reihenfolge, Felder, Labels, Widgets, Hilfetexte, Gruppen und Repeater-Felder.
- `access`: rollenabhängige Feldrechte mit getrenntem `view` und `edit`.
- `search`: Volltextfelder, Filterfelder und Standardsortierung.
- `list`: Spalten, Labels, Feldpfade und Sortierbarkeit.
- `presets`: Felder, die vorbelegt werden dürfen oder ausdrücklich ausgeschlossen sind.
- `ui_profiles`: reine Darstellungsprofile ohne Berechtigungslogik.

Die Konfiguration enthält keine GitHub-Zugangsdaten, Tokens oder andere Secrets. Strategien werden nur referenziert und parametrisiert; die eigentliche Umsetzung bleibt zentraler Anwendungscode.

## Zuständigkeiten

JSON-Schema beschreibt die kanonischen YAML-/Markdown-Daten: Struktur, Pflichtfelder, strukturelle Typen und strukturelle Validierung. Es enthält keine Formular- oder Rollenlogik.

Modulkonfiguration beschreibt, wie ein kanonischer Datensatz in der Erschließungsumgebung bearbeitet wird: Formularstruktur, Widgets, Feldrechte, Vorbelegungen, Suche, Listen, Speicherorte und Signaturstrategie. Sie speichert keine Information, die ausschließlich dort kanonisch wäre.

Vokabulare sind eigenständige Fachressourcen. `schemas/vocabulary.schema.json` definiert stabile Term-IDs, Labels, Aktivstatus, optionale Beschreibungen, Aliase, Sortierung und Rechte für `use`, `add`, `rename`, `deactivate` und `purge`. Verwendete Begriffe sollen später deaktiviert statt physisch gelöscht werden.

## Core Datatypes v1

Die erste Datentypbibliothek registriert folgende semantische Kerntypen:

- `agent`
- `place`
- `date`
- `date_range`
- `term_ref`
- `identifier`
- `record_ref`
- `digital_asset`
- `language`

Diese Typen beschreiben fachliche Semantik, nicht Widgets. Widgets bleiben Teil der Modul-/UI-Konfiguration.

Zusätzlich liegt eine maschinenlesbare JSON-Schema-Bibliothek in `schemas/core-datatypes.schema.json`. Sie definiert `$defs` für:

- `agent`: Person, Körperschaft oder Familie mit Name, optionalen Normdaten und Hinweis. Rollen von Akteuren gehören nicht in `agent`, sondern in den jeweiligen Datensatzkontext.
- `place`: Ort mit Name, optionalen Normdaten, Koordinaten und Hinweis.
- `date`: historische Einzelangabe mit Jahr, optional Monat und Tag, optionaler Anzeige, Unsicherheit und Hinweis. Unvollständige Datierungen benötigen keine künstlichen Monats- oder Tageswerte.
- `date_range`: Zeitraum mit `from`, optionalem `to`, Anzeige, Unsicherheit und Hinweis.
- `term_ref`: stabile Referenz auf einen kontrollierten Begriff.
- `identifier`: Kennung mit Wert, optionalem Typ und Schema.
- `record_ref`: Referenz auf einen anderen Datensatz.
- `digital_asset`: allgemeine digitale Repräsentation über ID oder Pfad, MIME-Type, Label und Dateiname.
- `language`: stabiler ISO-639-basierter Code mit optionalem Label.

Neue Core Datatypes und Widgets können später additiv ergänzt werden. Bestehende Module dürfen dadurch nicht ungültig werden.

## Rollen und Profile

Berechtigungsrollen und Darstellungsprofile sind getrennt:

- Rollen: `ehrenamtlich`, `redaktion`, `admin`
- Profile: etwa `standard`, `barrierearm`, `redaktion`

Rollen stehen ausschließlich in `access.fields.*.view` und `access.fields.*.edit`. Profile stehen in `ui_profiles` und steuern nur Darstellung, etwa technische Vorschau oder barrierearme UI. Ein redaktionelles Feld wird also über Rollenrechte sichtbar und bearbeitbar, nicht durch ein besonderes Profil.

## Benutzer, Rollen, Modulzugriff und aktives Modul

Benutzerrolle, Modulzugriff und aktives Modul sind drei verschiedene Ebenen:

- Die Benutzerrolle bestimmt Rechte innerhalb eines Moduls.
- `module_access` bestimmt, welche Module der Benutzer öffnen und auswählen darf.
- Das aktive Modul ist eine Laufzeitentscheidung und keine dauerhafte Benutzereigenschaft.

Alle Rollen verwenden dieselbe generische Modulauswahl. Die Rolle eines Benutzers legt nicht fest, welches Erfassungsmodul geöffnet wird.

Der Modulkatalog steht unter `GET /api/modules`. Er liefert nur Module, für die der angemeldete Benutzer laut `module_access` berechtigt ist. Die Antwort enthält bewusst nur Auswahlmetadaten:

```json
[
  {
    "id": "foto_papierabzuege",
    "module_id": "papierabzuege_9_4_2",
    "label": "Fotoerschließung",
    "description": "Erfassung einzelner Papierabzüge aus Bestand 9.4.2.",
    "category": "Fotobestand",
    "icon": "photo",
    "order": 10
  }
]
```

Die Detailkonfiguration bleibt unter `GET /api/modules/{module_key}`. Die Modulauswahl nach Login wird aus dem Katalog erzeugt und ist nicht statisch im Frontend hinterlegt. Direkte Modul-URLs bleiben Komfort; der Server prüft weiterhin `module_access`.

Der bestehende Foto-Direktzugang bleibt während der Migration erhalten. Bei einem einzigen freigegebenen Modul darf die Auswahlseite vorübergehend direkt dorthin navigieren. Bei mehreren Modulen wird eine generische Auswahl angezeigt. Ein Modulwechsel ist über die Arbeitsbereichsauswahl möglich, ohne dass der Benutzer sich abmelden muss.

## Generischer Application Shell und FormRenderer

Der erste generische Frontend-Schritt ist eine ausdrücklich lesende Modulvorschau unter `/app/module/?module={module_key}`. Sie ersetzt die bestehende Foto-Erfassungsmaske unter `/app/` noch nicht und führt keine Schreiboperationen aus.

Die Vorschau lädt:

- `GET /api/modules/{module_key}` für den rollenaufgelösten Modul-Descriptor.
- `GET /api/modules/{module_key}/records` für die konfigurierte Datensatzliste.
- `GET /api/modules/{module_key}/records/{record_id}` für den ausgewählten Datensatz.

Der `FormRenderer` arbeitet ausschließlich mit Descriptor-Metadaten: Abschnitte, Feldreihenfolge, Pfade, Labels, Hilfetexte, Widgets sowie den bereits serverseitig aufgelösten Flags `visible`, `editable` und `presettable`. Er enthält keine Kenntnis konkreter Erschließungsformate oder Foto-Feldnamen.

Die erste `WidgetRegistry` unterstützt für die read-only Vorschau:

- `text`
- `textarea`
- `checkbox`
- `select`
- `date`
- `date_range`
- `vocabulary_select`
- `repeater`

Repeater rendern ihre Unterfelder rekursiv über dieselbe Feldmetadaten-Schnittstelle. Pfade werden generisch über einfache Punktnotation gelesen. Unbekannte Widgets schlagen kontrolliert fehl, damit fehlende Renderer nicht stillschweigend falsche Anzeigen erzeugen.

Die generische Schreib-API ist nur für Tests freischaltbar. In diesem freigegebenen Testbetrieb kann die Preview bestehende Datensätze per `PUT` aktualisieren; eine Neuanlage ist nicht angeschlossen. Der Browser interpretiert keine Rollenlisten, sondern verwendet ausschließlich `visible` und `editable` aus dem serverseitigen Descriptor.

## Generischer Editiermodus

Die generische Modulvorschau besitzt zusätzlich zum `read`-Modus einen `edit`-Modus. Änderungen bleiben zunächst im clientseitigen Form State. Für einen bereits vorhandenen Datensatz kann der Benutzer sie im freigegebenen Testbetrieb ausdrücklich speichern.

Ohne Speichern verändern Bearbeitungen weder Server noch Datenrepository. Neue Datensätze, Autosave und ein produktiver Ersatz der Foto-Maske gehören weiterhin nicht zu diesem Schritt.

Die Modi sind klar getrennt:

- `read`: bisheriges read-only Rendering aus Modul-Descriptor und Datensatz.
- `edit`: sichtbare und editierbare Felder werden als bearbeitbare Controls gerendert; sichtbare, aber nicht editierbare Felder bleiben gesperrt; unsichtbare Felder werden nicht dargestellt.

Der Client interpretiert dabei keine Rollenlogik. Er verwendet ausschließlich die serverseitig aufgelösten Descriptor-Flags `visible` und `editable`.

### Form State, Original State und Dirty State

Die Preview erzeugt pro geladenem Datensatz einen `FormState` mit zwei getrennten Kopien:

- `original`: der zuletzt geladene fachliche Datensatz.
- `current`: der aktuelle Bearbeitungsstand.

Widget-Änderungen werden in `current` zurückgelesen. `isDirty()` vergleicht `original` und `current` generisch über die Datenstruktur, nicht feldspezifisch. `changedPaths()` kann zusätzlich die geänderten Descriptor-Feldpfade ausweisen. `Änderungen verwerfen` ersetzt `current` wieder durch `original`.

### Payload Builder

`buildPayload()` erzeugt aus dem Bearbeitungsstand einen fachlichen Payload. Enthalten sind nur Felder, die laut Descriptor sichtbar und editierbar sind. Serververwaltete bzw. technische Pfade werden explizit ausgeschlossen:

- `id`
- `revision`
- `base_revision`
- `technik.erstellt_am`
- `technik.erstellt_von`
- `technik.geaendert_am`
- `technik.geaendert_von`

Unsichtbare Felder werden nicht aus einem geladenen vollständigen Datensatz in den Payload zurückgeschrieben. Damit bleiben redaktionelle oder rollenabhängig ausgeblendete Werte geschützt, sobald später eine Schreib-API angeschlossen wird.

### Widget-Roundtrip und Repeater

Die `WidgetRegistry` besitzt nun pro Widget eine Zwei-Wege-Schnittstelle:

- `render`: Datenwert zu Control.
- `readValue`: Control zu Datenwert.
- `setValue`: programmatisches Setzen eines Controls.

Unterstützt sind `text`, `textarea`, `checkbox`, `select`, `date`, `date_range`, `vocabulary_select` und `repeater`. Text-Widgets erhalten Zeilenumbrüche bei `textarea`; strukturierte Werte können als JSON roundtrippen, bis spezifischere Editoren eingeführt werden. `checkbox` liefert Boolean-Werte. `select` speichert den kanonischen Optionswert. `vocabulary_select` speichert die stabile Term-ID bzw. erhält die `term_ref`-Struktur.

Repeater unterstützen generisch vorhandene Einträge, neue Einträge, Entfernen und mehrere Einträge. Unterfelder werden ausschließlich über `item_fields` beschrieben und rekursiv über dieselbe Renderer-/Widget-Schnittstelle verarbeitet. Es gibt keinen Sonderfall für Foto-Felder wie dargestellte Personen; derselbe Mechanismus kann später etwa für Beteiligte eines Autographenmoduls verwendet werden.

### Pflichtfelder und Vorvalidierung

Der Modul-Descriptor enthält erste aus dem fachlichen JSON-Schema abgeleitete Metadaten, insbesondere `required` und Optionen aus `enum` bzw. deklarativen Feldoptionen. Die clientseitige Vorvalidierung bleibt bewusst klein:

- leere Pflichtfelder,
- ungültige Select- bzw. Vocabulary-Optionen,
- strukturell ungültige Wiederholfelder.

Die vollständige Sicherheits-, Rechte- und Schema-Validierung bleibt Aufgabe der serverseitigen `RecordRuntime`. Im Browser wird keine zweite vollständige JSON-Schema-Validierungsarchitektur aufgebaut.

Die Entwicklungsfunktion `Payload anzeigen` zeigt Dirty State, geänderte Pfade, Vorvalidierungsfehler und den aktuell erzeugten fachlichen Payload lokal an. Diese Anzeige enthält keine Server-Secrets und löst keine Persistenz aus.

## Module Runtime Model

Die `ModuleRegistry` lädt und validiert deklarative Moduldateien. Das daraus erzeugte Module Runtime Model ist die zentrale Laufzeitschnittstelle für Backend und später Frontend. Andere Anwendungsteile sollen nicht beliebige YAML-Dictionaries durchsuchen, sondern über definierte Attribute und Methoden arbeiten.

Ein geladenes Modul stellt unter anderem bereit:

- `id`, `access_key`, `label`, `description`, `record_type`
- `schema_path`, `storage`, `id_strategy`, `signature_strategy`
- `sections` und `fields`
- `get_field(id)` und `get_field_by_path(path)`
- `can_view_field(field, role)` und `can_edit_field(field, role)`
- `search_config`, `list_config`, `vocabularies`, `ui_profiles`

## Feldkatalog

Der Feldkatalog normalisiert alle in der Modulkonfiguration beschriebenen Felder. Jedes Feld besitzt eine eigene Feldkennung und einen Datenpfad. Diese Werte müssen nicht identisch sein: Ein Feld kann `beschriftung` heißen und auf `erschliessung.beschriftung` zeigen.

Normalisierte Felder enthalten mindestens:

- Feldkennung
- Datenpfad
- Label
- Widget
- Abschnitt
- Reihenfolge
- Hilfetext und Placeholder
- Preset-Fähigkeit
- `view`- und `edit`-Rollen
- optionale Vokabularreferenz
- optionale Repeater-Unterfelder

Repeater werden ausschließlich durch ihre Feldmetadaten beschrieben. Es gibt keinen fotospezifischen Sonderfall für `dargestellte_personen`.

## Pfadmodell

Pfade verwenden in v1 eine einfache Punktnotation für verschachtelte Objekte, zum Beispiel:

- `erschliessung.beschriftung`
- `datierung.von`
- `technik.erstellt_am`

Die zentralen Pfadfunktionen können Werte lesen, Existenz prüfen und verschachtelte Objekte beim Schreiben erzeugen. Arrays und wiederholbare Strukturen werden noch nicht über eine komplexe Pfadsprache adressiert, sondern über Repeater-Felddefinitionen modelliert.

## Serverseitige Feldrechte

Die Laufzeitschicht löst statische Konfigurationen wie:

```yaml
access:
  fields:
    erschliessung.titel:
      view: [redaktion, admin]
      edit: [redaktion, admin]
```

für einen konkreten Benutzerkontext zu `visible` und `editable` auf. `edit` setzt `view` voraus; Konfigurationen, die diese Regel verletzen, sind ungültig.

Das Frontend ist nicht die Sicherheitsgrenze. Rollen- und Feldrechte werden serverseitig durchgesetzt.

`admin` erhält nicht automatisch Rechte. Maßgeblich ist die Modulkonfiguration.

## Servergeschützte Metadaten

Bestimmte technische Felder sind serververwaltet und dürfen auch dann nicht durch Clients geändert werden, wenn eine manipulierte Anfrage oder fehlerhafte Konfiguration dies nahelegt. Dazu zählen derzeit:

- `id`
- `base_revision`
- `revision`
- `technik.erstellt_am`
- `technik.erstellt_von`
- `technik.geaendert_am`
- `technik.geaendert_von`

Das bestehende Foto-Verhalten bleibt unverändert: Bei Neuanlage setzt das Backend `erstellt_am`, `erstellt_von`, `geaendert_am` und `geaendert_von`. Bei Aktualisierung bleiben Erstellungswerte erhalten, Änderungswerte werden neu gesetzt. Eine spätere generische Schreibschicht soll diese Regel zentral anwenden.

## Modul-Descriptor

`GET /api/modules/{module_key}` liefert keinen rohen YAML-Dump, sondern einen normalisierten Laufzeitdescriptor für den angemeldeten Benutzer. Der Descriptor enthält Modulmetadaten, Abschnitte, Felder, Widgets, Such- und Listenangaben, Vokabularreferenzen, UI-Profile sowie pro Feld bereits aufgelöste Rechte:

```json
{
  "id": "interne_bemerkung",
  "path": "erschliessung.interne_bemerkung",
  "visible": true,
  "editable": true
}
```

Der Browser muss dadurch langfristig keine Rollenlisten interpretieren, erhält aber trotzdem keine Sicherheitsautorität. Die serverseitige Prüfung bleibt verbindlich.

## Record Runtime Model

Die Record Runtime setzt zur Laufzeit zwei Ebenen zusammen:

- das fachliche JSON-Schema als Definition der kanonischen Datenstruktur
- die Modulkonfiguration als Definition, wie und von wem diese Daten bearbeitet werden dürfen

Die kanonische Datenstruktur wird durch das fachliche JSON-Schema definiert. Die Modulkonfiguration bestimmt, wie und von wem diese Daten bearbeitet werden. Die Record Runtime setzt diese beiden Ebenen zur Laufzeit zusammen.

Die Record Runtime kennt keine fachlichen Feldnamen wie `fotograf` oder `absender`. Sie arbeitet ausschließlich über den Feldkatalog des Moduls und die generischen Pfadoperationen. Dadurch kann sie Datensätze beliebiger Module filtern, Schreibpayloads prüfen und gegen das jeweilige Modulschema validieren.

Zentrale Operationen sind:

- `filter_for_view(record, role)`: erzeugt eine rollenabhängige fachliche Datensicht.
- `filter_for_edit(payload, role)`: prüft eingehende Nutzdaten und gibt nur erlaubte Änderungen zurück.
- `validate(record)`: validiert gegen das JSON-Schema des Moduls, inklusive referenzierter Core Datatypes.
- `prepare_create(payload, user, server_values)`: bereitet eine Neuanlage vor, übernimmt erlaubte Nutzdaten und setzt serververwaltete Metadaten.
- `prepare_update(existing, payload, user)`: wendet erlaubte Änderungen auf einen bestehenden Datensatz an und setzt Änderungsmetadaten.

## Rollenfilterung und Schreibprüfung

Bei der Ausgabe werden fachliche Felder, für die eine Rolle kein `view`-Recht besitzt, nicht in die fachliche Datensatzsicht übernommen. Technisch notwendige Transportinformationen können separat behandelt werden.

Bei Create und Update gilt v1:

- Unbekannte fachliche Felder werden abgelehnt.
- Nicht editierbare Felder werden abgelehnt.
- Serververwaltete Felder werden abgelehnt, auch wenn ein Client sie sendet.
- Danach wird der resultierende vollständige Datensatz gegen das fachliche JSON-Schema validiert.

Diese Runtime entscheidet sich bewusst gegen stillschweigendes Ignorieren manipulierter oder unbekannter Werte. Fehler sollen früh sichtbar sein und keine schleichenden Schemaabweichungen erzeugen.

## Technische und fachliche Metadaten

`id` und `technik.*` sind kanonische technische Metadaten des Datensatzes. `base_revision` und `revision` sind Transport- bzw. Persistenzinformationen und müssen nicht Bestandteil des kanonischen YAML-Frontmatters sein.

Architekturziel für die generische Runtime:

- Neuanlage: `erstellt_am` und `erstellt_von` werden gesetzt; `geaendert_am` und `geaendert_von` bleiben `null`.
- Spätere Änderung: `geaendert_am` und `geaendert_von` werden gesetzt; Erstellungswerte bleiben erhalten.

Analyse des aktuellen Foto-Piloten: `backend/records/photos.py` setzt bei Neuanlage derzeit `geaendert_am` und `geaendert_von` auf denselben Wert wie `erstellt_am` und `erstellt_von`. Die lokalen Beispieldatensätze unter `data/fotos/` enthalten dagegen `null`. Dieses produktive Foto-Verhalten wird in diesem Branch noch nicht geändert; eine spätere Umstellung muss bewusst als Kompatibilitätsschritt erfolgen.

## Repository-Grenze und API-Zielbild

Die Record Runtime weiß nicht, ob Datensätze aus GitHub, einem In-Memory-Testrepository oder einer späteren Persistenzschicht kommen. Sie verarbeitet Python-Dictionaries, Moduldefinitionen und Benutzerrollen. Laden, Commit, Ref-Konflikte, Index und State bleiben Aufgabe der Repository- bzw. Persistenzschicht.

Die generische Read-API ist aktiv:

- `GET /api/modules/{module_key}/records`
- `GET /api/modules/{module_key}/records/{record_id}`

Der Ablauf ist:

```text
API Route
  -> ModuleRegistry / Module Runtime
  -> Record Runtime
  -> Repository
```

Die Route lädt das Modul, prüft den Modulzugriff des Benutzers, liest Datensätze über die bestehende Repository-Schnittstelle und lässt die Record Runtime die rollenabhängige fachliche Sicht erzeugen. Listenwerte stammen aus `list.columns` der Modulkonfiguration. Ist eine konfigurierte Listenspalte für eine Rolle nicht sichtbar, wird ihr Wert nicht ausgeliefert.

Response für einen einzelnen Datensatz trennt fachliche Daten und Transportmetadaten:

```json
{
  "module": "foto_papierabzuege",
  "record_id": "foto-000001",
  "record": {},
  "meta": {
    "revision": "..."
  }
}
```

Listen verwenden entsprechend:

```json
{
  "module": "foto_papierabzuege",
  "records": [
    {
      "record_id": "foto-000001",
      "values": {},
      "meta": {
        "revision": "..."
      }
    }
  ]
}
```

`revision` ist die serverseitig bekannte Version eines gespeicherten Datensatzes. `base_revision` ist die vom Client bei `PUT` zurückgesendete Konfliktinformation und gehört nicht in den kanonischen YAML-/Markdown-Datensatz.

## Generische Schreib-API im Testbetrieb

Die Endpunkte `POST /api/modules/{module_key}/records` und `PUT /api/modules/{module_key}/records/{record_id}` sind implementiert. Beide verlangen Anmeldung, Modulzugriff und CSRF-Token. Sie sind standardmäßig gesperrt (`503`) und werden nur in automatisierten Tests mit `app.state.generic_writes_enabled = True` freigeschaltet. Die Moduldefinition liefert `datensatz_typ`. Ein optionaler `app.state.generic_server_values_provider(module, user, payload)` kann andere schemabedingte Server-Standardwerte liefern; technische ID und Signatur werden stets durch die zentralen Strategien vergeben und überschreiben solche Vorgaben.

### Strategien und Modul-State

Die Strategy Registry in `backend/records/strategies.py` ordnet deklarierte Namen zentralen Implementierungen zu. `prefixed_sequence` liest `prefix` und `width` aus `id` und formatiert `next_record_id` aus dem Modul-State. `partitioned_sequence` liest die Partition aus `partition_field` (standardmäßig `signatur.format`; bei genau einer Partition ist keine Client-Angabe nötig), prüft sie gegen `partitions`, vergibt `next_signature_number[partition]` und rendert `pattern`. Platzhalter wie `{bestand}`, `{objektgruppe}`, `{format}` und `{nummer}` stammen aus Konfiguration und Vergabe. Das Foto-Modul bildet damit A–F und `9.4.2.A.7` ab; ein zweites Testmodul benutzt dieselben Strategien mit `test-0001` und `T.1`. Der Strategiecode kennt keine Modulnamen.

`ModuleState` in `backend/records/module_state.py` lädt ausschließlich den konfigurierten `storage.state.path`. Das bestehende Foto-Format mit `next_record_id` und `next_signature_number` bleibt lesbar; fehlende oder ungültige Zähler werden nicht geschätzt. Strategien verändern nur eine Arbeitskopie. Erst nach Rechte- und Schema-Prüfung committen Datensatzdatei und State-Datei gemeinsam über `commit_files(expected_head=...)`. Validierungsfehler, Dateikollision und Ref-Konflikt lassen beide Dateien unverändert. Diese gemeinsame Repository-Commit-Grenze ist die optimistische Konkurrenzsicherung; bei konkurrierendem Head muss der Client erneut speichern, damit neu vergeben wird.

Ein im Formular angezeigter Signaturvorschlag ist keine Reservierung. Die verbindliche Nummer entsteht erst beim serverseitigen Create. `PUT` vergibt weder ID noch Nummer neu; eine Änderung der Partition ist ohne ausdrückliche Konfigurationsfreigabe `allow_update` gesperrt und bleibt zusätzlich an die Feldrechte gebunden.

Datensatz und Modul-State bestimmen die Vergabe. Ein Such-/Listenindex ist dagegen vollständig aus den Datensätzen abgeleitet. Bei konfiguriertem `storage.index.path` aktualisiert die generische Schreib-API ihn inzwischen gemeinsam mit Record und gegebenenfalls State. Die API bleibt für den Produktivbetrieb gesperrt. Die bisherigen Foto-Endpunkte verwalten ihren Legacy-Fotoindex unverändert.

Der Client sendet fachliche, bearbeitbare Felder unter `record`:

```json
{
  "record": {"daten": {"name": "Beispiel"}}
}
```

Bei `PUT` sendet der Client zusätzlich `base_revision` auf Transportebene. Der Payload muss sämtliche im bestehenden Datensatz vorhandenen, für diese Rolle bearbeitbaren Formularfelder enthalten. Geänderte Einzelwerte, verschachtelte Objekte und ganze Repeater-Listen ersetzen jeweils ihren bisherigen Feldwert. Nicht gesendete read-only oder unsichtbare Felder bleiben aus dem bestehenden Datensatz erhalten. Ein unvollständiger bearbeitbarer PUT-Payload wird abgelehnt; ein generisches `PATCH` existiert nicht.

```json
{
  "base_revision": "abc123",
  "record": {"daten": {"name": "Geaendert", "beteiligte": [{"name": "Person A"}]}}
}
```

Die Antworten verwenden dasselbe Grundmodell wie die Detail-Read-API: `module`, `record_id`, rollenabhängig mit `filter_for_view(...)` gefiltertes `record` und `meta.revision`. `base_revision` und `revision` werden niemals in die kanonische YAML-Frontmatter geschrieben. `PUT` prüft `base_revision` gegen die aktuelle Dateirevision; ein veralteter Wert oder ein konkurrierender Branch-Commit liefert `409`.

Die Runtime lehnt unbekannte Felder mit `422`, nicht berechtigte, unsichtbare, read-only und serververwaltete Felder mit `403` ab. Schemafehler und ein unvollständiger PUT-Payload liefern `422`; unbekanntes Modul oder unbekannter Datensatz `404`, fehlender Modulzugriff `403`, Persistenzfehler `500`. Erst nach Rechteprüfung, vollständigem Merge, technischen Metadaten, Schema-Validierung und Konfliktprüfung schreibt die Repository-Schicht den Datensatz über `commit_files(expected_head=...)` in einem Commit. Bestehender zusätzlicher Markdown-Body bleibt bei `PUT` erhalten.

Beim Erzeugen setzt der Server `technik.erstellt_am` und `technik.erstellt_von`; `technik.geaendert_am` und `technik.geaendert_von` bleiben `null`. Beim Aktualisieren bleiben die Erstellungswerte erhalten und die Änderungswerte werden serverseitig gesetzt. Der Client kann sie ebenso wenig wie `id` bestimmen.

Die normale Testsuite verwendet weiterhin ausschließlich lokale Testrepositories. Separat und ausdrücklich gestartete Integrationsläufe prüfen die generische Schreib- und Indexschicht mit dem echten GitHub-Adapter auf `Erschliessungsdaten/integration-test`. Die Produktivfreigabe ist ein gesonderter Schritt.

Die bestehenden Foto-Endpunkte bleiben während der Migration Referenz und werden erst ersetzt, wenn die generische API vollständige Funktionsparität nachgewiesen hat.

### Isolierter GitHub-Integrationstest

`integration_tests/generic_github.py` ist von der normalen Testsuche getrennt. Ein Live-Lauf erfordert sowohl `GENERIC_GITHUB_INTEGRATION=1` als auch `--write`:

```bash
GENERIC_GITHUB_INTEGRATION=1 .venv/bin/python -m integration_tests.generic_github \
  --write --report /private/tmp/generic-github-integration-report.json
```

Die wirksame Konfiguration muss bereits exakt `StiftsarchivSeitenstetten/Erschliessungsdaten`, Branch `integration-test`, ergeben; der Runner stellt den Branch nicht selbst um. Er verlangt den Anwendungsbranch `generic-module-architecture-v1`, prüft, dass `.env` nicht versioniert ist, und dokumentiert Code- sowie Daten-Heads. Vor jeder GitHub-Mutation kontrolliert er erneut den Zielbranch und den unveränderten `main`-Head. Seine Pfadfreigabe erlaubt nur `data/integration-test/integration-NNNN.md` und `state/integration-test.json`. Ref-Updates sind ausschließlich auf `integration-test` und mit `force: false` möglich.

Das Modul `generic_integration_test` wird nur in diesem Testprozess aus `integration_tests/generic_fixture.py` geladen. Es nutzt die vorhandene Modulvalidierung, beide Vergabestrategien, Text, Repeater, `date_range` sowie ein redaktionelles Feld. Login, CSRF, Rollenprüfung und die generischen HTTP-Routen laufen unverändert in einem lokalen ASGI-Testclient; nur die Modulauflösung wird auf die isolierte Testdefinition begrenzt. Benutzer und Sessions liegen in einer temporären SQLite-Datenbank. `generic_writes_enabled` wird ausschließlich an dieser App-Instanz aktiviert, nachdem die standardmäßige Sperre mit HTTP 503 geprüft wurde. Die laufende Produktionsanwendung erhält keine Freigabe.

Ein fehlender State wird nur für die isolierte Testfläche mit Zählern ab eins initialisiert, sofern noch kein Testverzeichnis existiert. Create vergibt ID und Signatur, validiert den vollständigen YAML-Datensatz und schreibt Record plus State atomar in einen Git-Commit. Jeder erfolgreiche Commit wird direkt über GitHub auf Dateiliste und Elterncommit geprüft. Der Read-back über GET wird mit den gespeicherten fachlichen Daten verglichen, einschließlich Repeater, Datierung und Rollenfilter.

Beim Update wird die Git-Blob-Revision als `base_revision` übergeben. ID, Signatur, Erstellungsmetadaten und State bleiben erhalten; Änderungsmetadaten und neue Revision werden geprüft. Ein zweites Update mit der alten Revision muss HTTP 409 ergeben. Schemafehler, unbekannte Felder, read-only und versteckte Felder, clientseitige ID, technische Metadaten sowie fehlende Revision dürfen weder Record noch State noch Branch-Head verändern.

Der Ref-Konflikttest hält einen alten Branch-Head fest, erzeugt regulär einen zweiten Datensatz und versucht danach einen Commit mit dem veralteten Head. Der echte Adapter muss ihn vor dem Erzeugen von Git-Objekten ablehnen. Eine zusätzliche künstliche Race Condition zwischen Git-Tree-Erzeugung und Ref-Update wird live nicht erzwungen; die bestehende Ref-Fehlerbehandlung bleibt durch Adapter-Unit-Tests abgedeckt. Es erfolgen keine Force-Pushes oder History-Umschreibungen.

Die Nachkontrolle vergleicht alle geschützten Git-Bäume und Blobs sowie die tatsächliche Commitfolge und Dateiliste. Damit werden auch `data/fotos`, Foto-State und vorhandener Fotoindex ohne Vollauflistung der Fotodatensätze auf Unverändertheit geprüft. Testdatensätze bleiben als nachvollziehbare Integrationsartefakte erhalten. Der JSON-Bericht enthält Heads, Commit-Dateilisten, IDs, Signaturen und Prüfergebnisse, aber keine Tokens oder Schlüssel.

Der gleiche HTTP-Ablauf ist mit `--offline` ausschließlich gegen ein In-Memory-Repository ausführbar und wird von `tests/test_generic_integration_safety.py` ohne Netzwerk geprüft. Die normale Suite aktiviert niemals den Live-Modus.

Beim ersten Integrationslauf ohne Index funktionierten Create, direkter Detailzugriff per bekannter ID, Update und die kleine Verzeichnisliste des Testmoduls. Unindexierte Module unterstützen diese Verzeichnisliste weiterhin. Für inzwischen indexierte Module wird die Liste ausschließlich aus dem generischen Index gelesen; ein fehlender Index muss zuerst aufgebaut werden.

Der erste ausgeführte Live-Lauf auf Architekturstand `5e77d6f1b9856d0bc5c42f95e0323b0590d07f8f` war erfolgreich:

| Prüfung | Ergebnis |
| --- | --- |
| Wirksamer Datenbranch | `integration-test` |
| Daten-main vorher und nachher | `bcde7c81187fd54466f4b2ecd80e10260bda40f0` |
| integration-test vorher | `1320701c74ab9a294c7b392b354050703af5616e` |
| integration-test nachher | `e54a27ff3c36afb1f220b0705a1eebd4fa6f052c` |
| Erster Datensatz | `integration-0001`, `INTEGRATION.T.1` |
| Zweiter Datensatz | `integration-0002`, `INTEGRATION.T.2` |
| Finaler Test-State | `next_record_id: 3`, `next_signature_number: {T: 3}` |
| Read-back | Fachwerte, Repeater, date_range, Revision und Rollen redaktion/ehrenamtlich korrekt |
| Update | ID, Signatur, `erstellt_*` und State unverändert; `geaendert_*` und neue Revision gesetzt |
| Fehlerfälle | Veraltete Revision 409; fehlende Revision, Schema und unbekanntes Feld 422; read-only, technische Metadaten, Client-ID und verborgenes Feld 403 |
| Fehlerfolgen | Kein zusätzlicher Commit, kein veränderter Record oder State |
| Ref-Konflikt | Veralteter Branch-Head vor Git-Objekterzeugung abgewiesen |
| Nachkontrolle | Exakt die vier beabsichtigten Testcommits; alle geschützten Bäume und Blobs unverändert |

Die erfolgreiche Commitfolge im Datenrepository:

1. `e988f72f358422804e4be1f0bca97d7076ca37fe`: ausschließlich Test-State initialisiert.
2. `bc96dbb4b680f9a6356964b3812b175c564bf155`: `data/integration-test/integration-0001.md` und Test-State gemeinsam erzeugt/fortgeschrieben.
3. `79d35f64056ab7d4165953311d2be59d1247771d`: ausschließlich `integration-0001.md` aktualisiert.
4. `e54a27ff3c36afb1f220b0705a1eebd4fa6f052c`: `data/integration-test/integration-0002.md` und Test-State gemeinsam erzeugt/fortgeschrieben.

Die erste Dateirevision `0b481fa6849396aca15ab7528d44c2b4aa0c4971` wurde durch das Update zu `9283b4c63c1e0378666d75a2a28af8bd7dd66f71`. Der anschließende PUT mit der alten Revision blieb ohne Commit. Im gesamten Lauf wurden nur die beiden Testdatensätze und `state/integration-test.json` verändert. `data/fotos`, `state/foto-papierabzuege.json`, bestehende Indizes und alle sonstigen Dateien blieben identisch.

### Erstes reales Foto über die generische Schreibarchitektur

`integration_tests/photo_github.py` prüft die echte Moduldefinition `foto_papierabzuege` mit dem vorhandenen GitHub-Adapter. Der Live-Modus erfordert zusätzlich zur allgemeinen Testfreigabe ausdrücklich `GENERIC_PHOTO_INTEGRATION=1`:

```bash
GENERIC_GITHUB_INTEGRATION=1 GENERIC_PHOTO_INTEGRATION=1 \
  .venv/bin/python -m integration_tests.photo_github --write \
  --report /private/tmp/photo-generic-live.json
```

Der Runner prüft vor jedem Schreiben den wirksamen Datenbranch, den Anwendungsbranch und den unveränderten Daten-main-Head. Aus dem gelesenen Foto-State bestimmt er die erwartete neue ID; Legacy-Index und direkter Dateizugriff müssen bestätigen, dass sie noch frei ist. Seine Pfadfreigabe erlaubt diese neue Datei sowie den gemeinsamen Create-Commit mit Foto-State und inzwischen auch generischem Index. Für heutige Wiederholungen muss der generische Index vorher aufgebaut sein. Bestehende Fotos und Legacy-Index bleiben geschützt. Zähler werden nicht manuell verändert; die generischen Strategien führen die Vergabe durch.

Der Test verwendet echte Login-/CSRF-Prüfung, die unveränderten generischen POST-/GET-/PUT-Routen und beide Rollen. `photo_fixture.py` liefert vollständige fachliche Testwerte und über den vorhandenen optionalen Serverwertegeber nur Schema-/Modulkennung, Workflow-Standardwerte und `technik.quelle: webapp`. Er liefert keine ID oder Signaturnummer. Diese Standardwerte sind weiterhin eine testlokale Konfiguration, keine allgemeine produktive Default-Engine.

Der erste Live-Lauf auf Code-Stand `1c05d99e9b2b27247c2dd9524d3cf45173454775` war erfolgreich:

| Merkmal | Ergebnis |
| --- | --- |
| Daten-main vorher/nachher | `bcde7c81187fd54466f4b2ecd80e10260bda40f0` |
| integration-test vorher | `e54a27ff3c36afb1f220b0705a1eebd4fa6f052c` |
| integration-test nachher | `5ee513fb2221bf2ceaa0d4f8739f507769b84fb4` |
| Neue Datei | `data/fotos/foto-010332.md` |
| ID / Signatur / Partition | `foto-010332` / `9.4.2.A.8610` / A |
| Create-Commit | `d655b9ad5e4358b19dd9d387e56cccedd306dbce`: neue Datei und Foto-State gemeinsam |
| Update-Commit | `5ee513fb2221bf2ceaa0d4f8739f507769b84fb4`: ausschließlich neue Foto-Datei |
| State nach Create und Update | ID 10333; A 8611, B 1046, C 579, D 81, E 36, F 1 |
| Konflikt | Veraltete `base_revision` ergibt 409 ohne weiteren Commit oder State-Fortschritt |
| Nachkontrolle | Exakt zwei beabsichtigte Commits; ausschließlich neue Datei und Foto-State verändert |

Der Datensatz enthält ausschließlich Felder des bestehenden Foto-Schemas: Beschriftung, Beschreibung, Fotograf, Orte, Schlagworte, Altsignatur, Korrespondenzstück, strukturierte Datierung und mehrere dargestellte Personen. Das Update änderte Fotograf und Beschreibung, ergänzte eine dritte Person, änderte einen Personenhinweis und setzte die Datierung auf 13.06.1967. ID, Signatur und Erstellungsmetadaten blieben erhalten; `geaendert_*` und die neue Blob-Revision wurden gesetzt. Revision A war `74fdb17bceeb81acbd05e0e12e6ba93a05269405`, Revision B `06e3efa3dccdd315cbc7d9e0cec7dae1faaf26e9`.

Die geschriebene YAML-Frontmatter wurde direkt gelesen, gegen Foto-Schema und Legacy-Fachprüfungen validiert und mit `build_new_record` für denselben fachlichen Payload, Ausgangs-State und Erstellungszeitpunkt verglichen. Alle kanonischen Werte stimmen überein, mit einer bewussten Ausnahme: Legacy füllt bereits beim Create `geaendert_am/von`, die generische Runtime setzt beide zunächst auf null. Die YAML-Schlüsselreihenfolge ist anders, ohne semantische Auswirkung. Erneutes Serialisieren mit `render_photo_markdown` erhält die geprüften kanonischen Werte. Die Wurzelstruktur entspricht dem unverändert gelesenen Importfoto `foto-000002`; Importprovenienz und unvollständige Altdaten bleiben davon unberührt.

`read_photo_record` und die bestehende Foto-GET-API lesen die neue Datei nach Create und Update korrekt. Der generische Read-back ist für Redaktion und Ehrenamt vollständig entsprechend dem Feldkatalog geprüft: Titel nur redaktionell; `technik` bleibt in der generischen Ansicht verborgen und wurde in der gespeicherten Datei sowie im Legacy-Read-back geprüft. Das ist die vorhandene Rollenfilterung, kein Verlust gespeicherter Metadaten.

Das alte Formular wurde im Browser unter `/app/?record=foto-010332` praktisch geprüft. Es zeigte Signatur, aktualisierte Texte, drei Personen, Orte, Korrespondenzstück und das aktualisierte Datum korrekt an. Ein separater Testserver mit `--serve-readonly --port 8768` verwendete eine temporäre Benutzer-Datenbank und blockierte sämtliche Record-Schreibanfragen sowohl im HTTP-Zugang als auch im Repository. Es wurde im Formular nichts gespeichert; der Server wurde danach beendet. Das reguläre Formular und sein Speicherweg wurden nicht geändert.

Der Fotoindex blieb bytegleich bei 10.330 Einträgen. Der neue Datensatz fehlt darin: Legacy-Liste und Suche zeigen ihn nicht, Signatur-Lookup liefert 404, Vorher-/Nachher-Navigation im Formular ist deaktiviert. Direkte ID-Lesung und direkte Formular-URL funktionieren. Generische Indexierung ist deshalb vor einer produktiven Umschaltung zwingend; eine Foto-Sonderlösung wurde nicht ergänzt.

Weitere noch bestehende Unterschiede: Die generische Runtime validiert JSON Schema, während Legacy zusätzlich fachliche Kalender- und Konsistenzprüfungen ausführt; der Test überprüft den konkret gespeicherten Datensatz zusätzlich mit diesen Legacy-Prüfungen. Legacy-Create wiederholt Ref-Konflikte begrenzt automatisch, generisches Create meldet 409 zur erneuten Vergabe. Diese Unterschiede sowie die noch testlokalen Server-Standardwerte müssen vor produktiver Funktionsparität berücksichtigt werden. Normale Unit-Tests führen den gleichen Foto-HTTP-Ablauf nur mit `--offline` aus; zusätzliche Vergleichstests prüfen sämtliche A–F-Partitionen mit unveränderten generischen Strategien.

### Generische Index- und Suchschicht

**Kein fachlicher Datensatz darf ausschließlich im Index existieren. Der Index ist vollständig aus den kanonischen Datensätzen rekonstruierbar.** Die YAML-/Markdown-Dateien bleiben die einzige kanonische Quelle fachlicher Werte; der Index darf gelöscht und durch einen Rebuild ersetzt werden.

`backend/records/module_index.py` wertet ausschließlich Modulkonfiguration, Schema, Feldpfade und generische Werte aus. `list.columns` liefert Listenwerte, `list.default_sort` beziehungsweise `search.default_sort` die Ordnung; `search.fulltext`, `search.lookup` und `search.filters` bestimmen Such-, Lookup- und vorbereitete Filterwerte. Es gibt keine zweite Suchkonfiguration und keine Foto-Feldnamen oder Modulabfragen in der Engine.

Das versionierte JSON-Format enthält `schema_version: 1`, die Modul-ID, einen Fingerprint der Indexkonfiguration und des Schemas sowie nach `record_id` stabil sortierte `records`. Jeder Eintrag enthält `record_id`, die Git-Blob-`revision`, `values` mit konfigurierten Pfad-Wert-Paaren, normalisierte `lookup`-Werte, normalisierte Suchtexte je Feld unter `search` und den serverinternen aggregierten `search_text`. Auch Sortier- und Filterfelder sind unter `values` enthalten. Unkonfigurierte Fachfelder oder technische Provenienz werden nicht mitkopiert.

Strings werden für die Suche mit Unicode-NFKC, Casefolding und vereinheitlichten Leerzeichen normalisiert. Leere Werte tragen nichts bei. Arrays und Repeater aggregieren ihre Unterwerte; auch Pfade innerhalb von Repeatern sind möglich. Strukturierte Werte tragen ihre kanonischen Skalare bei: beispielsweise Agent-/Ortsnamen, Term-IDs, Identifier-Werte und Sprachcodes. Datumsobjekte enthalten zusätzlich normalisierte Werte wie `1967-06-13`; Date-Ranges aggregieren Anfang, Ende und vorhandene Anzeige. Ein Vocabulary-Service zur nachträglichen Labelauflösung ist noch nicht angeschlossen.

Die natürliche Standardsortierung vergleicht Zahlen als Zahlen und zerlegt Identifier-Strings in Text- und Zahlenanteile (`X.2`, `X.2a`, `X.10`). Strukturierte Datumswerte werden chronologisch, Bereiche nach ihrem Anfang sortiert; bei gleichen Werten dient die ID als stabiler zweiter Schlüssel. Die API liefert diese Reihenfolge bereits als Grundlage späterer Nachbarnavigation.

`build_index_entry` erzeugt einen Eintrag. `build_module_index` validiert alle gelieferten Records mit einer wiederverwendeten Schema-Validatorinstanz, prüft ID/Dateipfad und doppelte IDs und erzeugt einen vollständigen Index. `rebuild_module_index` liest alle kanonischen Dateien des Moduls, baut den Index neu und schreibt ihn über die Repository-Commit-Grenze. Ein zweiter identischer Rebuild erzeugt keinen weiteren Commit. Der Rebuild ist Reparatur- und Referenzmechanismus; inkrementelle Indizes werden in Tests dagegen verglichen.

Der GitHub-Rebuild im Integrationsrunner verwendet einen Archiv-Snapshot des festgehaltenen Commit-Hashes. Er umgeht damit die auf 1.000 Einträge begrenzte Contents-Verzeichnisabfrage, ohne normale Listenaufrufe mit Einzeldaten zu belasten. Die Optimistic-Concurrency-Prüfung bindet das Schreiben an diesen Ausgangsstand. Das Archiv wird im Speicher gelesen, ohne Dateien daraus auf dem Rechner zu extrahieren.

Die Indexrevision ist der Git-Blob-Hash der tatsächlich serialisierten Record-Bytes und lässt sich vor dem Commit berechnen. Create schreibt Record, State und Index in **einem** Commit. Update ersetzt Record und Indexeintrag einschließlich Revision, ohne den State zu verändern. Validierungsfehler, Indexerfehler, Dateikollision oder Ref-Konflikt dürfen keine dieser Dateien teilweise fortschreiben. Ein fehlender, beschädigter oder wegen Konfigurationsänderungen veralteter Index führt zu einer Rebuild-Anforderung, nicht zu einem stillschweigenden Teilindex oder einer Vollauflistung als Fallback.

Die bestehende generische Liste nutzt bei konfiguriertem Indexpfad ausschließlich diese Datei. Direkter ID-Zugriff lädt weiterhin die bekannte kanonische Datei. Beispiele:

```text
GET /api/modules/foto_papierabzuege/records
GET /api/modules/foto_papierabzuege/records?q=INTEGRATIONSTEST
GET /api/modules/foto_papierabzuege/records?lookup_field=signatur.anzeige&lookup_value=9.4.2.A.8610
```

Mehrere Suchwörter werden über die konfigurierten Felder kombiniert. Lookup ist ein normalisierter exakter Vergleich und liefert passende Listeneinträge. Komplexe Filtersyntax, Pagination und serverseitiges Index-Caching sind noch nicht implementiert.

Der gespeicherte Index ist rollenunabhängig und wird niemals ungefiltert über die API ausgegeben. Listenwerte und Suchfelder werden anhand des aktuellen Feldkatalogs gefiltert. Ein verborgenes Feld darf auch keinen Treffer erzeugen; seine Werte werden deshalb beim Suchen nicht in den Suchtext des Benutzers aufgenommen. Lookup auf ein unsichtbares Feld wird abgewiesen. Unsichtbare Sortierfelder fallen auf ID-Sortierung zurück. Tests prüfen ausdrücklich, dass Ehrenamtliche weder redaktionelle Werte noch darüber hergeleitete Treffer erhalten.

Für Foto liegt der generische Index unter `indexes/generic/fotos.json`. Der Legacy-Index `indexes/fotos.json` enthält weiterhin nur ID, Signatur, Format, Nummer und optionalen Zusatz; die alten Listen-, Signatur- und Navigationsfunktionen hängen davon ab. Der generische Index benötigt keine Foto-spezifischen Kurzschlüssel: Signatur, Format und weitere Werte kommen aus Feldpfaden. Nummer und Zusatz müssen nur dann zusätzlich indexiert werden, wenn eine Modulkonfiguration sie benötigt. Der Legacy-Index und das alte Formular werden nicht umgestellt.

`integration_tests/index_github.py` ist ein ausdrücklich aktivierbarer Live-Test. Er prüft die Heads und die Schreibgrenze `integration-test`, validiert zunächst alle Snapshot-Dateien lokal, baut Foto- und Testmodulindex auf und prüft Rebuild-Idempotenz, Foto-ID/Lookup/Liste/Volltext sowie atomaren Create/Update und Rollenfilter des zweiten Moduls. Die normale Testsuite bleibt ohne externe Schreibzugriffe.

```bash
GENERIC_GITHUB_INTEGRATION=1 .venv/bin/python -m integration_tests.index_github \
  --write --report /private/tmp/generic-index-live.json
```

Beim ersten vollständigen Rebuild wurde ein vorhandener Parserfehler entdeckt: `foto-008727` enthält `63.---` innerhalb der Beschriftung. Die alte generische Frontmatter-Erkennung schnitt dort ab. Sie erkennt jetzt ausschließlich eigenständige Trennzeilen; ein Regressionstest sichert das ab. Der fehlgeschlagene erste Versuch erzeugte keinen Datencommit. Es wurden weder Foto-Inhalte ergänzt noch Datensätze von der Validierung ausgenommen.

Der danach erfolgreich ausgeführte Indexintegrationstest lieferte:

| Prüfung | Ergebnis |
| --- | --- |
| Daten-main vorher/nachher | `bcde7c81187fd54466f4b2ecd80e10260bda40f0` |
| integration-test vorher | `5ee513fb2221bf2ceaa0d4f8739f507769b84fb4` |
| integration-test nachher | `3e02dfb026ea33d7e68783ede6d41e0af1449ce6` |
| Generischer Fotoindex | 10.331 Einträge; 11.317.481 UTF-8-Bytes |
| Foto-ID und Lookup | `9.4.2.A.8610` findet `foto-010332`; direkte ID-Lesung bleibt erfolgreich |
| Foto-Liste und Volltext | `foto-010332` enthalten; Suche nach `INTEGRATIONSTEST nach generischem Update` erfolgreich |
| Foto-Reihenfolge | Position 8596 (nullbasiert), vorher `foto-010331`, danach `foto-008118` |
| Zweites Modul | zunächst zwei vollständig rekonstruierte Einträge, danach `integration-0003` / `INTEGRATION.T.3` atomar ergänzt und aktualisiert |
| Test-State | `next_record_id: 4`, `next_signature_number: {T: 4}`; beim Update unverändert |
| Rollenprüfung | `IndexGeheimNurRedaktion` erzeugt nur redaktionell einen Treffer; Ehrenamt erhält weder Wert noch Treffer |
| Konflikt | veraltete Revision 409; Index und State unverändert |
| Rebuild | beide Module zweimal gebaut; zweiter identischer Rebuild ohne Commit |
| Geschützte Daten | Daten-main, sämtliche Fotos, Foto-State und Legacy-Fotoindex unverändert |

Die vier beabsichtigten Commits auf `integration-test`:

1. `d9de7f8a1bfbdee5f5779517ee76ffc3defc3c47`: `indexes/generic/fotos.json` aufgebaut.
2. `1e94d94dae0ae8d580567cc25c38755d32bee5c5`: `indexes/generic/integration-test.json` aufgebaut.
3. `700b39301ad44769b01800b5b023fd4427d07167`: `integration-0003.md`, Test-State und Testindex gemeinsam committed.
4. `3e02dfb026ea33d7e68783ede6d41e0af1449ce6`: `integration-0003.md` und Testindex gemeinsam aktualisiert.

Die Nachkontrolle bestätigte exakt diese Commitfolge und vier geänderte Dateien. Der Legacy-Fotoindex enthält weiterhin 10.330 Einträge; die zusätzliche Auffindbarkeit besteht über die generische API. Eine Umschaltung des alten Formulars oder seiner Suche wurde nicht vorgenommen.

### Generische Anwendung: Liste, Suche und Navigation

Die Anwendung unter `/app/module/?module={module_key}` verwendet die vorhandene generische Record-/Index-API. `app/generic/record-list.js` rendert eine semantische Tabelle ausschließlich aus `list.columns`, in deren deklarierter Reihenfolge. Labels stammen aus der Spaltendefinition oder dem Feld-Descriptor. Die erste Spalte öffnet den Datensatz; ohne konfigurierte Spalten dient die technische ID als Fallback. Strings, leere Werte, Identifier und einfache Datums-/Bereichswerte werden generisch dargestellt. Es gibt keine Foto-Spalten oder Foto-Modulabfragen im Frontend.

Die Suchmaske sendet `q` sowie optional `lookup_field` und `lookup_value` an dieselbe Listenroute. Suche löschen lädt die ungefilterte Liste; keine Treffer werden ausdrücklich angezeigt. Das Frontend führt weder eine eigene Volltextsuche noch eine Nachsortierung durch. Suchfelder und Listenspalten werden schon im serverseitigen Descriptor rollenabhängig freigegeben; der Browser implementiert keine Rollenmatrix. Der vorhandene serverseitige Trefferfilter verhindert weiterhin Treffer allein über unsichtbare Felder.

`ResultState` hält Modul, Suchbegriff, Lookup, serverseitige Standardsortierung, Trefferliste, geöffnete ID und zuletzt geöffnete ID. Die Position wird aus der tatsächlichen Trefferliste bestimmt. **Vorheriger und Nächster beziehen sich immer auf die aktuelle serverseitig bestimmte Treffer- und Sortierreihenfolge.** Am ersten/letzten Treffer ist die jeweilige Richtung deaktiviert, bei einem einzelnen Treffer beide. Ein direkt geöffneter Record außerhalb der aktuellen Suche bleibt lesbar, hat aber keine Nachbarn. Neue Suchergebnisse schließen den bisherigen Record. Die Liste kann später über denselben Ladeweg nach einem gespeicherten Update aktualisiert werden.

Record-Ladung und Read-/Edit-Darstellung verwenden unverändert `FormState` und `FormRenderer`. Vor Recordwechsel, Rückkehr zur Liste, Modulwechsel und Browser-History-Navigation wird der aktuelle Formularzustand ausgelesen. Bei Änderungen fragt ein nativer HTML-Dialog nach ausdrücklichem Verwerfen; Abbrechen und Escape erhalten den Entwurf. Während einer Ladeanfrage oder Speicherung ist der betroffene Formular-/Listenbereich gegen weitere Eingaben gesperrt. Überholte Ladeantworten werden anhand einer Anfragegeneration verworfen. Reload oder Verlassen des Dokuments werden zusätzlich durch `beforeunload` geschützt. Es gibt keine automatische Speicherung.

Modul, Suchbegriff, Lookup und geöffnete Record-ID stehen in der URL. `pushState`/`popstate` ermöglichen Zurück/Vorwärts ohne Routerbibliothek. Zurück zur Liste erhält Suchbegriff und Reihenfolge und fokussiert den zuletzt geöffneten Link. Bei abgebrochener History-Navigation stellt die App die bisher akzeptierte URL wieder her; dabei kann ein neuer History-Eintrag entstehen. Eine vollständige History-Transaktionsverwaltung ist nicht Teil von v1.

`Modul wechseln` führt auf `/arbeitsbereiche?view=generic`. Nur diese ausdrücklich gewählte Ansicht verlinkt die generischen Module. Der bisherige Login-Einstieg und die Arbeitsbereichsauswahl ohne Parameter führen weiterhin zum alten Fotoformular. `/app/`, Foto-Suche, Presets und Legacy-Navigation wurden nicht umgestellt.

#### Update bestehender Datensätze

Im Edit-Modus wird `Speichern` nur für einen geöffneten, geänderten Datensatz aktiviert. Der generische Payload-Builder liefert ausschließlich sichtbare und für die Rolle editierbare Fachfelder. Das Frontend sendet diesen Payload zusammen mit der beim Laden erhaltenen `base_revision` an `PUT /api/modules/{module_key}/records/{record_id}`; technische Metadaten werden nicht aus dem Formular übernommen. Während des Requests sind Formular und Navigation gesperrt, und ein zweiter PUT wird verhindert.

Bei Erfolg ist die Serverantwort maßgeblich: `record` ersetzt Original- und Arbeitszustand, `meta.revision` wird zur neuen Basisrevision und `dirty` wird `false`. Anschließend wird die aktuelle Trefferliste über die bestehende Listenroute neu geladen, wobei geöffneter Datensatz und Trefferposition erhalten bleiben. Validierungs- und Berechtigungsfehler, ein `409` wegen veralteter Basisrevision sowie Netzwerk- und Serverfehler lassen Entwurf, Basisrevision und Dirty State unverändert. Es gibt kein automatisches Retry, Force-Save oder clientseitiges Zusammenführen.

Der abgesicherte Browserintegrationstest aktualisierte `foto-010332` und `integration-0003` jeweils zusammen mit ihrem generischen Index. ID, Signatur, State-Dateien und Legacy-Fotoindex blieben unverändert; das Legacy-Lesen von `foto-010332` funktioniert weiterhin. Ein Schemafehler (`422`) und ein echter Revisionskonflikt (`409`) erhielten die lokalen Eingaben. Daten-main blieb auf `bcde7c81187fd54466f4b2ecd80e10260bda40f0`; die beiden beabsichtigten Testcommits auf `integration-test` sind `8d721185d396f1f720b1fb4124c846b0b0ef80b4` und `7eaad9b88905b607b2dff3cc893e291b66c4b725`.

#### Neuanlage in der generischen Anwendung

`Neuer Datensatz` öffnet im gewählten Modul denselben `FormRenderer` im Edit-Modus. Der Moduldescriptor liefert dazu den generischen Ausgangswert aus `RecordRuntime.empty_record()`; anschließend werden die tatsächlich gerenderten, generischen Widget-Leerwerte beziehungsweise deklarativen Optionen einmalig als sauberer Formular-Ausgangszustand übernommen. Original- und Form State beginnen damit ohne technische ID, Revision, endgültige Signatur oder technische Metadaten. Die URL kennzeichnet den ungespeicherten Zustand mit `new=1`, ohne eine ID vorzutäuschen. Änderungen verwerfen setzt das Formular auf genau diesen leeren Ausgangszustand zurück.

Der eigenständige generische `RecordCreate` baut den Request ausschließlich mit `FormState.buildPayload()` und sendet `{ "record": ... }` an `POST /api/modules/{module_key}/records`. Clientseitig werden weder ID noch Signaturnummer, Revision oder technische Metadaten erzeugt. Während der Anfrage sind Formular, Navigation und Anlege-Schaltfläche gesperrt; ein zweiter POST ist ausgeschlossen.

Nach erfolgreichem POST ist ausschließlich die Serverantwort maßgeblich. Ihre rollenabhängig gefilterte `record`-Struktur ersetzt Original- und Form State, `record_id` wird zur geöffneten ID und `meta.revision` zur Basisrevision. Der Create-State wechselt damit in den normalen bestehenden Record-/PUT-State, `dirty` ist `false`, die URL enthält die Server-ID und die aktuelle Trefferliste wird kontrolliert neu geladen. So kommt der bereits atomar in Record, State und Index geschriebene Datensatz ohne clientseitige Indexlogik in Liste und Navigation.

Bei `422`, fehlender Berechtigung, abgelaufener Anmeldung, Netzwerk- oder Serverfehlern bleiben Form State und Dirty State erhalten; es wird keine technische ID oder Signatur angenommen. Die bestehende Dirty-Warnung schützt auch ungespeicherte Create-Entwürfe bei Listen-, Record-, Modul- und Browsernavigation. Vocabulary-Verwaltung, Autosave, Signaturvorschau und Batch-Erfassung sind weiterhin nicht Bestandteil dieses Schritts.

#### Generische Vorbelegungen

Die Modulkonfiguration kennzeichnet erlaubte Vorbelegungsfelder ausschließlich mit `presettable: true`. Der generische Client berücksichtigt davon nur Felder, die der rollenabhängige Descriptor zugleich als sichtbar und editierbar ausliefert. Record-ID, Revisionen, erzeugte Signaturangaben, serververwaltete Pfade und sämtliche `technik.*`-Felder sind zusätzlich ausgeschlossen. Gespeicherte Pfade, deren Rechte später entfallen, werden beim Laden verworfen und weder angewendet noch in der Oberfläche aufgeführt; die serverseitige Payload-Prüfung bleibt die Sicherheitsgrenze.

Pro Browser, Benutzer und Modul existiert in v1 ein Preset-Set im `localStorage`. Das normalisierte Format lautet `{ "version": 1, "module": "…", "values": { "fachlicher.pfad": … } }`. Gespeichert werden alle aktuell nicht leeren, zulässigen Felder. Strings, Select- und kanonische Vocabulary-Werte, Checkboxen, Datum, Datumsbereich sowie Repeater werden ohne Widget- oder Modulspeziallogik tief kopiert. Die Aktion verändert oder speichert keinen Record.

Bei `Neuer Datensatz` entsteht zuerst der unveränderte leere Form State einschließlich deklarativer Widget-Defaults. Danach werden die Vorbelegungen einmalig angewendet. Solche anfänglichen Defaults gelten dabei als noch unbelegte Ausgangswerte, sodass zum Beispiel ein deklarativer Select- oder Checkbox-Default durch das Preset ersetzt werden kann. Der Record wird dadurch dirty, bleibt aber ungespeichert; ein POST erfolgt ausschließlich über den normalen Create-Workflow. `Änderungen verwerfen` stellt den Ausgangszustand der Neuanlage wieder her, ohne das getrennt gespeicherte Preset zu verändern.

Die ausdrückliche Aktion `Vorbelegungen anwenden` steht auch im Edit-Modus bestehender Records bereit und füllt ausschließlich semantisch leere Werte (`null`, fehlend, Leerstring, leere Liste oder rekursiv leeres Objekt). Vorhandene Strings, strukturierte Werte und auch `false` werden nicht still überschrieben. `Vorbelegungen löschen` leert nur das Set des aktiven Benutzers und Moduls; der aktuelle Record State bleibt unverändert.

Frühere lokale Presets mit einem Schlüssel der Form `erschliessung.*.activePreset.vN` werden lesend erkannt. Eindeutige alte Feld-IDs werden über den aktuellen Descriptor in kanonische Feldpfade normalisiert und nur bei weiterhin vorhandener Berechtigung in den neuen benutzer- und modulbezogenen Eintrag übernommen. Der alte Eintrag wird nicht geändert oder gelöscht. Ein explizit gelöschtes Preset bleibt durch einen leeren neuen Eintrag gelöscht und wird nicht erneut aus dem Legacy-Format importiert. Das alte Fotoformular selbst bleibt unverändert.

#### Kontrollierte Vokabulare (read-only)

Vokabulare liegen als kleine versionierte YAML- oder JSON-Dateien im Anwendungsrepository und entsprechen `schemas/vocabulary.schema.json`. Die stabile Vocabulary-ID steht in `id`; jeder Term besitzt eine stabile `id`, ein veränderbares primäres `label` und `active`. Optional bleiben `description`, `aliases` und `sort_order` erhalten. Sobald mindestens ein Term `sort_order` verwendet, stehen nummerierte Terms deterministisch davor; sonst bleibt die deklarierte Dateireihenfolge maßgeblich. Doppelte Term-IDs, ein Schemafehler, eine fehlende Datei oder eine Abweichung zwischen referenzierter und enthaltener Vocabulary-ID verhindern das Laden der Modulkonfiguration.

Ein Modul referenziert die Datei unter `vocabularies.{vocabulary_id}.path`; ein `vocabulary_select` nennt ausschließlich diese Vocabulary-ID. Der zentrale Vocabulary-Service validiert und cached die read-only Datei, löst `id -> label` auf und stellt aktive sowie alle Terms bereit. `GET /api/vocabularies/{vocabulary_id}` liefert die kleinen Term-Metadaten nur angemeldeten Benutzern, die Zugriff auf mindestens ein tatsächlich referenzierendes Modul besitzen. Es existieren weder Schreibroute noch Vocabulary-GitHub-Persistenz.

Der kanonische Recordwert folgt `term_ref`, beispielsweise `{ "id": "brief", "vocabulary_id": "dokumenttypen" }`. Das Label wird nicht gespeichert. `vocabulary_select` lädt seine Terms generisch, bietet bei einer neuen Auswahl ausschließlich aktive Terms an und schreibt stets den kanonischen `term_ref`. Ein bereits gespeicherter inaktiver Term bleibt auflösbar und erscheint als `Label (inaktiv)`, ohne andere inaktive Terms zur Neuauswahl anzubieten. Eine unbekannte Term-ID bleibt sichtbar als Datenfehler markiert, statt still geleert oder in einen neuen Term verwandelt zu werden; neue beziehungsweise aktualisierte Records mit unbekannten IDs werden zusätzlich serverseitig abgewiesen. Strukturelle Formprüfung bleibt Aufgabe des JSON-Schemas, fachliche Referenzprüfung Aufgabe des Vocabulary-Service.

Presets übernehmen denselben kanonischen `term_ref`. Nach dem Laden wird das jeweils aktuelle Label über die stabile Term-ID aufgelöst, sodass eine spätere Labeländerung weder Record- noch Presetmigration erfordert. Für die künftige Redaktion gilt bereits die Policy **deaktivieren statt löschen**: verwendete Terms bleiben mit `active: false` auflösbar. Hinzufügen, Umbenennen, Deaktivieren, Purgen, Revisionskonflikte und eine Vocabulary-Redaktionsoberfläche sind in diesem Stand bewusst nicht implementiert.

#### Rein lesender Browsertest

`integration_tests/navigation_browser.py` startet die reguläre Anwendung mit temporärer SQLite-Benutzerdatenbank und zwei lokalen Testkonten (`navigation-redaktion`, `navigation-ehrenamtlich`, Testpasswort `NavigationTest123!`). Die GitHub-Konfiguration muss auf das freigegebene Datenrepository und exakt `integration-test` zeigen. GitHub-Record-Schreiben wird sowohl im Repository als auch per HTTP-Middleware blockiert; die generische Schreibfreigabe bleibt aus. Beim Beenden werden beide Branch-Heads erneut geprüft.

```bash
.venv/bin/python -m integration_tests.navigation_browser --port 8768
.venv/bin/python -m integration_tests.navigation_browser --port 8769 --alternate-config
```

`--alternate-config` variiert ausschließlich das zweite Testmodul: Spalten Testtext/Testzeitraum/redaktioneller Testwert, Lookup auf `daten.text` und absteigende Sortierung nach `daten.text`. Sein Index wird aus den drei vorhandenen kanonischen Testdateien nur im Arbeitsspeicher abgeleitet. Es entsteht kein GitHub-Commit. Ohne Option wird der vorhandene Testindex gelesen.

Praktisch bestätigt wurden die vollständige Fotoliste, ID-Direktlink, Signatur-Lookup `9.4.2.A.8610`, Volltext `INTEGRATIONSTEST nach generischem Update`, Öffnen von `foto-010332` und die Nachbarn `foto-010331` / `foto-008118`. Position ohne Filter ist 8597 von 10.331. Ein Lookup-Einzeltreffer hat keine Nachbarn. Keine-Treffer-Zustand und Löschen der Suche wurden geprüft. Im zweiten Modul begrenzt die Suche `GENERIC INTEGRATION` die Navigation auf genau zwei Records; der dritte ist nicht erreichbar. Rückkehr, URL sowie Browser-Zurück/Vorwärts erhalten die Suche.

Dirty-Prüfung: Textänderung, Warnung bei Nächster und Modulwechsel, Abbrechen ohne Datenverlust, bestätigtes Verwerfen und erneuter sauberer Zustand wurden im Browser geprüft. Dabei wurde ein vorhandener Fehler im Date-Range-Widget gefunden: Auslesen ergänzte fehlende optionale Schlüssel und erzeugte dadurch falschen Dirty State. Die Widget-Lesung erhält jetzt die sparse kanonische Struktur, einschließlich null, fehlender Schlüssel und vorhandener Datumsschlüssel. Ein ausführbarer JavaScript-Regressionstest prüft den Roundtrip nach Verwerfen.

Rollenprüfung: `IndexGeheimNurRedaktion` liefert redaktionell einen Treffer und eine sichtbare Spalte. Ehrenamt erhält keinen Treffer und keine solche Spalte. Im Foto-Modul fehlt für Ehrenamt das Titelfeld, Beschreibung ist editierbar und Signatur bleibt gesperrt. Das alte Fotoformular wurde zusätzlich rein lesend geöffnet.

#### Performance und Grenzen

Im lokalen Browser wurden 10.331 Fototreffer vollständig geladen und als Tabelle dargestellt. Messung mit kaltem Repository-Cache: 2.836 ms für Listenrequest inklusive GitHub-Indexdownload, JSON und serverseitiger Suche; 480 ms DOM-Aufbau; rund 22 MB JavaScript-Heap (keine Messung des gesamten Browser-/DOM-Prozessspeichers). Mit vorhandenem Cache: 954 ms Request und 489 ms DOM-Aufbau. Signatur-Lookup und Volltext lagen bei 554 bzw. 562 ms. Dies sind lokale Einzelmessungen, keine garantierten Produktionslatenzen.

Ein wiederholter Download des 11-MB-Indexes brach während der Prüfung mit `IncompleteRead` ab. Als begrenzte Übergangslösung hält der GitHub-Adapter höchstens eine große Datei im Speicher. Jeder Zugriff fragt weiterhin deren aktuelle Contents-Metadaten ab; nur bei identischem Pfad und identischer Blob-SHA wird der Inhalt wiederverwendet. Geänderte Revisionen werden neu geladen; Fehler werden nicht durch veraltete Cachewerte verdeckt. Abgebrochene Transfers werden jetzt als Repository-Fehler gemeldet. Commit-/Ref-Logik und Atomarität bleiben unverändert. Es gibt keinen clientseitigen Suchindex, keine Pagination und keinen Cache für rollenabhängige Treffer.

Die Tabelle war im lokalen Desktopbrowser bedienbar; rund eine halbe Sekunde synchroner DOM-Aufbau bleibt eine bekannte Grenze. Bei 390 Pixeln Breite wurde kein horizontales Seiten-Scrolling festgestellt. Für weitere Größenordnungen und mobile Langlisten sind Pagination oder begrenztes Rendering spätere Aufgaben. Komplexe Filter, frei wählbare Sortierung, produktives Speichern und die Legacy-Umschaltung bleiben ausdrücklich offen.

Die Browserprüfung erzeugte keine Datencommits. Beide Testserver wurden beendet und bestätigten unveränderte Heads vor/nach der Prüfung: Daten-main `bcde7c81187fd54466f4b2ecd80e10260bda40f0`, integration-test `3e02dfb026ea33d7e68783ede6d41e0af1449ce6`. Die lokale `.env` blieb unversioniert und auf `integration-test`.

Abschlussprüfung: 184 Python-Unittests einschließlich ausführbarer JavaScript-Assertions für Trefferzustand, Navigation, Spaltenrenderer und Datums-Roundtrip erfolgreich; `scripts/validate.py` und `git diff --check` erfolgreich. Für die JavaScript-Assertions wird Node.js benötigt (lokal Node 24); ohne Node wird dieser einzelne Test ausdrücklich als übersprungen gemeldet. Normale Tests schreiben nicht nach GitHub.

## Refactoring-Plan

1. Modul-Registry einführen, die bestehende Modulkonfigurationen laden kann, ohne die Foto-Funktion zu verändern.
2. Rollen und Darstellungsprofile im Konfigurationsmodell trennen. Rollen bestimmen Rechte; Profile bestimmen nur Darstellung.
3. Foto-API intern schrittweise über generische Modulmetadaten führen, während `/api/records/photos` als stabile Kompatibilitätsroute bestehen bleibt.
4. Wiederverwendbare Dienste aus `backend/records/photos.py` herauslösen: State, Index, Pfade, YAML/Markdown-Serialisierung, Feldrechte, technische Metadaten.
5. Frontend schrittweise von fest codierten Foto-Feldern auf Modulkonfiguration umstellen, ohne den bestehenden Foto-Pilot zu ersetzen.
6. Erst nach stabiler generischer Grundlage ein neues Modul wie Autographen deklarativ vorbereiten.

## Regression

Der Foto-Pilot bleibt der verbindliche Regressionstest. Vor jedem größeren Refactoring müssen die bestehenden Tests grün sein. Neue generische Infrastruktur bekommt eigene Tests, bevor bestehende Foto-Logik darauf umgestellt wird.

Der aktuelle Schritt baut eine generische ID-/Signaturengine, schaltet die generische Schreib-API aber nicht für den Produktivbetrieb frei. `foto_papierabzuege` bleibt als Zugriffsschlüssel erhalten; die bestehende Foto-API, die bestehende Foto-Erfassungsmaske und die bestehenden YAML-/Markdown-Daten werden nicht migriert.
