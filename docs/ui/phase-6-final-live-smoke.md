# Phase 6 – finaler Codex-Live-Smoke

Stand: 31. Juli 2026

## Entscheidung

Der letzte offene Phase-6-Codex-Live-Gate ist **vollständig bestanden**.
Damit ist Phase 6 technisch vollständig bestanden.

Phase 7 bleibt dennoch gesperrt und darf ohne eine neue ausdrückliche
Freigabe nicht begonnen werden. In diesem Abschluss wurden keine Learning-,
Skill- oder sonstigen Phase-7-Arbeiten ausgeführt.

## Ausgangszustand

- Repository: `C:\Users\Playe\Documents\JARVIS\openjarvis-codex`
- Branch: `feature/codex-jarvis-orchestrator`
- Ausgangs-HEAD: `7c4845f944f284f1fa0967446efc926e863f3f7b`
- Arbeitsbaum am Start: sauber
- Upstream Fetch: `https://github.com/open-jarvis/OpenJarvis.git`
- Upstream Push: `DISABLED`
- verifiziertes Ausgangs-Bundle:
  `outputs\phase-6-final-gates\openjarvis-phase6-final-gates-7c4845f9.bundle`
- Ausgangs-Bundle SHA-256:
  `CEFE9D3943DAF17BF76AF1F78546FB6BBC1EE3E170DF3B102EB3DC3D56B76C96`
- `git bundle verify`: erfolgreich; Bundle-HEAD entsprach dem Ausgangs-HEAD
  und das Bundle meldete vollständige Historie.

Der exakte finale Repository-HEAD nach Commit dieses Berichts wird im
nachgelagerten externen Recovery-Nachweis festgehalten. Der Bericht selbst
kann den Hash seines eigenen Commits nicht in seinen Commit-Inhalt einbetten.

## Freigabe und Preflight

Es war genau ein weiterer Python-Codex-SDK-Live-Turn freigegeben. Vor dem
Live-Zugriff durchlief derselbe Harness einen vollständig lokalen Fake-
Preflight. Dabei wurde kein Modell-Turn gestartet.

Der Preflight bestätigte:

- genau einen kanonischen `POST /v1/chat` im Harness
- Python-SDK-Routing ohne CLI-Fallback
- `read_only` und `deny_all`
- prozesslokales Turn-Limit 24.000
- temporären Task- und lokalen Trace-State
- Analytics und externe Traces deaktiviert
- kein Memory-/Vault-Service
- kein `ToolActionService`
- erfolgreichen Taskabschluss `done/completed`
- zweimal identischen Timeline-Readback
- Summary-, Session-, Usage- und Trace-Readback
- keine Tools, Tool-Items, Actions oder Approvals
- bytegleiches leeres Workspace
- App-/Backend-Shutdown und Entfernen des temporären Roots

Ein persistenter Einmal-Guard wurde unmittelbar vor dem realen POST atomar
angelegt. Er verhindert einen zweiten Live-Aufruf:

`outputs\phase-6-final-live-smoke\one-turn.guard`

## Python SDK und Anmeldung

- SDK: `openai-codex 0.144.4`
- gepinnte Runtime: `openai-codex-cli-bin 0.144.4`
- `codex login status`: `Logged in using ChatGPT`
- SDK-Health: verfügbar und authentifiziert
- Auth-Modus: `chatgpt`
- Backend: `python_sdk`
- Sandbox: `read_only`
- OpenAI-SDK-Approval-Policy: `never`
- OpenJarvis-Approval-Modus: `deny_all`
- kein API-Key-, Responses-API-, App-Server- oder normaler CLI-Fallback

Der SDK- und Sandbox-Aufbau entspricht dem dokumentierten Python-SDK-Pfad:
ein frischer Thread, ein Turn und `Sandbox.read_only`. Die nicht-interaktive
Kombination `read-only` plus Approval `never` verhindert Freigabeprompts.

## Exakt ein neuer Live-Turn

Es wurde genau ein neuer realer POST und genau ein persistierter Python-SDK-
Turn ausgeführt. Es gab keinen Retry.

```text
Prompt:  Antworte ausschließlich mit: PHASE6-CODEX-SMOKE-OK
Antwort: PHASE6-CODEX-SMOKE-OK
```

Identitäten:

- Task-ID:
  `phase6-final-task-eb9ed61bd1344585a4c18a53bdcc8201`
- Session-ID:
  `phase6-final-session-eb9ed61bd1344585a4c18a53bdcc8201`
- Correlation-ID:
  `phase6-final-correlation-eb9ed61bd1344585a4c18a53bdcc8201`
- Thread-ID: `019fb53a-6a7a-74f1-82f0-81d739e602da`
- Turn-ID: `019fb53a-6e72-7ce1-9a04-693f00bbc303`

Ergebnis:

- `POST /v1/chat`: HTTP 200
- Task-Readback: HTTP 200
- erster Timeline-Readback: HTTP 200
- zweiter Timeline-Readback: HTTP 200
- Summary-Readback: HTTP 200
- Session-Readback: HTTP 200
- Usage-Readback: HTTP 200
- Taskstatus: `done`
- Outcome: `completed`
- Task-Result: exakt `PHASE6-CODEX-SMOKE-OK`
- API-/UI-Projektion der Assistant-Nachricht: exakt
  `PHASE6-CODEX-SMOKE-OK`
- Summary `safe_to_present_as_success`: `true`

## Token-Budget

Das Limit galt ausschließlich prozesslokal für diesen Smoke. Es wurde keine
Produktionskonfiguration und keine allgemeine Budgetlogik geändert.

- Turn-Limit: 24.000 Tokens
- Input-Tokens: 13.345
- davon gecachte Input-Tokens: 6.912
- Output-Tokens: 15
- Reasoning-Output-Tokens: 0
- gemeldete Gesamttokens: 13.360
- verbleibender Abstand zum Turn-Limit: 10.640

Gecachte Tokens wurden unverändert in der normalen SDK-Usage-Meldung und im
lokalen Turn-Limit berücksichtigt.

## Timeline, Summary und lokaler Trace

Die persistierte kanonische Timeline enthielt 24 Events. Beide API-Readbacks
lieferten dieselben 24 Event-IDs in derselben Reihenfolge.

Nachgewiesene Lebenszyklus- und Antworttypen:

- `task.created`
- `chat.user_message`
- `thread.started`
- `task.state_changed` nach `running`
- `turn.started`
- `item.started` / `item.delta` / `item.completed`
- `usage.updated`
- `turn.completed`
- `task.state_changed` nach `done`
- `chat.assistant_message`

Die Summary meldete:

- letzter Schritt: `chat.assistant_message`
- letzte Sequenz: 24
- offene Approvals: 0
- Tool-Actions: 0
- sicher als Erfolg darstellbar: `true`

Der temporäre lokale Trace-Store enthielt 19 projizierte Codex-Events. Externe
Traces blieben deaktiviert. Task-, Usage-, Timeline- und Trace-Daten wurden nur
im temporären State gehalten und nach dem Readback entfernt.

## Keine Tools, Actions oder Approvals

Die einzigen persistierten Item-Typen waren:

- `userMessage`
- `agentMessage`

Es gab keine Command-, File-Change-, MCP-, Browser-, Web-Search- oder anderen
Tool-Events und keine Tool-Items. `forbidden_events` und `forbidden_items`
waren leer. Es wurden keine Actions und keine Approvals erzeugt.

## Workspace-Bytegleichheit

Das temporäre Workspace war vor und nach dem Turn leer:

- Dateien vorher/nachher: 0 / 0
- Bytes vorher/nachher: 0 / 0
- Manifest SHA-256 vorher:
  `526AD7E4D03E19938BB6B1AA2EEFC207368D7CC8F7B26ED11E5A3C8A713E0247`
- Manifest SHA-256 nachher:
  `526AD7E4D03E19938BB6B1AA2EEFC207368D7CC8F7B26ED11E5A3C8A713E0247`

Die Manifestobjekte waren bytegleich. Der gesamte temporäre Root mit
Workspace, Task-State und Trace-State wurde anschließend entfernt.

## Prozess-Cleanup

- FastAPI-Lifespan meldete `shutdown_complete=true`.
- Der SDK-Backend-Client wurde durch den besitzenden Task-Runtime-Shutdown
  geschlossen.
- Nach dem Smoke existierten 0 temporäre Roots mit dem Smoke-Präfix.
- Die Prozessinventur nach dem Smoke entsprach dem vorherigen Baselinebestand.
- Es blieb kein neuer SDK-, Browser-, Desktop-, OpenJarvis- oder Serverprozess
  zurück.
- Bereits vor dem Smoke vorhandene Codex-Desktop-, WebView2- und fremde
  Python-Prozesse wurden weder beendet noch verändert.

Der maschinenlesbare Ergebnisnachweis liegt extern unter:

`outputs\phase-6-final-live-smoke\live-smoke-result.json`

SHA-256:
`8B50C38EB89AE1D7EF2188F35EAB5A2C35C3B238BC690BDBBE22227E582228F1`

## Fokussierte Regressionstests

Ausgeführt wurden ausschließlich die betroffenen Testbereiche:

- kanonischer Chat-/Task-Pfad
- Timeline-, Summary-, Session- und Usage-API
- Budget- und Orchestratorverhalten
- Python-SDK-Health und SDK-Lifecycle
- Codex-Eventnormalisierung
- FastAPI-Lifespan und idempotenter Shutdown
- betroffene Phase-6-Desktop-Härtungs-Smokes

Ergebnis:

```text
46 passed in 10.09s
```

Es wurde keine vollständige 7.000+-Suite ausgeführt. Da kein Produktionscode
geändert wurde, war kein allgemeiner Implementierungscommit erforderlich.

## Weiterhin gesperrte Pfade

Unverändert eingehalten:

- kein Phase-7-Code
- kein Zugriff auf das echte Obsidian-Vault oder die 46 echten Notizen
- kein Zugriff auf das alte `jarvis-desktop`
- keine echten Browserprofile
- außer der ausdrücklich erlaubten ChatGPT-Anmeldung keine Nutzerkonten
- keine Tools oder Tool-Items
- kein `full_access`
- kein API-Key-, Responses-API- oder normaler CLI-Fallback
- keine externen Aktionen oder Dienste außer dem freigegebenen Codex-Turn
- keine automatische oder dauerhafte Freigabe
- kein Upstream-Push
- kein zweiter Codex-Turn

Die gesperrten Vault- und Altprojektpfade wurden für diesen Nachweis
absichtlich weder aufgelistet noch gehasht.

## Recovery

Nach Commit dieses Berichts wird ein neues externes Vollhistorien-Bundle unter
`outputs\phase-6-final-live-smoke\recovery` erstellt. Der externe Nachweis
enthält den exakten finalen HEAD, `git bundle verify`, Bundle-SHA-256,
Restore-Clone, exakten Restore-HEAD-Vergleich und
`git fsck --full --strict`. Der temporäre Restore wird danach entfernt.
