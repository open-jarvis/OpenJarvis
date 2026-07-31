# Phase 7: Skill-Ausführungssicherheit und Verifikationsnachweis

Stand: 31. Juli 2026.

## Kanonischer Ausführungspfad

```text
active scope selection
  -> persistent exact version pin
  -> canonical task identity and budget
  -> schema, lane, depth, cycle and secret checks
  -> deterministic ToolProposal
  -> ToolActionService
  -> CentralRiskPolicy / allow-once approval / lane
  -> ToolAction verification
  -> immutable SkillExecutionRecord
  -> persisted TraceEvaluation binding
  -> versioned metric snapshot
```

`CanonicalSkillExecutor` besitzt weder eine Toolfunktion noch einen
`ToolExecutor`. Seine einzige Ausführungsabhängigkeit ist das schmale
`ActionServiceProtocol`, das der produktive `ToolActionService` erfüllt. Fehlt
dieser Service, schlägt der Pfad vor Ausführung geschlossen fehl.

Jeder Step erzeugt nur ein strukturiertes `ToolProposal`. Proposal-ID und
Idempotency-Key werden deterministisch aus Pin, Step und Task-Idempotency
abgeleitet. Dadurch findet ein nach Approval oder Prozessneustart
fortgesetzter Lauf dieselbe ToolAction wieder und kann keine zweite Wirkung
erzeugen.

## Policy-, Capability- und Approval-Schutz

Tool-ID, Capability, Side-Effect-Klasse, Lane, Timeout und Tool-Risiko kommen
aus dem vertrauenswürdigen Tool Manifest Catalog. Der effektive Risk Floor ist
das Maximum aus Manifest-, Tool-, Task-, Untrusted-Input-, External-Effect-
und Side-Effect-Risiko. Level 4 wird vor Proposal-Erzeugung verweigert.

Ein Skill kann weder zusätzliche Toolnamen oder Capabilities noch Roots oder
Approvals angeben. Waiting-Approval wird nur mit einer exakten, Step-gebundenen
Allow-once- oder Deny-Entscheidung fortgesetzt. `Always allow` existiert im
Skillmodell nicht.

## Budget, Rekursion und Wirkung

Vor und während der Ausführung gelten Input-Schema, erlaubte Lane, maximale
Steps, maximale Laufzeit und maximale Call Depth. Der Call Stack wird auf
Zyklen geprüft. Das Gesamtbudget umschließt auch Await-Zeiten des Action
Service.

Ein Timeout während einer möglicherweise gestarteten Action wird ehrlich als
unbekannte Wirkung gespeichert. Unbekannte Wirkung wird nie automatisch
wiederholt. Ein Retry ist nur möglich, wenn sowohl Skill- als auch Toolpolicy
ihn erlauben und die vorherige Wirkung bekannt ist.

## Erfolgskriterium

Ein Step ist nur erfolgreich, wenn die persistierte ToolAction den Zustand
`completed` und die Verifikation `passed` trägt. Modelltext, Skilltext,
Exitcode 0 oder HTTP 200 können keinen Skill-Erfolg erzeugen. Partial,
Canceled, Interrupted, Policy-Denial, Approval-Denial/-Timeout,
Verification-Failure und Unknown bleiben getrennte Outcomes.

Execution Records speichern nur IDs, Hashes, Zustände, Risikowerte, Evidence-
Referenzen und Zeitpunkte. Eingabewerte und Toolausgaben werden nicht in den
Skill-Audit-Events dupliziert.

## Version Pinning und Restart

Die Auswahl schreibt vor der Ausführung einen hashgebundenen
`SkillExecutionPin` mit Scope-Revision, Skill-ID, SemVer und Manifest-Hash.
Nach Aktivierung einer neuen Version bleibt dieser Pin unverändert. Ein neuer
Task liest die neue Scope-Projektion. Deprecation verhindert neue Pins, beendet
aber keinen bereits gepinnten Lauf. Pins, Executions, Scope Heads,
Idempotency- und Audit Records werden nach Neustart mit Hash- und
Indexvalidierung erneut gelesen.

## Gehärtete Legacy-Pfade

Im kanonischen Modus sind folgende produktiv erreichbaren Altpfade gesperrt:

- `skills/executor.py` und `skills/tool_adapter.py`;
- Discovery, Ausführung, Subskill-Resolver und Tool-Wrapping in
  `skills/manager.py`;
- TOML-, Markdown- und Directory-Loader in `skills/loader.py`;
- produktiver Import und Overlays;
- Trace-basierte Legacy-Skill-Erzeugung;
- direkte `WorkflowEngine`-Ausführung;
- Legacy-Skill- und Workflow-Wiring in `system/builder.py` bei aktiviertem
  Codex-Modus.

Der Legacy-Parser markiert Resultate ausdrücklich als untrusted. Der
read-only Phase-7-Adapter liest ausschließlich lokale synthetische Fixtures,
führt nichts aus und registriert oder aktiviert nichts.

## Hermetischer Smoke

Der Offline-Smoke erzeugt einen temporären Root und führt dort den gesamten
Pfad aus: Candidate, Review, Manifest, Testing, vollständige Verification,
Promotion Pending, Allow-once, Promotion ohne Aktivierung, Aktivierung,
Version Pin, Fake ToolActionService, Postcondition Verification,
TraceEvaluation, Metrik, Version 2, Pin-Stabilität für Version 1, neue Auswahl
von Version 2, Rollback auf Version 1, lokaler Paketexport/-import und
Restart-Recovery. Ein Socket-Guard lässt jeden Verbindungsversuch sofort
fehlschlagen. Der temporäre Root wird am Testende entfernt.

Zusätzliche Tests decken unbekannte Tools/Capabilities, Risk Floor, Level 4,
Timeout, maximale Steps und Tiefe, Zyklus, unknown effect, Approval genau
einmal, fehlende ToolAction-Verifikation, offene Konflikte, fehlgeschlagenen
Healthcheck, Scope-CAS-Konkurrenz, Deprecation und manipulierte Pakete ab.

## Verifikationskommandos

Die Abschlussprüfung verwendet ausschließlich lokale Tests und schließt das
mit `@pytest.mark.live` markierte Ollama-Modul explizit aus:

```powershell
python -m pytest tests/learning/skills tests/learning/store `
  tests/learning/candidates tests/learning/evaluation -q
python -m pytest tests/skills -q `
  --ignore=tests/skills/test_integration_live.py
python -m pytest tests/workflow/test_workflow.py tests/sdk/test_system.py `
  tests/skills/test_native_react_few_shot.py `
  tests/learning/test_system_learning.py -q
python -m pytest tests/tools/test_action_service.py tests/tasks `
  tests/browser/test_recovery.py tests/browser/test_actions.py `
  tests/server/test_approval_routes.py tests/server/test_tool_browser_routes.py `
  tests/server/test_task_routes.py tests/server/test_ws_bridge.py -q
python -m ruff check src tests
python -m ruff format --check src tests
python -m compileall -q src/openjarvis tests/learning/skills
git diff --check
```

Die endgültigen Pass-Zahlen und die Git-/Secret-/Offline-Gates werden im
Abschlussbericht des Arbeitsblocks festgehalten.

Abschlussstand dieses Commits:

- Learning Skills/Store/Candidates/Evaluation: **320 passed**;
- bestehende Skills ohne das explizite Live-Modul: **269 passed**;
- Workflow/SDK-Builder/System-Learning: **68 passed**;
- Phase-5/6 ToolAction, Policy, Approval, Browser, Tasks, Timeline und
  Lifespan: **201 passed**;
- `ruff check src tests`: bestanden;
- Ruff-Format für alle 38 in diesem Arbeitsblock geänderten Python-Dateien:
  bestanden;
- Compileall, `git diff --check`, High-Confidence-Secret-Scan und der
  Socket-gesperrte Offline-Smoke: bestanden.

Der repositoryweite Format-Check meldet unabhängig von diesem Arbeitsblock
140 bereits zuvor vorhandene, unveränderte Dateien als formatierbar. Sie
wurden nicht massenhaft umgeschrieben. Alle in diesem Arbeitsblock geänderten
Python-Dateien sind formatkonform.

## Abgrenzung und ehrliche Testklassifikation

`tests/skills/test_integration_live.py` ist eine vorhandene, nicht hermetische
Live-Suite für Ollama und nutzerinstallierte Skills. Sie gehört nicht zur
Phase-7-Verifikation und wird im Abschlusslauf explizit ausgeschlossen. Bei
einem frühen, zu breit gewählten Testkommando wurde dieses Modul einmal
versehentlich gesammelt; es scheiterte an der nicht verfügbaren lokalen
Ollama-/Skill-Umgebung, bevor ein erfolgreicher Modellturn zustande kam. Danach
wurden alle Läufe explizit hermetisch begrenzt. Es gab keinen Codex-Live-Turn,
keinen erfolgreichen externen Modellaufruf, keinen Remote-Skill-Download und
keinen Zugriff auf Vault oder Altprojekt.

Phase 8, Shadow Routing, Feedback-UI, neue API-Routen und Frontendänderungen
bleiben gesperrt.
