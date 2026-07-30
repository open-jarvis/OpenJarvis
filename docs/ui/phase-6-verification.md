# Phase 6 – Verifikations- und Abschlussbericht

Stand: 30. Juli 2026

## Ergebnis

Die einheitliche Jarvis-Oberfläche, der kanonische Chat-/Task-Pfad, die
Sprachabstraktion, die sichere Approval-Interaktion, die System-Health-Anzeige
und der FastAPI-Lifespan sind implementiert. Die fokussierten Backend-,
Frontend-, Lifecycle- und Regressionsprüfungen sind grün.

Phase 6 erfüllt die Definition of Done trotzdem noch nicht vollständig:

1. Ein nativer Tauri/Rust-Build und Desktop-Laufzeitsmoke waren nicht möglich,
   weil `cargo`/Rust auf dem Testsystem nicht installiert beziehungsweise nicht
   im `PATH` verfügbar ist. Der Browser-Produktionsbuild und der
   Tauri-Webview-Asset-Build bestehen.
2. Der laut Auftrag höchstens einmal erlaubte Codex-Live-Smoke wurde genau
   einmal ausgeführt, scheiterte aber sicher am bewusst engen Turn-Limit mit
   `CodexPolicyError: turn token limit exceeded`. Es gab keinen Retry und keine
   externe Nebenwirkung.

Darum sollte Phase 7 noch nicht beginnen. Zuerst müssen ein nativer
Tauri-Build/Laufzeitsmoke und – nach neuer ausdrücklicher Freigabe – ein neuer
einmaliger Codex-Smoke mit angemessenem Turn-Limit erfolgreich sein.

## Sicherer Start und gesperrte Pfade

- Repository: `C:\Users\Playe\Documents\JARVIS\openjarvis-codex`
- Branch: `feature/codex-jarvis-orchestrator`
- Start-HEAD: `bac695e042f3bb2b7643e831845da6b2dad1ba60`
- Upstream Fetch: `https://github.com/open-jarvis/OpenJarvis.git`
- Upstream Push: `DISABLED`
- Das Phase-5-Bundle `openjarvis-phase5-bac695e0.bundle` wurde vor Änderungen
  mit SHA-256
  `D4CB0DCA443FE18B31BE88CD4CAF49874BE707995F39ABA665B3147CAE590292`
  validiert. Bundle-Historie und Restore-HEAD entsprachen dem erwarteten
  Start-HEAD.
- Das echte Obsidian-Vault und
  `C:\Users\Playe\Documents\Codex\2026-07-24\wei-nicht-ob-du-es-kennst\work\jarvis-desktop`
  wurden weder gelesen noch verändert. Die Prüfung beruht auf der strikt auf
  Repository, temporäre Testpfade und den freigegebenen Outputpfad begrenzten
  Befehls- und Testauswahl; für die gesperrten Pfade wurden absichtlich keine
  Hashes oder Verzeichniszugriffe erzeugt.
- Es wurden keine echten Browserprofile, Nutzerkonten, externen Dienste oder
  extern wirksamen Aktionen verwendet. Es erfolgte kein Push.
- `full_access`, API-Key-/Responses-API- und normaler CLI-Fallback sowie
  automatische oder dauerhafte Approvals wurden nicht eingeführt.

## Commits

1. `9c8e4aded7d272aa3bdc62ae928112fc42fa23a3` – docs: audit Jarvis UI voice and lifecycle
2. `513f6ffb26c72a03c8f25fdfd6820c9f6faf51bd` – feat: connect chat to canonical task runtime
3. `dc4b8db15b23d25ecc689c18da407ab38af837ea` – feat: add unified Jarvis workspace and navigation
4. `eec7078038a03e68a6f363ead3af7f18185db09e` – feat: add bounded local and browser speech providers
5. `a1ef1eeff0801e32f6adef6bab99f2c95af6dc90` – feat: unify system health and lifecycle shutdown
6. `2e8992c1b31af2377c883d146146f1f47e1a19fc` – feat: harden desktop controls and task close choices
7. `7efbedaae3938c97e7380eda346f0615933b36c9` – refactor: route exposed legacy tools through action service
8. `cfec8bca54653356ee765da8312e7d883e5d9d29` – feat: expose open tasks and browser recovery health
9. `7fcab5b156318411bdbe471abfd0583c0fe1ad8d` – fix: guard desktop close across every page

Der Audit wurde damit als erster Phase-6-Commit vor Produktionscodeänderungen
erstellt. Dieser Bericht wird als separater Abschlusscommit hinzugefügt.

## Audit und Informationsarchitektur

Der Vorab-Audit steht in `docs/ui/phase-6-ui-voice-audit.md`. Er erfasst das
bestehende React-/Tauri-Frontend, Navigation, API- und State-Pfade,
Approval-Altpfade, Speech-Fähigkeiten, direkte Toolaufrufe und die früheren
FastAPI-Shutdown-Hooks. Die Legacy-Inventur steht in
`docs/tools/phase-6-legacy-call-sites.md`.

Die bestehende Anwendung wurde erweitert, nicht dupliziert. Home/Jarvis, Chat,
Tasks, Approvals, Memory, Tools/Aktionen, Browserstatus, Agents/Systemstatus und
Einstellungen bleiben über dieselbe Navigation erreichbar. Die zentrale
Jarvis-Ansicht zeigt Session, aktiven Task, Schritt/Status/Outcome, Backend,
Sandbox, Risiko, Quellen, Aktionen, Verifikation, Artifacts, Approvals, Fehler
und Task-Steuerung. Der Leerzustand ist explizit.

## Kanonischer Chat-, Task- und Timeline-Pfad

`POST /v1/chat` erzeugt oder verwendet `session_id`, `task_id`,
`correlation_id`, `idempotency_key`, Codex-Thread und persistierte Timeline.
Text und Sprache senden über denselben API- und Task-Pfad. Retrieval-Belege
werden als nicht vertrauenswürdige Evidenz gekennzeichnet; große Ergebnisse
werden als Artifacts referenziert. Interne Chain-of-Thought-Inhalte werden
nicht dargestellt.

Die UI lädt persistierte Events zuerst und streamt anschließend ab
`after_sequence`. Der Client dedupliziert Events, authentifiziert die
Verbindung, meldet beim Komponentenabbau ab und verwendet einen begrenzten
Reconnect mit höchstens sechs Versuchen. Unsichere Mutationen werden nicht
automatisch wiederholt. Task, Quellen, Aktionen, Verifikation, Approvals und
Outcome liegen in einem kanonischen Store.

Pause, Resume, Cancel und Turn-Interrupt sind getrennte Operationen. Eine
fertige Textantwort überschreibt keinen offenen Approval-, Tool- oder
Verifikationszustand.

## Approval-UX

Die UI verwendet ausschließlich den persistenten Phase-3-/Phase-5-Pfad. Sie
zeigt Aktion, Tool, Ziel, redigierte Parameter, erwartete Wirkung, Risiko,
Sandbox/Root, Rückgängig-Machbarkeit, Verifikationsplan, Ablaufzeit und
Task-Kontext. Angeboten werden nur `Allow once` und `Deny`.

Idempotency und persistierte Entscheidung schützen gegen Doppelklick und
Reload. Timeout bedeutet Deny. Freitext, Modellinhalt, Website-Inhalt oder ein
gesprochenes „ja“ können keine Freigabe erzeugen. Ein Task kann zusätzlich
abgebrochen werden.

## Speech, Push-to-talk, TTS und Interrupt

Backend und Frontend definieren austauschbare `SpeechToTextProvider` und
`TextToSpeechProvider`. Ein reproduzierbar konfigurierter lokaler Provider hat
Vorrang; alternativ stehen Browser Web Speech oder ein deaktivierter Provider
zur Verfügung. Standard ist Deutsch, die Ausgabesprache ist einschließlich
Arabisch konfigurierbar.

Push-to-talk ist sichtbar, auf 60 Sekunden und 10 MiB begrenzt und prüft den
MIME-Typ. Media-Tracks werden gestoppt; Audio bleibt als temporärer
In-Memory-Blob und wird standardmäßig nicht gespeichert. Das Transkript ist vor
dem Senden editierbar. TTS kann separat gestartet und gestoppt werden.
Barge-in stoppt TTS, ohne automatisch den Task abzubrechen; Codex-Turn und
gesamter Task bleiben separat steuerbar.

Datenschutzhinweis: Browser Web Speech ist nur ein Fallback. Je nach Browser
kann dessen Implementierung Audio an den Browseranbieter übertragen und ist
nicht als vollständig lokaler Pfad garantiert. Die UI/Health-Anzeige macht den
Provider sichtbar; für strikt lokale Verarbeitung muss ein lokaler Provider
konfiguriert oder Speech deaktiviert werden.

## Accessibility und RTL

Die Phase-6-Komponenten besitzen Tastaturbedienung, sichtbaren Fokus,
Screenreader-Labels und ARIA-Live-Regionen. Status wird nicht nur über Farbe
vermittelt. Approval- und Desktop-Dialoge unterstützen Escape und
Fokusmanagement; die global wirksame Close-Guard-Komponente besitzt einen
Fokus-Trap. CSS deckt skalierbare Darstellung bis 200 %, Reduced Motion,
responsive Layouts und RTL/arabische Textdarstellung ab.

Die automatisierten Tests prüfen Struktur und Verhalten. Eine abschließende
manuelle Prüfung mit mehreren nativen Screenreadern und realen OS-/Browser-
Zoomkombinationen bleibt vor allgemeiner Verteilung empfehlenswert.

## Fehler-, Recovery- und System-Health-UX

Die Oberfläche unterscheidet nicht angemeldet, Backend/Server getrennt,
WebSocket getrennt, Browser-Recovery läuft/fehlgeschlagen, Memory oder Speech
degraded, Approval abgelaufen, pausiert, wartet auf Entscheidung, unklare
Nebenwirkung und sicher fortsetzbar. Fehler werden nicht als Erfolg oder leere
Antwort ausgegeben.

`GET /v1/system/health` liefert credential-sicher Version, Codex-Backend und
Anmeldestatus, SDK-Runtime, Server, Memory/FTS5, Task- und Trace-Store,
Tool-Registry, Browser einschließlich Ownership/Recovery-Grund,
Desktopadapter, STT/TTS, offene Tasks/Approvals und letzte Fehlerkategorie.
Tokens, `auth.json`, Cookies, API-Keys und rohe private Inhalte werden nicht
ausgegeben.

## Legacy-Call-Sites und zentrale Policy

Modell- oder nutzererreichbare verwaltete Agentenpfade erzeugen deterministisch
eine `ToolProposal` und laufen über `ToolActionService`, `CentralRiskPolicy`,
Approval und Verification. Ohne den Action Service schlagen sie geschlossen
fehl. Deep Research nutzt denselben Gateway. Direkte Agent-/Channel-Mutationen
werden im kanonischen Action-Modus blockiert; der Legacy Completion-Tool-Agent
verweist auf `/v1/chat`.

CLI-/Standalone-MCP-Kompatibilitätscode bleibt dokumentiert im Quellbaum, ist
aber aus Phase-6-UI und Tauri nicht erreichbar. Verbleibende direkte
`ToolExecutor`-/MCP-Zweige im Agent-Manager sind durch die kanonische
Konfiguration deaktiviert und als Residualkompatibilität klassifiziert.

## Lifespan und Desktop-Härtung

Alle vier früheren `@app.on_event("shutdown")`-Pfade wurden durch einen
FastAPI-Lifespan ersetzt. Startup stellt persistierte Zustände wieder her;
Shutdown räumt idempotent in umgekehrter Abhängigkeitsreihenfolge WebSockets,
eigene Browsersitzungen, MCP-Clients, Codex/Task/Trace, Vault/Memory und
Analytics auf. Partieller Startup-/Cleanup-Fehler wird getestet. Fremde
Prozesse werden nicht beendet.

Tauri enthält keine Shell-Plugin-Berechtigung und keine breite
`process:default`-Berechtigung. Erlaubt ist nur `process:allow-restart` neben
den nötigen Fenster-/Dialogrechten. Der alte beliebige
`run_jarvis_command(args)`-Pfad ist kein Tauri-Command/Handler und wird per
Compile-Konfiguration ausgeschlossen. Das Admin-Frontend kann nur den
definierten Backend-Start/-Stop aufrufen.

Der globale Desktop-Close-Guard gilt auf allen Seiten und bietet Hintergrund,
Pause, Abbruch oder Fenster behalten. Es wurde kein Installer erstellt.

## API-Änderungen

- `POST /v1/chat`
- `GET /v1/sessions`
- `GET /v1/sessions/{id}`
- `GET /v1/tasks/{id}/summary`
- `GET /v1/tasks/{id}/artifacts`
- `POST /v1/tasks/{id}/interrupt`
- `GET /v1/system/health`
- vorhandene Speech-Health-/Transkriptionspfade mit Provider- und
  Größen-/MIME-Schutz
- persistierter Task-Event-Stream mit Cursor, Authentifizierung und sauberem
  Unsubscribe

Es wurde keine zweite Task- oder Approval-API eingeführt.

## Abhängigkeiten und Laufzeitversionen

- Python 3.11.9
- `openai-codex` 0.144.4
- `openai-codex-cli-bin` 0.144.4
- FastAPI 0.129.0
- Uvicorn 0.41.0
- pytest 9.0.2
- Pydantic 2.12.5
- websockets 15.0.1
- HTTPX 0.28.1
- Node.js v24.13.1
- npm 11.8.0
- externes `codex-cli` 0.145.0

Die bestehende isolierte Python-Umgebung enthält kein aufrufbares `pip`-Modul;
Python-Paketversionen wurden daher read-only über `importlib.metadata`
ermittelt. `npm install` meldete 29 bekannte Abhängigkeitsbefunde (2 niedrig,
16 mittel, 11 hoch). Es wurde wie verlangt kein blindes `npm audit fix`
ausgeführt. Die Befunde sollten vor einer Verteilung separat triagiert werden.

## Test- und Build-Ergebnisse

### Fokussierte Phase-6- und Regressionsprüfungen

- Backend Speech: **14 bestanden**
- Frontend fokussiert und vollständiges Vitest: **16 bestanden**, 5 Dateien
- Managed-Legacy/API-Regression: **46 bestanden**
- serielle Action-/Phase-6-Nachprüfung: **82 bestanden**
- hermetische Phasenmatrix für Codex, Tasks, Memory, Tools, Browser, Desktop
  und neue Serverpfade: **1150 bestanden, 21 übersprungen**
- lokale UI-/Voice-/Server-Smokes: **18 bestanden**

Diese Prüfungen decken die 44 geforderten synthetischen Szenarien ab,
einschließlich kanonischem Chat, Mehrturn-Thread, Replay/Live-Deduplizierung,
Pause/Resume/Cancel, Approval exact once/deny/timeout, Evidence/Artifacts,
Speech/TTS/Barge-in, A11y/RTL, Reconnect/Idempotency, Health-Redaktion,
Lifespan-Cleanup, Legacy-Action-Gateway und Prozess-Orphan-Prüfungen.

### Frontend und Desktop

- `npm run build`: **bestanden**
- `npm run build:tauri`: **bestanden** für die Tauri-Webview-Assets
- nativer Rust/Cargo-Build: **nicht verfügbar**, da `cargo` fehlt

Der Produktionsbuild meldet nicht blockierende Hinweise zu gemischtem
Analytics-Import, leerem React-Chunk und einem ungefähr 901-KiB-JavaScript-
Chunk. Ein nativer Desktop-Start/Close-Smoke ist ohne Rust-Toolchain nicht als
bestanden zu werten.

### Breite Suite

Selektor:

```text
pytest tests --ignore=tests/evals/test_dataset_splits_integration.py -n auto -q --tb=no --disable-warnings -m "not live and not cloud and not hub and not live_external and not live_channel and not docker"
```

Ergebnis: **7429 bestanden, 46 übersprungen, 70 fehlgeschlagen, 10 Fehler, 2
Warnungen** in 179,28 Sekunden. Die Gesamtsuite ist ausdrücklich nicht grün.

Die bekannte native PyArrow-Abbruchdatei
`tests/evals/test_dataset_splits_integration.py` wurde als einzige Datei
isoliert. Die übrigen Fehlergruppen betreffen vor allem POSIX-
Berechtigungen/Prozesse unter Windows (`setsid`, `killpg`, Mode-Bits),
Windows-Pfad-/Temp-/SQLite-/FTS-Locks, Linux-RAPL, install-/background-abhängige
Tests, einen nicht vorhandenen optionalen Ollama-Embed-Endpunkt (`/api/embed`
404), POSIX-`echo`-Templates sowie Legacy-Fixture-/Registry-/xdist-Reihenfolge.

In der parallelen Suite gemeldete Phase-5-Action-Fehler wurden unmittelbar
seriell nachgeprüft: **82/82 bestanden**; auch die vorherige serielle
Phasenmatrix war grün. Sie sind daher als xdist-/Fixture-Kontamination
klassifiziert, nicht als reproduzierbarer Phase-6-Defekt.

## Smoke-Tests

Der lokale Fake-Smoke prüfte Serverstart, kanonischen Fake-Chat, Timeline,
Quellen, Aktion, Approval, Ergebnis, PWA/static UI, Reload-Persistenz,
Speech-Provider, editierbares Transkript, TTS-Stop, Desktop-Härtung und
kontrollierten Lifespan-Shutdown. Es blieben keine Audioartefakte und keine
eigenen Jarvis-, Browser- oder Desktop-Testprozesse zurück.

Der einzige Codex-Live-Versuch:

- `codex login status`: `Logged in using ChatGPT`
- Python Codex SDK, kein normaler CLI-/API-Key-/Responses-Fallback
- `read_only`, `deny_all`, temporäres leeres Workspace/State, keine Tools,
  keine externen Dienste
- exakt ein Turn
- Ergebnis: sicherer Abbruch mit
  `CodexPolicyError: turn token limit exceeded` bei Turn-Limit 2000
- Backend geschlossen und temporärer Root gelöscht; kein Retry

Damit ist der Live-Smoke nicht erfolgreich und DoD-Punkt 26 offen.

## Geänderte oder neue Dateien

Gegenüber dem Phase-5-Start-HEAD wurden einschließlich dieses Berichts 44
Dateien geändert oder angelegt (4485 Einfügungen, 252 Löschungen):

```text
docs/tools/phase-6-legacy-call-sites.md
docs/ui/phase-6-ui-voice-audit.md
docs/ui/phase-6-verification.md
frontend/package-lock.json
frontend/package.json
frontend/src-tauri/Cargo.lock
frontend/src-tauri/Cargo.toml
frontend/src-tauri/capabilities/default.json
frontend/src-tauri/src/lib.rs
frontend/src/App.tsx
frontend/src/components/Desktop/AdminPanel.tsx
frontend/src/components/Desktop/DesktopCloseGuard.tsx
frontend/src/components/Layout.tsx
frontend/src/components/Sidebar/Sidebar.tsx
frontend/src/hooks/useSpeech.ts
frontend/src/hooks/useTextToSpeech.ts
frontend/src/index.css
frontend/src/lib/api.ts
frontend/src/lib/jarvisStore.ts
frontend/src/lib/speechProviders.test.ts
frontend/src/lib/speechProviders.ts
frontend/src/lib/useCanonicalTaskStream.ts
frontend/src/pages/JarvisPage.test.tsx
frontend/src/pages/JarvisPage.tsx
frontend/tsconfig.tsbuildinfo
src/openjarvis/core/config.py
src/openjarvis/server/agent_manager_routes.py
src/openjarvis/server/api_routes.py
src/openjarvis/server/app.py
src/openjarvis/server/routes.py
src/openjarvis/server/system_health_routes.py
src/openjarvis/server/task_routes.py
src/openjarvis/server/ws_bridge.py
src/openjarvis/speech/__init__.py
src/openjarvis/speech/_discovery.py
src/openjarvis/speech/providers.py
tests/desktop/test_tauri_hardening.py
tests/server/test_legacy_action_gateway.py
tests/server/test_speech_routes.py
tests/server/test_system_health_routes.py
tests/server/test_task_routes.py
tests/speech/test_config.py
tests/speech/test_discovery.py
tests/speech/test_providers.py
```

Das externe Recovery-Bundle und dessen Bericht werden ausschließlich unter dem
freigegebenen Phase-6-Outputpfad erzeugt und nicht committed.

## Bekannte Einschränkungen und Phase-7-Gate

Vor Phase 7 sind erforderlich:

1. Rust/Cargo reproduzierbar installieren und `cargo check`/nativen Build sowie
   den Desktop-Start-, Health-, Bedien- und Close-Smoke bestehen lassen.
2. Für einen weiteren Codex-Live-Turn eine neue ausdrückliche Freigabe erteilen;
   der Phase-6-Rahmen „höchstens ein“ ist ausgeschöpft. Dann den identischen
   read-only/deny-all-Smoke mit ausreichend hohem oder keinem zusätzlichen
   lokalen Turn-Limit wiederholen.
3. Vor allgemeiner Verteilung die npm-Befunde und Bundle-Größe triagieren sowie
   manuelle Screenreader-/Zoom-/RTL-Prüfungen durchführen.

Bis diese beiden zwingenden Gates erfolgreich sind, lautet die klare
Empfehlung: **Phase 7 nicht beginnen.**
