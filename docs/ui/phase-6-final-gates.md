# Phase 6 – Abschlussgates

Stand: 31. Juli 2026

## Entscheidung

Phase 6 ist **noch nicht vollständig bestanden**. Der native Cargo-/Tauri-
Build und der echte Desktop-Laufzeitsmoke wurden nachgeholt. Der genau einmal
freigegebene neue Python-Codex-SDK-Turn lieferte zwar die exakte erwartete
Modellantwort, wurde aber wegen des lokalen 8.000-Token-Limits nach 13.366
gemeldeten Tokens sicher unterbrochen. Die kanonische API antwortete deshalb
mit HTTP 503. Gemäß Auftrag gab es keinen Retry.

**Phase 7 darf nicht beginnen.** Learning-, Skill- und sonstige Phase-7-Arbeit
wurde nicht begonnen.

## Sicherer Ausgangszustand

- Repository: `C:\Users\Playe\Documents\JARVIS\openjarvis-codex`
- Branch: `feature/codex-jarvis-orchestrator`
- Ausgangs-HEAD: `5a7cbf93b2b2854c240f90b668be3d7f4fa8e7a8`
- Arbeitsbaum am Start: sauber
- Upstream Fetch: `https://github.com/open-jarvis/OpenJarvis.git`
- Upstream Push: `DISABLED`
- Verifizierter Ausgangs-Bundle-Pfad:
  `outputs\phase-6\openjarvis-phase6-5a7cbf93.bundle`
- Ausgangs-Bundle SHA-256:
  `778CE749F9977270B1BD41322E301207A604F2697E75930EAAABBA7D7E462032`
- `git bundle verify`: erfolgreich; Bundle-HEAD entsprach dem Ausgangs-HEAD.

Der finale Produktions-/Build-HEAD vor diesem Berichtscommit ist
`87178c6ff58ae8f814688eaf4e77803fe87a02e2`. Der exakte Repository-HEAD nach
dem Berichtscommit steht im nachgelagerten externen Recovery-Nachweis unter
`outputs\phase-6-final-gates`; ein Commit kann seinen eigenen Hash nicht in
seinen Inhalt einbetten.

## Erforderliche Build-Korrekturen

Der Start-HEAD enthielt keinen unter Windows verwendbaren aktuellen Cargo-Lock
für den Tauri-Teil und eine nicht kompatible Tauri-JavaScript-Version. Die
Korrekturen wurden getrennt committed:

1. `c7ae1b1f402a08330340f52d7fb39c0492e82761` –
   `build: refresh Tauri dependency lock`
2. `87178c6ff58ae8f814688eaf4e77803fe87a02e2` –
   `build: align Tauri JavaScript tooling`

Geändert wurden ausschließlich:

- `frontend/src-tauri/Cargo.lock`
- `frontend/package.json`
- `frontend/package-lock.json`

Die JavaScript-Seite verwendet danach `@tauri-apps/api 2.11.1` und
`@tauri-apps/cli 2.11.4`, passend zu Rust-Tauri 2.11.3. Es wurde kein
Versions-Mismatch-Schalter verwendet und kein `npm audit fix` ausgeführt.

## Rust-, MSVC- und Windows-SDK-Nachweis

Die verlangten Suchschritte (`where.exe`, direkte Pfade unter
`%USERPROFILE%\.cargo\bin`, `.rustup`/`.cargo` und PATH-Vererbung) ergaben,
dass Rust tatsächlich fehlte. Die vorhandene `.cargo`-Struktur enthielt keine
Werkzeuge; eine nur prozesslokal verdeckte Installation lag nicht vor.

Installiert wurde ohne Administratorrechte ausschließlich der offizielle
`rustup-init.exe` für `x86_64-pc-windows-msvc`. Der Download wurde gegen die
offizielle SHA-256-Datei geprüft:

- rustup-init SHA-256:
  `86478E53F769379D7F0EBFA7C9AA97CB76CA92233F79AA2CC0DBEE2EFAAC73C7`
- Installation: Profil `minimal`, Host und Toolchain
  `stable-x86_64-pc-windows-msvc`, `--no-modify-path`
- Persistenter Benutzer-PATH wurde nicht verändert; Befehle nutzten einen
  prozesslokalen Pfad.
- Installer und Prüfdatei wurden nach Abschluss aus `%TEMP%` entfernt.

Versionen:

- Rust: `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- Cargo: `cargo 1.97.1 (c980f4866 2026-06-30)`
- aktive Toolchain: `stable-x86_64-pc-windows-msvc (default)`
- Visual Studio Build Tools 2022: `17.14.37516.0`
- MSVC: `19.44.35228`, Tool-Verzeichnis `14.44.35207`
- Windows SDK: `10.0.26100.0`

Die benutzerspezifischen Installationsverzeichnisse `%USERPROFILE%\.cargo`
und `%USERPROFILE%\.rustup` bleiben bewusst erhalten; sie sind keine
temporären Smoke-Artefakte.

## Nativer Cargo-/Tauri-Build

Kanonische Befehle aus `frontend/package.json`,
`frontend/src-tauri/Cargo.toml` und der Projektdokumentation:

```text
cargo check --manifest-path frontend/src-tauri/Cargo.toml --locked
npm run tauri -- build --no-bundle --ci
```

Ergebnis:

- `cargo check --locked`: bestanden, 4 min 19 s
- nativer Release-Build: bestanden, 7 min 57 s
- kontrollierter Smoke-Rebuild mit prozesslokalem
  `VITE_OPENJARVIS_NO_UPDATER=1`: bestanden, 2 min 47 s
- kein Bundle, Installer oder signiertes/distribuierbares Paket erzeugt
- natives Artefakt:
  `frontend\src-tauri\target\release\openjarvis-desktop.exe`
- Größe: 17.936.384 Bytes
- SHA-256 des für den Laufzeitsmoke verwendeten updaterfreien Builds:
  `0CBA3F5E565C04BDA4D158B44942BB7FCD696C688B70514D5B2790369C4BD1B9`

Build-Warnungen:

- leerer Vite-Chunk `react`
- `analytics.ts` wird statisch und dynamisch importiert
- Hauptchunk ungefähr 901 KiB und damit über der 500-KiB-Warngrenze
- `npm install` meldet weiterhin 29 Audit-Befunde: 2 niedrig, 16 mittel,
  11 hoch; diese wurden nicht automatisch verändert.

## Echter nativer Desktop-Laufzeitsmoke

Der echte `openjarvis-desktop.exe` wurde mit einem temporären Profil,
temporärem OpenJarvis-Home, leerem Workspace, separatem WebView2-Profil und
einem ausschließlich an `127.0.0.1:8000` gebundenen synthetischen Backend
gestartet. Der Updater war im Smoke-Build deaktiviert. WebView2 erhielt
zusätzliche Fail-Closed-Netzwerkregeln; beobachtet wurden nur lokale
Verbindungen zu `127.0.0.1:8000`.

Bestätigt wurden:

- native Anwendung und echtes OpenJarvis-Fenster gestartet
- vorhandenes gesundes Test-Backend korrekt erkannt
- System-Health `phase6-synthetic` erreichbar
- Jarvis-Hauptseite sichtbar
- Navigation zu Tasks, Approvals, Tools, Browser und Jarvis erfolgreich
- kein echtes Vault und kein echtes Browserprofil verwendet
- keine Shell-, UAC- oder Administratorfreigabe angefordert
- Close-Guard nach echtem `WM_CLOSE` sichtbar
- alle vier Optionen aktiv: Hintergrund, aktiven Task pausieren und
  ausblenden, aktiven Task abbrechen und ausblenden, Fenster behalten
- `Fenster behalten` getestet; Dialog geschlossen, Fenster blieb sichtbar
- `Im Hintergrund fortfahren` getestet; Fenster wurde ausgeblendet und der
  Prozess blieb als Tray-Anwendung aktiv
- kein Installer und kein Updater ausgelöst

Cleanup-Nachweis:

- `stop_backend` wurde erfolgreich aufgerufen; das fremd gestartete
  synthetische Backend wurde dabei korrekt nicht beendet.
- Der Tauri-Traypunkt `Quit` war über Windows UI Automation nicht
  adressierbar. Nach verifiziertem Prozessnamen wurde deshalb nur der exakt
  eigene Desktop-PID durch den Testharness beendet.
- Das synthetische Backend erhielt danach sein geordnetes lokales
  `POST /__shutdown__`.
- Port 8000 geschlossen, Debug-Port 9223 nicht mehr vorhanden.
- 0 dem Smoke gehörende WebView2-Prozesse, keine Desktop-/Backend-Waisen.
- Das gesamte temporäre Smoke-Verzeichnis wurde entfernt.

Diese Tray-Automationsgrenze ist eine bekannte Einschränkung des Nachweises;
sie ist kein Zugriff auf ein echtes Browserprofil oder einen fremden Prozess.

Eine weitere Windows-Einschränkung: Der Desktop prüft `uv`, bevor er ein
bereits laufendes Backend übernimmt. Auf diesem Rechner war `uv` nicht
installiert. Für den isolierten Smoke wurde ein fail-closed Teststub nur zur
Pfadauflösung bereitgestellt; der Stub wurde nicht ausgeführt, weil das
gesunde bestehende Test-Backend übernommen wurde. Eine reale Verteilung muss
`uv` bereitstellen oder diesen frühen Check im Produktcode verbessern.

## Genau ein neuer Codex-Live-Smoke

Vor dem Modellzugriff bestand ein turnfreier lokaler Preflight:

- kanonische Route `POST /v1/chat`
- `primary_backend=python_sdk`
- kein instanziierter CLI-Fallback
- ChatGPT-Anmeldung: `codex login status` meldete
  `Logged in using ChatGPT`
- `openai-codex 0.144.4` und `openai-codex-cli-bin 0.144.4`
- Sandbox `read_only`
- Approval-Modus `deny_all`, im SDK-Rollout als `never` bestätigt
- Turn-Limit 8.000
- Analytics und Traces aus
- Memory aus, kein Vault-Service, kein ToolActionService
- leeres temporäres Workspace und temporärer Task-State
- Preflight: 0 gestartete Live-Turns

Dann wurde **genau ein** POST mit genau einem neuen Python-SDK-Turn
ausgeführt:

```text
Prompt:   Antworte ausschließlich mit: PHASE6-CODEX-SMOKE-OK
Antwort:  PHASE6-CODEX-SMOKE-OK
```

Der SDK-Rollout belegt:

- Backend-Laufzeit `0.144.4`, ChatGPT-authentifiziert
- CWD war das temporäre leere Workspace
- Sandbox `read-only`
- Approval-Policy `never`
- keine Command-, File-Change-, MCP-, Browser- oder sonstigen Tool-Items
- genau eine Agent-Nachricht mit der erwarteten Antwort
- Usage: 13.351 Input-, 15 Output-, insgesamt 13.366 Tokens;
  davon 9.984 gecachte Input-Tokens
- anschließend `turn_aborted` mit Grund `interrupted`

Der lokale 8.000er Grenzwert wertet auch gecachte SDK-Kontexttokens aus. Die
Usage-Meldung lag deshalb 5.366 Tokens über dem Limit. OpenJarvis unterbrach
fail-closed; die kanonische API gab HTTP 503 aus. Es gab keinen zweiten
Versuch.

Folgen für die geforderten Einzelnachweise:

- exakt ein neuer Turn: bestanden
- Python SDK / ChatGPT / `read_only` / `deny_all`: bestanden
- keine Tools und keine Tool-Items: bestanden
- Modellantwort exakt erkannt: im SDK-Rollout bestanden
- kanonischer API-Erfolg, nachgelagerter Task-/Timeline-/UI-Readback:
  **nicht bestanden**, weil die Route mit 503 endete
- Workspace-Bytegleichheit: der SDK-Sandboxnachweis ist read-only, der
  Harness entfernte das Workspace; wegen der vorzeitigen 503 konnte der
  geplante Nachher-Manifestvergleich nicht als API-Gate protokolliert werden
- temporärer Task-State und Workspace: entfernt
- SDK-Backend: geschlossen; kein gehörender SDK-Unterprozess blieb zurück

Der Live-Smoke ist damit insgesamt **fehlgeschlagen**, obwohl Antwort und
Sicherheitsgrenzen korrekt waren. Für einen neuen Versuch ist erneut eine
ausdrückliche Freigabe erforderlich. Ein künftiges Limit muss oberhalb des
beobachteten SDK-Grundkontexts liegen oder gecachte Kontexttokens bewusst
anders behandeln; diese Phase hat daran keinen Produktionscode geändert.

## Fokussierte Regressionen

Es wurde keine erneute 7.000+-Gesamtsuite ausgeführt.

Python-Fokussuite:

```text
126 passed in 27.81s
```

Enthalten waren Desktop/Tauri-Härtung, FastAPI-Lifespan und idempotenter
Shutdown, kanonischer Chat-/Task-Pfad, Speech/Health, Task-Orchestrator,
Budgets, Policy, Projection sowie Phase-5-ToolAction- und Browser-Recovery-
Tests.

Frontend:

- Vitest: 5 Dateien, 16 Tests bestanden, 11,23 s
- Browser-Produktionsbuild: `npm run build` bestanden
- Vite 6.4.1: 3.102 Module, Build 25,25 s
- PWA: 20 Precache-Einträge, 2.072,34 KiB

## Weiterhin gesperrte Pfade

Unverändert eingehalten:

- Das echte Obsidian-Vault und die 46 echten Notizen wurden weder gelesen noch
  verändert. Es erfolgte keine Migration, Bereinigung oder Neuordnung.
- Das alte `jarvis-desktop`-Projekt wurde weder gelesen noch verändert.
- Es wurden keine echten Browserprofile oder Nutzerkonten verwendet.
- Es gab keine extern wirksamen Aktionen, keinen Upstream-Push, kein
  `full_access`, keinen API-Key-, Responses-API- oder normalen CLI-Fallback.
- Es gab keine automatischen oder dauerhaften Approvals.
- Phase 7 wurde nicht begonnen.

Die Aussage beruht auf der bewusst auf Repository, offizielle Rust-/Paketquellen,
OpenAI-Python-SDK und exakt benannte temporäre Testpfade begrenzten Ausführung.
Die gesperrten Vault-/Altprojektpfade wurden für den Nachweis absichtlich nicht
aufgelistet oder gehasht.

## Recovery

Nach Commit dieses Berichts wird unter
`C:\Users\Playe\Documents\Codex\2026-07-29\der-agent-soll-bevorzugt-den-python\outputs\phase-6-final-gates`
ein neues externes Vollhistorien-Bundle erstellt. Der dortige Nachweis enthält
den exakten finalen HEAD, Bundle-SHA-256, `git bundle verify`, Restore-Clone-
HEAD-Vergleich und `git fsck --full --strict`. Der temporäre Restore wird nach
erfolgreicher Prüfung entfernt.
