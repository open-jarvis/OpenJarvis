# AGENTS.md — Hinweise fuer KI-Agenten (Codex, Claude Code, Gemini, ...)

Dieses Repo ist ein Andre-spezifischer Klon von **open-jarvis/OpenJarvis** mit lokalen Erweiterungen:
- `engine/codex_cli.py` — Codex-CLI als Engine
- `speech/gemini_tts.py` + `speech/text_normalizer.py` — Gemini TTS
- `connectors/strato_mail.py`, `connectors/thunderbird_calendar.py` — eigene Connectors
- diverse Server-Routes/Tools rund um digest_collect, cloud_router

Sprache: **Deutsch** in PR-Beschreibungen, Commit-Messages und Kommentaren wo passend.

## WICHTIG: pytest niemals parallel feuern

**Hintergrund (2026-05-09):** Codex hat in einer Session drei `pytest -vv -s`-Aufrufe innerhalb von 20 Millisekunden parallel gestartet. Zwei Streaming-Tests sind ins 64-Sek-Timeout gelaufen, ihre Subprozesse blieben jedoch als Zombies aktiv und haben zusammen ueber **57 GB virtuellen Speicher** belegt — der Windows-PC ist mit Kernel-Power Event 41 abgestuerzt (3x in einer Stunde). Details: `memory/project_pc_crashes_2026_05_09.md`.

**Konsequenz fuer Agenten — diese Regeln sind nicht optional:**

1. **Niemals zwei `pytest`-Aufrufe gleichzeitig** in flight haben. Immer auf das Ergebnis eines Aufrufs warten, bevor der naechste startet. Auch nicht mit unterschiedlichen Selektoren.
2. **Beim ersten Timeout-Exit (124) sofort stoppen.** Nicht den gleichen Aufruf in einem zweiten Subprozess wiederholen — der erste haengt vermutlich noch im Hintergrund. Erst:
   ```powershell
   Get-Process python | Sort-Object WS -Desc | Format-Table Id,WS,VM,StartTime,Path
   ```
   und Zombies mit `Stop-Process -Id <pid> -Force` killen.
3. **Streaming-Tests einzeln** laufen lassen, nie als Suite mit anderen Modulen kombinieren:
   ```
   pytest tests/server/test_routes.py::TestChatCompletions::test_streaming_codex_model_uses_engine_stream -v
   ```
4. **`-s` (no-capture) vermeiden** ausser zum Debuggen einer einzelnen Funktion. Ohne Capture sammelt pytest alle stdout-Bytes im Memory.
5. **`pytest-timeout` ist seit Mai 2026 Pflicht.** Default 30 Sek (`timeout_method = thread`). Tests die laenger duerfen, brauchen `@pytest.mark.timeout(N)` mit Begruendung im Docstring.

## Test-Befehle

```powershell
# Korrekt (eine Datei zur Zeit, mit PYTHONPATH):
$env:PYTHONPATH = 'src'
python -m pytest tests/server/test_routes.py -v

# Korrekt (gezielt, einzelner Test):
$env:PYTHONPATH = 'src'
python -m pytest tests/server/test_routes.py::TestChatCompletions::test_basic_completion -v

# FALSCH (Zombie-Risiko):
python -m pytest tests/server/test_routes.py tests/agents/test_digest_store.py tests/server/test_digest_routes.py -vv -s
```

## Lokale Mods nicht in upstream Push-Pfad bringen

Branch `main` zeigt auf `https://github.com/open-jarvis/OpenJarvis.git`. Vor jedem Push pruefen, ob die Aenderungen wirklich nach upstream gehen sollen, oder ob ein lokaler Branch (z.B. `andre/local`) sinnvoller ist. Andre's lokale Module (`codex_cli`, `gemini_tts`, `strato_mail`, `thunderbird_calendar`) sind nicht fuer upstream gedacht — sie enthalten produkt-spezifische Defaults.

## Frontend

```powershell
cd frontend
npm install
npm run build
```

`tsconfig.tsbuildinfo` ist generiert, NICHT committen — falls modified, ist das ein Build-Artefakt-Drift, nicht eine echte Aenderung.
