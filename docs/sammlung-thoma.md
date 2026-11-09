# Sammlung Thoma – deklarative Konfiguration

Die Konfiguration liegt in `ui/modules/sammlung-thoma.yaml`. Dateiname und
Speicherpfade verwenden Bindestriche; `module.id`, `module.access_key` und das
kanonische Datensatzfeld `modul` verwenden durchgehend `sammlung_thoma`.

Konfiguriert sind `data/sammlung-thoma/Thoma000001.yaml`,
`state/sammlung-thoma.json` und `indexes/generic/sammlung-thoma.json` im bestehenden
Datenrepository. Keine dieser Dateien wird durch das Anlegen der Konfiguration
erzeugt. Initiale Zähler existieren ausschließlich in der InMemory-Testfixture
`thoma_repository()` in `tests/test_thoma_module.py`.

Die vorhandenen Strategien reservieren Inventarnummer und Signatur gemeinsam.
Die einzelne Partition `A` wird bei fehlender Vergabeeingabe vom vorhandenen
`partitioned_sequence`-Mechanismus gewählt. `create.server_values` ergänzt beim
Create Schema-Version, Modul, Sammlung, Erfassungsstatus und Lagergruppe; der
bestehende Writer ergänzt Datensatztyp, reservierte Identität und Technikfelder.
Diese Felder werden nicht als editierbare Clientwerte verlangt.

Die Schema-Defaults unterscheiden die initiale Maßliste (eine Gruppe
`Objektmaß`) von den Unterfelddefaults für zusätzliche Gruppen (leere Maßart).
Höhe und Breite starten mit `null`, Einheit mit `mm`, Maßbemerkung mit `""`.
Defaults werden weder durch Schema-Validierung eingefügt noch beim Laden eines
bestehenden Datensatzes nachgetragen.

## Anfangswerte und Rechte

Die beiden ursprünglichen Blocker sind behoben; ihre Abnahmetests laufen ohne
Erwartungsmarkierung.

`RecordRuntime.empty_record(role)` trennt Sichtbarkeit von Editierbarkeit.
Sichtbare schreibgeschützte Felder erhalten vorhandene `create.server_values`
oder explizite Schema-Defaults beziehungsweise `const`-Werte. Unsichtbare Felder
werden nicht ausgegeben, auch nicht in Repeater-Defaults. Nicht reservierte IDs,
Signaturnummern und Signaturanzeigen werden nicht initialisiert. Bestehende
Datensätze werden beim Laden nicht mit Defaults überschrieben.

Unterfeldrechte werden unter vollständigen Pfaden wie
`erschliessung.masse[].einheit` deklariert. Ohne eigene Regel erbt das Unterfeld
die effektiven Elternrechte. Mit eigener Regel gilt die Schnittmenge mit den
Elternrechten, rekursiv auch für verschachtelte Repeater. Sichtbare
schreibgeschützte Unterfelder werden angezeigt; unsichtbare werden ausgeblendet.
Hinzufügen und Entfernen bleiben an die Schreibrechte des Repeaters gebunden.

Neue Gruppen kopieren auch die sichtbaren schreibgeschützten Schema-Defaults
unabhängig voneinander in den lokalen Formularzustand. Der editierbare Payload
enthält diese geschützten Werte nicht. Das Backend prüft Unterfeldrechte vor der
Schema-Validierung, weist mitgesendete geschützte Felder ab und ergänzt sie in
neuen Gruppen aus den kanonischen Schema-Defaults/`const`-Werten. Bei Updates
bleiben geschützte Werte bestehender Arraypositionen erhalten. Die lokale
Wiederherstellung ergänzt Anzeigeinformationen aus dem geladenen Stand oder den
Defaults neuer Gruppen; sie erweitert den editierbaren Payload nicht.

Die serverseitige Rollenfilterung berücksichtigt Unterfelder auch in
Leseantworten, Listen und Suchindizes. Ausgeblendete Defaults werden nicht über
den Descriptor weitergegeben. Der Status wird zusätzlich schreibgeschützt in
der Identifikation geführt, damit er mit dem bestehenden Feldkatalog in der
Liste sichtbar ist.

Die Speicheraktionen sind über `create.workflow` aktiviert: `draft` speichert
`entwurf`, `complete` setzt `abgeschlossen`, `save` korrigiert abgeschlossene
Datensätze ohne Rückstufung. Der Status bleibt ein geschütztes Feld. Der Server
prüft Modulzugriff, konfigurierte Rollen, erlaubten Ausgangsstatus und das volle
resultierende Schema. Die vorgeschaltete Validierung schreibt keine Daten und
erzeugt keinen Queue-Auftrag; der Writer validiert erneut. Aktion und Snapshot
werden zusammen im bestehenden Queue-Eintrag gesichert. Create-Wiederholungen
berücksichtigen die Aktion in der idempotenten Anfrage, PUT-Recovery vergleicht
zusätzlich den Zielstatus.

Die Produktivfreigabe steht weiterhin aus. Es werden weder Benutzerzugriffe vergeben
noch `GENERIC_WRITE_MODULES` oder Produktivzähler verändert.

## Nächstes Objekt

`create.next_record` aktiviert den fortlaufenden Ablauf. `carry_fields` enthält
nur `erschliessung.objektart` und `signatur.format`; `focus_field` legt den
Eingabefokus fest. Alle übrigen Anfangswerte stammen erneut aus `empty_record`.
Benutzerpresets werden bei diesem Wechsel nicht automatisch angewendet.

Bestätigte oder unverändert lokal vorgemerkte Stände dürfen verlassen werden.
Bei ungesicherten Änderungen bietet der Schutzdialog Abbrechen, ausdrückliches
Verwerfen oder die passende vorhandene Speicheraktion mit anschließendem Wechsel.
Der Wechsel wartet auf die lokale Queue-Ablage, nicht auf die Übertragung.
Bloße Reservierungen werden zusätzlich ausdrücklich aufgegeben; Nummern bleiben
verbraucht. Vor dem Formularwechsel wird die neue Operation lokal gesichert.
Reservierungsfehler bleiben mit dieser Operations-ID wiederaufnehmbar.
Reservierung und Create-Vormerkung sperren nur ihre Operations-ID; der bestehende
Übertragungsworker behält seinen gemeinsamen Queue-Lock. Späte Bestätigungen
bleiben über Form-State- und Operationskontext dem vorherigen Objekt zugeordnet.

## Lokale fachliche Endabnahme (Markus)

Aus dem Repository in einem **separaten Prozess** starten:

```bash
.venv/bin/python -m integration_tests.thoma_local
```

Dann `http://127.0.0.1:8798/app/module/?module=sammlung_thoma&new=1` öffnen.
Bei belegtem Port `--port 8799` verwenden und die URL entsprechend ändern.
Der Runner erzeugt ausschließlich eine temporäre SQLite-Datenbank und ein
InMemory-Datenrepository. Er authentifiziert den Browser intern als synthetischen
Testbenutzer; ein Passwort muss nicht eingegeben werden. Die drei Modulzugriffe
und Schreibfreigaben gelten nur in diesem Prozess. Keine Produktivzugriffe werden
geändert. Keine GitHub-Verbindung wird für die Testdaten verwendet. Stoppen mit
Strg+C verwirft sämtliche serverseitigen Testdaten.

Für jeden Neustart einen neuen Port oder ein neues Browserprofil verwenden:
IndexedDB-Queue und Reservierungen gehören zum Browser-Origin und überleben den
Serverneustart. Alte Test-Queue-Einträge nicht mit einem neu initialisierten
Testrepository vermischen. In Produktivsitzungen niemals den Browserspeicher zur
Fehlerbehandlung löschen; ausstehende Operationen zuerst sichern und abgleichen.

Manueller Ablauf:

1. Sammlung/Status und verbindliche Nummern prüfen. Beschreibung/Maße leer lassen,
   Motiv setzen, als Entwurf speichern. Über Volltext und anschließend exakten
   Lookup nach Inventarnummer und Lagersignatur wieder öffnen; Status `entwurf`.
2. Abschluss ohne Angaben versuchen: feldbezogene Fehler, Eingaben erhalten,
   kein Schreibauftrag. Beschreibung und positive Maße (`12,5` und `8.5`)
   ergänzen und abschließen. Status `abgeschlossen`, Kennungen unverändert.
3. Beschreibung ändern, speichern, erneut ändern und speichern, ohne Neuladen.
   Keine Rückstufung; auch nach Wiederöffnung beide letzte Werte kontrollieren.
4. Nächstes Objekt: keine alten Texte/Maße, nur eine leere Objektmaßgruppe, `mm`
   gesperrt, neue Kennungen. Klappbild: Objektmaß geschlossen und zusätzliche
   Gruppe `Objektmaß, geöffnet`; freie Maßart ergänzen. Unvollständige zusätzliche
   Gruppe muss den Abschluss verhindern, darf aber als Entwurf gespeichert werden.
5. Schutzdialog testen: Abbrechen, Speichern und weiter, ausdrückliches Verwerfen.
   Bloße Reservierung zusätzlich aufgeben; Nummernlücke bleibt erhalten.
6. Optional gezielt eine verlorene Schreibantwort simulieren: in einem zweiten
   lokalen Tab `/test-control?hold=1` öffnen, dann das Objekt speichern. Der Server
   schreibt in den Testspeicher, hält die Antwort aber bis zur Freigabe zurück.
   Nächstes Objekt beginnen; die alte Queue muss sichtbar bleiben. Reload, dann
   `/test-control?release=1` öffnen und die Speicherung wiederaufnehmen. Neue
   Kennungen und neues Formular dürfen nicht überschrieben werden. Nur lokal
   verfügbar, mit höchstens fünf Minuten Wartezeit pro verzögerter Antwort.
7. `/test-state` liefert ausschließlich synthetische Dateiinhalte und Zähler.
   YAML-ID/Dateiname, Signatur, Status, Maßgruppen und Indexzeilen vergleichen.
   Wiederholungen dürfen keine zweite Objektdatei oder zweite Vergabe erzeugen.

Autographen und Foto-Gemeinschaftsrenderer lassen sich im selben Runner über
`/app/module/?module=autographen_9_6&new=1` beziehungsweise
`/app/module/?module=foto_papierabzuege&new=1` öffnen. Sie erhalten keine
Thoma-Speicheraktionen. Der ältere Foto-Client (`app/app.js`) wurde nicht geändert;
seine UI-/API-/Markdown-Regressionen gehören zur gemeinsamen Testsuite.

## Bereitstellung – nur vorbereiten, nicht automatisch ausführen

1. Fachliche Abnahme protokollieren und den vollständigen Arbeitsstand prüfen:
   neue/unversionierte Dateien einschließlich Schema, Konfiguration und neuer
   JS-Dateien müssen im später freigegebenen Artefakt enthalten sein. Dieser
   Branch enthält noch uncommittete Arbeit; ein reiner Export von `HEAD` reicht
   nicht. Zusammenführung und Veröffentlichung benötigen einen eigenen Auftrag.
2. Bestehende Daten, Zähler und vorhandene produktive Modulfreigaben sichern.
   Lokale Queues vor dem Versionswechsel möglichst abarbeiten. Für den Wechsel
   keine Erfassungen parallel laufen lassen; alte Browserseiten nachher neu laden.
3. Backend, Schema und Konfiguration vor dem neuen Frontend bereitstellen;
   Schreibfreigabe für `sammlung_thoma` zunächst geschlossen lassen. Backend
   versteht die neuen Aktions-/Validierungsanfragen. Danach das zusammengehörige
   Frontend inklusive neuer Dateien und Imports mit `v=thoma-review-1` ausliefern.
   Keine Kombination aus neuer HTML-Datei und alten JS-Dateien betreiben.
   Deployment/Passenger-Neustart und Healthcheck gemäß
   `docs/deployment-domainfactory.md`; bestehende Abhängigkeiten genügen, keine
   zusätzliche Datenbankmigration ist durch dieses Modul erforderlich.
4. Im konfigurierten **Datenrepository** Zielbranch und Pfade prüfen:
   `data/sammlung-thoma/`, `state/sammlung-thoma.json`,
   `indexes/generic/sammlung-thoma.json`. Testdaten niemals dorthin kopieren.
5. Erstinitialisierung ausschließlich bei nachweislich neuer Sammlung:
   alle drei Pfade bzw. Verzeichnisinhalte prüfen; existieren Objekte, State oder
   Index, abbrechen und Bestand/History prüfen. Fehlende Zähler bei vorhandenen
   Objekten nicht mit 1 oder allein aus dem größten Dateinamen rekonstruieren:
   aufgegebene Reservierungen können höhere Nummern verbraucht haben.
6. Für eine nachweislich leere, nie initialisierte Sammlung den folgenden State
   zusammen mit einem leeren Index in **einem** optimistisch gesicherten Commit
   anlegen (vorherigen Branch-Head festhalten, `commit_files(expected_head=...)`).
   Vorhandene Dateien niemals überschreiben oder Zähler zurücksetzen:

   ```json
   {"next_record_id":1,"next_signature_number":{"A":1},"identity_reservations":{},"create_operations":{}}
   ```

   Den Index nicht von Hand erfinden: mit `get_module('sammlung_thoma')`,
   `make_index(module, [])` und `dump_index(...)` aus
   `backend.records.module_index` erzeugen. So stimmt der Konfigurationsfingerprint.
   Ein leeres Git-Verzeichnis muss nicht angelegt werden; die erste Objektdatei
   erzeugt den Datenpfad. Bei bestehenden Objekten ist gegebenenfalls
   `rebuild_module_index(repository, module)` der vorhandene Wiederaufbauweg;
   er setzt den Vergabe-State nicht zurück und ersetzt keine State-Rekonstruktion.
7. Getrennte Freigaben: `sammlung_thoma` selektiv als `ModuleAccess` für die
   vorgesehenen Benutzer ergänzen (bestehende Zugriffe/Rollen erhalten). Der
   aktuelle CLI hat keinen Befehl zum Ändern bestehender Modulzugriffe; das ist
   ein kontrollierter administrativer Datenbankvorgang, keine direkte
   SQL-Anweisung in dieser Anleitung. Zusätzlich `GENERIC_WRITE_MODULES` um
   `sammlung_thoma` erweitern, ohne vorhandene Einträge zu entfernen, und Backend
   neu starten. Die zentrale Modulliste erkennt den Schlüssel bereits.
8. Abschließender berechtigungsbezogener Smoke-Test: nicht freigegebener Benutzer
   sieht kein Modul; berechtigter Benutzer öffnet es. Schreib-Smoke-Test erst
   nach expliziter Freigabe mit einem echten Erfassungsobjekt; bereits reservierte
   Nummern anschließend nicht zurücksetzen. Bei Rollback zuvor entstandene
   Thoma-Daten und Queues erhalten; Freigabe schließen und Kompatibilität prüfen.

## Review vor Bereitstellung (Stand dieses Arbeitsbranches)

Gemeinsamer Ausgangspunkt: `main` und Branch-HEAD lagen beide auf
`93f3e8f5975caa7e29f83ad5648bd1adc699b77f`. Geprüft wurde zusätzlich der komplette
uncommittete Arbeitsstand, einschließlich neuer Dateien.

- **P1, behoben durch sichere Unterstützungsgrenze (Lösungsweg B):**
  Backend und lokale Wiederherstellung übernehmen keine geschützten Werte mehr
  anhand alter Zeilenpositionen. Gemischte Repeater erlauben nur erforderliche,
  eindeutig bestimmte Schema-Konstanten; Default allein reicht nicht. Variable
  geschützte Werte, nicht deklarierte variable Felder gemischter Zeilen und
  nicht eindeutig auswertbare Strukturen werden mit Feldpfad abgelehnt.
  Abweichende geschützte Bestandswerte werden auch beim Löschen einer Zeile
  zurückgewiesen, nicht normalisiert. Unsichere Module werden einzeln aus der
  Registry ausgeschlossen. Unsichere lokale Aufträge bleiben pausiert erhalten;
  unklare Übertragungen behalten Snapshot und Operations-ID. Thoma-Queues und
  Hinzufügen/Entfernen von Maßgruppen mit kanonischem `mm` bleiben unterstützt.
  Eine allgemeine Lösung für variable geschützte Zeilenwerte ist ausdrücklich
  nicht implementiert; siehe Unterstützungsgrenze in der Architekturdokumentation.
- **P1, behoben:** Vollständig editierbare Repeater wurden ebenfalls mit alten
  Arraypositionen zusammengeführt. Dadurch konnten entfernte optionale Werte
  wiederkehren. Sie verwenden jetzt wieder das bisherige Ersetzen der Liste;
  unbeschränkte Client-Payloads behalten ihre bisherigen strukturierten Werte.
- **P2, behoben:** Queue-Status war bei laufender Übertragung in einem versteckten
  Panel und damit beim nächsten Objekt nicht nachvollziehbar. Solange Einträge
  existieren, bleibt das Panel mit passender Überschrift sichtbar.
- **P2, behoben:** Geänderte Frontend-Einstiegspunkte und gemeinsame Imports
  verwenden konsistente neue Cachekennungen, damit alte Modulstände nicht mit
  neuen Aktionen/HTML-Elementen gemischt werden.

Der fachliche Modellabgleich ist erfüllt: keine Digitalisat-, Standort- oder
Verpackungsfelder, keine Maßgruppen-Hilfetexte. `Objektmaß` bedeutet fachlich
bei Klappbildern den geschlossenen Zustand; das Schema kann die sachgerechte
Messung nicht automatisch überprüfen. Das geöffnete Maß wird separat erfasst.

Isoliert im Browser geprüft: Entwurf, Volltext-Wiederöffnung, Abschluss, zwei
Korrekturen ohne Neuladen, Klappbild, nächstes Objekt bei zurückgehaltener
Schreibantwort, Reload und idempotente Wiederaufnahme. Der Dateiabgleich ergab
3 YAML-Records und 3 Indexeinträge, 4 Reservierungen und nächste Zähler 5;
das neue vierte Objekt blieb nur reserviert. Die zweite Beschreibungskorrektur
und beide Klappbildmaße waren erhalten. Autographen- und Foto-Gemeinschaftsrenderer
öffneten ohne Thoma-Aktionen. Legacy-Foto ist durch die gemeinsame Regression
abgedeckt, nicht durch eine neue manuelle Legacy-Erfassung.

Die isolierte fachliche Endabnahme für Markus kann beginnen. Eine automatische
oder uneingeschränkte Produktivfreigabe wird daraus nicht abgeleitet; insbesondere
bleiben die dokumentierte Unterstützungsgrenze und die tatsächliche Hosting-/
Zugriffskonfiguration ausdrücklich zu bewerten.

Prüfnachweis: gemeinsame Regression mit
`.venv/bin/python -m unittest discover -s tests`: 318 ausgeführte Tests, davon
317 erfolgreich und eine veraltete statische Cacheversions-Erwartung. Nach deren
Anpassung bestand `tests.test_generic_navigation` mit 9 Tests. Der neue
Unabhängigkeitsnachweis für die beiden Zähler und die gezielte Regression für
entfernte optionale Repeaterwerte bestanden gemeinsam mit 2 Tests. Bereits
bestandene Gesamtläufe wurden danach nicht ohne Anlass vollständig wiederholt.
`git diff --check` war fehlerfrei. Die bestehenden Deprecation-Warnungen betreffen
Starlette/httpx und jsonschema.RefResolver, nicht fehlgeschlagene Fachprüfungen.


### Nachprüfung Lösungsweg B

Die gemeinsame Regression (`.venv/bin/python -B -m unittest discover -s tests`)
bestand mit 325 Tests. Zusätzliche gezielte Prüfungen betreffen rekursive
Schema-Konstanten, Default-ohne-const, variable/abweichende geschützte Werte,
unbekannte Bestandsinformationen, Isolierung unsicherer Module sowie pausierte
Queue-Snapshots und unklare Übertragungsergebnisse. Die gezielte Regression
prüft auch die tatsächlichen Autographen- und Fotorepeater auf Listenersetzung.

Im vorhandenen isolierten lokalen Runner wurden im Browser die erste und eine
mittlere Maßgruppe entfernt, Gruppen erneut ergänzt und ein Entwurf als Create
sowie anschließend als Update gespeichert. `mm` blieb überall sichtbar und
gesperrt; YAML und Index wurden im InMemory-Repository abgeglichen. Dezimalwerte
`12,5` und `8.5` blieben als `12.5` und `8.5` erhalten. Es wurden keine
produktiven Daten, State-Dateien oder Freigaben verändert.


### Gemeinsame Aktionsleisten

Die generische Oberfläche bietet oben Öffnen/Neuanlage, Vorheriger/Nächster und
Bearbeiten/Speichern/Verwerfen; unten unmittelbar vor Vorbelegungen dieselben
Speicher-/Verwerfhandler und Zustände. Bestehende Datensätze öffnen zur Ansicht.
Thoma verwendet bei neuen Datensätzen und Bestandsentwürfen `complete`, bei
abgeschlossenen Datensätzen `save`. Neue Entwurfsspeicherung wird nicht angeboten;
alte `draft`-Queue-Aufträge werden unverändert verarbeitet. Frühere Abnahmeschritte
mit den separaten Entwurfs-/Abschlussbuttons beschreiben den vorherigen Stand.

Der URL-Marker `search=1` erhält einen ausdrücklich geöffneten Suchkontext auch
bei leerer Suchanfrage; Suchparameter erhalten ihn ebenfalls. Direkte Recordlinks
ohne Suchkontext navigieren im zugänglichen Gesamtbestand natürlich nach ID
(`Thoma000001`, `autograph-000001`). Trefferkontexte behalten ihre Indexsortierung;
außerhalb ihrer Liste sind Nachbarn deaktiviert. Reservierungen sind keine
Listeneinträge. Öffnen der Suche erhält eine bestätigte lokale Reservierung.

Neuanlage und Schutzdialoge sind nun zusammengeführt: „Neuer Datensatz“ nutzt bei
Thoma den bisherigen fortlaufenden Reservierungsablauf. Nur Objektart und
Lagergruppe werden übernommen; die kanonischen Defaults erzeugen genau eine
leere Objektmaßgruppe. Auch beim ersten Start und bei Reservierungswiederaufnahme
werden keine Presets automatisch angewendet. Autographen behalten ihren bisherigen
Neuanlage-/Presetablauf. Der zusätzliche Button „Nächstes Objekt“ entfällt.

Suche, Datensatzwechsel, Vorheriger/Nächster, Neuanlage und Modulwechsel verwenden
den gemeinsamen Schutzablauf: Abbrechen, Speichern und weiter, ausdrücklich
Verwerfen und weiter. Die Speicherung muss vollständig validiert und dauerhaft
lokal vorgemerkt sein; die Serverantwort wird nicht abgewartet. Änderungen nach
dem Snapshot verhindern den Wechsel. Vorhandene Queue-Aufträge werden niemals
allein durch Navigation oder Verwerfen gelöscht. Besteht für denselben Datensatz
bereits ein Queue-Auftrag und wurden weitere Änderungen vorgenommen, kann ein
weiterer Snapshot erst nach Auflösung dieses Auftrags gespeichert werden; der
Wechsel mit „Speichern und weiter“ wird bis dahin nicht zugelassen.

Bestätigte bloße Reservierungen bleiben beim Öffnen der Suche erhalten. Über
„Lokalen Stand öffnen“ sind sie wiederaufnehmbar. Vor einer anderen Neuanlage
wird ausdrücklich nach Aufgabe gefragt; Abbrechen erhält die alte Operation.
Unklare Reservierungen müssen zunächst mit derselben Operations-ID abgeglichen
werden. Vorgemerkte Creates sind keine bloßen Reservierungen.

Isolierte Browserprüfung: Thoma-Neuanlage und Abschluss, frisches Folgeobjekt,
unvollständige Eingabe, abgebrochener Wechsel, fehlgeschlagenes Speichern und
weiter, Vervollständigung, erfolgreiches Speichern und weiter, Suche und
Wiederaufnahme derselben Reservierung. Aufgeben-Dialog mit Abbrechen sowie OK
geprüft: Thoma000003 blieb beim Abbrechen erhalten, nach Aufgabe folgte
Thoma000004. Autographen-Create ebenfalls geprüft. Die Baseline-Korrektur aus dem
vorherigen Auftrag ist im Browser bestätigt: nach Create sind Speichern und
Verwerfen oben und unten deaktiviert; kein falscher Änderungszustand durch leere
optionale Felder. Die automatische gemeinsame Regression bestand mit 327 Tests;
die abschließende gezielte Nachprüfung ist im Auftragsbericht angegeben.

Für den nächsten Frontend-Rollout benötigen `module.js` und dessen Import von
`next-record.js` den gemeinsamen Cachemarker `thoma-navigation-2`.
