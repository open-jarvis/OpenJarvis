# Phase 5: Tools, zentrale Policy, Browser-Recovery und Windows-Desktopautomation

## Ergebnis

Phase 5 fuehrt eine zentrale, schema-validierte Ausfuehrungsgrenze fuer von
Codex vorgeschlagene Aktionen ein. OpenJarvis besitzt Manifest, Capability,
Risiko, Lane, Approval, Ausfuehrung, Verifikation, Retry, Artifact und Audit.
Codex liefert im kontrollierten Pfad ausschliesslich strukturierte Parameter;
es kann keine Berechtigung erzeugen.

Der implementierte Zyklus ist:

```text
observe -> plan -> policy -> act -> verify -> observe/replan
```

Ein Handler-Ergebnis oder Exitcode 0 reicht nicht fuer Erfolg. Erst eine
separate Postcondition-Verifikation fuehrt ueber `verified` nach `completed`.

Die lokale Phase-5-Verifikation ist bestanden. Der breite Upstream-Testbestand
ist auf diesem Windows-Host weiterhin nicht vollstaendig gruen; die exakten
Ergebnisse und Ursachen stehen unter [Tests](#tests). Die Phase-5-Testgruppe
selbst besteht auch nach dem im Gesamtlauf ausgeloesten Registry-Reload.

## Sicherer Start und unveraenderte Schutzgrenzen

Vor der ersten Produktionscodeaenderung wurden folgende Werte verifiziert:

| Kontrolle | Ergebnis |
|---|---|
| Repository | `C:\Users\Playe\Documents\JARVIS\openjarvis-codex` |
| Branch | `feature/codex-jarvis-orchestrator` |
| Phase-4-HEAD | `5e0cbc563022aafac1b5e5847effd6bff099ecec` |
| Arbeitsbaum | sauber |
| Upstream Fetch | `https://github.com/open-jarvis/OpenJarvis.git` |
| Upstream Push | `DISABLED` |
| Phase-4-Bundle SHA-256 | `64EDBD68BF9FA6C64A936A00A1809E62A35B799AE5C2027E4879045CA8B17741` |
| Bundle/Restore | gueltig; 907/907 Commits; `git fsck --full --strict` bestanden; Restore-HEAD gleich Phase-4-HEAD |

Der vorgeschriebene Audit wurde vor Produktionscode als Commit `31a5d043`
gesichert: `docs/tools/phase-5-tools-security-audit.md`.

Das echte Obsidian-Vault, seine 46 Notizen und das alte `jarvis-desktop` wurden
in Phase 5 weder geoeffnet noch geaendert. Alle Dateitests nutzten
`TemporaryDirectory`, alle Browsertests eigene temporaere Profile und
Loopback-Seiten, alle Desktoptests einen selbst gestarteten synthetischen
Prozess. Es gab keine realen Konten, Cookies, externen Dienste, Nachrichten,
Formularsendungen, Kaeufe, Zahlungen, Administratoraktionen oder Upstream-
Pushes.

## Toolmanifest

`ToolManifest` ist ein eingefrorenes Pydantic-Modell mit `extra="forbid"`.
Jedes ueber `BaseTool` verfuegbare Tool besitzt ein lokales Manifest; Legacy-
Tools erhalten ein konservatives Manifest aus ihrem code-eigenen `ToolSpec`,
neue sicherheitskritische Tools definieren es explizit.

Pflichtfelder:

| Feldgruppe | Felder |
|---|---|
| Identitaet | `tool_id`, `name`, `version`, `description` |
| Vertrag | `input_schema`, `output_schema` |
| Autoritaet | `capability`, `risk_level`, `allowed_lanes`, `supported_platforms` |
| Laufzeit | `timeout`, `max_retries`, `idempotency_policy` |
| Wirkung | `side_effect_class`, `verification_strategy`, `undo_strategy` |
| Grenzen | `required_approval`, `allowed_roots`, `network_policy`, `secret_policy`, `log_redaction_policy` |
| Zustand | `enabled`, `degraded_reason` |

Eingabeschemas werden auf Objektform normalisiert und immer mit
`additionalProperties=false` ausgewertet. Unbekannte Tools, unbekannte
Parameter, fehlende Pflichtparameter, falsche Typen, nicht unterstuetzte
Plattformen und deaktivierte Level-4-Manifeste scheitern geschlossen.

Unterstuetzte Wirkklassen sind `none`, `local_read`,
`reversible_local_write`, `visible_preparation`, `external_write`,
`destructive`, `financial` und `security_critical`. Retry ist entweder
`safe_retry`, `key_required` oder `never_retry_after_unknown_effect`;
`max_retries` ist in Phase 5 hoechstens eins.

## Tool- und Capability-Matrix

| Tool/Familie | Capability | Level | Lane | Wirkung/Regel |
|---|---:|---:|---|---|
| `file.read`, `file.list`, `file.stat`, `file.search` | `file:read` | 0 | model | Nur erlaubte Roots; keine Mutation |
| `file.write`, `file.patch`, `file.copy`, `file.move`, `directory.create` | `file:write` | 1 | model | atomar/reversibel; Hash, Diff und Restore |
| `file.delete` | `file:write` | 3 | model | Quarantaene statt permanentem Delete; Allow once |
| `shell.exec` | `code:execute` | 3 | model | argv ohne Shell; enge Executable-/Argumentpolicy |
| `git.status`, `git.diff`, `git.log`, `git.branch`, `git.bundle.verify` | `file:read` | 0 | model | read-only |
| `git.worktree.create`, `git.commit`, `git.bundle.create` | `file:write` | 1 | model | nur eigener Task-Worktree/Task-Branch |
| `git.restore`, `git.worktree.remove` | `file:write` | 3 | model | Besitzpruefung und einzelne Freigabe im Action-Pfad |
| `browser.local.navigate` im Live-Smoke | eigene Manifest-Capability | 0 | interactive | nur expliziter Loopback-Port |
| `browser.local.prepare` im Live-Smoke | eigene Manifest-Capability | 2 | interactive | sichtbare Formularvorbereitung |
| `browser.local.submit` im Live-Smoke | eigene Manifest-Capability | 3 | interactive | exact-once `Allow once`, danach Verifikation |
| `WindowsDesktopSession`-Aktionen | adaptergebunden | 0-2 | interactive | nur eigener synthetischer Prozess, semantisch zuerst |

Die neue enge Registry enthaelt zehn Filesystemtools, ein strukturiertes
Shelltool und zehn Gittools. Browser- und Desktopaktionen werden ueber
sessiongebundene Adapter ausgefuehrt; die API verwaltet deren eigene Sessions.
Nicht lokal gemappte oder vom Modell erfundene Tools werden abgelehnt.

Der alte `ToolExecutor` bleibt als Kompatibilitaetsoberflaeche fuer native
OpenJarvis-Agenten bestehen, validiert jetzt aber jedes Tool und alle Argumente
gegen das Manifest. Codex-Proposals und API-Actions laufen ausschliesslich
ueber `ToolActionService`. Direkte Python-Aufrufe von `tool.execute()` gelten
weiterhin als interner, vertrauenswuerdiger Codepfad und duerfen nicht als
Autorisierungsweg fuer Codex exponiert werden.

## Zentrale Policy Level 0 bis 4

`CentralRiskPolicy` aus Phase 3 bleibt die einzige Risikoklassifikation:

| Level | Bedeutung | Phase-5-Ausfuehrung |
|---:|---|---|
| 0 | read-only | automatisch nach Schema-, Capability- und Auditpruefung |
| 1 | reversible lokale Workspace-Aenderung | nur isolierter Root/Worktree, Restore und Verifikation |
| 2 | sichtbare/externe Vorbereitung | Vorbereitung erlaubt; keine endgueltige Wirkung |
| 3 | destruktiv oder sensibel | einzelne konkrete `Allow once`-Entscheidung |
| 4 | finanziell oder sicherheitskritisch | immer verweigert; nur Simulation/Vorbereitung |

Der effektive Wert ist das Maximum aus Manifest, vertrauenswuerdigem
Taskkontext und Untrusted-Input-Befund. Modell-, Memory-, Website- oder
Tooltext kann Risiko erhoehen, aber nie senken. Capability-Grants und erlaubte
Roots kommen ausschliesslich aus dem OpenJarvis-Kontext. `full_access`,
Auto-Approval, `always allow` und remembered approvals werden nicht erzeugt.

## Proposal-, Action- und Auditmodell

`ToolProposal` erfasst Proposal-, Task-, Session-, Correlation-, Thread-,
Turn- und Item-Identitaet, Tool, strikt validierte Argumente, erwartetes
Ergebnis und Wirkung, Risiko, Capability, Ziel, Verifikations- und Undo-Plan,
Idempotency-Key, Timeout, Begruendung und die Quelle jedes Parameters.

OpenJarvis materialisiert daraus eine `ToolAction` und validiert erneut gegen
Manifest und kanonischen Task. `ActionStore` persistiert Proposal, Action,
Event und Artifact mit exact-once Idempotency. Zulaessige Uebergaenge sind
explizit; unbekannte oder terminale Uebergaenge scheitern geschlossen.

Der Ausfuehrungspfad lautet:

```text
proposed -> validated -> [waiting_approval] -> running
         -> verifying -> verified -> completed
```

Fehler fuehren zu `failed`, Ablehnung zu `denied`, Abbruch zu `canceled`.
Retry ist nur bei bekanntem Effekt, passender Manifestregel und hoechstens
einmal erlaubt. Nach unklarer Wirkung gibt es keinen automatischen Retry.

Alle geforderten Korrelationsfelder werden ueber Tool- und Task-Events
weitergereicht. Grosse Outputs werden ab 16 KiB redigiert, gehasht und als
Artifact ausserhalb der Timeline gespeichert. Die implementierten Events
umfassen `tool.proposed`, `tool.validated`, `tool.denied`,
`tool.waiting_approval`, `tool.started`, `tool.output`,
`tool.verification_started`, `tool.verified`, `tool.verification_failed`,
`tool.completed`, `tool.failed`, `tool.canceled` sowie Browser- und Desktop-
Health-/Recovery-/Focus-/Action-Ereignisse.

## Filesystem-Sicherheitsmodell

`SecurePathPolicy` loest Pfade kanonisch und vergleicht Windows-Pfade
case-insensitive. Blockiert werden `..`, Alternate Data Streams, Symlinks,
Junctions/Reparse Points, Root Escapes, sensible Dateien, Browserprofil- und
Systempfade. Es gelten Datei-/Outputlimits und enge Root-Allowlisten.

Writes verwenden eine temporaere Datei plus atomaren Replace. Ergebnis,
Before-/After-SHA-256, Diff und Restore-Artefakt werden verifiziert. Copy und
Move pruefen Quelle und Ziel separat. Delete verschiebt in eine Quarantaene
unter dem Restore-Root und ist Level 3; permanentes oder rekursives Loeschen
ausserhalb des Testroots ist nicht implementiert. Waerend eines Approvals
bleiben keine Dateihandles offen.

## Shell-Sicherheitsmodell

`shell.exec` akzeptiert `executable` und eine Argumentliste statt einer freien
Shellzeichenfolge. `subprocess.Popen` wird mit `shell=False`, explizitem `cwd`,
Environment-Allowlist, getrenntem stdout/stderr, Groessenlimits, Timeout und
einer eigenen Prozessgruppe gestartet. Der eigene Prozessbaum wird bei
Timeout beendet.

Pipes, Redirects, Subshells, Command-Substitution und interaktive
Passwortabfragen sind nicht Teil des Vertrags. ExecutionPolicy-, Registry-,
Benutzer-, Firewall-, Dienst-, Task-Scheduler-, Credential-, Paketinstall-,
Systemordner-, Disk-/Format-, Shutdown- und Neustartpfade werden blockiert.
Secrets werden in Argumenten, Environment und Ausgabe redigiert.

## Git-Worktree-Ablauf

`SecureGitService` verifiziert zuerst das Integrationsrepository und seine
Remotes. Mutationen sind nur in einem vom Service angelegten, markierten
Task-Worktree mit `task/`-Branch zulaessig. Der Integrationsarbeitsbaum muss
vor Erstellung sauber sein. Commit erfordert Diff und erfolgreiche Tests;
Restore ist eng, Bundle Create/Verify erzeugt Hash- und Ref-Nachweise.

`push`, Force-Push, Tag-Push, `reset --hard` und `clean -fdx` sind nicht als
ausfuehrbare Phase-5-Tools verfuegbar. Die Policy verweigert insbesondere
Push zu `upstream` dauerhaft.

## Browserarchitektur

Die neue Abstraktion besteht aus `BrowserSession`,
`BrowserProcessManager`, `BrowserControlHealth`, `CdpBrowserAdapter`,
`BrowserToolAdapter`, `BrowserActionVerifier`, `BrowserProfilePolicy`,
`BrowserRecoveryController` und `BrowserSessionService`.

Der Process Manager startet Microsoft Edge/Chromium nur mit einem vom Manager
erzeugten temporaeren Profil, einem reservierten Loopback-CDP-Port und einem
eindeutigen Sessionmarker. Er speichert PID, Startzeit, Profil, Port,
Health-Endpunkt, Heartbeat und sicheren Checkpoint. Besitz wird vor Stop/Cancel
erneut geprueft; fremde Browser werden nicht beendet. Beim Schliessen werden
nur der eigene Prozessbaum und das eigene temporaere Profil entfernt.

Der CDP-Adapter unterstuetzt Snapshot mit URL/Titel/DOM-Text/Ready-State,
Navigation, Reload, Elementpruefung, Click, Fill, Wertpruefung, Select, Scroll,
Page-Screenshot, Downloadroot, Uploadauswahl und Tabs oeffnen/schliessen.
Der Phase-5-Netzwerkvertrag erlaubt nur explizit freigegebene Loopback-Ports.

### Begrenzter Recovery-Automat

```text
process -> control service -> port owner -> connection probe
        -> genau ein reconnect
        -> optional genau ein kontrollierter control restart
        -> re-check -> resume am sicheren Checkpoint oder ehrlich fail
```

Der Standard ist `maximum_attempts=1`. Prozess-, Port-, Endpoint- und
Verbindungszustand werden vor und nach Recovery beobachtet. Bei unbekannter
Wirkung wird nicht wiederholt. Tests decken fehlenden Prozess/Service,
Portkonflikt und falschen Portbesitzer, Verbindungsabbruch, erfolgreichen und
fehlgeschlagenen Reconnect, kontrollierten Restart, Maximalversuch, keine
doppelten Browser und keinen falschen Erfolg ab.

Der reale lokale Edge-Smoke hat den zuvor bekannten BrowserOpenError-Pfad als
klassifizierbaren CDP-Verbindungszustand behandelt und nach absichtlichem
Verbindungsabbruch genau einmal erfolgreich reconnectet.

### Aktionsverifikation, Injection und Transfers

Navigation verifiziert exakte URL, Dokumentzustand und Titel. Click verlangt
eine beobachtbare Zustandsaenderung; Submit wird ohne Allow once verweigert.
Fill liest den Feldwert zurueck. Screenshots, Downloads und grosse Ergebnisse
werden gehasht als Artifacts gespeichert.

`WebInjectionGuard` behandelt Seitentext immer als Daten und erkennt unter
anderem Override-, Security-Bypass-, Secret-, Shell- und Approval-Forgery-
Muster, einschliesslich Unicode-Normalisierung und Base64-Decodierung. Ein
Befund erhoeht das Risiko auf mindestens Level 3 und blockiert Click, Fill und
Upload; er kann Manifest, Capability, Root oder Approval nie veraendern.

Downloads bleiben im isolierten Downloadroot, haben Groessenlimit, MIME/
Extension und SHA-256; Executables werden blockiert und nichts wird automatisch
geoeffnet oder ausgefuehrt. Uploads akzeptieren nur eine explizite Datei aus
einem erlaubten Root, pruefen Name, Groesse, Hash und sensible Pfade und werden
zunaechst nur ausgewaehlt. Das endgueltige Submit ist eine getrennte Level-3-
Aktion.

## Windows-Desktopautomation

`WindowsDesktopSession` startet ausschliesslich eine explizite Testdatei unter
einem erlaubten Root und bindet jede Aktion an den eigenen Prozess. Der
ctypes-basierte `Win32SemanticBackend` findet Fenster und klassische Child-
Controls semantisch ueber Prozess, Titel, Control-ID und Rolle. Er kann
Elementbaum lesen, Text setzen und zuruecklesen, Button klicken, Fokus
verifizieren, nur das eigene Fenster aufnehmen und geordnet schliessen.

Koordinaten sind ein expliziter Fallback. Er verlangt unveraendertes Fenster,
Prozessbesitz, Fokus, Monitor/Rechteck, Aufloesung, DPI/Skalierung,
Vorher-Screenshot, Zielbereich, Interrupt und Nachher-Verifikation. UAC,
Secure Desktop, Administrator- oder fremde Anwendungsautomation ist nicht
implementiert und wird nicht bestaetigt.

Browser und Desktop teilen die exklusive `interactive_lane`. Die
`model_lane` bleibt frei, waehrend eine Action auf Approval wartet. Pause,
Resume und Cancel pruefen Besitz und Zustand erneut und stoppen nur eigene
Testprozesse.

Screenshots sind fenster-/seitenbegrenzt, temporaer, gehasht und taskbezogen.
Es gibt keinen externen Vision-Provider und keinen Upload echter Screenshots.

## Lokale API

Die bestehende FastAPI-Anwendung erhielt keine zweite App. Implementiert sind:

```text
GET    /v1/tools
GET    /v1/tools/{tool_id}
GET    /v1/tools/health
GET    /v1/browser/health
GET    /v1/browser/sessions
GET    /v1/tasks/{task_id}/actions
GET    /v1/actions/{action_id}
GET    /v1/actions/{action_id}/artifacts
POST   /v1/tasks/{task_id}/actions
POST   /v1/actions/{action_id}/approve
POST   /v1/actions/{action_id}/deny
POST   /v1/actions/{action_id}/cancel
POST   /v1/actions/{action_id}/retry
POST   /v1/browser/sessions
POST   /v1/browser/sessions/{session_id}/recover
DELETE /v1/browser/sessions/{session_id}
```

Mutationen verwenden die bestehende Loopback-/Auth-Grenze und verlangen
Task-, Correlation- und Idempotency-Identitaet. Proposal, Capability, Risiko,
Approval und Retry werden serverseitig erneut validiert. API-Tests pruefen
exact-once Idempotency und `Allow once`.

## Bestehende UI

`CodexTasksPanel` zeigt jetzt registrierte Manifeste, Health, aktive Actions,
Tool, Ziel, Parameterzusammenfassung, Capability, Risk Level, Root/Sandbox,
erwartete Wirkung, Status, Verification, Fehler, Artifacts, Diff/Undo sowie
Browser-PID, Control-Port und Recovery. Der Approvaldialog bietet nur
`Allow once` und `Deny`; es gibt kein `always allow`.

## Tests

### Fokussierte Phase-5-Suite

Nach einem absichtlich vorangestellten Legacy-Registry-Reload wurden alle
geaenderten Phase-5-Testdateien in demselben Python-Prozess ausgefuehrt:

```text
109 passed, 1 skipped in 35.46s
```

Der Skip ist eine plattform-/fixturebedingte Windows-Variante. Zuvor bestand
die engere Gruppe mit `97 passed, 1 skipped`. Ruff fuer alle geaenderten
Python-Dateien und `git diff --check` bestanden.

Die 52 geforderten Sicherheitsfaelle sind durch die fokussierte Suite und die
Smokes abgedeckt: Manifest/Unknown Tool/Unknown Parameter, Risk-/Capability-
Non-Escalation, Root/Symlink/Junction/ADS, atomare Writes/Quarantaene/Restore,
no-shell/Redaction/Timeout/Prozessbaum, Worktree/Push-Blockaden, Browserprofil/
Health/Aktionen/Transfers/Injection/Recovery, exact-once Approval/Timeout/
Retry, Desktop/Koordinaten/Artifacts/Lanes, API/UI, Server und die gesperrten
realen Datenquellen.

### Frontend

```text
Vitest: 10 passed
TypeScript/Vite production build: passed
```

Es bleiben nur die bestehenden Vite-Warnungen zu grossem Chunk und gemischtem
statischem/dynamischem Import. Die generierte `tsconfig.tsbuildinfo` wurde auf
den committed Zustand zurueckgesetzt.

### Gesamtsuite

Der erste echte serielle Volltest lief bis 42 Prozent und brach nach 508,6 s
in einer bestehenden Eval-Dataset-Integration nativ ab:

```text
tests/evals/test_dataset_splits_integration.py::
test_train_and_test_are_disjoint_per_provider
Fatal Python error: Aborted
datasets.arrow_dataset.to_list / pyarrow
```

Da ein nativer Abort kein JUnit-Endergebnis schreibt, wurde genau diese eine
Crash-Datei fuer einen Klassifikationslauf ausgeschlossen. Telemetrie und
externe Datasetzugriffe waren deaktiviert. Dieser Lauf schrieb vollstaendiges
JUnit nach 1.078,712 s:

```text
7,571 tests
7,408 passed
56 skipped
97 failed
10 errors
```

Der pytest-Prozess hing danach im globalen Teardown und wurde nach Verifikation
der exakten, von diesem Lauf gestarteten PIDs beendet. Die Problemgruppen sind
bereits bekannte Upstream-/Hostabhaengigkeiten: POSIX `setsid`/`killpg` und
Mode-Bits auf Windows, Windows-Dateisperren bei SQLite/FTS, Linux-RAPL-Pfade,
fehlende optionale Ollama-/Gemma-/Connector-/Node-Konfiguration, Telemetrie-
Timing sowie Windows-Pfad-/TOML-Fixtures und weitere unabhaengige Upstream-
Contracttests.

Der Klassifikationslauf entdeckte zusaetzlich 21 Reihenfolgefehler in neuen
Phase-5-Tests: `test_tool_registration` lud auch zustandsbehaftete Manifest-,
Enum- und Exception-Module neu. Commit `0a28c983` begrenzt den Reload auf die
tatsaechlich getesteten Legacy-Registrierungsmodule. Der danach ausgefuehrte
Einprozess-Reproduktionstest (`Registry-Reload` zuerst, dann alle Phase-5-
Dateien) bestand mit `109 passed, 1 skipped`. Es wurde kein dritter 20-Minuten-
Volltest gestartet. Im JUnit-Lauf gab es keine Phase-1-bis-4-Codex-, Task- oder
Vault-Memory-Regression.

### Server-Smoke

Der reale FastAPI-Lebenszyklus ueber `TestClient` startete die Anwendung,
beantwortete `/health` mit 200 und schloss anschliessend die eigene
Task-Runtime sowie den Trace-Store:

```text
1 passed in 1.67s
```

Es bestehen zwei FastAPI-Deprecation-Warnungen fuer `on_event("shutdown")`;
die Funktion ist korrekt, soll aber in Phase 6 auf Lifespan migriert werden.

## Lokale End-Smokes

### Filesystem/Git

```text
status: passed
task commit: 1bb2398675de7e42a133a83309f02e97d0687858
before SHA-256: bcda334e568b98ddac90facdf5bd52a5f1cb5771cdf55f4087a43841e3658310
after SHA-256:  e8bf220aaef126f93ff4d416990fc22b290660ba7613386c9d5371b795f59d29
restore SHA-256: c4a16de54a510773d84e384d26e9c62b83f3a16640dc4bb2e3f99028a23eabdd
bundle SHA-256:  e78225f0dc658bc10395a8d57b6863a013643e5cddc48fcf0a6dca11a5d358f8
test exit code: 0
worktree removed: true
push attempted: false
upstream push: DISABLED
```

### Browser

Microsoft Edge `150.0.4078.105` bestand Navigation, Fill, Select, Click,
Upload-Vorbereitung, Download, Screenshot, Submit-Blockade und lokales Submit
nach Allow once. Das Profil war temporaer und `external_network_used=false`.

```text
download SHA-256:   16cd94271807647fa3620703a15688d643a33b58e5c1f72b03e5390bbaa76dde
screenshot SHA-256: 1d4151569e927cc37daf1f66a4226db3c102a9c3ac862afc6cf2917fc7bb9027
recovery attempt: 1/1
cause: synthetic_control_interruption
result: reconnected
checkpoint: after.click.verified
```

### Desktop

Die synthetische Win32-Anwendung bestand Prozessbesitz, semantische
Fenster-/Elementsuche, Text-Write/Readback, Button-Click, Zustandspruefung,
fensterbegrenzten Screenshot und geordnetes Schliessen.

```text
owned_process: true
semantic_text_verified: true
semantic_click_verified: true
screenshot SHA-256: f2431d6e98df92ddb772a0df524457127eb0614b8990f2878da20810d75ee2ad
```

## Einziger kontrollierter Codex-Live-Smoke

Es wurde genau ein Python-Codex-SDK-Turn ausgefuehrt und nicht wiederholt:

| Kontrolle | Ergebnis |
|---|---|
| Anmeldung | ChatGPT (`codex login status`) |
| SDK | `openai-codex 0.144.4` |
| Codex-Turns | exakt 1 |
| Sandbox | `read_only` |
| Approval-Mode im Codex-Turn | `deny_all` |
| Workspace | temporaer und unveraendert |
| Browserprofil | temporaer |
| Netz | nur Loopback; keine externe Verbindung |
| CLI/API-Key/Responses-Fallback | nicht verwendet |
| `full_access` | nicht verwendet |
| Codex Tool-Items | keine |

Codex lieferte nur das verlangte Schema mit Loopback-URL, `#name`,
`Fake Codex User` und `#submit`. OpenJarvis erzeugte daraus Level 0 Navigation,
Level 2 Vorbereitung und Level 3 Submit. Navigation und Vorbereitung wurden
verifiziert; Submit blieb persistent auf Approval stehen, wurde vom lokalen
Testbroker exakt einmal erlaubt und danach verifiziert abgeschlossen. Alle
drei Actions endeten `completed` mit Verification `passed` und vollstaendiger
Task-Timeline.

## Windows-Verifikation und Umgebung

| Komponente | Version/Ergebnis |
|---|---|
| Windows | NT `10.0.26200.0` |
| Python | `3.11.9` |
| Codex CLI | `0.145.0`; Login: ChatGPT |
| Python Codex SDK | `openai-codex 0.144.4`, CLI-Bin-Paket `0.144.4` |
| FastAPI / Pydantic | `0.129.0` / `2.12.5` |
| pytest / pytest-asyncio | `9.0.2` / `1.3.0` |
| Uvicorn / HTTPX | `0.41.0` / `0.28.1` |
| Ruff | `0.15.1` |
| Node / npm | `24.13.1` / `11.8.0` |
| Microsoft Edge | `150.0.4078.105` |

Explizit getestet wurden case-insensitive Pfade, ADS, Junction/Reparse Point,
gesperrte Datei, eigener Prozessbaum, Browser-Child-Prozesse, Portbesitz,
Fokusverlust, DPI-/Skalierungsmetadaten, Monitor-/Fensterkontext und
Interrupt. Secure Desktop/UAC und Administratorautomation bleiben technisch
ausgeschlossen; ein UAC-Dialog wird niemals automatisch bestaetigt.

## Commits

Ausgehend von Phase-4-HEAD `5e0cbc56`:

```text
31a5d043 docs: audit OpenJarvis tools browser and desktop security
2108d3b2 feat: add versioned tool manifests and registry validation
48af72f1 feat: centralize tool risk and capability policy
3fd92527 feat: add structured tool proposals and execution records
848b8e4c feat: harden root-confined filesystem tools
a4bbd5b3 feat: add structured no-shell process execution
91bf6928 feat: add isolated Git worktree tool flow
3e891178 feat: add bounded browser process recovery
d642e940 feat: verify browser actions and isolate transfers
f1f12930 feat: add semantic Windows desktop automation
7a3b394f feat: integrate tool actions with task traces
8bf7aa39 feat: expose tool browser and action API
1c6fe715 feat: show tool actions browser health and approvals
f1711071 test: add isolated Phase 5 local smokes
be51aa15 test: verify one Codex planned local browser action
0a28c983 test: isolate stateful tool modules from registry reloads
```

Der Implementierungs-HEAD vor diesem Dokumentationscommit ist
`0a28c9832af046f34a900bf3e0cb2d515df9b14e`. Der exakte finale HEAD und das
von ihm erzeugte Recovery-Bundle stehen im externen Handoff-Bericht, weil ein
Git-Commit seinen eigenen Hash und den SHA-256 eines erst danach erzeugbaren
Bundles nicht in sich selbst enthalten kann.

## Veraenderte Dateien

Vor diesem Bericht umfasste Phase 5 48 Dateien; dieser Bericht ist Datei 49.

```text
docs/tools/phase-5-tools-security-audit.md
docs/tools/phase-5-tools.md
frontend/src/components/CodexTasksPanel.test.tsx
frontend/src/components/CodexTasksPanel.tsx
frontend/src/lib/api.ts
scripts/phase5_codex_smoke.py
scripts/phase5_local_smoke.py
src/openjarvis/browser/__init__.py
src/openjarvis/browser/actions.py
src/openjarvis/browser/cdp.py
src/openjarvis/browser/models.py
src/openjarvis/browser/process.py
src/openjarvis/browser/recovery.py
src/openjarvis/browser/service.py
src/openjarvis/desktop/__init__.py
src/openjarvis/desktop/models.py
src/openjarvis/desktop/session.py
src/openjarvis/desktop/win32.py
src/openjarvis/server/api_routes.py
src/openjarvis/server/app.py
src/openjarvis/server/tool_browser_routes.py
src/openjarvis/tasks/policy.py
src/openjarvis/tools/__init__.py
src/openjarvis/tools/_stubs.py
src/openjarvis/tools/action_service.py
src/openjarvis/tools/action_store.py
src/openjarvis/tools/actions.py
src/openjarvis/tools/git_secure.py
src/openjarvis/tools/manifest.py
src/openjarvis/tools/safe_filesystem.py
src/openjarvis/tools/safe_shell.py
tests/browser/__init__.py
tests/browser/test_actions.py
tests/browser/test_process.py
tests/browser/test_recovery.py
tests/desktop/__init__.py
tests/desktop/test_session.py
tests/fixtures/phase5_desktop_app.py
tests/server/test_tool_browser_routes.py
tests/tasks/test_tool_policy_phase5.py
tests/tools/test_action_service.py
tests/tools/test_actions.py
tests/tools/test_git_secure.py
tests/tools/test_manifest.py
tests/tools/test_safe_filesystem.py
tests/tools/test_safe_shell.py
tests/tools/test_stubs.py
tests/tools/test_tool_registration.py
tests/tools/test_tool_timeout.py
```

Keine temporaeren Profile, Screenshots, Testdatenbanken, JUnit-Dateien,
Recovery-Bundles, Vault-Inhalte oder Secrets sind im Repository enthalten.

## Bekannte Einschraenkungen

- Phase 5 ist keine Freigabe fuer unbeaufsichtigte produktive PC-Kontrolle.
- Browserzugriff ist fuer die neue sichere Schicht auf temporaere Profile und
  explizite Loopback-Ports begrenzt. Echte Konten/Profile bleiben gesperrt.
- Der reale Recovery-Smoke verifiziert Reconnect; ein separater Control-
  Service-Restart ist mit Fakes getestet, aber nicht als fremder Dienst
  gestartet.
- Der Win32-Adapter ist fuer eigene synthetische klassische Controls
  verifiziert. Fremde Apps, Secure Desktop, UAC, Adminaktionen und blinde
  Automation sind nicht freigegeben.
- Mehrmonitor- und DPI-Invarianten sind modelliert und synthetisch getestet,
  nicht auf jeder physischen Monitortopologie dieses Hosts ausgefuehrt.
- Externe Vision, echte Nachrichten/Formulare, Installationen, Deletes echter
  Daten, Push/Merge und Level 4 bleiben deaktiviert.
- Direkte interne Python-`execute()`-Aufrufe sind eine Legacy-
  Kompatibilitaetsflaeche. Codex und die neue Action-API exponieren sie nicht;
  Phase 6 soll verbleibende native Call-Sites inventarisieren und schrittweise
  auf `ToolActionService` zwingen.
- Die breite Upstream-Suite hat die dokumentierten Windows-/Dienst-/Fixture-
  Fehler und einen nativen PyArrow-Abbruch. Phase-5-Tests selbst sind gruen.
- FastAPI-Shutdown verwendet noch den deprecated `on_event`-Hook.

## Recovery und Phase-6-Empfehlung

Nach dem Dokumentationscommit wird ein Git-Bundle ausserhalb des Repositorys
erzeugt, mit `git bundle verify` geprueft und in ein neues Verzeichnis
wiederhergestellt. Der externe Handoff nennt Bundlepfad, SHA-256, Refanzahl,
Restore-HEAD und `git fsck`-Ergebnis.

**Phase 6 kann sicher als weitere isolierte, testorientierte Phase beginnen.**
Die Freigabe gilt nur unter denselben Grenzen: temporaere Roots/Profile,
Loopback, synthetische Prozesse, ChatGPT-Anmeldung, kein `full_access`, kein
API-Key-/Responses-Fallback, keine realen externen Wirkungen, kein echtes
Vault und kein Zugriff auf `jarvis-desktop`. Vor produktiver Automation sind
die Legacy-Call-Site-Migration, Lifespan-Umstellung, physische Multi-Monitor-
Validierung und eine separate Freigabe fuer reale Ziele erforderlich.
