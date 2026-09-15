# Autographen 9.6

`autographen_9_6` ist nach dem Foto-Pilot das zweite reale Fachmodul der generischen Erschließungsumgebung. Datenschema, Formular, Rechte, Liste, Suche, Presets und Vokabulare werden deklarativ konfiguriert; es gibt keinen eigenen Editor und keinen eigenen Speicherpfad im Anwendungscode. Der deklarative Modul-Einstieg `generic` führt bereits aus der normalen Arbeitsbereichsauswahl in den generischen Editor, während der Foto-Pilot seinen Legacy-Einstieg behält.

Das kanonische Record-Schema liegt in `schemas/autograph.schema.json`. Es verwendet die gemeinsamen Core-Datentypen `agent`, `place`, `date_range` und `term_ref`. Beteiligte bleiben als geordnete Liste erhalten; jeder Eintrag enthält einen Agenten, eine kontrollierte Rolle und eine optionale Notiz. Dokumenttyp, Erhaltungsform und Beteiligtenrolle verweisen auf die drei Autographen-Vokabulare. Deren Terms können über die bestehende Vocabulary-Verwaltung von Redaktion und Administration ergänzt, umbenannt und deaktiviert werden.

Die Signatur folgt der vorhandenen `partitioned_sequence`-Strategie mit dem Muster `9.6.<Nummer>`. Beim Öffnen einer Neuanlage liest die API den nächsten State-Wert lediglich als Vorschlag. Sie reserviert und erhöht ihn nicht. Erst der idempotente generische Create mit `identity_assignment: on_create` vergibt ID und endgültige Signatur und schreibt Record, State und abgeleiteten Index atomar. `on_create` genügt, weil vor dem vollständigen Speichern keine verbindliche Signatur benötigt wird.

`erschliessung.altsignatur` ist als einziges fachliches Preset-Feld aktiviert. `erschliessung.interne_bemerkung` ist für `ehrenamtlich` weder sichtbar noch les- oder schreibbar; `redaktion` und `admin` dürfen es bearbeiten. Das Feld wird bewusst nicht indexiert. Redaktion, Bearbeitung und Publikation bleiben in v1 optionale, leere Objektbereiche; fachliche Workflow-Felder werden erst ergänzt, wenn sie benötigt werden.

Für lokale Browserprüfungen startet `python -m integration_tests.autograph_browser` einen ausschließlich speicherinternen Datenbestand mit Testkonten. Der Harness greift nicht auf das GitHub-Datenrepository zu.
