# Phase 8B: Read-only-Inventur des Legacy-Website-Stagings

Stand: 1. August 2026

## Umfang und Herkunft

Diese Inventur wurde ausschließlich aus dem vollständig verifizierten
Phase-8A-Legacy-Content-Archiv erstellt. Das frühere Arbeitsprojekt wurde nicht
erneut geöffnet. Es wurde keine Legacy-Datei importiert oder ausgeführt.

Archivnachweis:

- 223 Content-Dateien und 1.755.382 Content-Bytes;
- Archiv-SHA-256:
  `468d8a83e0e291eb1a970af77774b4567e4884851528683095571221d4691117`;
- Content-Manifest-SHA-256:
  `b019509bdbdedfe2ad79bdda5d7a8f23ac33a34658682fe477d74964630873c3`;
- vollständige Archivlesung, interne Manifestbindung und alle Datei-Hashes
  unmittelbar vor der Inventur erneut verifiziert.

Aus dem Archiv wurden nur die einschlägigen Source-, Konfigurations-,
Dokumentations-, UI- und Testdateien als Text untersucht:

- `backend/jarvis_backend/website/staging.py`;
- die beiden Routen in `backend/jarvis_backend/app.py`;
- die Website-Felder in `backend/jarvis_backend/config.py`;
- `config/website-staging.json`;
- `skills/website-staging.json`;
- die Website-Ansicht und Aufrufe in `frontend/index.html` und
  `frontend/app.js`;
- `tests/test_website_staging.py`, `tests/test_policy.py` und
  `tests/test_config.py`;
- die einschlägigen Aussagen in der Legacy-Dokumentation.

## Tatsächliche Legacy-Funktion

Die Backend-Funktion besteht aus einem `WebsiteStagingService` mit zwei
Methoden und genau zwei HTTP-Routen.

### `GET /api/website/status`

Die Route verlangt eine bestehende Legacy-Sitzung. Sie ruft `status()` für das
konfigurierte Projekt auf und liefert folgende Felder:

- `selected_project`;
- `repository`;
- `branch`;
- `clean`;
- `remote`;
- `staging_workspaces`.

Ohne ausgewähltes Projekt werden leere Git-Felder geliefert. Bei einem
Verzeichnis mit `.git` führt der Service drei lokale Git-Unterprozesse aus:
Branch, Porcelain-Status und Origin-URL. Ein Git-Fehler oder Timeout wird als
Servicefehler behandelt.

### `POST /api/website/stage`

Die Route verlangt Legacy-Sitzung, Same-Origin und einen nicht pausierten
Server. Sie nimmt keinen Request-Body an. Projekt- und Stagingpfad stammen
vollständig aus globaler Konfiguration.

Bei einem als Git-Repository erkannten Projekt wird ein nicht sauberer Status
abgelehnt. Anschließend kopiert `create()` den gesamten konkreten
Projektunterordner unter einen zeitgestempelten Stagingnamen. Ignoriert werden
unter anderem `.git`, Editor-/Agentenordner, `node_modules`, `.venv`, `dist`,
`build` und `__pycache__`. Bei einem Kopierfehler wird der neu angelegte
Stagingordner bestmöglich entfernt.

Die Response enthält:

- `status=created`;
- einen zeitabhängigen `identifier`;
- den absoluten Stagingpfad;
- `snapshot_method`, entweder `git_worktree_required` oder `snapshot_copy`.

Das Feld `git_worktree_required` ist nur eine Kennzeichnung. Der Legacy-Code
erstellt keinen Git-Worktree. Nach Erfolg wird ein Audit-Ereignis mit
Identifier und Snapshotmethode angehängt.

## Request-, Datei- und Workspace-Semantik

Die Legacy-Stage-Route besitzt kein fachliches Requestmodell und akzeptiert
keine explizite Dateiliste, Operation, Budgets, Hashbindungen oder
Idempotenzkennung. Die einzige Eingabe ist indirekt das global konfigurierte
Projekt.

Die Konfiguration kennt:

- geschützten Root;
- ausgewählten konkreten Projektpfad;
- Stagingroot;
- deklarative Schalter für Git/Snapshot, Diff, Bestätigung und Promotion-PIN.

Nur die Pfadbeziehung des ausgewählten Projekts zum geschützten Root wird beim
Laden validiert. Es gibt keine Positivliste für Dateitypen, keine Datei- oder
Größenbudgets, keine Reparse-Point-Prüfung, kein quellgebundenes Before-
Manifest und keine atomare dateiweise Apply-Phase. `copytree()` entscheidet
rekursiv über den gesamten verbleibenden Baum.

Die Tests beweisen lediglich:

1. Ein konkreter Kindordner wird kopiert und die Quelle bleibt bei diesem
   einfachen Beispiel unverändert.
2. Der geschützte Root selbst wird als Quelle abgelehnt.
3. Die alte Policy fordert für `website.stage` eine Bestätigung.
4. Versionierte Konfiguration soll keinen fest codierten privaten Nutzerpfad
   enthalten.

Symlinks/Junctions, Traversal, geheime Dateien, Archive, Binärdateien,
Dateibudgets, Teilfehler, Hash-CAS, Restart-Idempotenz, Verifikation und
Rollback sind nicht abgedeckt.

## Preview- und Execute-Realität

Legacy-Konfiguration, Skillmanifest, README und UI versprechen eine sichtbare
Diff-Vorschau, Projekttests, Bestätigung vor Übernahme und einen Git-basierten
Rollback. In den inventarisierten Website-Komponenten ist davon nur die
Bestätigung **vor dem Erstellen der Kopie** vorhanden.

Es gibt insbesondere keine Website-spezifische Route oder Implementierung für:

- einen schreibfreien Preview-Plan;
- einen kanonischen Preview-Hash;
- einen Diff der vorgeschlagenen Dateien;
- Apply auf einzelne genehmigte Dateien;
- statische HTML-/Link-/Scriptverifikation;
- Artifact-Manifeste;
- eine Promotion oder Veröffentlichung;
- einen bytegleichen Restore oder driftgeschützten Rollback.

Die tatsächlich ausführende Operation ist daher nicht „Preview und Execute“,
sondern nur „vollständige Arbeitskopie erzeugen“. Die UI zeigt nach Erfolg nur
den Identifier an.

## Sicherheitsannahmen und versteckte Abhängigkeiten

Die Legacy-Funktion vertraut auf globale Konfiguration, eine alte
Sitzungsprüfung, Same-Origin, einen Pausenstatus, UI-Bestätigung und eine
separate Legacy-Policy. Der Service selbst besitzt keine an einen Task oder
Actor gebundene Autorisierung.

Weitere implizite Abhängigkeiten sind:

- lokales `git` für Statusabfragen;
- Systemzeit für nicht deterministische Workspace-IDs;
- ein vorhandener Nutzerprojektbaum;
- ein frei konfigurierbarer Stagingroot;
- rekursive Betriebssystem-Kopiersemantik;
- ein globaler Auditlogger;
- laut Skillmanifest ein nicht näher bestimmtes „project-test-runtime“.

Die letzte Abhängigkeit ist nicht implementiert oder näher gebunden. Sie wird
nicht übernommen. Für die fachliche Kernsemantik „lokale statische Dateien in
einem isolierten Arbeitsbereich vorschlagen und prüfen“ sind weder Account,
Netzwerk noch dieses unbekannte Test-Runtime erforderlich.

## Bereits durch OpenJarvis ersetzt

OpenJarvis besitzt bereits die maßgeblichen Trust Boundaries:

- Task-, Session-, Event- und Timeline-Modelle;
- `ToolProposal`, persistente Toolaktionen und den `ToolActionService`;
- `CentralRiskPolicy`, Risiko-Floor und Allow-once-Approval;
- gebundene, sichere Filesystem-Lanes;
- Verifikationsresultate, Toolartefakte und Trace-Evaluation;
- loopbackgebundene, authentifizierte FastAPI-Routen;
- die bestehende einheitliche Jarvis-UI.

Diese Komponenten ersetzen Legacy-Sitzung, Legacy-Policy, globales
Skillmanifest, ungebundene Filesystem-Autorität und den bloßen
`copytree()`-Erfolgsstatus.

## Selektiv zu portierende Semantik

Übernommen wird ausschließlich:

- eine echte Website bleibt außerhalb des Pilot-Workspaces unangetastet;
- Arbeit findet in einem neu erzeugten, lokalen und wegwerfbaren Workspace
  statt;
- ein geplanter Dateisatz ist vor jeder Mutation sichtbar;
- Änderungen sind explizit risikobewertet, verifiziert und rollbackfähig;
- Status und Artefakte sind in API, Timeline und UI nachvollziehbar.

Der Port verwendet nur synthetische lokale Fixtures und positive Dateityp-
Listen. Er kopiert kein Nutzerprojekt und führt weder Git noch JavaScript noch
ein Projekt-Test-Runtime aus.

## Bewusst verworfen

Nicht übernommen werden:

- absolute oder nutzerprofilgebundene Projektpfade;
- ein global ausgewähltes Produktivprojekt;
- vollständiges rekursives Kopieren eines beliebigen Projektbaums;
- Zeitstempel als Identitäts- oder Idempotenzmechanismus;
- Git-Unterprozesse und Remote-URL-Ermittlung;
- Legacy-Skillrouting oder Legacy-Policyentscheidungen;
- pauschale Autonomie für reversible Writes;
- `git_worktree_required` ohne tatsächlichen Worktree;
- ein unbekanntes Projekt-Test-Runtime;
- Promotion, Deployment, Veröffentlichung, Netzwerk oder Accounts;
- die Rückgabe privater absoluter Workspacepfade.

## Unklare Legacy-Semantik

Unklar bleibt, wie der versprochene Diff, die Projekttests, eine spätere
Übernahme und der behauptete gepinnte Git-Rollback geplant waren. Ebenso ist
nicht definiert, ob `snapshot_copy` bei Git-Projekten jemals zulässig sein
sollte. Diese Lücken werden nicht erraten und nicht als Legacy-Kompatibilität
ausgegeben.

## Erforderliche Pilotgrenzen und Entscheidung

Der isolierte Funktionspilot ist ohne Accounts, Netzwerk und unbekannte
Runtime-Abhängigkeiten klar realisierbar, wenn folgende Grenzen fail-closed
gelten:

- strikt validierte, unveränderliche Requests und relative Pfade;
- neu erzeugter temporärer Root außerhalb realer Projekte und Vaults;
- Positivlisten für Dateien und Operationen sowie harte Budgets;
- verpflichtender Preview-Hash und Before-Manifest-CAS;
- Mutation ausschließlich über `ToolActionService` und
  `CentralRiskPolicy`;
- keine Ausführung von JavaScript, Shell, Git oder Legacy-Code;
- atomare Writes, vollständige statische Verifikation und kanonische
  Artifact-Manifeste;
- bytegleicher, hashgebundener Rollback in einem getrennten temporären Root;
- vollständiges Cleanup nach jedem hermetischen Lauf.

Es liegt damit kein Isolationsblocker vor. Diese Inventur autorisiert weder
einen Zugriff auf echte Websiteprojekte noch einen Produktivpilot.
