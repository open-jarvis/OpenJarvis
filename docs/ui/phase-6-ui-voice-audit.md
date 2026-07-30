# Phase 6: UI-, Voice- und Lifecycle-Audit

Stand: 2026-07-30

Audit-Basis: `bac695e042f3bb2b7643e831845da6b2dad1ba60`

Branch: `feature/codex-jarvis-orchestrator`

## Zweck und Sicherheitsgrenze

Dieser Bericht dokumentiert den Iststand vor jeder Phase-6-Aenderung am
Produktionscode. Geprueft wurden ausschliesslich das neue
`openjarvis-codex`-Repository und synthetisch erreichbare Komponenten. Das
alte `jarvis-desktop`, das echte Obsidian-Vault, echte Browserprofile,
Nutzerkonten und externe Dienste wurden nicht geoeffnet oder verwendet.

Die Phase-3-/Phase-5-Schicht ist bereits die richtige kanonische Basis:
`TaskService`, `CodexTaskOrchestrator`, persistierte `TaskEvent`s,
`ApprovalBroker`, `ToolActionService`, `CentralRiskPolicy`, Artefakte und die
Browser-Session-Verwaltung. Die vorhandene Haupt-Chatoberflaeche ist damit
jedoch noch nicht verbunden.

## Kurzfazit

- Die Anwendung besitzt eine einzelne React-/Tauri-Oberflaeche, aber noch
  keinen einheitlichen Jarvis-Workspace. Tasks, Approvals, Memory, Browser-
  und Toolstatus sind auf verschiedene Flaechen und lokale Caches verteilt.
- Der normale Chat laeuft ueber `/v1/chat/completions` beziehungsweise
  `/api/research`, nicht ueber den kanonischen Task-Orchestrator. Browser-
  `localStorage` ist dort die Gespraechswahrheit.
- Die kanonische Task-API kann bereits Tasks erstellen, pausieren,
  fortsetzen, abbrechen, Quellen und Usage liefern. Die Task-WebSocket-Route
  kann Replay ab `after_sequence`, Authentifizierung und serverseitige
  Deduplizierung. Das Frontend nutzt diese Faehigkeiten noch nicht.
- Die Approval Bell vereinigt den proaktiven Legacy-Store und den
  persistenten Task-Approval-Store in einer Liste. Phase-3-Approvals werden
  korrekt mit Correlation- und Idempotency-Headern entschieden; Legacy-
  Approvals bleiben ein zweiter, schwach abgesicherter Pfad.
- Push-to-talk existiert als `MediaRecorder`-Upload zum Server. Ein
  editierbares Transkript ist vorhanden, aber Browser-STT, allgemeines TTS,
  Barge-in, Provider-Capabilities, Aufnahme-Timeout und Unmount-Cleanup fehlen.
- Vier FastAPI-Shutdown-Hooks verwenden noch `on_event("shutdown")`.
- Die Tauri-Shell hat eine CSP, besitzt aber unnoetig breite Shell-/Process-
  Rechte und exponiert `run_jarvis_command(args)` mit frei waehlbaren Jarvis-
  CLI-Argumenten an das Frontend.

## Gepruefte Flaechen

### React und Routing

`frontend/src/App.tsx` definiert derzeit diese Routen:

| Route | Seite | Heutige Aufgabe |
| --- | --- | --- |
| `/` | `ChatPage` | Legacy-Chat mit `ChatArea` und `SystemPanel` |
| `/dashboard` | `DashboardPage` | Metriken und Uebersichten |
| `/data-sources` | `DataSourcesPage` | Datenquellen/Connectoren |
| `/memory` | `MemoryPage` | Memory und `MemoryVaultPanel` |
| `/agents` | `AgentsPage` | Agenten; `CodexTasksPanel` ist hier eingebettet |
| `/logs` | `LogsPage` | Logs |
| `/settings` | `SettingsPage` | Anwendungseinstellungen |
| `/get-started` | `GetStartedPage` | Einrichtung |

`Sidebar`, `Layout`, `SystemPulse`, `ApprovalBell` und `CommandPalette`
bilden den globalen Rahmen. Eigene, klar benannte Einstiege fuer Tasks,
Approvals, Tools/Aktionen und Browserstatus fehlen. Dieselben Informationen
werden teilweise im Agentenbereich, Systempanel, Pulse und Approval-Dropdown
angeboten.

### State Management

`frontend/src/lib/store.ts` verwendet Zustand, ist aber noch kein
kanonischer Phase-6-State. Gespraeche und Nachrichten werden als
`openjarvis-conversations` in `localStorage` gespeichert. Komponenten wie
`CodexTasksPanel`, `ApprovalBell`, Memory- und Health-Panels besitzen jeweils
eigene Polling-Zustaende und Caches. Es gibt keinen gemeinsamen State fuer
aktive Session, aktiven Task, Timeline, Quellen, Approvals, Toolaktionen,
Browser-, Memory-, Speech- und System-Health.

### Chat, API und Events

`InputArea` verwendet `streamChat()` gegen `/v1/chat/completions` oder
`streamResearch()` gegen `/api/research`. Lokale UI-Nachrichten-IDs sind
nicht mit `session_id`, `task_id`, `correlation_id`, `idempotency_key`,
Codex-Thread oder persistierter Timeline verbunden. Der Stop-Knopf bricht nur
den Browser-Fetch ab; er pausiert oder unterbricht keinen kanonischen Turn und
bricht keinen Task ab. Tool-SSE-Events stammen aus dem alten `ToolExecutor`-
Pfad. Eine fertige Textantwort kann deshalb als abgeschlossen erscheinen,
ohne dass offene Approvals, Verifikation oder unklare Nebenwirkungen geprueft
werden.

`CodexTasksPanel` liest dagegen `/v1/tasks`, Timeline, Usage und Actions. Es
pollt in festen Intervallen und zeigt technische Eventtypen. Persistiertes
Replay plus Live-Stream, Event-Deduplizierung im Frontend, verstaendliche
Labels, Quellen, Recovery und vollstaendige Action-/Verification-Darstellung
fehlen.

`useAgentEvents` verbindet `/v1/agents/events` mit exponentieller Wartezeit,
aber unbegrenzten Versuchen. Der Hook fuehrt keinen Sequenzcursor und keine
Task-Timeline-Deduplizierung. Er ist fuer Agentenereignisse gebaut, nicht fuer
die kanonische Taskansicht. Die Backend-Route `/v1/tasks/events` unterstuetzt
bereits API-Key-Authentifizierung, `task_id`, `after_sequence`, Replay und
serverseitige Deduplizierung; diese Route ist im Frontend unbenutzt.

API-Fehler werden in verschiedenen Helfern unterschiedlich behandelt.
Timeouts sind nicht ueberall vorhanden. Sicherheitsrelevante Phase-3/5-
Mutationen senden Correlation- und Idempotency-Header und werden nicht
automatisch wiederholt; der restliche Client besitzt noch kein gemeinsames
normalisiertes Fehlerobjekt oder Abort-/Timeout-Modell.

### Speech

Vorhanden sind:

- `useSpeech`: `getUserMedia` + `MediaRecorder`, temporaerer Blob im Speicher,
  Upload an `/v1/speech/transcribe`, anschliessendes Freigeben der Tracks;
- `MicButton`: Start/Stop fuer die Aufnahme;
- editierbares Transkript im normalen Chat-Eingabefeld;
- `AudioPlayer` fuer bereits an einzelne Nachrichten angehaengte Audiodateien;
- serverseitiges STT-ABC `SpeechBackend` und `TranscriptionResult`;
- lokale STT-Implementierung `FasterWhisperBackend`;
- Cloud-STT `OpenAIWhisperBackend` und `DeepgramSpeechBackend`;
- separates TTS-ABC `TTSBackend` mit lokalem Kokoro sowie OpenAI- und
  Cartesia-Cloud-Backends.

Es fehlen die geforderten, einheitlich benannten Providergrenzen
`SpeechToTextProvider` und `TextToSpeechProvider`, ein deaktivierter Provider,
Browser-Web-Speech-Fallback, allgemeines Antwort-TTS, Stop/Barge-in,
Sprachwahl, Permission-/Capability-State, begrenzte Aufnahmedauer sowie
Cleanup einer noch laufenden Aufnahme beim Unmount. Die Audio-Chunks werden
standardmaessig nicht persistiert, aber der Server liest den gesamten Upload
ohne explizite Groessen-/MIME-Grenze in den Speicher. Der bestehende
`auto`-Discovery-Pfad kann nach lokalem Faster-Whisper still OpenAI oder
Deepgram waehlen, falls Umgebungs-Keys vorhanden sind. Das ist kein sicherer
Phase-6-Standard.

### Accessibility und Darstellung

Einzelne Base-UI-Komponenten besitzen Fokus-Stile; eine durchgaengige
Tastatur-/Screenreader-Strategie fehlt. Im Anwendungscode wurde keine
`aria-live`-Region gefunden. `MicButton` und mehrere Icon-Buttons haben keine
ausreichenden zugreifbaren Namen/Zustaende. Die Approval Bell schliesst per
Mausklick ausserhalb, aber nicht explizit per Escape und besitzt weder
Dialogsemantik noch definiertes Fokusmanagement. Status wird an mehreren
Stellen ueberwiegend durch Farbe vermittelt. Reduced Motion deckt nur einen
Teil der Animationen ab. Explizite RTL-Regeln fehlen. Das feste
`overflow:hidden` am Root und starre Desktop-Mindestgroessen sind Risiken fuer
125 bis 200 Prozent Zoom und schmale Ansichten.

### Tauri/Desktop

Positiv sind feste Loopback-Backend-Adressen und eine vorhandene CSP. Die CSP
erlaubt jedoch Inline-Skripte/-Styles. `capabilities/default.json` gewaehrt
globale `process:default`- sowie `shell:allow-execute`, `allow-spawn`,
`allow-stdin-write`, `allow-kill` und `allow-open`-Rechte zusaetzlich zu einer
Sidecar-Ausnahme. `run_jarvis_command(args: Vec<String>)` nimmt beliebige
Jarvis-Unterbefehle/Argumente entgegen und liegt im Tauri-Invoke-Handler.
Damit ist die Desktop-Grenze breiter als fuer den Phase-6-Workspace noetig.

Die Shell startet den Backendprozess automatisch. Beim App-Exit wird
`stop_all()` nur asynchron gestartet; der Exit wartet nicht nachweisbar auf
das Ende. Fensterschliessen bietet noch keine explizite Auswahl zwischen
Weiterarbeiten, Pause und Abbruch aktiver Tasks. Die Bundle-Konfiguration ist
aktiv und besitzt einen Updater-Endpunkt, aber Windows-Signierung ist nicht
konfiguriert. Ein allgemein verteilter Installer ist daher nicht Teil von
Phase 6.

### FastAPI-Lifecycle

`src/openjarvis/server/app.py` verwendet vier veraltete Shutdown-Decorator-
Pfade:

1. Task Runtime/Codex-Orchestrator, Task Store und Trace Store;
2. Analytics EventBridge und Client;
3. Memory Service;
4. Vault Memory Service.

Browser-Sessions, Desktop-Testprozesse und WebSocket-Clients sind darin nicht
als gemeinsame, geordnete Lifespan-Ressourcen modelliert. Die mehrfachen
bedingten Hooks erschweren umgekehrte Shutdown-Reihenfolge, idempotentes
Schliessen und Cleanup bei partiellem Startup-Fehler.

## Antworten auf die zehn Pflichtfragen

### 1. Welche Seiten und Komponenten existieren bereits?

Vorhanden sind Chat, Dashboard, Data Sources, Memory, Agents, Logs,
Settings und Get Started. Global existieren Sidebar/Layout, SystemPulse,
SystemPanel, ApprovalBell und CommandPalette. Fachlich relevant sind
ChatArea/InputArea/MessageBubble, CodexTasksPanel, MemoryVaultPanel,
useAgentEvents, useSpeech, MicButton und AudioPlayer. Tauri stellt Setup,
Backendstart/-stop, Health, Speech-Proxy und Tray bereit.

### 2. Welche Informationen werden mehrfach oder widerspruechlich dargestellt?

- Backend-/Systemstatus erscheint in SystemPulse, SystemPanel, Setup,
  Agenten-/Taskpanel und Tauri-Health mit unterschiedlichen Datenquellen.
- Task- und Agentenaktivitaet wird in Agenten-Events, lokalen Chat-SSE-Events
  und kanonischen TaskEvents getrennt dargestellt.
- Approvals erscheinen sowohl als proaktive Legacy-Actions als auch als
  Task-/Tool-Actions; die Bell mischt beide, waehrend das CodexTasksPanel
  zusaetzlich Actions anbietet.
- Memory hat generische Memory-Ansichten, Vault-Ansicht und Chatkontext ohne
  gemeinsame Quellenprojektion.
- Chatabschluss und Task-Outcomes koennen widersprechen, weil der Legacy-Chat
  nicht auf den Taskstatus wartet.

### 3. Welche UI liest nicht aus dem kanonischen Task-/Event-System?

Die Haupt-Chatseite, ihre Conversation-Historie, Deep Research, SystemPanel,
SystemPulse und der Agenten-WebSocket sind nicht an die kanonische
Task-Timeline gebunden. `ApprovalBell` liest nur teilweise kanonisch. Das
`CodexTasksPanel` liest kanonische REST-Daten, nutzt aber nicht den bereits
vorhandenen Task-WebSocket und verwaltet einen eigenen Polling-Cache.

### 4. Welche Approval-Pfade benutzen noch Legacy-Stores?

`ApprovalStore` in `openjarvis.tools.approval_store` bleibt der Store des
proaktiven Agenten. `/v1/approvals/pending` vereinigt dessen Records mit
`TaskStore.list_pending_approvals()`. Bei Approve/Deny wird zuerst nach einem
Task-Approval gesucht; andernfalls wird der Legacy-Record direkt auf approved
oder denied gesetzt. Nur der Task-Pfad erzwingt lokale Herkunft,
Correlation-ID, Idempotency-Key, `ApprovalBroker.decide()` und ein
`approval.user_decided`-Event. Proaktive Permission-Memory/Auto-Approval-
Altlogik darf nicht fuer Codex weiterverwendet werden.

### 5. Welche Komponenten besitzen keine Lade-, Fehler- oder Reconnect-Zustaende?

- `ApprovalBell` verschluckt Ladefehler und zeigt keinen Offline-/Reconnect-
  Zustand; Entscheidungsfehler werden nicht erklaert.
- `CodexTasksPanel` hat Polling, aber keinen WebSocket-/Cursor-/Reconnect-
  Zustand und keine belastbare Recovery-Anzeige.
- `SystemPulse`, App-Initialloads und mehrere Dashboards unterdruecken
  Fetch-Fehler.
- Chat kennt Streaming/Abort, normalisiert Backend-, Task-, Approval- und
  Verifikationsfehler aber nicht gemeinsam.
- Memory-/Browser-/Tool-Panels besitzen voneinander getrennte Loading/Error-
  Darstellungen.
- `useAgentEvents` reconnectet unbegrenzt und meldet keinen terminalen
  degraded state.

### 6. Welche Sprachkomponenten existieren bereits?

Frontend: `useSpeech`, `MicButton`, `AudioPlayer` und ein editierbares
Textarea-Transkript. Backend: `SpeechBackend`, Faster Whisper, OpenAI Whisper,
Deepgram, `TTSBackend`, Kokoro, OpenAI TTS und Cartesia. Server/Tauri bieten
Transcribe und einen einfachen Speech-Health-Proxy. Browser
`SpeechRecognition` und `speechSynthesis` werden noch nicht verwendet.

### 7. Welche Sprachpfade benoetigen externe Dienste?

OpenAI Whisper, Deepgram, OpenAI TTS und Cartesia benoetigen externe APIs und
Credentials. Faster Whisper und Kokoro sind lokal, erfordern aber optionale
Modelle/native Abhaengigkeiten. Browser Web Speech kann je nach Browser und
Plattform intern einen Herstellerservice verwenden und darf daher nur als
explizit ausgewiesene Browser-Capability gelten, nicht als garantiert lokal.
Der deaktivierte Pfad braucht keinen Dienst. Der Phase-6-Standard darf keinen
Cloudprovider automatisch auswaehlen.

### 8. Welche direkten Tool-Call-Sites umgehen ToolActionService?

Modell- oder nutzererreichbar und damit prioritaer zu migrieren sind:

- `server/api_routes.py`: drei proaktive API-Aufrufe rufen `tool.execute()`
  direkt auf;
- `server/agent_manager_routes.py`: MCP-Adapter und ad-hoc `ToolExecutor`;
- die ueber Server/CLI waehlbaren Agenten `native_react`, `orchestrator`,
  `operative`, `monitor_operative`, `native_openhands`, `deep_research`,
  `proactive_agent`, `morning_digest` und `rlm`;
- `workflow/engine.py` und der in `system/builder.py` erzeugte
  `ToolExecutor`;
- `agents/hybrid/_base.py` mit direktem `tool.execute()`.

Interne/evaluative oder bootstrap-nahe Pfade existieren unter anderem in
`learning/intelligence/orchestrator/environment.py`, `evals/**`, Skill-
Quellen, Connector-/Channel-Prozesshelfern und den Implementierungen der
Browser-/Desktop-/Filesystem-/Git-/Shell-Tools. Nicht jede interne
Subprozess- oder Dateisystemoperation ist eine Modell-Toolaktion; die genaue
Klassifikation und Migrationsentscheidung wird im separaten Bericht
`docs/tools/phase-6-legacy-call-sites.md` festgehalten. Bestehende
Kompatibilitaet wird nicht blind geloescht.

### 9. Welche FastAPI-Hooks verwenden noch das veraltete `on_event`?

Alle vier Vorkommen liegen in `server/app.py`: Task Runtime/Stores, Analytics,
Memory Service und Vault Memory Service verwenden `@app.on_event("shutdown")`.
Weitere Startup-/Shutdown-Abhaengigkeiten werden bisher ausserhalb eines
gemeinsamen Lifespan-Stacks initialisiert.

### 10. Welche Funktionen werden erst in Phase 7 oder 8 umgesetzt?

Phase 6 liefert die einheitliche, lokale und synthetisch getestete
Bedienoberflaeche. Zurueckgestellt bleiben:

- Wake Word und dauerhaftes/ambient Listening;
- produktive, unbeaufsichtigte PC-, Browser- oder externe Kontosteuerung;
- reale Nachrichten, Posts, Formulare, Uploads, Kaeufe oder Zahlungen;
- allgemeine Windows-Desktopautomation, UAC/Admin/Secure Desktop und blinde
  Koordinatensteuerung;
- echte Browserprofile, Cookies, Accounts und fremde Fenster-Screenshots;
- Aktivierung automatischer, dauerhafter, Bulk-, Modell- oder Website-
  Approvals sowie Level 4 und `full_access`;
- API-Key-, Responses-API- und normaler CLI-Fallback fuer Codex;
- produktiver Rollout/signierter allgemeiner Installer, solange Signing,
  Updatepfad und Berechtigungsmodell nicht freigegeben sind;
- produktive Aktivierung externer Speech-Provider;
- in Phase 8: Lesen/Migrieren/Umordnen des echten Vaults und seiner 46
  Notizen, reale Vault-Writes, produktiver Watcher sowie Import oder Migration
  aus `jarvis-desktop`.

## Verbindliche Phase-6-Entscheidung

Die bestehende UI wird erweitert, nicht dupliziert. Die Haupt-Chataktion wird
auf einen einzigen kanonischen Ablauf umgestellt:

`Text/Transkript -> Session -> Task -> Codex -> Memory -> ToolProposal ->`
`ToolActionService -> CentralRiskPolicy -> Approval -> Verification ->`
`TaskEvent/Trace -> Antwort`.

Die React-Anwendung erhaelt einen gemeinsamen Workspace-State. Persistierte
REST-Timeline wird zuerst geladen; danach folgt `/v1/tasks/events` mit
`after_sequence`, Event-ID/Sequenz-Deduplizierung, begrenztem exponentiellem
Reconnect und erneutem Replay. Approvals bleiben ausschliesslich explizite
Buttons `Allow once` und `Deny`. Sprache liefert nur editierbaren Text an
denselben Sendepfad; TTS ist eine abbrechbare Ausgabeschicht und hat keine
Approval-Befugnis.

FastAPI-Ressourcen werden ueber einen einzigen Lifespan/ExitStack in
umgekehrter Abhaengigkeitsreihenfolge geschlossen. Tauri erhaelt nur eng
benannte Commands und die minimal noetigen Capabilities. Alle Tests bleiben
bei Fakes, temporaeren Datenbanken/Vaults/Profilen, lokalen Testseiten und
eigenen Prozessen.

## Implementierungsreihenfolge nach diesem Audit-Commit

1. Einheitliche Navigation und kanonischen Workspace-State einfuehren.
2. Chat/Session/Task-API und Task-Replay/Live-Stream verbinden.
3. Sources, Tool-Actions, Verification, Approvals und Recovery integrieren.
4. Speech-Provider/Capabilities, Push-to-talk, editierbares Transkript,
   Browser-TTS und Barge-in ergaenzen.
5. Accessibility, RTL, Zoom und Fehlerzustaende haerten.
6. Credential-sichere Gesamt-Health ergaenzen.
7. FastAPI-Lifespan und Tauri-Prozess-/Berechtigungsgrenzen haerten.
8. Nutzer-/modell-erreichbare Legacy-Toolpfade inventarisieren und ueber die
   zentrale Action-Grenze fuehren.
9. Fokus-, Regressions-, Build-, Smoke- und genau einen kontrollierten
   read-only/deny-all Codex-Live-Test ausfuehren.
