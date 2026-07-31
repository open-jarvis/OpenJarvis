# Phase 7: Deterministische Trace Evaluation

Stand: 2026-07-31

Schema: `1.0`

Evaluator: `openjarvis.deterministic_trace_classifier` in Version `1.0.0`

## Zweck und Grenze

Die Trace-Evaluation-Domain erzeugt aus einem streng typisierten,
metadatenbasierten Task-/Trace-Snapshot ein unveränderliches und
reproduzierbares `TraceEvaluation`-Ergebnis.

Der Ablauf ist ausschließlich:

```text
Task-/Trace-Snapshot
-> Normalisierung
-> deterministische Klassifikation
-> Confidence aus kanonischer Evidenz
-> input_digest und evaluation_hash
-> unveränderliches TraceEvaluation
```

Die Schicht erzeugt keine Candidates, verändert keine Skills, schreibt keine
Datenbank, aktiviert keinen Router und ruft weder Tools noch Modelle auf. Sie
öffnet insbesondere keinen bestehenden Task- oder Trace-Store.

## Module

| Modul | Verantwortung |
| --- | --- |
| `learning/evaluation/models.py` | Geschlossene Enums sowie strikt validierte und unveränderliche Input-, Evidence- und Outputmodelle |
| `learning/evaluation/evidence.py` | Klassenspezifische Anforderungen an verifizierte Evidenz für hohe Confidence |
| `learning/evaluation/normalization.py` | Sortierung, Legacy-Reduktion, read-only Runtime-Adapter, kanonisches JSON und SHA-256 |
| `learning/evaluation/classifier.py` | Explizite Prioritätsregeln, Klassifikation, Confidence und Evaluationserzeugung |

Alle Pydantic-Modelle verwenden `extra="forbid"` und `frozen=True`.
Unbekannte Felder werden abgelehnt; nach der Erzeugung kann kein Feld in place
geändert werden.

## TraceEvaluation-Schema

`TraceEvaluation` enthält:

| Feld | Bedeutung |
| --- | --- |
| `schema_version` | Version des Ergebnisformats; aktuell `1.0` |
| `evaluation_id` | Opaque Identität dieser konkreten Evaluation; nicht Teil des fachlichen Hashes |
| `evaluator_id` | Identität des deterministischen Evaluators |
| `evaluator_version` | Fachliche Version der Regeln |
| `task_id`, `session_id`, `correlation_id`, `trace_id` | Korrelation ohne Payloadkopie |
| `task_type` | Eng begrenzter kanonischer Typbezeichner |
| `requested_goal` | Redigierte, längenbegrenzte Zusammenfassung, kein vollständiger Prompt |
| `terminal_task_state` | Geschlossener `TaskStatus` |
| `task_outcome` | Geschlossenes `CanonicalTaskOutcome` |
| `evaluation_class` | Deterministisch ermittelte kanonische Ergebnisklasse |
| `verification_state` | Kanonischer Verifikationszustand |
| `approval_state` | Kanonischer Approval-Zustand |
| `policy_result` | Kanonische Policy-Entscheidung |
| `evidence_state` | Ausreichend, unzureichend, widersprüchlich oder unbekannt |
| `tool_result_summary` | Ausschließlich Zähler und Metadaten; keine Toolausgabe |
| `failure_category` | Geschlossene fachliche Fehlerkategorie |
| `confidence` | `high`, `medium` oder `low` |
| `confidence_basis` | Maschinenlesbare Begründung der Confidence |
| `evidence_references` | Sortierte, metadata-only Evidence-Referenzen |
| `warnings` | Redigierte, begrenzte, nicht blockierende Warnungen |
| `created_at` | Normalisierter UTC-Zeitpunkt dieser Evaluation |
| `input_digest` | SHA-256 des normalisierten Inputs |
| `evaluation_hash` | SHA-256 des fachlichen Ergebnisses |

`evaluation_id` und `created_at` dürfen zwischen zwei Evaluationen variieren.
Sie sind absichtlich nicht Teil von `evaluation_hash`.
Das Modell berechnet den Hash bei der Validierung erneut und lehnt ein
fachlich verändertes Ergebnis mit einem alten oder erfundenen Hash ab.

## Geschlossene Ergebnisklassen

Die kanonischen Werte sind:

- `completed`
- `completed_with_warning`
- `partial`
- `interrupted`
- `canceled`
- `policy_denied`
- `approval_denied`
- `approval_timeout`
- `verification_failed`
- `tool_failed`
- `browser_failed`
- `insufficient_evidence`
- `conflicting_evidence`
- `budget_exceeded`
- `unsafe_request`
- `unknown_failure`

`success` ist weder eine Ergebnisklasse noch ein kanonisches Task-Outcome.

Weitere geschlossene Enums decken Task-Outcome, Verification, Approval,
Policy, Evidence, ToolAction-Endzustand, Browser-Recovery, Budget, bekannte
externe Wirkung, Fehlerkategorie, Confidence, Evidence-Typ, Evidence-Quelle
und Trusted Boundary ab.

## EvaluationInput

`EvaluationInput` ist ebenfalls unveränderlich und enthält nur die für die
Klassifikation notwendigen Metadaten:

- Task-, Session-, Correlation- und Trace-ID;
- redigiertes Ziel und Tasktyp;
- Taskstatus, kanonisches Outcome und relevante Statusübergänge;
- Verification-, Approval-, Policy-, Evidence-, Budget- und
  Browser-Recovery-Zustand;
- metadata-only ToolAction-Endzustände;
- Nutzerabbruch, Turn-Interrupt und bekannte beziehungsweise unbekannte
  externe Wirkung;
- relevante Event- und Artifact-IDs;
- Evidence-Referenzen;
- begrenzte Warnungen;
- optional strikt begrenzte, ausdrücklich untrusted Legacy-Hinweise.

Chats, Webseiten, Notizinhalte, Toolausgaben, Browserinhalte, vollständige
Prompts, vollständige Responses und Chain-of-Thought sind keine Felder des
Schemas und werden durch `extra="forbid"` abgelehnt.

## Normalisierung und Runtime-Kompatibilität

Vor der Klassifikation werden:

- Status und Outcomes in geschlossene Enums überführt;
- State Events nach Sequenz und ID sortiert;
- ToolActions nach Action-ID sortiert;
- Evidence nach Evidence-ID sortiert;
- Event-/Artifact-IDs und Warnungen dedupliziert und sortiert;
- Zeitpunkte in UTC normalisiert;
- kollidierende IDs mit unterschiedlichem Inhalt abgelehnt.

`snapshot_from_runtime()` kann bestehende `TaskRecord`-, `TaskEvent`-,
`ToolAction`-, Approval-, Policy-, Browser-Recovery- und Usage-Wertobjekte
read-only adaptieren. Fehlende Daten werden sicher als `unknown` oder
`not_evaluated` abgebildet. Der Adapter liest keine Stores und kopiert weder
`TaskRecord.description`/`result` noch Event-Payloads oder Tool-
`output_summary`.

Der Aufrufer muss ein bereits redigiertes `requested_goal` übergeben. Damit
wird verhindert, dass ein Runtime-Adapter stillschweigend einen privaten
Tasktext in Learning-Daten kopiert.

## Klassifikationspriorität

Die Regeln werden in folgender Reihenfolge geprüft:

1. `unsafe_request`
2. `policy_denied`
3. expliziter Nutzerabbruch beziehungsweise terminales Cancel
4. `approval_denied`
5. `approval_timeout`
6. `budget_exceeded`
7. `interrupted`, sofern kein vollständig verifizierter terminaler Erfolg
   vorliegt
8. unbekannte externe Wirkung als `unknown_failure`
9. `verification_failed`
10. `conflicting_evidence`
11. `insufficient_evidence`
12. `browser_failed`, wenn Browser-Recovery die kanonische Ursache ist
13. `tool_failed`, wenn keine spezifischere Ursache vorliegt
14. `partial`
15. `completed_with_warning`
16. `completed`
17. `unknown_failure` als sicherer Fallback

Die Reihenfolge sorgt insbesondere dafür, dass Policy- oder Approval-Denial
nicht als Toolfehler gezählt werden. Ein Nutzerabbruch ist ebenfalls kein
Tool-, Skill- oder Systemfehler.

## Bedingungen für completed

`completed` und `completed_with_warning` erfordern gemeinsam:

- `TaskStatus.DONE`;
- `task_outcome` ist `completed` oder `completed_with_warning`;
- Verification ist `passed`;
- Approval ist `approved` oder ausdrücklich `not_required`;
- Policy ist `allowed` oder ausdrücklich `not_required`;
- Evidence ist `sufficient`;
- Budget ist innerhalb der Grenze oder nur im Warning-Bereich;
- externe Wirkung ist `known` oder `none`;
- keine fehlgeschlagene, denied, canceled, pending oder unbekannte ToolAction;
- keine ToolAction mit unbekannter Wirkung.

Ein abgeschlossenes Outcome ohne Verification wird
`insufficient_evidence`. Eine unbekannte externe Wirkung wird
`unknown_failure` und niemals Erfolg.

`completed_with_warning` benötigt zusätzlich ein kanonisches Warning-Outcome,
eine nicht blockierende Warnung oder einen Budget-Warning-Zustand. `partial`
bleibt stets eine eigene, nicht vollständige Erfolgsklasse.

## Warum Modelltext und Exitcode kein Erfolgsbeweis sind

Ein Modell kann einen erfolgreichen Zustand behaupten, ohne dass eine externe
Wirkung eingetreten ist. Entsprechend beweisen auch Exitcode 0 oder HTTP 200
nur einen Transport- beziehungsweise Prozesszustand, nicht die fachliche
Postcondition.

Darum berücksichtigt die Klassifikation nicht:

- Modelltext mit „success“;
- den alten freien Trace-Wert `outcome="success"`;
- numerisches Nutzerfeedback;
- Modell-Judge-Scores;
- Exitcode 0;
- HTTP 200;
- `SkillExecutor.success=True`;
- Teacher- oder Optimizer-Empfehlungen.

Diese Signale können ausschließlich als begrenzte `LegacyHints` aufgenommen
werden. `LegacyHints.untrusted` ist fest `true`. Die Hinweise verändern weder
`evaluation_class` noch den Evidenzsatz und zählen nicht als Verification.

## Evidence-Referenzen

Eine `EvidenceReference` enthält ausschließlich:

- `evidence_id`;
- geschlossenen `evidence_type`;
- geschlossenen `source_kind`;
- `source_id`;
- SHA-256-`digest`;
- Evidence-Verification-Zustand;
- Trusted Boundary;
- UTC-`created_at`.

Zulässige Evidence-Typen sind Taskstatus, Task-Outcome, Verification, Policy,
Approval, Toolresultat, Browser-Recovery, Budget, Nutzerabbruch und
Artifact-Digest. Es findet keine modellgestützte Quellenbewertung statt.

Für hohe Confidence müssen die für die jeweilige Klasse notwendigen
Evidence-Typen verifiziert aus `canonical_runtime` oder `explicit_user`
vorliegen. Externe oder Legacy-Inhalte gelten nicht als trusted Evidenz.

## Confidence

Confidence ersetzt keine Evidenz und kann die Ergebnisklasse nie ändern:

- `high`: vollständiger klassenspezifischer, verifizierter und trusted
  Evidenzsatz;
- `medium`: eine spezifische kanonische Ursache liegt vor, aber
  nicht-blockierende Evidence-Metadaten fehlen;
- `low`: unvollständige, unbekannte oder widersprüchliche Daten oder vorhandene
  Legacy-Hinweise.

`confidence_basis` dokumentiert diese Entscheidung mit geschlossenen Werten.
Ein hoher Confidence-Wert kann fehlende Verification, offene Approvals,
Policy-Denial oder unbekannte Wirkung nicht überstimmen.

## Determinismus und Hashing

Die kanonische Serialisierung verwendet UTF-8-JSON mit:

- sortierten Feldnamen;
- stabilen Enum-Werten;
- stabil sortierten Evidence-, Event-, Artifact- und ToolAction-Tupeln;
- expliziten `null`-Werten;
- festen JSON-Separatoren;
- keiner Dict-Reihenfolgeabhängigkeit.

`input_digest` ist SHA-256 über den vollständig normalisierten Input.

`evaluation_hash` ist SHA-256 über das fachliche Ergebnis einschließlich
Evaluator-ID/-Version und `input_digest`. Ausgeschlossen sind:

- `evaluation_id`;
- `created_at`;
- `evaluation_hash` selbst.

Zwei Evaluatorinstanzen erzeugen für denselben normalisierten Input und
dieselbe Evaluatorversion denselben `input_digest` und `evaluation_hash`.
Eine neue Evaluatorversion erzeugt eine neue Evaluation und einen anderen
fachlichen Hash, referenziert aber weiterhin dieselbe Input-Identität.

## Datenschutz und Sicherheitsgrenzen

- Keine Datenbank und kein Runtime-Store wird geöffnet.
- Es gibt keine Netzwerk-, Ollama-, Cloudmodell- oder Codex-Abhängigkeit.
- Es gibt keine Modell-, Tool- oder Browserausführung.
- Rohe Toolausgaben sind nicht Teil von `ToolActionSnapshot` oder
  `ToolResultSummary`.
- IDs, Digests und begrenzte redigierte Zusammenfassungen ersetzen Payloads.
- Unbekannte Felder, Chain-of-Thought-Felder und rohe private Payloadfelder
  werden abgelehnt.
- Typische Secret-Muster in redigierten Textfeldern werden abgelehnt.
- Normale Tests verwenden ausschließlich synthetische Wertobjekte und keinen
  persistenten Store.

## Bekannte Grenzen dieses Commits

- Es gibt noch keinen persistenten Learning Store und keine Migration.
- Evaluationen werden noch nicht automatisch aus produktiven Task-Stores
  erzeugt.
- Es gibt noch keine Candidate Extraction, Skill Registry, Promotion oder
  Skillausführung.
- Routing Learning, Feedbackrevisionen, API und UI sind nicht angebunden.
- Der Runtime-Adapter ist absichtlich konservativ: Fehlende kanonische Daten
  bleiben `unknown` und können keinen Erfolg erzeugen.
- Das Schema bewertet keine fachlichen Inhalte mit einem Modell. Spätere
  optionale Modellhinweise dürfen die kanonischen Felder nicht überschreiben.

## Spätere Phase-7-Nutzung

Nach separater Freigabe dient `TraceEvaluation` als alleinige klassifizierte
Eingabe für:

- Evidence-basierte Candidate Extraction;
- Deduplizierung, Konflikt- und Independence-Prüfung;
- hermetische Skilltests und Promotion Gates;
- verifizierte Skillmetriken;
- Routingempfehlungen im Shadow Mode;
- revisioniertes Nutzerfeedback;
- Learning-API und bestehende Jarvis-UI.

Keine dieser späteren Komponenten ist Bestandteil dieses Commits.
