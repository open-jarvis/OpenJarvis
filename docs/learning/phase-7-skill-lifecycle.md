# Phase 7: kontrollierter Skill-Lifecycle

Stand: 31. Juli 2026. Dieses Dokument beschreibt ausschließlich den
freigegebenen Phase-7-Arbeitsblock. Phase 8, Shadow Routing, API- und
Frontend-Integration sind nicht enthalten.

## Vertrauensgrenze

OpenJarvis ist die einzige Autorität für Candidate-Zustand, Manifestprüfung,
Versionierung, Verifikation, Promotion, Aktivierung, Deprecation, Rollback,
Ausführung, Metriken und Audit. Modelltext, Legacy-Skills, Dateien und
Webinhalte können keine Transition, kein Approval und keine Capability
erteilen.

Der kontrollierte Pfad lautet:

```text
under_review -> testing -> verified -> promotion_pending
             -> explicit allow_once -> promoted
             -> explicit activation + healthcheck -> active
             -> deprecated oder rolled_back
```

Fehlgeschlagene Verifikation führt nach `verification_failed` und kann nur
durch Review nach `under_review` oder `rejected` gelangen. `rejected` bleibt
terminal. Ein Sicherheits- oder Integritätsproblem kann jeden nicht-terminalen
Zustand nach `quarantined` führen. Eine deprecated Version kann ausschließlich
im atomaren, evidenzgebundenen Rollback wieder aktiv werden.

## Versioniertes SkillManifest

`openjarvis.learning.skills.SkillManifest` ist ein unveränderliches
Pydantic-Modell mit `extra="forbid"`. Es enthält die in Phase 7 geforderten
Identitäts-, Herkunfts-, Schema-, Tool-, Capability-, Risiko-, Lane-, Budget-,
Retry-, Test-, Verifikations-, Rollback- und Metrikfelder. Semantischer Inhalt
wird als sortiertes kanonisches JSON serialisiert und mit SHA-256 gebunden.

Die Validierung verweigert unter anderem:

- unbekannte Felder, ungültige SemVer und naive Zeitstempel;
- Secrets, Tokens, Cookies, private Chats und Chain-of-Thought-Inhalte;
- URLs, `full_access`, automatisches Approval und Autoritätsbehauptungen;
- `eval`, `exec`, Pickle, Shellbefehle und sonstigen ausführbaren Inhalt;
- unbekannte Tool-IDs, Capability-Abweichungen, Risk-Floor-Senkung und
  nicht unterstützte Execution Lanes;
- leere Evidence-, Precondition- oder Postcondition-Bindungen.

Manifestobjekte werden nie in-place geändert. Ihr `status` dokumentiert den
registrierten Inhalt; der aktuelle Lifecycle-Zustand liegt als separate,
CAS-geschützte Registry-Projektion vor. Eine neue Bedeutung erfordert eine neue
semantische Version und einen neuen Content Hash.

## Registry und Migration 2

Migration 1 blieb unverändert. Migration 2 wird wie alle Migrationen vor der
Ausführung checksum-geprüft. Die SQLite-Laufzeit behält Foreign Keys und WAL.
Die Mindesttabellen sind:

- `skill_manifests`, `skill_versions`, `skill_candidate_links`;
- `skill_verification_runs`, `skill_test_results`;
- `skill_promotion_records`, `skill_activation_records`;
- `skill_deprecation_records`, `skill_rollback_records`;
- `skill_execution_records`, `skill_metric_snapshots`.

Ergänzende Projektionen und Auditgrenzen sind `skill_version_heads`,
`skill_scope_heads`, `skill_execution_pins`, `skill_idempotency_records`,
`skill_audit_events`, `candidate_conflict_resolutions`,
`skill_package_records` und `skill_import_quarantine_records`.

Die Registry erzwingt eine stabile Skill-ID, genau eine SemVer pro Inhalt,
monotone Versionen, einen expliziten `supersedes_version`-Vorgänger,
append-only Manifeste und vollständig lesbare Historie. Jeder Read validiert
Payload-Hash und Indexspalten erneut. Mutationen besitzen Idempotency Records;
Heads und aktive Scopes werden per Compare-and-Swap fortgeschrieben.

Runtime-Datenbanken und Paketdateien werden nicht in Git abgelegt.

## Hermetische Verifikation

`SkillTestCase`, `SkillTestResult`, `SkillTestRun` und
`SkillVerificationRecord` sind versioniert, unveränderlich und hashgebunden.
Ein Verifikationslauf akzeptiert ausschließlich `hermetic=True` und verlangt
mindestens:

- positive und negative Tests;
- Input- und Output-Schema;
- Policy, Capability und Risk Floor;
- Postconditions;
- bekannte Wirkung und kanonisches Outcome.

Verifikation wird verweigert, solange ein Conflict Link oder Quarantänegrund
offen ist. Aktivierungsbereitschaft verlangt zusätzlich mindestens drei
positive synthetische Ausführungen, zwei Fixtures und einen getrennten
Holdout. Development und Holdout sind explizit klassifiziert.

## Explizite Konfliktauflösung

Ein Konflikt wird nur durch einen hashgebundenen
`ConflictResolutionRecord` geschlossen. Zulässige Entscheidungen sind
`keep_both_scoped`, `reject_left`, `reject_right`, `supersede_left`,
`supersede_right` und `unresolved`. Beteiligte Candidate-Revisionen,
Entscheidung, Actor, Reason, Evidence, Correlation und Idempotency werden in
einer Transaktion gebunden. `unresolved` schließt nichts. Nutzerkorrektur oder
Modelltext wählen nie automatisch einen Gewinner.

## Promotion und Aktivierung

Promotion besteht aus zwei Mutationen:

1. `request_promotion` prüft Verifikation, Manifest- und Toolbindung,
   Candidate-Revision, Konflikte, Quarantäne und optional die volle
   Aktivierungsbereitschaft. Ergebnis ist `promotion_pending`.
2. `decide_promotion` akzeptiert nur den Enumwert `allow_once` oder `deny`.
   Allow-once ist auf lokale Nutzer oder deterministische Testakteure
   beschränkt. Freies oder gesprochenes „ja“ ist kein gültiger Wert.

Eine erfolgreiche Promotion aktiviert nicht automatisch. Aktivierung verlangt
nochmals eine explizite Allow-once-Entscheidung, den erwarteten aktiven Scope,
Scope-Revision, Candidate- und State-Revision, vollständige
Aktivierungsverifikation und einen an Manifest-ID, Version und Hash gebundenen
Healthcheck. Bei Konkurrenz gewinnt genau ein Scope-CAS.

Wird eine neue Version aktiv, bleibt die vorherige Historie unverändert und
die vorherige Version wird in derselben Transaktion deprecated. Laufende Tasks
behalten ihren bereits gespeicherten Version Pin; nur neue Tasks sehen die neue
aktive Version.

## Deprecation und Rollback

Deprecation erzeugt Candidate-Revision, Skill-Head, Deprecation Record und
Audit Event atomar. Bei einer aktiven Version erhöht sie außerdem die
Scope-Revision. Die Scope-Projektion bleibt als CAS-Tombstone erhalten, aber
die Auswahl verweigert jede nicht aktive Version. Bereits gepinnte Tasks
dürfen kontrolliert zu Ende laufen.

Rollback verlangt aktuelle und Zielversion, Scope-CAS, Actor, Reason,
Evidence, Idempotency, Allow-once und einen neuen Ziel-Healthcheck. Es erzeugt
einen Activation- und Rollback-Record, markiert die ersetzte Version
`rolled_back`, reaktiviert exakt die Zielversion und verändert keine
historischen Records.

## Verifizierte Metriken

Metrik-Snapshots sind append-only und versioniert. Eine Beobachtung zählt nur,
wenn eine persistierte `TraceEvaluation` exakt zu Skill-ID, Version,
Execution-ID, Task, Session und Correlation passt. Toolnutzung und Laufzeit
kommen aus dem Skill Execution Record. Tokenwerte werden nur mit einem
kanonischen Usage-Evidence-Digest akzeptiert.

Erfasst werden Attempts, verifizierte Erfolge/Fehler, Partial, Unknown,
Policy-Denial, Approval-Denial/-Timeout, Verification Failure, Canceled,
Interrupted, Rollbacks, Regressionen, Laufzeit, Tokens, Toolnutzung und letzter
verifizierter Zeitpunkt. Policy-Denial ist kein Skillfehler; Approval-Denial
ist kein Toolfehler. Jede Quote enthält den Nenner `sample_size`, und weniger
als 30 Beobachtungen setzen `small_sample_warning`. Eine Kennzahl kann niemals
Promotion auslösen.

## Lokaler Export und Quarantäne-Import

Das JSON-Paket enthält nur Manifest, versionierte Testfälle, Provenance,
Evidence Digests, Registry-Revision und Content-/Package-Hashes. Es enthält
keine Executions, Tasktexte, Sessions, privaten Traces, Testresultate oder
Secrets. Der Integritätsmodus heißt bewusst `sha256_only_unsigned`; es wird
keine Signatur-Infrastruktur vorgetäuscht.

Export und Reimport akzeptieren nur lokale `.json`-Pfade. Der Import prüft
Größe, UTF-8, striktes Schema, sämtliche Hashes, Tool-/Capability-Bindung,
Secrets, Injection, URLs und verbotenen Code. Er registriert und aktiviert
nichts und schreibt ausschließlich einen quarantänisierten Import Record.

## Bekannte Grenzen

- Subskills sind derzeit nicht Teil des vertrauenswürdigen Manifests. Dadurch
  ist jeder ungebundene rekursive Aufruf fail-closed; eine spätere Erweiterung
  benötigt exakte Skill-ID-/Versionsbindungen und neue Verifikation.
- Rollback zwischen Versionen setzt getrennte Candidate-Linien voraus, damit
  beide Lifecycle-Zustände unabhängig und revisionssicher bleiben.
- Legacy-Standalone-Kompatibilität bleibt bei `canonical_mode=False` erhalten.
  Sie ist keine Trust Boundary und wird im Codex-/Jarvis-Modus nicht entdeckt,
  nicht in Prompts aufgenommen und nicht ausgeführt.
- Die Registry-Auswahl ist als Phase-7-Service vorhanden. Eine neue API,
  Frontenddarstellung oder Shadow-Routing-Anbindung bleibt bis zur
  ausdrücklichen Phase-8-Freigabe gesperrt.

## Repository- und Scope-Nachweis

Der Arbeitsblock startete auf Branch `feature/codex-jarvis-orchestrator` bei
`1d9fff5752739b5ae4d54a3ddef32d70fdb2a7c3`; dessen Parent ist
`bc0fc635d50edc2cdb2919e1261b0b15e5f8247f`. Das offizielle OpenJarvis-Remote
blieb Fetch-Upstream, während Push deaktiviert blieb. Es wurde weder gemergt
noch gepusht.

Alle normalen und Smoke-Tests verwendeten synthetische Candidates,
Tool-Manifeste, Fake Action Services, lokale JSON-Pakete und temporäre
SQLite-/Workspace-Roots. Es gab keinen Zugriff auf das echte Obsidian-Vault,
die 46 Notizen oder `jarvis-desktop`; diese Pfade waren nicht Teil eines
Datei- oder Testkommandos. Es wurden keine Runtime-Datenbank, kein Paket, kein
Recovery-Bundle und keine temporäre Datei committed.
