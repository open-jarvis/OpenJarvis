# Phase 7: Audit der Learning- und Skill-Architektur

Stand: 2026-07-31

Audit-Basis: `e614c26bfd20d016c4885e32af37f0e7291a1efd`

Branch: `feature/codex-jarvis-orchestrator`

Status: verpflichtender Audit vor jeder Phase-7-Produktionscodeänderung

## 0. Umfang, Grenzen und sicherer Start

Dieser Bericht ist eine statische Bestandsaufnahme des aktuellen
`openjarvis-codex`-Repositories. Es wurden nur Repository-Inhalte und bereits
vorhandene Phase-6-Recovery-Artefakte gelesen. Es wurden keine produktiven
Learning-Läufe, keine externen Modelle, keine Skill-Imports, keine
Browserprofile, keine Nutzerkonten und kein Codex-Live-Turn gestartet.

Die gesperrten Pfade blieben unangetastet: Das echte Obsidian-Vault, die 46
echten Notizen und das alte `jarvis-desktop` wurden weder gelesen noch
verändert. Phase 8 wurde nicht begonnen.

Vor der ersten Änderung wurden folgende Voraussetzungen nachgewiesen:

| Prüfung | Ergebnis |
| --- | --- |
| Branch | `feature/codex-jarvis-orchestrator` |
| Ausgangs-HEAD | `e614c26bfd20d016c4885e32af37f0e7291a1efd` |
| Arbeitsbaum | sauber |
| Upstream Fetch | `https://github.com/open-jarvis/OpenJarvis.git` |
| Upstream Push | `DISABLED` |
| Recovery-Bundle | vorhanden, vollständige Historie, 92 Referenzen, SHA-1-Repository |
| Bundle SHA-256 | `DF5DE4F5568EE314201E81EF507BCD868203C9FE9AF8BC4B81B1212FA9884766` |
| Restore-Probe | exakter Restore-HEAD, sauberer Restore-Arbeitsbaum |
| Restore-Integrität | `git fsck --full --strict` erfolgreich; nur erwartete dangling Commits |

## 1. Kurzurteil

OpenJarvis besitzt bereits viele Bausteine mit den Namen „Learning“,
„Optimization“, „Skills“ und „Evaluation“. Sie bilden aber keinen
einheitlichen, beweisgebundenen Phase-7-Lifecycle. Insbesondere fehlen ein
kanonisches `TraceEvaluation`-Modell, revisionierte Learning Candidates, eine
versionierte Skill Registry mit Zustandsautomat sowie eine sichere
Promotionsgrenze.

Die wichtigsten Sicherheitsbefunde sind:

1. `SkillExecutor` und `WorkflowEngine` führen Tools über den alten
   `ToolExecutor` und nicht über den kanonischen `ToolActionService` aus.
2. Entdeckte Skills werden bei aktivierter Skill-Konfiguration ohne
   Promotionszustand als Modelltools registriert. Optimierungs-Overlays können
   Beschreibungen und Few-Shot-Inhalte produktiv verändern.
3. Der `LearnedRouterPolicy` kann nach Konfiguration die produktive
   Modellauswahl beeinflussen und wird aus Trace-Outcome beziehungsweise
   numerischem Feedback aktualisiert; er ist kein reines Shadow-System.
4. Agent-Optimierer und Spec Search können Prompts, Agent-Konfigurationen,
   Toollisten und Routingparameter auf Datenträger verändern. Spec Search kann
   diese Änderungen abhängig vom Autonomiemodus direkt anwenden.
5. Mehrere Pfade behandeln unbestätigten Trace-Status, Nutzer-Score oder von
   einem Modell erzeugte Bewertung als Erfolgsgrundlage.
6. Traces und Optimierungsartefakte können rohe Anfragen, Nachrichten,
   Tool-Ein-/Ausgaben, Modellantworten und Few-Shot-Beispiele speichern oder an
   externe Modelle weitergeben.

Folgerung: Bestehende Learning-Komponenten dürfen nicht unverändert zum
Phase-7-Kern erklärt werden. Sichere Typen, Store-Muster und hermetische
Eval-Schnittstellen können übernommen werden; Aktivierung, Promotion,
Ausführung und produktives Routing müssen neu an die kanonischen
Task-/Policy-/Approval-/Verification-Grenzen gebunden werden.

## 2. Pflichtantworten

### 2.1 Welche Learning-Komponenten existieren bereits?

| Bereich | Vorhandene Komponenten | Heutige Funktion |
| --- | --- | --- |
| Trace-Basis | `core/types.py`, `traces/store.py`, `traces/collector.py` | Speichert Anfragen, Nachrichten, Schritte, Ergebnisse, Outcome, Feedback und Metadaten. |
| Learning-Abstraktionen | `learning/_stubs.py` | Interfaces für Router-, Query-, Reward- und Learning-Policies. |
| Routing Learning | `learning/routing/router.py`, `heuristic.py`, `learned_router.py` | Heuristische und trace-gelernte Modellauswahl; Registry-Einbindung. |
| Trainingsdaten | `learning/training/data.py` | Leitet SFT-, Präferenz- und Agent-Konfigurationspaare aus Traces ab. |
| Gewichtstraining | `learning/training/lora.py`, `learning/intelligence/*` | SFT-, GRPO- und LoRA-Trainingspfade sowie Checkpoint-Artefakte. |
| Agent-Optimierung | `learning/agents/dspy_optimizer.py`, `gepa_optimizer.py`, `ace_optimizer.py` | Optimiert Prompts/Few-Shots/Toollisten beziehungsweise erzeugt ACE-Playbooks. |
| Agent-Konfiguration | `learning/agents/agent_config_evolver.py` | Schreibt versionierte Agent-TOMLs und History-Dateien; bietet Rollback. |
| Skill Discovery | `learning/agents/skill_discovery.py` | Ermittelt wiederkehrende Toolsequenzen aus Traces und erzeugt ausführbare Skillvorschläge. |
| Skill Optimization | `learning/agents/skill_optimizer.py`, `skills/overlay.py` | Erzeugt `optimized.toml` mit Beschreibung und Few-Shot-Beispielen. |
| Orchestrierung | `learning/learning_orchestrator.py` | Verkettet Mining, Evaluation, Konfigurationsänderung, Skilloptimierung und optional LoRA. |
| Feedback/Optimierung | `learning/optimize/feedback/*`, `learning/optimize/*` | Sammelt Scores, lässt Modell-Judges bewerten, synthetisiert Benchmarks und sucht Optimierungskonfigurationen. |
| Spec Search | `learning/spec_search/*` | Teacher-Diagnose, typisierte Edits, Gates, direkte Applier, Pending Queue, SQLite-Sessions und Git-Checkpoints. |
| Evaluation | `evals/core/*`, `evals/datasets/*`, `evals/backends/*`, `evals/scorers/*`, `evals/trackers/*` | Umfangreiches Benchmark- und Experimentierframework. |
| Skill-Laufzeit | `skills/types.py`, `parser.py`, `loader.py`, `manager.py`, `executor.py`, `tool_adapter.py` | Discovery, Modellkatalog, Tool-Wrapping, sequenzielle Ausführung und Subskills. |
| Skill-Quellen | `skills/importer.py`, `skills/sources/*`, `skills/index.py` | Importiert Skills aus lokalen Git-Klonen beziehungsweise Hermes, OpenClaw, GitHub oder Skill-Index. |
| Task-Sicherheitsbasis | `tasks/*`, `tools/action_service.py` | Kanonische Tasks, Events, Approvals, Idempotenz, Risikoboden, Lanes und Postcondition-Verifikation. |
| Memory Candidates | `memory/candidates.py`, `memory/vault_models.py` | Bereits kontrollierter Candidate-/Approval-/CAS-Write-Pfad für Test-Vaults. |

Zusätzlich liegen 20 TOML-Beispielskills unter `src/openjarvis/skills/data/`.
Der produktive `SystemBuilder` scannt jedoch standardmäßig das konfigurierte
Skillverzeichnis und optional `./skills`; die 20 Paketdateien werden dort
nicht automatisch als vertrauenswürdige Built-ins registriert.

### 2.2 Welche Komponenten sind nur Evaluation oder Benchmarking?

Im Wesentlichen benchmarkorientiert sind:

- `evals/core` mit Datensatz-, Runner-, Split-, Scorer-, Event- und
  Reporting-Schnittstellen;
- die Benchmark-Datensätze und Benchmarkkonfigurationen unter `evals`;
- `evals/skill_benchmark.py`, das Bedingungen wie „Skills aus“, „Skills an“
  und optimierte Overlays gegeneinander vergleicht;
- die reine Trial-/Run-Erfassung in `learning/optimize/store.py`;
- Gate- und Vergleichslogik in `learning/spec_search/gate`, solange sie nur
  auf hermetische Ergebnisse angewendet und von den Appliers getrennt wird.

„Benchmarking“ bedeutet hier nicht automatisch „sicher“ oder „hermetisch“.
Vorhandene Eval-Datensätze und Backends können Hugging Face herunterladen,
Docker und Subprozesse starten, externe Agenten ausführen, Cloudmodelle
aufrufen oder generierten Code mittels `eval`/`exec` bewerten. Tracker können
an Weights & Biases oder Google Sheets senden. Diese Implementierungen sind
für den Phase-7-Harness nicht direkt verwendbar.

### 2.3 Welche Komponenten verändern produktives Verhalten?

| Komponente | Produktive Wirkung |
| --- | --- |
| `SystemBuilder` + `SkillManager` | `skills.enabled` ist standardmäßig wahr. Gefundene Skills werden als `skill_<name>`-Tools registriert und – sofern nicht explizit `disable_model_invocation` – dem Modell angeboten. |
| Skill Overlays | `optimized.toml` überschreibt beim Discovery-Lauf Skillbeschreibung und Few-Shot-Beispiele; diese Inhalte gelangen in den Modellkontext. |
| `LearnedRouterPolicy` | Kann über `AgentExecutor` das produktiv verwendete Modell auswählen, wenn `router_policy = "learned"` konfiguriert ist. `observe()` und `update_from_traces()` verändern seine Map. |
| `AgentConfigEvolver` | Schreibt Agent-Toollisten, `max_turns` und Systemprompts in Agentkonfigurationen. |
| DSPy/GEPA | Können Systemprompt, Few-Shots, Toolbeschreibungen, Toollisten, Temperatur und Turnlimits ableiten und über den Evolver schreiben. |
| `LearningOrchestrator` | Schreibt Agentkonfigurationen, kann Skilloptimierung starten und optional LoRA trainieren; bei fehlendem Evaluator markiert er Ergebnisse ohne unabhängiges Gate als akzeptiert. |
| Spec Search | Applier verändern `config.toml`, Agent-Systemprompts, Few-Shots, Toollisten und Toolbeschreibungen. Auto/Tiered-Modi können Edits direkt anwenden und in einem lokalen Git-Repository committen oder zurückrollen. |
| ACE | Schreibt ein Playbook und Zwischenartefakte. Das verändert allein noch keine Laufzeit, wird aber produktiv, sobald ein Agent dieses Playbook einliest. |
| Skill Import/Discovery | Schreibt Skillpakete oder automatisch entdeckte `skill.toml`-Dateien in konfigurierte Skillroots; sie werden beim nächsten Systemaufbau ohne Promotionszustand modell-sichtbar. |
| Gewichtstraining | SFT/GRPO/LoRA verändert Modellgewichte beziehungsweise Checkpoints und ist in Phase 7 ausdrücklich verboten. |

### 2.4 Welche Komponenten verwenden externe Dienste?

| Komponente | Mögliche externe Abhängigkeit |
| --- | --- |
| Skill Sources/Index | `git clone`/`git pull` von Hermes-, OpenClaw-, GitHub- und Index-Repositories; beliebige GitHub-URL bei entsprechender Konfiguration. |
| DSPy/GEPA/ACE | Optionale Drittbibliotheken und modellgestützte Optimierung; ACE wird aus einem Git-Repository installiert und nutzt standardmäßig einen OpenAI-Provider, sofern aktiviert. |
| Spec Search | Standard-Teacher ist ein Cloudmodell; Teacher und Student werden direkt über Engine-Objekte aufgerufen. |
| Feedback Judge/LLM Optimizer | Sendet Trace-Inhalte an den konfigurierten Inference-Backend; dieser kann lokal oder extern sein. |
| Eval Backends | OpenAI-kompatible, OpenAI-, Anthropic-, lokale/Ollama- und externe Harness-Backends. |
| Eval Datasets | Hugging-Face-Downloads, Git-Repositories, benchmarkeigene Downloads und gated datasets. |
| Eval Trackers | Weights & Biases und Google Sheets. |
| Eval Environments | Docker, lokale Subprozesse und externe Hermes-/OpenClaw-Prozesse. |
| Analytics/Telemetry | OpenJarvis besitzt Telemetrie- und Analytics-Pfade. Laut Konfigurationsvertrag soll Analytics keine Chat-Inhalte senden; Learning-Feedbackereignisse können dennoch Metadaten verlassen und müssen für hermetische Tests deaktiviert bleiben. |
| Embeddings/Modelle | Memory/Eval/Inference können Ollama oder andere lokale HTTP-Engines verwenden. Das ist zwar lokal betreibbar, aber nicht hermetisch und nicht Teil des Phase-7-Normaltests. |

Keiner dieser externen Pfade wird für die erste Phase-7-Implementierung oder
deren normale Tests benötigt. Dort gelten ausschließlich Fakes,
aufgezeichnete synthetische Events und temporäre Stores.

### 2.5 Welche Komponenten können Skills automatisch aktivieren?

Es existiert kein formaler `proposed -> ... -> active`-Automat. Stattdessen
entsteht faktische Aktivierung durch Discovery:

1. `SystemBuilder` prüft nur `config.skills.enabled` (Standard: `true`).
2. Er scannt `./skills` und das konfigurierte Nutzer-Skillverzeichnis.
3. `SkillManager` registriert jeden erfolgreich geladenen Skill.
4. `get_skill_tools()` wrappt jeden registrierten Skill als ausführbares Tool.
5. Der Modellkatalog blendet nur Skills mit
   `disable_model_invocation = true` aus.

`SkillsConfig.active = "*"`, `auto_discover = true`, `max_depth` und
`sandbox_dangerous` sind vorhanden, werden im produktiven Builder-/Executor-
Pfad aber nicht als belastbare Promotions-, Tiefen- oder Sandboxgrenzen
durchgesetzt.

`SkillManager.discover_from_traces()` schreibt automatisch erzeugte
Toolsequenzen als `skill.toml`. Diese werden nicht im selben Methodenaufruf
hot-aktiviert, aber beim nächsten Discovery-/Systemaufbau faktisch aktiv und
modell-sichtbar. Auch importierte Remote-Skills und erzeugte Overlays wirken
beim nächsten Aufbau ohne Review- oder Promotionsrecord.

### 2.6 Welche Komponenten umgehen Task, Policy oder ToolActionService?

| Pfad | Umgehung |
| --- | --- |
| `skills/executor.py` | Ruft `ToolExecutor.execute()` direkt auf. Es fehlen kanonische Taskidentität, dauerhafte Approvalbindung, Lane-Steuerung und Postcondition-Verifikation des `ToolActionService`. |
| `skills/tool_adapter.py` | Wrappt den obigen Executor als Modelltool und übernimmt dessen Erfolgsausgabe. |
| `workflow/engine.py` | Tool-Nodes rufen `system.tool_executor.execute()` direkt auf. |
| `learning/spec_search/diagnose/teacher_agent.py` | Führt Teacher-Diagnosetools direkt über `tool.fn(**args)` aus. |
| Spec-Search-Applier | Schreiben Konfigurations-, Prompt- und Tooldateien direkt und committen diese in einem separaten lokalen Git-Repository; es gibt keine kanonische Task-/Action-Service-Grenze. |
| Skill Import/Remove/Discovery | Schreiben oder löschen Skillverzeichnisse direkt auf Dateisystemebene. |
| Eval Framework | Startet je nach Backend direkte Modell-, Docker-, Git- oder Subprozessoperationen außerhalb des Phase-3-Task-/Approval-Modells. |
| Agent-/Skill-Optimierer | Schreiben Konfigurationen, Overlays und Playbooks ohne Phase-7-Candidate-, Review- und Promotionsrecord. |

Der vorhandene `ToolActionService` selbst besitzt bereits die richtige
Richtung: Proposalvalidierung, Task-/Session-/Correlation-Bindung,
CentralRiskPolicy, Allow-once-Approval, Lane-Ausführung, Risikoboden und
Postcondition-Verifikation. Er muss für jede zukünftige Skillausführung die
einzige Ausführungsgrenze werden.

### 2.7 Wo wird Modelltext als Wahrheit oder Erfolgsnachweis behandelt?

- Das alte `Trace.outcome` ist ein freier, grober String. Skill Discovery,
  Training Data Miner, Agent Config Evolver und Learned Router behandeln
  `outcome == "success"` und/oder numerisches Feedback als belastbare
  Erfolgslabels, ohne kanonische Task-/Policy-/Approval-/Verification-Prüfung.
- Der Feedback Judge rendert rohe Query-, Ein-/Ausgaben und Resultattext in
  einen Modellprompt und parst einen numerischen Modellscore. Dieser Score
  wird wie anderes Feedback gesammelt.
- Der Personal-Benchmark-Synthesizer kann eine gut bewertete Modellantwort als
  `reference_answer` übernehmen. Das macht die Antwort zur Referenz, obwohl
  keine Postcondition- oder Quellenverifikation vorliegen muss.
- DSPy, GEPA und Skill Optimizer verwenden Feedback und „beste“ Trace-
  Resultate als Trainings-/Few-Shot-Beispiele. Die Fallbacks übernehmen rohe
  `query`/`result`-Paare in produktiv geladene Overlays.
- Skill Discovery macht aus häufigen, als erfolgreich markierten
  Toolsequenzen direkt ausführbare Skilldefinitionen.
- Der alte `SkillExecutor` erklärt einen Skill zum Erfolg, wenn alle alten
  Toolresults `success` melden; Skillpostconditions werden nicht geprüft.
- Spec Search verwendet Teacher-Modelltext für Diagnosen und typisierte
  Editvorschläge. Benchmark-Gates begrenzen die Wirkung, ersetzen aber keine
  Provenance- oder Policy-Grenze; Auto-/Tiered-Modi können Modellvorschläge
  anwenden.
- Skillbeschreibungen, `SKILL.md`-Inhalte und Overlays werden als
  Modellinstruktion beziehungsweise Few-Shot-Kontext eingeblendet, obwohl
  importierte oder trace-abgeleitete Inhalte untrusted sein können.

Phase 7 muss deshalb ausschließlich deterministische, versionierte
`TraceEvaluation`-Regeln als Erfolgsquelle verwenden. Modell-Evaluatoren dürfen
nur ergänzende, klar markierte Hinweise liefern.

### 2.8 Welche Datenbanken oder Dateiformate existieren?

| Store/Format | Inhalt und Eigenschaften |
| --- | --- |
| Task SQLite Store | `schema_migrations`, Tasks, Events, Steps, Sources, Codex Items, Artifacts, Approvals, Usage und Recovery Checks; geeignetes Vorbild für Migrationen und Korrelation. |
| Trace SQLite Store | `traces`, `trace_steps`, `task_trace_events` und FTS5 über Query/Result; WAL und Foreign Keys. Speichert rohe Payloads. |
| Optimization SQLite Store | `optimization_runs`, `trial_results`; WAL, JSON-Spalten für Konfiguration, Reasoning, Scores, Fehler und Benchmarks; keine kanonische Phase-7-Registry. |
| Spec-Search SQLite Store | `learning_sessions`, `edit_outcomes`; WAL und Foreign Keys, teilweise `INSERT OR REPLACE`. |
| Memory Candidate SQLite Store | Revisionierbare Memory Candidates, Konflikte, Write Operations und Idempotenz; guter Sicherheitsreferenzpfad, aber fachlich getrennt vom Learning Store. |
| Skill TOML | `skill.toml` mit minimalem Manifest und sequenziellen Steps. |
| Skill Markdown | `SKILL.md` mit YAML-Frontmatter und freiem Markdownkörper. |
| Import-Provenance | `.source` als TOML-artige Sidecar-Datei mit Source/Commit. |
| Skill Optimization | `<overlay>/<skill>/optimized.toml` mit Beschreibung, Traceanzahl und Few-Shots. |
| Skill Index | `index.toml` plus Git-Checkout/Cache. |
| Skillpakete | Optionale `scripts/`, `references/` und `assets/`; derzeit kein verpflichtender Content Hash über das Gesamtpaket. |
| Agentkonfiguration | Agent-TOML, Prompt-Markdown, Few-Shot-Dateien und `.history`-Revisionen. |
| Spec Search | Pending-JSON, Session-/Diagnose-/Plan-JSON beziehungsweise JSONL/Markdown sowie lokales Git-Checkpoint-Repository. |
| ACE/Training | Text-Playbooks, JSON-Ergebnisse, Dataset-/Checkpoint-/Adapter-Artefakte. |
| Eval Results | TOML-Konfigurationen sowie JSON/JSONL/CSV/Tracker-Ausgaben abhängig vom Runner. |

Es gibt aktuell keinen einzigen persistenten Store, der unveränderliche
Evaluationen, revisionierte Learning Candidates, versionierte Skills,
Promotions-, Aktivierungs-, Rollback- und Metrikrecords gemeinsam mit
Idempotenz und Content Hashes abbildet.

### 2.9 Welche Learning-Pfade können sensible Daten speichern?

Hohes Risiko besteht in folgenden Pfaden:

- `TraceStore` speichert vollständige Query, Resultat, Nachrichten sowie jeden
  Step-Input und -Output; FTS indexiert Query und Resultat zusätzlich.
- `TrainingDataMiner` leitet daraus SFT-, Präferenz- und
  Konfigurationsbeispiele ab. Diese können private Konversationen und
  Tooldaten duplizieren.
- DSPy/GEPA/Skill Optimizer und ACE übernehmen Trace-Inhalte in Datasets,
  Few-Shots, Sidecars, Playbooks und Zwischenartefakte.
- Der Feedback Judge und Spec-Search-Teacher können rohe Trace-/Promptdaten an
  ein extern konfiguriertes Modell senden.
- Der Personal-Benchmark-Synthesizer persistiert Query und Resultat als
  Benchmarkfall und Referenzantwort.
- Spec Search speichert Diagnosen, Modellvorschläge, Pläne, Promptdiffs,
  Teacher-Traces und Fehlerdaten in SQLite, JSON/JSONL und Markdown.
- Eval-Runs können Prompts, Antworten, Tooltraces und Scores in lokalen
  Resultaten oder externen Trackern ablegen.
- Skill Overlays können rohe Query-/Resultatpaare als produktive Few-Shots
  speichern. Importierte Skillpakete können außerdem unbeabsichtigte Secrets
  in Markdown, TOML, Skripten oder Assets enthalten.
- Nutzerfeedback ist derzeit überwiegend ein unmittelbarer numerischer
  Trace-Score. Es fehlt ein revisioniertes, widerrufbares und eindeutig an
  Task plus Antwort gebundenes Feedbackmodell.

Vor jeder Phase-7-Persistenz sind Redaction, Größenlimits,
Provenance-Klassifikation, Secret Scanning, Retention-Regeln und ein Verbot
roher privater Testdaten erforderlich. Interne Chain-of-Thought-Inhalte dürfen
nie gespeichert werden.

### 2.10 Welche Bestandteile können sicher übernommen werden?

Sicher wiederverwendbar sind nur klar abgegrenzte Teile:

- kanonische Taskstatus-/Outcome-Prinzipien aus `tasks/types.py` und die
  terminalen Sicherheitsprüfungen des `TaskOrchestrator`;
- Task Store als Muster für Migrationen, WAL, Foreign Keys, Events,
  Idempotenz, Artifacts, Approvals und Recovery;
- `ToolActionService` als alleinige Ausführungsgrenze einschließlich
  Taskidentität, CentralRiskPolicy, Risikoboden, Lanes, Allow-once und
  Postcondition-Verifikation;
- Phase-4-Patterns aus Memory Candidates: explizite Candidate-Erzeugung,
  Provenance, Konflikte, Idempotenz, Approval, Compare-and-Swap und
  Recovery-Artefakte. Learning und Memory bleiben separate Domänen;
- EventBus-, Artifact- und Korrelationsmuster der Phasen 3 bis 6;
- reine Eval-Protokolle, deterministische Scorer-Interfaces, Split-Idee und
  Reporter, wenn alle Backends durch hermetische Fakes ersetzt werden;
- typisierte Spec-Search-Edit-/Gate-Modelle und die Idee eines
  Regressionsgates, jedoch nicht die direkten Applier, Teacher-Tools oder
  Git-Checkpoint-Seiteneffekte;
- Parser-/Loader-Code als Migrationsleser für vorhandene Skillformate, aber
  nicht als neue Vertrauensgrenze;
- vorhandene Security-Scanner- und Signing-Primitiven als Bausteine, nach
  Erweiterung um Paket-Hash, unbekannte Felder, Prompt Injection, Secrets,
  verbotenen Code, Größenlimits und sichere URL-/Toolbindung;
- 20 TOML-Beispielskills ausschließlich als untrusted Legacy-Fixtures für
  Parser- und Migrationstests, nicht als automatisch aktive Skills.

### 2.11 Welche Bestandteile müssen deaktiviert, umgebaut oder isoliert werden?

| Maßnahme | Komponenten |
| --- | --- |
| Deaktivieren | LoRA/SFT/GRPO und jedes Gewichtstraining; Spec-Search-Auto-/Tiered-Applier; produktives `LearnedRouterPolicy.observe()`; automatische Skillaktivierung; automatische Prompt-/Config-Übernahme. |
| Umbauen | `SkillManifest`, Parser, Loader, Importer, Registry, Executor, Tool Adapter, Discovery und Overlays auf strikte Schemas, Hashes, Provenance, Zustandsautomat, Versionspinning, Promotion und Rollback. |
| Kanonisch anbinden | Jede Skillausführung und jeder Workflow-Toolstep an Task -> `ToolProposal` -> `ToolActionService` -> Policy -> Approval -> Verification -> Outcome -> Trace. |
| Isolieren | Bestehendes `evals`-Framework hinter einer hermetischen Phase-7-Fassade; Docker-, Subprozess-, Download-, Cloud-, W&B-, Sheets-, `eval`- und `exec`-Pfade bleiben aus. |
| Shadow-only | Routing Learning. Empfehlungen werden protokolliert und verglichen, verändern aber weder Route noch Modell. |
| Quarantäne | Importierte Skills, Fremdskills, Modellvorschläge, Webseiten-, Dokument-, Tool-, Memory- und externe Trace-Inhalte bis Schema-, Provenance-, Secret-, Injection-, Capability- und Hashprüfung bestanden sind. |
| Datenhärtung | Trace-/Feedback-/Optimierungsdaten redigieren, task- und antwortgebunden revisionieren, Retention und Artifacts einführen; rohe private Payloads nicht in Git oder Testkorpora übernehmen. |
| Entfernen aus Trust Boundary | Alter `ToolExecutor` darf kein Phase-7-Skill- oder Promotionspfad sein; direkte `tool.fn`, Dateisystem-Applier und Skill-Delete/Import-Operationen benötigen zentrale Actions. |

Zusätzlich muss der neue Learning Runtime technisch daran gehindert werden,
den Integrationsarbeitsbaum zu ändern, zu mergen oder zu pushen. Ein
`code_improvement_proposal` darf nur ein revisioniertes Proposal bleiben; ein
späterer Testlauf darf ausschließlich ein synthetisches Repository und einen
isolierten Worktree verwenden.

### 2.12 Welche Funktionen werden erst in Phase 8 oder nach dem Pilot freigegeben?

Bis zu einer gesonderten Freigabe bleiben zurückgestellt:

- Zugriff, Migration, Bereinigung, Umbenennung oder Neuordnung des echten
  Obsidian-Vaults und der 46 echten Notizen;
- Schreiben von Learning- oder Memory-Ergebnissen in das echte Vault;
- Verwendung realer privater Tasks oder Traces als Lern-, Test- oder
  Benchmarkkorpus;
- produktive Umschaltung durch gelerntes Agent-/Modellrouting;
- automatische Promotion oder Aktivierung extrahierter/importierter Skills;
- Ausführung heruntergeladenen oder selbstgenerierten Codes;
- reales Self-Improvement mit Patchübernahme, Merge oder Push;
- Cloud-Teacher, externe Modell-Judges, Remote-Skill-Hubs und Telemetrie in
  normalen Learning-Läufen;
- reale Browserprofile, Nutzerkonten oder externe Nebenwirkungen;
- Codex-Live-Turns;
- dauerhafte oder automatische Approvals, `full_access` und Level-4-Aktionen;
- Modellgewichtstraining. Eine spätere Zulassung wäre ein eigenes,
  ausdrücklich genehmigtes Vorhaben und folgt nicht automatisch aus Phase 8;
- breite produktive Skillfreigabe. Nach dem Pilot sind belastbare Stichproben,
  Sicherheits- und Regressionsnachweise sowie eine bewusste Nutzerentscheidung
  erforderlich.

## 3. Quellenbelege im Repository

Die zentralen Befunde sind insbesondere in folgenden Dateien nachvollziehbar:

- `src/openjarvis/system/builder.py`: Skill Discovery und Toolregistrierung;
- `src/openjarvis/core/config.py`: Learning-, Spec-Search-, Skill-, Trace- und
  Externalitätsdefaults;
- `src/openjarvis/tasks/types.py`, `tasks/orchestrator.py`, `tasks/store.py`:
  kanonische Task-/Outcome-/Persistenzbasis;
- `src/openjarvis/tools/action_service.py`: zentrale Policy-, Approval-, Lane-
  und Verification-Grenze;
- `src/openjarvis/tools/_stubs.py`: alter direkter `ToolExecutor`;
- `src/openjarvis/skills/{types,parser,loader,manager,executor,tool_adapter,importer,overlay}.py`:
  heutiger Skill-Lifecycle und seine Lücken;
- `src/openjarvis/workflow/engine.py`: direkte Workflow-Toolausführung;
- `src/openjarvis/learning/learning_orchestrator.py` und
  `learning/agents/*`: Trace Mining, Optimierung, Discovery, Config Writes und
  Gewichtstraining;
- `src/openjarvis/learning/routing/learned_router.py` und
  `src/openjarvis/agents/executor.py`: produktiv schaltbarer Learned Router;
- `src/openjarvis/learning/optimize/*`: Feedback Judge, Benchmark-Synthese,
  Optimierung und SQLite-Trials;
- `src/openjarvis/learning/spec_search/*`: Teacher, Edits, Applier, Gates,
  Pending Queue, Session Store und Git-Checkpoints;
- `src/openjarvis/traces/store.py`: rohe Trace-Persistenz und FTS;
- `src/openjarvis/memory/{candidates,vault_models}.py`: kontrollierbare
  Candidate-/Approval-/CAS-Muster;
- `src/openjarvis/evals/*`: Benchmarking, externe Backends/Tracker/Downloads
  und nicht-hermetische Evaluatoren.

## 4. Verbindliche Architekturentscheidung für die nächste Phase-7-Änderung

Der nächste Produktionscode-Commit darf nicht vorhandene automatische
Learning-Pfade aktivieren. Er soll zuerst ein neues, versioniertes und
deterministisches `TraceEvaluation`-Modell samt hermetischen Tests einführen.
Danach folgen in getrennten Commits:

1. kanonische Outcome-Klassifikation aus Task-, Policy-, Approval-, Tool- und
   Verification-Daten;
2. revisionierte, evidenzgebundene Learning Candidates mit Deduplication,
   Conflict Detection, Quarantine und Independence-Zählung;
3. transaktionaler Candidate-/Skill-Zustandsautomat;
4. striktes versioniertes Skillmanifest und persistente Registry;
5. ausschließliche Skillausführung über den `ToolActionService`;
6. hermetischer Development-/Verification-/Holdout-Harness;
7. Routingempfehlungen ausschließlich im Shadow Mode;
8. explizite, task- und antwortgebundene Feedbackrevisionen;
9. API und bestehende UI erst nach stabiler Domain- und Store-Schicht.

Dieser Audit selbst aktiviert keine dieser Komponenten und verändert kein
Produktionsverhalten.
