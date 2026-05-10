# C3PO auf OpenJarvis-Basis — Migrations-Design

**Datum:** 2026-05-10
**Autor:** Andre (astockma2) + Claude
**Status:** Approved (Brainstorming abgeschlossen)
**Strategie:** Big-Bang Hard-Fork

---

## Kontext

C3PO ist ein lokaler Voice-Agent fuer Andres Windows-PC, gebaut als Single-File-FastAPI-Loesung. Stand 2026-05-09: 39 Tools registriert, 6 von 8 Phasen fertig, Web-Cockpit auf :8050, PyQt6-Tray, 3-Stufen-Permission, Audit-Log. Lebt in `c:\Users\andre\Projekt\C3PO-legacy\`, GitHub `astockma2/c3po-legacy` (geplant).

OpenJarvis (`open-jarvis/OpenJarvis`) ist ein Stanford-Open-Source-Backend-Framework fuer modulare AI-Assistants. Bietet Engine-/Agent-/Channel-/Connector-/Tool-/Skill-Architektur, FastAPI-Server mit OpenAI-API-Kompatibilitaet, React-19+Tauri-2-Frontend. Andre hatte bereits lokale Mods (Codex-CLI-Engine, Gemini-TTS, deutsche Text-Normalisierung, Strato-Mail, Thunderbird-Calendar) im `_external/OpenJarvis/`-Klon.

Andre hat entschieden: **C3PO wird voll auf OpenJarvis-Basis migriert, C3PO-legacy archiviert, neuer Code in einem Hard-Fork `astockma2/c3po`.**

---

## Architekturentscheidungen (aus Brainstorming)

| Frage | Entscheidung |
|---|---|
| Repo-Strategie | Hard-Fork `astockma2/c3po` von `open-jarvis/OpenJarvis` |
| Voice-Architektur | Neuer Channel `voice_local` |
| Tool-Migration | Mostly OpenJarvis-Tools; Mail+Calendar als Connectors |
| UI | OpenJarvis-Frontend (React+Tauri) angepasst; Cockpit-Lite als Fallback |
| Permission-System | Generisches kanal-aware `permission_gate` |
| Migrations-Reihenfolge | Big-Bang mit internen Stufen |
| Architektur-Variante | Channel-als-Voice-Daemon (siehe Sektion 1) |

**C3PO-legacy** bleibt parallel installiert und funktionsfaehig, bis Stufe 5 (Cutover) abgeschlossen ist.

---

## 1. Repository & Setup

### Repo-Topologie

```
GitHub:
  astockma2/c3po                    ← Hard-Fork, alleinige Heimat
  astockma2/c3po-legacy             ← C3PO-alt, eingefroren als Read-Only-Archiv

Lokal:
  c:\Users\andre\Projekt\C3PO-legacy\    ← umbenannt aus C3PO\
  c:\Users\andre\Projekt\c3po\           ← Fork-Clone (nicht mehr in _external\)
```

### Upstream-Sync

OpenJarvis-Updates kommen per Bedarf:
```bash
cd c:\Users\andre\Projekt\c3po
git fetch upstream
git merge upstream/main
```

Konflikt-Risiko bleibt niedrig durch Konvention: **Andre-spezifische Logik lebt in eigenen Files** (siehe Sektion 2). Existierende Mods in Stanford-Files (`routes.py`, `cloud_router.py`, `digest_store.py`) werden in Stufe 0 isoliert, wo moeglich.

---

## 2. Modul-Architektur

```
c3po/
├── src/openjarvis/
│   ├── channels/
│   │   ├── voice_local.py            ← NEU. Wake-Word, VAD, Mic-Loop, STT, TTS-Output
│   │   └── ... (Standard-Channels: telegram, slack, etc.)
│   ├── engine/
│   │   ├── codex_cli.py              ← Andre Mod, bleibt
│   │   └── ollama.py, openai_compat_engines.py, ...
│   ├── speech/
│   │   ├── faster_whisper.py         ← Standard
│   │   ├── piper_tts.py              ← NEU
│   │   ├── gemini_tts.py             ← Andre Mod
│   │   ├── text_normalizer.py        ← Andre Mod
│   │   └── wakeword.py               ← NEU
│   ├── connectors/
│   │   ├── strato_mail.py            ← Andre Mod
│   │   ├── thunderbird_calendar.py   ← Andre Mod
│   │   └── ...
│   ├── tools/c3po/                   ← NEU. Andres 39 Tools, themengruppiert.
│   │   ├── __init__.py               ← registriert alle Tools beim Import
│   │   ├── time_tools.py
│   │   ├── windows_tools.py
│   │   ├── browser_tools.py
│   │   ├── mail_tools.py
│   │   ├── calendar_tools.py
│   │   ├── messaging_tools.py
│   │   └── admin_tools.py
│   ├── security/
│   │   └── permission_gate.py        ← NEU. 3-Stufen-Gate, kanal-aware.
│   └── server/
│       └── routes.py                 ← MOD. /audit/log, /voice/*, /permission/respond
│
├── desktop/                           ← NEU. Eigener Prozess fuer GUI.
│   ├── tray.py                       ← portiert aus C3PO-legacy/ui/tray.py
│   ├── confirm_dialog.py             ← portiert
│   ├── pin_dialog.py                 ← portiert
│   └── main.py                       ← Entrypoint, WebSocket zu Server
│
├── frontend/                          ← React 19 + Tauri 2 (OpenJarvis-Standard)
│   ├── src/views/AuditLog.tsx        ← NEU
│   ├── src/views/VoiceStatus.tsx     ← NEU
│   ├── src/views/Permissions.tsx     ← NEU
│   └── ...
│
├── configs/c3po/                      ← C3PO-spezifische Configs (TOML statt YAML)
│   ├── settings.toml
│   ├── permissions.toml
│   └── admin_whitelist.toml
│
├── piper-models/                      ← TTS-Modelle (140 MB), .gitignore'd
│   ├── de_DE-thorsten_emotional-medium.onnx
│   ├── de_DE-pavoque-low.onnx
│   └── openwakeword/hey_jarvis_v0.1.onnx
│
├── tests/                             ← OpenJarvis-Tests + neue C3PO-Tests
│   ├── channels/test_voice_local.py
│   ├── speech/test_piper_tts.py, test_wakeword.py
│   ├── tools/c3po/test_*.py
│   ├── security/test_permission_gate.py
│   └── desktop/test_dialogs.py
│
└── pyproject.toml                     ← OpenJarvis-Original + neue Deps:
                                          openwakeword, piper-tts, sounddevice,
                                          webrtcvad-wheels, PyQt6, keyring
```

### Modul-Details

#### `channels/voice_local.py`

Implementiert OpenJarvis' Channel-Interface. Verantwortlich fuer Eingang+Ausgang gesprochener Sprache.

- `class VoiceLocalChannel(Channel)`
- `async def listen(self) -> AsyncIterator[Message]` — Wake-Word-Loop, yield bei erkanntem Spruch
- `async def respond(self, message: Message) -> None` — TTS-Ausgabe

**Dependencies:** `speech.wakeword`, `speech.faster_whisper`, `speech.piper_tts`, `speech.text_normalizer`, `core.events.EventBus`.

**Was es nicht tut:** Permission-Checks (das macht das Gate beim Tool-Call), Tool-Auswahl (macht der Agent), UI (macht der Tray-Daemon).

#### `security/permission_gate.py`

Singleton im Server. Bei jedem Tool-Call: ist die Aktion erlaubt; falls confirm/admin: User fragen.

- `async def check(self, tool_name: str, args: dict, channel: str) -> PermissionResult`
  - Returns: `granted` / `denied(reason)` / `needs_confirm(prompt_id)` / `needs_pin(prompt_id)`
- `async def confirm(self, prompt_id: str, response: str) -> bool` — wird vom Channel oder Tray gerufen
- prompt_id ist UUID, asyncio.Future-Map mit Lock gegen Races
- 30-Sek-Timeout, danach Auto-Decline

**Kanalverhalten:**
- Voice: Tray-Dialog (HTTP-Push), bei admin Tray-PIN-Dialog
- Telegram: Inline-Frage als Bot-Nachricht, wartet auf naechste User-Antwort
- Frontend: Modal-Dialog im React-UI

#### `desktop/main.py`

Eigener Python-Prozess, getrennt vom Server. PyQt6-Tray + tkinter-Dialoge.

- Start: Windows-Autostart (`shell:startup`)
- WebSocket zu Server (`ws://127.0.0.1:8000/desktop/events`)
- Lauscht auf `permission.confirm_requested`, `permission.pin_requested`, `voice.status_changed`
- Antwortet per HTTP zurueck an Server

---

## 3. Datenfluss & Lifecycle

### Szenario A — "Hey Jarvis, was hab ich um 14 Uhr?"

```
1. Tray bereits aktiv (Server gestartet, WebSocket verbunden)
2. voice_local: WakeWordDetector → VAD → faster_whisper → Message(channel="voice_local")
3. server/agent_manager: codex_cli-Engine → tool_call calendar.upcoming(when="14:00")
4. permission_gate.check → permissions.toml → "calendar.upcoming"=free → granted
5. tools/c3po/calendar_tools.upcoming() → connectors.thunderbird_calendar
6. Agent → LLM-Antwort → Message(role=ASSISTANT, channel="voice_local")
7. voice_local.respond: text_normalizer → piper_tts → sounddevice
8. server/audit: append-only log

Zeitbudget: ~5-8 Sek end-to-end.
```

### Szenario B — "Hey Jarvis, starte Reboot" (admin-Tool, PIN noetig)

```
1-3. wie A, aber tool_call admin.reboot()
4. permission_gate.check → "admin.reboot"=admin → needs_pin(prompt_id=UUID)
5. agent_manager: SUSPENDED, bus.publish("permission.pin_requested", channel="voice_local")
6. voice_local: spricht "Reboot ausfuehren? Bitte am Tray die PIN eingeben."
7. desktop/main: empfaengt Event → pin_dialog.py → keyring-Vergleich
8. HTTP POST /permission/respond/{prompt_id} {"pin":"1234"}
9. permission_gate.confirm(prompt_id, "1234") resolves Future → True
10. agent_manager: tool_call ausgefuehrt → admin_tools.reboot() → shutdown.exe /r /t 60
11. audit: granted_by="admin", prompt_id, pin_correct=True
```

### Szenario C — "Andre via Telegram: /reboot"

Identisch zu B, aber Permission-Anfrage geht als Inline-Telegram-Message an Andre, antwortet textlich. Permission-Gate ist kanal-agnostisch.

### Lifecycle der drei Prozesse

| Prozess | Start | Stop |
|---|---|---|
| **Server** (uvicorn) | `c3po serve` (CLI), Windows-Service | SIGTERM, schliesst Channels+Connectors |
| **voice_local Channel** | im Server-Prozess als asyncio-Task | mit Server. Crash → disabled, Server bleibt |
| **Tray-Daemon** | Windows-Autostart, eigener Prozess | User-"Quit" oder Logout |
| **Frontend (Tauri)** | User-Doppelklick, optional | User-Klick X |

---

## 4. Migrations-Reihenfolge (Big-Bang, intern strukturiert)

### Stufe 0 — Repo-Setup (~halber Tag)

| Schritt | Aktion |
|---|---|
| 0.1 | Hard-Fork `astockma2/c3po` aus `open-jarvis/OpenJarvis` (gh repo fork). **DONE 2026-05-10** |
| 0.2 | Lokal-Klon nach `c:\Users\andre\Projekt\c3po\`. **DONE** |
| 0.3 | C3PO-Ordner umbenannt zu `C3PO-legacy/`. **DONE** |
| 0.4 | Andres bisherige Mods (codex_cli, gemini_tts, text_normalizer, strato_mail, thunderbird_calendar, modifizierte routes/cloud_router/digest_store) aus `_external/OpenJarvis/` in den Fork uebernehmen, als Commit `feat: andre-local mods import` |
| 0.5 | `_external/OpenJarvis/` loeschen |
| 0.6 | pytest-timeout-Konfig + AGENTS.md aus dem heutigen morgen-Patch im Fork uebernehmen |
| 0.7 | Smoke-Test: `pip install -e .[server,inference-cloud]`, `pytest tests/agents/test_digest_store.py` |
| 0.8 | C3PO-legacy Audit-Log nach `c3po/data/audit-legacy.log` kopieren |

**Cutover-Kriterium Stufe 0:** Andres Mods sind im Fork, OpenJarvis-Tests gruen, _external/ weg.

### Stufe 1 — Voice-Pipeline (~3-4 Tage)

**Ziel:** "Hey Jarvis" → STT → Codex → TTS funktioniert. Keine Tools, keine Permission, keine Tray.

| Datei | Aktion |
|---|---|
| `src/openjarvis/speech/wakeword.py` | NEU. openWakeWord-Wrapper |
| `src/openjarvis/speech/piper_tts.py` | NEU. Piper-ONNX, registriert als `"piper"` in TTSRegistry |
| `src/openjarvis/channels/voice_local.py` | NEU. Channel-Klasse |
| `configs/c3po/settings.toml` | NEU |
| `tests/channels/test_voice_local.py` | NEU. Mit WAV-Datei statt Mikro |
| `tests/speech/test_piper_tts.py` | NEU |
| `tests/speech/test_wakeword.py` | NEU |
| Manueller End-to-End-Test | Mikro → Antwort |

**Cutover-Kriterium Stufe 1:** Wake-zu-Antwort < 8 Sek.

### Stufe 2 — Permission-Gate + Audit (~2-3 Tage)

| Datei | Aktion |
|---|---|
| `src/openjarvis/security/permission_gate.py` | NEU |
| `src/openjarvis/server/audit.py` | NEU |
| `src/openjarvis/server/routes.py` | MOD. /audit/log, /permission/respond, /voice/* |
| `desktop/main.py` | NEU |
| `desktop/tray.py` | PORT aus C3PO-legacy/ui/tray.py |
| `desktop/confirm_dialog.py` | PORT |
| `desktop/pin_dialog.py` | PORT |
| `configs/c3po/permissions.toml` | NEU (initial leer) |
| `configs/c3po/admin_whitelist.toml` | NEU |
| `tests/security/test_permission_gate.py` | NEU. inkl. Race-Test |

**Cutover-Kriterium Stufe 2:** Mock-Tool auf "confirm", Voice-Befehl loest Tray-Dialog, Klick → ausgefuehrt, Audit-Eintrag.

### Stufe 3 — 39 Tools (~5-7 Tage)

| Sub-Stufe | Tool-Block | Anzahl | Datei | Permission |
|---|---|---|---|---|
| 3.1 | Time + Hello | 3 | `tools/c3po/time_tools.py` | free |
| 3.2 | Windows | 6 | `tools/c3po/windows_tools.py` | open=free, kill=confirm |
| 3.3 | Mail | 4 | `tools/c3po/mail_tools.py` | read=free, send=confirm |
| 3.4 | Calendar | 3 | `tools/c3po/calendar_tools.py` | free |
| 3.5 | Browser | 8 | `tools/c3po/browser_tools.py` | navigate=free, click/fill=confirm |
| 3.6 | Messaging | 5 | `tools/c3po/messaging_tools.py` | send=confirm |
| 3.7 | Admin | 10 | `tools/c3po/admin_tools.py` | alle=admin |
| 3.8 | `permissions.toml` final | — | — | aus Klassifikation |

Pro Tool: pytest mit gemocktem Connector/Subprocess.

**Cutover-Kriterium Stufe 3:** 39 Tools registriert, alle Tests gruen, manueller Voice-Test "sag mir die Mails" liefert echte Liste.

### Stufe 4 — Frontend (~3-5 Tage)

| Datei | Aktion |
|---|---|
| `frontend/src/views/AuditLog.tsx` | NEU. Tabelle mit Filtern, polled `/audit/log` |
| `frontend/src/views/VoiceStatus.tsx` | NEU. WS-live |
| `frontend/src/views/Permissions.tsx` | NEU. permissions.toml-Editor |
| `frontend/src/views/Settings.tsx` | MOD. C3PO-Settings |
| Tauri-Build verifizieren | `npm run tauri build` Windows |
| Smoke-Tests | `npm run tauri dev` |

**Fallback bei Tauri-Build-Failure:** Cockpit-Lite (FastAPI+statisches HTML) auf :8050 als Uebergang.

**Cutover-Kriterium Stufe 4:** Tauri-App startet, Views funktional. Oder Cockpit-Lite zeigt Audit+Voice.

### Stufe 5 — Cutover (~1 Tag)

| Schritt | Aktion |
|---|---|
| 5.1 | C3PO-legacy stoppen (Service abschalten) |
| 5.2 | Windows-Autostart umbiegen: `c3po serve` + `desktop/main.py` |
| 5.3 | Live-Tag mit Andre |
| 5.4 | Fix-Liste durcharbeiten |
| 5.5 | Memory aktualisieren: `project_c3po_voice_agent.md` -> neuer Repo-Pfad |

**Cutover-Kriterium Stufe 5:** Werktag durchgaengig genutzt, kein Crash, alle Befehle die Andre heute nutzt funktionieren.

### Zeitbudget gesamt

| Stufe | Best-Case | Realistisch |
|---|---|---|
| 0 | 0.5 d | 1 d |
| 1 | 3 d | 4 d |
| 2 | 2 d | 3 d |
| 3 | 5 d | 7 d |
| 4 | 3 d | 5 d |
| 5 | 1 d | 2 d |
| **Gesamt** | **~2.5 Wochen reine Bauzeit** | **~4-5 Wochen reine Bauzeit** |

Kalendarisch (Andres Stil) eher **6-8 Wochen**, mit aggressiver Codex+Claude-Hilfe **3-4 Wochen**.

---

## 5. Risiken & Fallbacks

| ID | Risiko | Wahrsch. | Fallback | Frueh erkennbar in |
|---|---|---|---|---|
| R1 | Tauri-Build versagt auf Windows | Mittel-Hoch | Cockpit-Lite (FastAPI+HTML) | Stufe 4 Tag 1 |
| R2 | openWakeWord-ONNX Python-inkompatibel | Niedrig | venv mit Python 3.12 erzwingen | Stufe 1.7 |
| R3 | Permission-Race bei parallelen Channels | Niedrig | UUID-prompt_ids, Future-Map mit Lock | Stufe 2 Test |
| R4 | Codex-CLI zu langsam | Hoch | OpenAI-API-Engine als Alternative, leichteres Modell | Stufe 1.8 |
| R5 | Strato-Mail kaputt nach Migration | Mittel | `setup_credentials.py` portieren | Stufe 3.3 |
| R6 | Tools/c3po-Import zu lang | Mittel | Lazy-Import pro Tool | Stufe 3.7 |
| R7 | PyQt6+asyncio+WS klemmt | Mittel | qasync oder Polling-HTTP statt WS | Stufe 2.4 |
| R8 | Audit-Log-History geht verloren | Hoch wenn vergessen | Stufe 0.8 — kopieren | Stufe 0 |
| R9 | Upstream-Merge-Konflikte spaeter | Hoch nach 6 Mon. | Andre-Code in eigenen Files (Konvention) | Stufe 0 |
| R10 | Big-Bang dauert zu lang, Frust | Hoch | Pause-Punkte nach jeder Stufe | nach jeder Stufe |

### Hartes Stop-Kriterium

Wenn nach Stufe 1 der Voice-Loop nicht aehnlich schnell wie C3PO-legacy ist (Wake-zu-Antwort > 12 Sek), ist die Architektur falsch. Zurueck auf Brett, Variante 3 (Headless+Wrapper) erwaegen.

### Pause-Punkte

Nach jeder Stufe (1, 2, 3, 4) ist die Migration pausierbar — C3PO-legacy bleibt live. Cutover (Stufe 5) ist der einzige unterbrechungsfreie Schritt.

---

## 6. Akzeptanzkriterien & Definition of Done

### Voice-Funktion
- [ ] Wake-Word "Hey Jarvis" erkannt, ≤1 False-Positive pro 30 Min
- [ ] STT-Latenz ≤ 3 Sek nach Sprech-Ende
- [ ] TTS-Latenz ≤ 1 Sek bis erste Audio-Ausgabe
- [ ] Wake-zu-Antwort ≤ 8 Sek bei einfachen Tools
- [ ] Voice-Channel ueberlebt 30 Min idle ohne Crash, Memory < 100 MB Wachstum

### Tools
- [ ] Alle 39 Tools registriert (`c3po tools list`)
- [ ] 3 Stichproben pro Tool-Block manuell getestet
- [ ] Strato-Mail liest+sendet (Test-Mail an andre@astockma.de)
- [ ] Thunderbird-Calendar liefert heutigen Termin
- [ ] Browser-Tool: persistente Session ohne user_data_dir-Konflikt
- [ ] Telegram-Bot empfaengt+antwortet
- [ ] Admin-Tool `disk_status` mit korrekter PIN

### Permission-System
- [ ] `permissions.toml` enthaelt alle 39 Tools mit Stufe
- [ ] confirm im Voice-Channel: Tray-Dialog → Ja → ausgefuehrt; Nein → abgelehnt
- [ ] admin: PIN-Pruefung, falsche abgelehnt, korrekte fuehrt aus
- [ ] PIN im Windows-Credential-Manager (`c3po:admin_pin`)
- [ ] Admin-Whitelist greift
- [ ] Timeout 30 Sek → Auto-Decline, Audit "timeout"
- [ ] Telegram-Channel Permission-Antworten via Inline

### Audit-Log
- [ ] Jeder Tool-Call in `~/.c3po/audit.log`: ts, channel, tool, args, perm, result_size
- [ ] Keine PINs/Mail-Inhalte (nur Metadaten)
- [ ] Legacy-Log lesbar, klar abgegrenzt
- [ ] Frontend zeigt 100 letzte mit Filter

### Tray-Daemon
- [ ] Windows-Autostart
- [ ] Reconnect-Loop bei Server-Restart
- [ ] Menue: Voice-Toggle, View Logs, Quit
- [ ] Voice-Toggle ruft `/voice/toggle`

### Frontend
- [ ] **Path A — Tauri:** App startet, alle 4 Views funktional
- [ ] **Path B — Cockpit-Lite:** :8050 zeigt Audit + Voice-Status
- [ ] Pfad-Wahl vor Stufe 4 (Tauri-Smoke-Test in Stufe 0)

### Tests
- [ ] `pytest tests/` gruen (ausser slow/live)
- [ ] pytest-timeout=30 thread aktiv
- [ ] AGENTS.md verbietet parallele pytest-Aufrufe
- [ ] Mind. 1 Integration-Test pro Tool-Block
- [ ] Voice-Pipeline-Test mit aufgenommener WAV

### Repo-Hygiene
- [x] Hard-Fork `astockma2/c3po` (DONE 2026-05-10)
- [ ] C3PO-legacy als `astockma2/c3po-legacy` archiviert
- [x] Lokal `C3PO-legacy/` umbenannt (DONE)
- [ ] `_external/OpenJarvis/` geloescht
- [ ] README.md aktualisiert
- [ ] CLAUDE.md im Fork beschreibt: Modul-Layout, Andre-Code-Konvention, Migration-Datum, Upstream-Verweis

### Live-Betrieb
- [ ] Andre nutzt System einen kompletten Werktag exklusiv
- [ ] Audit-Log dieses Tages reviewed
- [ ] Keine Crash-Logs in `~/.c3po/logs/`

### Memory
- [ ] `memory/project_c3po_voice_agent.md` aktualisiert
- [ ] `MEMORY.md`-Index passt
- [ ] Bei Lessons-learned: `feedback_openjarvis_migration.md`

### Definition of "fertig"
1. Alle Punkte oben abgehakt **oder** explizit als Phase-2-Backlog akzeptiert
2. Andres Live-Tag ohne Kritikalitaet
3. Cutover-Commit `feat: c3po live on openjarvis basis` gepusht

### Backlog (NICHT fuer Stufe 5 noetig)
- Custom "Hey C3PO"-Wake-Word (war Phase 6 in legacy)
- Browser-Daemon (parallele Playwright ohne user_data_dir-Lock)
- Telegram-Confirm-Flow (statt Tray)
- Skill-System 2.0-Adoption fuer 39 Tools
- Mining-/Eval-Features

---

## Naechste Schritte

1. Spec wird ins Repo committed
2. Andre reviewt
3. Bei Approval: writing-plans-Skill erstellt detaillierten Implementations-Plan
4. Stufe 0 wird ausgefuehrt (groesstenteils schon erfolgt)
