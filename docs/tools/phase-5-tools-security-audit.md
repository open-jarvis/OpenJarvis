# Phase 5: Tool-, Browser- und Windows-Desktop-Sicherheitsaudit

## Zweck, Stand und Sicherheitsgrenze

Dieser Bericht wurde vor der ersten Produktionscodeaenderung in Phase 5
erstellt. Untersucht wurden ausschliesslich der aktuelle OpenJarvis-Quellcode,
vorhandene Tests und die bereits committed Phase-1-bis-4-Dokumentation. Das
alte `jarvis-desktop`-Projekt und das reale Obsidian-Vault wurden weder geoeffnet
noch gelesen. Es wurden keine echten Browserprofile, Konten oder externen
Dienste verwendet.

Sicherer Start am 2026-07-30:

| Pruefung | Ergebnis |
| --- | --- |
| Repository | `C:\Users\Playe\Documents\JARVIS\openjarvis-codex` |
| Branch | `feature/codex-jarvis-orchestrator` |
| HEAD | `5e0cbc563022aafac1b5e5847effd6bff099ecec` |
| Arbeitsbaum | sauber |
| `upstream` Fetch | `https://github.com/open-jarvis/OpenJarvis.git` |
| `upstream` Push | `DISABLED` |
| Phase-4-Bundle SHA-256 | `64EDBD68BF9FA6C64A936A00A1809E62A35B799AE5C2027E4879045CA8B17741` |
| Bundle-Verifikation | gueltig; vollstaendige Historie; SHA-1-Objektformat |
| Restore-Verifikation | Restore-HEAD entspricht Phase-4-HEAD; 907/907 Commits; `git fsck --full --strict` ohne Fehler |
| Frischer Restore | `work/phase5-start-restore-6e4ca078` ausserhalb des Repositories |

Die Phase-4-Sperren bleiben kanonisch: Das echte Vault, seine 46 Notizen und
das Altprojekt bleiben ausserhalb des Phase-5-Zugriffs. `full_access`, ein
stiller API-Key-/Responses-API-Fallback, automatische oder erinnerte
Genehmigungen fuer Codex-Aktionen sowie reale Level-4-Aktionen bleiben
verboten.

## Executive Summary

OpenJarvis besitzt gute Einzelbausteine, aber noch keine geschlossene,
zwingende Tool-Sicherheitsgrenze. Die Phase-3-Komponenten
`CentralRiskPolicy`, `PersistentApprovalBroker`, `ExecutionLaneScheduler`,
Task-Timeline und korrelierte Traces sind eine geeignete Basis. Ebenso sind
SSRF-Pruefung, Capability-Typen, Injection Scanner, Boundary Guard,
Dateisensitivitaetsmuster und Container-Mount-Pruefungen wiederverwendbar.

Die aktuelle `ToolRegistry` speichert dagegen nur einen Namen und eine Klasse.
Die 61 tatsaechlichen Decorator-Registrierungen besitzen kein versioniertes
Manifest. `ToolExecutor` parst JSON, validiert es aber nicht gegen das
angegebene JSON-Schema. Capability-Pruefung ist optional und die vorhandene
`CapabilityPolicy` ist standardmaessig offen. Direkte `tool.execute()`-Aufrufe
umgehen den Executor vollstaendig. Timeout beendet bei Thread-Ausfuehrung die
laufende Operation nicht. Ein Exitcode oder ein von der Implementierung
gesetztes `success=True` gilt ohne nachgelagerte Zustandsverifikation als
Erfolg.

Die Filesystem-, Shell-, Git- und Browserwerkzeuge sind deshalb nicht fuer
unbeaufsichtigte Desktopkontrolle freigegeben. Der Python-Shellpfad verwendet
`shell=True`; Filesystem-Allowlisten sind optional und leer gleich global;
`apply_patch` hat gar keine Root-Allowlist; Git akzeptiert beliebige
Repositorypfade; Screenshots koennen an beliebige Pfade geschrieben und als
vollstaendiges Base64 in Metadaten/Logs getragen werden. Der Browser besteht
aus einer globalen lazy Playwright-Seite, ohne temporaeres persistentes
Profil, PID-/Port-/Health-Modell, Prozessbesitz, Recovery-Automat oder
Aktionsverifikation. Eine Windows-Desktopautomation existiert nicht.

## Bestandsarchitektur

### Registry, Schema und Ausfuehrung

- `openjarvis.core.registry.ToolRegistry` ist eine generische In-Memory-Map.
  Registrierung prueft nur doppelte Namen.
- `openjarvis.tools._stubs.ToolSpec` enthaelt Beschreibung, Parameter-Schema,
  Kategorie, Confirmation-Flag, Timeout und Capability-Liste. Version,
  Plattform, Lane, Risiko, Side-Effect, Netzwerk, Secrets, Roots,
  Idempotency, Verification und Undo fehlen.
- `ToolExecutor` kennt nur die bei Konstruktion uebergebenen Instanzen. Er
  lehnt unbekannte Namen ab und parst JSON, setzt aber weder `required` noch
  Typen, Grenzen oder `additionalProperties=false` durch.
- Boundary-, Capability-, Taint- und Confirmation-Pruefungen werden nur im
  Executor ausgefuehrt und sind teils optional. Direkte Toolaufrufe,
  Scheduler-, Workflow-, MCP- und andere Adapterpfade koennen davon
  abweichen.
- Das Timeout basiert auf `ThreadPoolExecutor.future.result(timeout=...)`.
  Der Python-Thread wird dadurch nicht beendet; ein Kontextmanager kann auf
  die noch laufende Arbeit warten. Das ist keine belastbare
  Prozessbaumkontrolle.

### Toolinventar

Die 61 tatsaechlich registrierten Built-ins verteilen sich auf folgende
Sicherheitsgruppen:

| Gruppe | Vorhandene Werkzeuge | Auditbewertung |
| --- | --- | --- |
| Lokal read-only | `calculator`, `think`, `file_read`, `git_status`, `git_diff`, `git_log`, Retrieval-/Knowledge-Reads | Logik teilweise wiederverwendbar; zentrale Manifest-, Root- und Schema-Pruefung fehlt |
| Lokale Writes | `file_write`, `apply_patch`, Memory-/Knowledge-Writes, Scheduler, Profile-/Skill-Management | nicht ohne zentrale Policy; atomare Writes, Restore, Idempotency und Verifikation uneinheitlich |
| Prozess/Code | `shell_exec`, `repl`, `code_interpreter`, Docker-Varianten | hochriskant; kein einheitlicher enger Command-Vertrag; mehrere Ausfuehrungspfade |
| Git | `git_status`, `git_diff`, `git_log`, `git_commit` | read-only Kern brauchbar; Root-/Remote-/Branch-/Worktree-Policy und Push-Sperren fehlen |
| Browser/Netzwerk | sechs Browsertools, `http_request`, `web_search` | keine Session-/Recovery-/Verification-Grenze; Webinhalt nicht durchgaengig als untrusted markiert |
| Externe Wirkung | `channel_send`, proaktive Actions, Agent-/Connector-Pfade | bis zur zentralen Action-/Approval-Schicht deaktiviert oder nur simuliert verwenden |
| MCP | dynamisch adaptierte Remotetools | Beschreibung/Schema wird vom Server uebernommen; lokales Manifest und lokale Risikohoheit fehlen |

### Filesystem

`file_read` und `file_write` loesen Pfade auf und koennen optionale
`allowed_dirs` erhalten. Eine leere Liste bedeutet jedoch Zugriff auf jeden
nicht als sensitiv erkannten Pfad. Es gibt keine gemeinsame kanonische
Windows-Pfadpolicy, keine zwingende Root-Allowlist, keine ADS-Sperre, keine
explizite Reparse-/Junction-Abweisung und keine case-insensitive
`normcase`-Grenzpruefung. `file_write` schreibt direkt, `append` oeffnet die
Zieldatei direkt, und beide Pfade erzeugen weder Before-/After-Hash noch Diff
oder Restore-Artefakt. `apply_patch` hat keine Root-Allowlist, schreibt direkt
und legt optional eine `.bak` neben dem Ziel ab; dies ist weder atomar noch
taskisoliert.

Die Mount-Security loest Pfade und kennt sensible Muster, laesst aber bei
leerer Rootliste ebenfalls alle nicht geblockten Ziele zu. Sie ist ausserdem
nicht die gemeinsame Policy der normalen Filesystemtools.

### Shell und Prozesse

`shell_exec` nimmt eine freie Command-Zeichenfolge an. Der Rustpfad und der
Pythonfallback haben unterschiedliche Semantik. Der Pythonfallback ruft
`subprocess.run(..., shell=True)` auf, akzeptiert zusaetzliche frei benannte
Environmentvariablen und prueft das `cwd` nur auf Existenz. Pipes,
Redirects, Subshells, Systemkommandos, Paketinstallation oder unbekannte
Downloads werden nicht zentral klassifiziert. Timeout und Outputlimit sind
vorhanden, aber der Prozessbaum wird in diesem Tool nicht nachweisbar beendet.

`security.subprocess_sandbox` besitzt Environmentfilter, Timeout und einen
POSIX-Prozessgruppenansatz, verwendet jedoch ebenfalls `shell=True` und
`preexec_fn=os.setsid`; das ist unter Windows nicht die erforderliche
Prozessbaumimplementierung.

### Git

Die vorhandenen Gittools verwenden fuer CLI-Fallbacks strukturierte
Argumentlisten und `shell=False` (Default). `status`, `diff` und `log` sind
als enge read-only Operationen wiederverwendbar. `git_commit` kann jedoch
beliebige Pfade stagen und in einem beliebigen Repository committen. Es gibt
keine Task-Worktree-Grenze, keine Branch-/Remote-Policy, keine Promotion-
Pruefung, keine Bundle-Tools und keine zentrale Sperre fuer Push,
Force-Push, `reset --hard` oder `clean -fdx`. Letztere sind nicht als enge
Tools implementiert, koennen aber ueber die freie Shell erreicht werden.

### Browser

`openjarvis.tools.browser._BrowserSession` startet lazy genau einen globalen
headless Chromium-Prozess mit `sync_playwright().start()` und
`chromium.launch(headless=True)`. Es wird anschliessend nur eine Seite
geteilt. Es gibt keine explizite Context-/Profilpolicy, keinen Besitznachweis,
keine PID, Startzeit, Port-, Control-Service- oder Heartbeatverwaltung und
keinen Recovery-Checkpoint.

`browser_navigate` fuehrt eine SSRF-Pruefung aus und liest URL, Titel und Body.
Die uebrigen Browsertools greifen direkt auf die globale Seite zu.
`browser_click` und `browser_type` melden nach erfolgreichem Playwright-Aufruf
Erfolg, ohne den erwarteten Zustand zu beobachten. `browser_screenshot` kann
beliebige Dateien schreiben und speichert das gesamte Bild als Base64 in
Result-Metadaten. Downloads, Uploads, Tabs, Select, Scroll, Reload und
geordnete Sessionressourcen sind nicht als sichere Tools modelliert.

Die exakte Klasse oder Meldung `BrowserOpenError` existiert im aktuellen
Repository nicht. Launch-, Page-, Navigations- und Verbindungsfehler werden
als generische Exception in den jeweiligen Toolresultaten zusammengefasst.
Damit sind die fuer den bekannten Fehler relevanten Komponenten die globale
`_BrowserSession`, Playwright-Start, Chromium-Launch, Page-Erzeugung und die
direkten Toolzugriffe. Ein eigener Steuerungsdienst oder CDP-Port wird derzeit
nicht verwaltet.

Eine weitere Besonderheit: Die allgemeine SSRF-Policy blockiert Loopback.
Phase-5-Tests brauchen daher keine globale Lockerung, sondern eine enge,
explizite BrowserProfile-/Network-Policy, die nur den eigenen Testserver und
seinen gebundenen Port innerhalb der synthetischen Session erlaubt.

### MCP

Der MCP-Adapter erzeugt dynamische `BaseTool`-Adapter aus entfernten
Definitionen. Name, Beschreibung und Inputschema stammen dabei vom MCP-
Server. Das ist fuer Discovery geeignet, darf aber keine lokale Capability,
kein Risiko und keine Freigabe erzeugen. Vor Aktivierung ist deshalb fuer
jedes MCP-Tool ein lokales, versioniertes Manifest erforderlich; ungemappte
Remotetools muessen deaktiviert bleiben.

### Approval, Capability, Scanner und Sandbox

- Die Phase-3-`CentralRiskPolicy` definiert bereits Level 0 bis 4 und erhoeht
  Risiko anhand von Markern. Diese Enum bleibt die einzige kanonische
  Risikoklassifikation.
- `PersistentApprovalBroker` persistiert Codex-Requests, wartet ohne die
  model lane zu belegen, weist Timeouts ab und claimt jede Antwort genau
  einmal. Dieser Broker ist wiederverwendbar.
- Der aeltere `tools.approval_store` enthaelt hingegen
  `always_approve`/Permission Memory. Dieser Pfad darf fuer Phase-5-Codex-
  Aktionen nicht verwendet werden.
- `CapabilityPolicy` unterstuetzt Grants und Denials, ist aber ohne explizite
  Konfiguration offen. Die neue Toolgrenze muss deny-by-default sein und nur
  serverseitig konfigurierte Grants akzeptieren.
- Injection Scanner, Boundary Guard, Credential Stripper, Taint- und SSRF-
  Pruefung sind geeignete Sensoren. Sie sind heute nicht als zwingende Stufe
  vor jeder Webaktion verdrahtet.
- Container-/WASM-Sandboxen sind nuetzlich fuer bestehende isolierte
  Codepfade, ersetzen aber weder Windows-Rootpruefung noch Prozessbesitz und
  Desktop-/Browser-Lanes.

### Tasks, Events, Traces und Artifacts

Phase 3 liefert task-, session-, thread-, turn-, item-, approval- und
correlation-bezogene Datentypen, einen SQLite Event Store, Projection,
Recovery und exact-once Idempotency. Phase 4 ergaenzt Task Sources und
Memory-Artefakte. Tool Proposal, Action, Tool Run, Verification, Undo und die
vollstaendige geforderte Artifact-Korrelation existieren noch nicht als
kanonisches Modell. Der generische Legacy-EventBus schneidet Tooloutput bei
10 KiB ab, speichert aber immer noch Output statt eines Artifact-Verweises.

### API und bestehende UI

Der Server besitzt API-Key-Middleware, eine Schutzpruefung gegen nicht-
Loopback-Bindung ohne Key sowie in Phase 3/4 etablierte Anforderungen fuer
`X-Correlation-ID` und `Idempotency-Key`. `GET /v1/tools` existiert bereits im
Agent-Manager, liefert aber keine Phase-5-Manifeste oder Healthdaten. Action-
und Browser-Session-Endpunkte fehlen.

Die bestehende React-Oberflaeche besitzt `CodexTasksPanel`, Approval-Anzeige,
Task-Timeline, Trace- und Memory-Komponenten. Sie ist der richtige
Integrationspunkt. Toolmanifest, Actionstatus, Wirkung, Root/Sandbox,
Verification, Browserhealth, Artifacts, Diff und Undo fehlen. Der bestehende
Approvalpfad darf um `Allow once` und `Deny` erweitert werden; ein
`always allow` darf dort nicht erscheinen.

### Windows-Desktop und Vision

Es gibt keine produktive `pywinauto`-, UIAutomation-, `pyautogui`- oder
vergleichbare Windows-Desktopabstraktion im aktuellen OpenJarvis-Code.
Maus-/Tastaturpfade finden sich nur in Eval-Umgebungen. Es existieren keine
Produktionsmodelle fuer Prozess-/Fensterbesitz, Fokus, Monitor, DPI,
Skalierung, Vorher-/Nachher-Screenshot, Not-Aus oder Secure-Desktop/UAC-
Grenzen. Phase 5 muss deshalb eine standardmaessig deaktivierte semantische
Abstraktion mit synthetischem Adapter einfuehren; reale fremde Anwendungen
bleiben ausserhalb der Tests.

## Antworten auf die zehn Pflichtfragen

### 1. Welche vorhandenen Tools koennen unveraendert verwendet werden?

Keine bestehende Toolklasse darf unveraendert direkt als autorisierte
Phase-5-Aktion ausgefuehrt werden, weil das Manifest-Gate fehlt. Hinter der
neuen zentralen Schicht koennen die reine Berechnungslogik von `calculator`
und `think`, read-only Git-CLI-Helfer (`status`, `diff`, `log`) sowie Teile der
Retrieval-/Knowledge-Reads wiederverwendet werden. Phase-3-Policy, Broker,
Lanes, Task Store und Scanner koennen als Infrastruktur weitgehend
unveraendert verwendet werden.

### 2. Welche Tools umgehen derzeit zentrale Policy oder Approval?

Jeder direkte `BaseTool.execute()`-Aufruf umgeht den `ToolExecutor`. Im
Executor sind CapabilityPolicy, Boundary Guard und interaktive Confirmation
optional. Besonders relevant sind `shell_exec`, `file_write`, `apply_patch`,
`git_commit`, Browsertools, `channel_send`, proaktive Actiontools,
Code-Interpreter, Scheduler und dynamische MCP-Adapter. Der aeltere
ApprovalStore mit `always_approve` darf nicht an Codex-Actions angeschlossen
werden.

### 3. Wo werden Parameter nur durch Modelltext statt durch ein Schema begrenzt?

Alle `ToolSpec.parameters` werden dem Modell als JSON-Schema angezeigt, aber
im Executor nicht validiert. Viele Tools pruefen nur einzelne Felder manuell
und ignorieren unbekannte Parameter. Shellkommandos, Patchtext,
Browserselector, MCP-Argumente, freie Git-Dateilisten und Pfade sind besonders
kritisch. `additionalProperties=false` wird nicht erzwungen.

### 4. Welche Toolausfuehrungen haben keine Verifikation?

Nahezu alle mutierenden Tools. File Write prueft nur die Endgroesse, Patch nur
den eigenen Schreibaufruf, Git Commit nur den Exitcode, Shell nur Exitcode,
Browser Click/Type nur das Ausbleiben einer Playwright-Exception. Channel-,
Scheduler-, Memory-, MCP- und proaktive Actions haben keine einheitliche
erwarteter-Zustand-Pruefung. Read-only Tools benoetigen weiterhin
Schema-/Root-Pruefung, aber keine Undo-Verifikation.

### 5. Welche Tools besitzen keine Idempotency-Regel?

Das Legacy-Toolmodell besitzt generell keinen Idempotency-Key. Besonders
gefaehrdet sind File Append/Write/Patch, Commit, Shell, Browser Click/Type,
Channel Send, Scheduler, Memory Writes und Remote-/MCP-Aktionen. Phase-3/4-
Task- und API-Mutationen zeigen bereits ein geeignetes exact-once Muster, das
auf Actions uebertragen werden muss.

### 6. Welche Tools koennen ausserhalb ihrer erlaubten Roots arbeiten?

`file_read` und `file_write`, wenn `allowed_dirs` leer ist; `apply_patch`
immer; `shell_exec` ueber frei waehlbares `working_dir`; alle Gittools ueber
`repo_path`; `browser_screenshot` ueber `path`; diverse Datenbank-, Upload-,
Profile-, Skill-, Memory- und Connectorpfade je nach Konfiguration. Es gibt
keine gemeinsame Root-Policy fuer diese Pfade.

### 7. Welche Browserkomponenten fuehren zum bekannten BrowserOpenError?

Der Fehlername ist nicht implementiert. Die korrespondierenden Fehlerstellen
sind Playwright-Import/Start, Chromium-Launch, Page-Erzeugung und der Zugriff
auf die globale `_BrowserSession.page`; sie werden als generische Navigation-,
Click-, Type-, Screenshot- oder Extract-Fehler ausgegeben. Ohne getrennte
Healthdaten kann die Ursache nicht klassifiziert werden.

### 8. Welche Browserkomponenten verwalten Prozess, Port und Steuerungsdienst?

Keine OpenJarvis-Komponente verwaltet sie explizit. Playwright besitzt den
intern gestarteten Browserprozess. PID, Child-Prozesse, Startzeit,
Profilpfad, CDP-/Control-Port, Portbesitz, Health-Endpunkt und Heartbeat werden
nicht erfasst. Ein Control-Service existiert nicht als kanonische Komponente.

### 9. Welche Windows-UI-Adapter existieren bereits?

Keine produktiven Adapter. Es gibt keine semantische UIAutomation-Schicht und
keinen sicheren Koordinatenfallback. Browser-/Web-Evals verwenden lokal
Playwright-Maus und -Tastatur, sind aber keine Windows-Desktopautomation.

### 10. Was bleibt bis Phase 8 oder separater Freigabe deaktiviert?

- Zugriff, Migration, Umbenennung, Neuordnung oder Schreiben im echten Vault;
- Zugriff oder Aenderung am alten `jarvis-desktop`;
- private Standardbrowserprofile, echte Cookies, Konten, Extensions und
  Passwortmanager;
- reale Nachrichten, Posts, Formularsendungen, Uploads und Loeschungen;
- Git-Push, insbesondere upstream, Force-Push, Tags, `reset --hard` und
  `clean -fdx`;
- finanzielle, vertragliche und sicherheitskritische Level-4-Ausfuehrungen;
- Paketinstallation, Admin-, Registry-, Firewall-, Dienst-, Task-Scheduler-,
  Credential-Manager-, UAC- oder Secure-Desktop-Automation;
- blinde Maus-/Tastaturautomation in fremden Anwendungen;
- externe Visionanbieter und Upload echter Screenshots;
- `full_access`, stiller CLI-/API-Key-/Responses-Fallback, Auto-Approval,
  `always allow` und remembered approval fuer Codex-Aktionen.

## Verbindliche Implementierungsentscheidung

Phase 5 fuehrt eine neue, zentrale Ausfuehrungsgrenze ein, ohne die
Phase-3-Risikoklassifikation zu duplizieren:

1. Jedes verfuegbare Tool erhaelt ein lokales versioniertes Manifest.
2. Registry und Executor validieren Namen, Eingabe, Capability, Lane, Risiko,
   Plattform, Roots, Netzwerk und Secrets vor jeder Ausfuehrung.
3. Nicht registrierte oder nicht lokal gemappte MCP-Tools bleiben deaktiviert.
4. Mutationen werden als Proposal und Action persistiert, korreliert,
   verifiziert und mit Artifact-/Undo-Verweisen abgeschlossen.
5. Engere Filesystem-, Git-, Browser- und Desktoptools ersetzen freie
   Shellumwege. Shell bleibt eine separat klassifizierte Ausnahme.
6. Browser und Desktop teilen die exklusive `interactive_lane`; Approval-
   Warten belegt die `model_lane` nicht.
7. Browser-Recovery ist auf genau einen Versuch begrenzt und wiederholt keine
   Aktion nach unklarer Wirkung.
8. Normale Tests verwenden nur Temp-Roots, temporaere Profile, Loopback-
   Seiten, Fake-Daten und eigene synthetische Prozesse.

Dieser Audit ist die Sicherheitsbaseline fuer alle folgenden Phase-5-Commits.
