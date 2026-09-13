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

## Refactoring-Plan

1. Modul-Registry einführen, die bestehende Modulkonfigurationen laden kann, ohne die Foto-Funktion zu verändern.
2. Rollen und Darstellungsprofile im Konfigurationsmodell trennen. Rollen bestimmen Rechte; Profile bestimmen nur Darstellung.
3. Foto-API intern schrittweise über generische Modulmetadaten führen, während `/api/records/photos` als stabile Kompatibilitätsroute bestehen bleibt.
4. Wiederverwendbare Dienste aus `backend/records/photos.py` herauslösen: State, Index, Pfade, YAML/Markdown-Serialisierung, Feldrechte, technische Metadaten.
5. Frontend schrittweise von fest codierten Foto-Feldern auf Modulkonfiguration umstellen, ohne den bestehenden Foto-Pilot zu ersetzen.
6. Erst nach stabiler generischer Grundlage ein neues Modul wie Autographen deklarativ vorbereiten.

## Regression

Der Foto-Pilot bleibt der verbindliche Regressionstest. Vor jedem größeren Refactoring müssen die bestehenden Tests grün sein. Neue generische Infrastruktur bekommt eigene Tests, bevor bestehende Foto-Logik darauf umgestellt wird.

Der aktuelle Schritt baut noch keinen generischen Formularrenderer und keine generische Signaturengine. `foto_papierabzuege` bleibt als Zugriffsschlüssel erhalten; die bestehende Foto-API und die bestehenden YAML-/Markdown-Daten werden nicht migriert.
