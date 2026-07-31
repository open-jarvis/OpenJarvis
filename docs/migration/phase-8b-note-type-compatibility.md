# Phase 8B: Legacy-Notiztyp-Kompatibilität und isolierter Pilot v2

Stand: 1. August 2026

## Entscheidung

Der begrenzte Phase-8B-Arbeitsblock ist bestanden. Der zweite isolierte
Vault-Pilot erfüllt alle 32 kombinierten Pflichtgates. Alle 46 Notizen sind
syntaktisch und semantisch validiert, besitzen einen unterstützten geschlossenen
Notiztyp, sind in FTS5 indexiert und genau einer code-eigenen Trust-, Retrieval-,
Authority- und Scope-Klasse zugeordnet.

Das echte Vault wurde weder geöffnet, gescannt, verglichen noch verändert. Der
Pilot verwendete ausschließlich eine temporäre Kopie des verifizierten
Phase-8A-Backups. Pilot-, Restore-, Rollback- und SQLite-Kopien wurden nach jedem
Lauf entfernt. Es gab keine Website-Staging-Arbeit, keine reale Migration,
keinen Cutover, keine Legacy-Codeausführung, keine externen Modelle, keinen
Codex-Live-Turn, keine Skill-/Workflowaktivierung und keinen Push.

## Repository und Commits

- Ausgangs-HEAD: `80e0c9c2f36354c9ed85bcfe7c89c8c3e47ee658`
- Branch: `feature/codex-jarvis-orchestrator`
- `98722feb` – `feat: add typed legacy vault note compatibility`
- `eaa7bba9` – `feat: show vault trust boundaries in memory UI`
- `71a3bf91` – `test: cover legacy note type trust boundaries`
- `40ecba50` – `fix: honor scoped and archived vault review boundaries`
- Fetch-Upstream bleibt das offizielle OpenJarvis-Repository; Push bleibt
  deaktiviert.

Der Dokumentationscommit und finale HEAD werden im Task-Abschluss ausgewiesen.

## Semantische Vorinventur

Die metadata-first Inventur wurde aus einer neuen, hashgleichen temporären
Kopie des verifizierten Backups erstellt. Sie enthält nur relative Pfade,
UUID/Legacy-ID, Feldnamen, Body-Hash, Dateigröße, Referenzzähler und abgeleitete
Klassifikationen, aber keine Notizkörper.

| Legacy-Notiztyp | Anzahl |
| --- | ---: |
| `memory_proposal` | 12 |
| `category` | 6 |
| `navigation` | 2 |
| `project_profile` | 1 |
| `system_policy` | 1 |
| `system_profile` | 1 |
| **Gesamt** | **23** |

Die tatsächlichen Felder und Verwendungszwecke sind mit der vorgegebenen
Sicherheitspolicy vereinbar. Das `project_profile` besitzt eine vorhandene,
nichtleere Scope-Bindung. Diese wird als opaker, exakter Projekt-Schlüssel
behandelt und weder normalisiert noch in der committed Dokumentation
offengelegt.

## Geschlossene Notiztypen und code-eigene Klassifikation

Die sechs Legacy-Typen wurden als echte Enum-Werte ergänzt. Bestehende
kanonische Typen bleiben aus Kompatibilitätsgründen erhalten. Typwerte werden
exakt und ohne Groß-/Kleinschreibungsnormalisierung geprüft; unbekannte Werte
bleiben harte Parserfehler und gelangen nicht in FTS oder Retrieval.

| Notiztyp | Trust | Retrieval | Authority | Scope |
| --- | --- | --- | --- | --- |
| `capture` | `source_bound` | `normal` | `none` | `declared` |
| `memory_proposal` | `untrusted_proposal` | `review_only` | `none` | `review_only` |
| `category` | `structural` | `taxonomy_only` | `none` | `structural` |
| `navigation` | `structural` | `navigation_only` | `none` | `structural` |
| `project_profile` | `scoped_context` | `project_scoped` | `none` | `exact_project` |
| `system_policy` | `authority_sensitive_source` | `explicit_review_only` | `prohibited_runtime_authority` | `explicit_review_only` |
| `system_profile` | `authority_sensitive_source` | `explicit_review_only` | `prohibited_runtime_authority` | `explicit_review_only` |

Die vier Klassifikationen werden ausschließlich von OpenJarvis aus dem exakt
erkannten Notiztyp abgeleitet. Gleichnamige Frontmatter-Felder bleiben als
Quellmetadaten sichtbar, können die abgeleiteten Werte aber nicht
überschreiben.

## Parse-, Index- und Health-Semantik

Die frühere Mehrdeutigkeit zwischen `indexed: 46` und offenen Parserfehlern ist
beseitigt. Pro Datei werden getrennt geführt:

- `discovered`;
- `frontmatter_parsed`;
- `schema_valid`;
- `type_supported`;
- `content_indexed`;
- `retrieval_eligible`;
- `retrieval_class`;
- `parse_status` und optionaler `parse_error`.

Ein Parser- oder Schemafehler setzt `content_indexed=false`, erhält den
metadata-only Fehlerdatensatz für Diagnosezwecke und verhindert einen
FTS-Eintrag. Health-, API- und Pilotberichte verwenden dieselben getrennten
Zähler.

Ergebnis des bestandenen Pilots:

| Status | Anzahl |
| --- | ---: |
| discovered | 46 |
| Frontmatter technisch geparst | 46 |
| schema_valid | 46 |
| type_supported | 46 |
| content_indexed / FTS-Dokumente | 46 |
| normale Retrievalberechtigung | 23 |
| review-only einschließlich explicit-review | 14 |
| strukturelle Notizen | 8 |
| project-scoped | 1 |
| authority-sensitive | 2 |
| abgelehnt | 0 |
| Parserfehler | 0 |

Die exakten Retrievalklassen sind:

- `normal`: 23;
- `review_only`: 12;
- `taxonomy_only`: 6;
- `navigation_only`: 2;
- `project_scoped`: 1;
- `explicit_review_only`: 2.

## Retrieval-, Learning- und Authority-Grenzen

- Normale Task- und Memory-Context-Abfragen sehen ausschließlich `normal` und
  bei explizit exakter Projektbindung `project_scoped`.
- `memory_proposal` ist nur in einer expliziten Review-Abfrage sichtbar und
  erzeugt beim Parsen oder Indexieren keinen Memory- oder Learning-Candidate.
- Legacy-/authority-sensitive Typen sind keine zulässigen Candidate-Schreibtypen
  und können deshalb nicht über einen API-Parameter bestätigt werden.
- `category` und `navigation` sind nur über eine getrennte Strukturabfrage
  erreichbar und werden nicht als faktische Antwortbelege ausgewählt.
- `project_profile` benötigt die bytegenau passende Scope-Bindung; fehlende oder
  abweichende Bindungen liefern keinen Treffer.
- `system_policy` und `system_profile` sind standardmäßig nicht modell-sichtbar
  und besitzen immer `prohibited_runtime_authority`.
- Vault-Inhalte können weder CentralRiskPolicy noch Approval, Toolrechte,
  Capabilities, Router, Skill-Evidence, Systemprompt oder Personality ändern.
- Phase-7-Learning bleibt ausschließlich über den vorhandenen kontrollierten
  Candidate- und Review-Lifecycle erreichbar.

Normale Suche, explizite Review und Vault-Struktursuche verwenden getrennte
interne Retrievalzwecke und getrennte lokale API-Endpunkte. Review- und
Strukturergebnisse werden keinem Taskkontext angehängt und nicht als normale
Memory-Quelle persistiert.

## API und bestehende UI

Memory-Health, Note, Graph und Retrieval liefern die abgeleiteten metadata-only
Felder `note_type`, `trust_class`, `retrieval_class`, `authority_class`,
`scope_class`, `parse_status` und `retrieval_eligible`.

Die bestehende Memory-UI wurde erweitert, nicht dupliziert. Sie kennzeichnet
Review-, Struktur- und authority-sensitive Quellen und verlangt für Review und
Struktur einen expliziten Modus. Diese Modi zeigen sichtbar an, dass die Quelle
keine Runtime-Autorität erhält und nicht an einen Taskkontext gebunden wird.

## Erneuter isolierter Pilot

Die deterministische Mappingpolicy blieb unverändert:

- Namespace: `4898f42f-c416-5ea1-9e0e-1bafd4d2e206`;
- Mapping-SHA-256:
  `9c25e6cb89593922c1971275e2de5e221dfb0d8f8a18e669a85a27bc3eb183c2`;
- 41 ungültige vorhandene IDs mit exaktem `legacy_id`;
- 5 fehlende IDs mit deterministischer UUIDv5;
- 46/46 `schema_version: 1`;
- Markdown-Bodies 46/46 bytegleich.

Manifeste:

- Before:
  `1f5df782ede04759003a4f678c104ce47a1bab313b7aa5b94227924a7e0c2e28`;
- After:
  `7b5bbed05a5670f5dc104bd06e7456cfbe8ccaae083575bae13948f4b6c0fa3e`;
- 59 Dateien vor und nach Apply;
- 46 geänderte Markdown-Dateien und 13 unveränderte sonstige Dateien;
- keine verlorenen oder zusätzlichen Pfade;
- keine Datei-/Ordnerumbenennungen;
- keine Referenzintegritätsblocker.

Reindex und Readback:

- 46/46 FTS5-Dokumente;
- 0 doppelte IDs oder Inhalte;
- 0 unbekannte Typen;
- Klassifikationen nach Prozessneustart identisch;
- zweiter Sync: 46 unverändert;
- zweiter Apply: 0 Änderungen, 46 No-ops.

Rollback:

- Restore-Quelle vor Apply bytegleich zum Before-Manifest;
- Rollback in ein neues leeres Verzeichnis;
- 59/59 Dateien bytegleich;
- Rollback-Manifest entspricht dem Before-Manifest;
- Rollback-Verzeichnis anschließend entfernt.

## Erster Pilot-v2-Versuch

Der erste Lauf wurde nicht als grün gezählt. Parser, Mapping, FTS, Authority,
Idempotenz, Restart und Rollback waren bereits grün; zwei positive
Retrievalprüfungen schlugen fehl, weil der Prüfer für ein bestehendes
Projektprofil implizit `status=active` und für drei explizite Strukturquellen
`archived=false` voraussetzte.

Der Fehler war keine Trust- oder Authority-Umgehung: Missing-/Wrong-Scope und
alle normalen verbotenen Klassen blieben blockiert. Der Prüfer und die
Retrievalgrenze wurden eng korrigiert: kanonische normale Memories behalten
ihre bisherigen Active-/Archive-Regeln, exakt gebundene Projektprofile werden
über ihre Scope-Bindung geprüft und explizite Review-/Strukturabfragen dürfen
archivierte Quellen untersuchen. Der fehlgeschlagene metadata-only Review-Satz
wurde separat als `failed-1` erhalten. Sein Cleanup-Nachweis ist vollständig.

Der zweite Lauf bestand danach alle 32 Gates.

## Tests und Qualitätsprüfungen

- neue Typ-/Trust-/Retrieval-/Pilot-Fokussuite: 99 bestanden, 1
  plattformbedingter Skip;
- Backend-/API-Nachprüfung: 46 bestanden;
- vollständige Migrationssuite: 68 bestanden, 1 plattformbedingter Skip;
- Phase-4 Memory-/Vault-Suite: 260 bestanden, 16 optionale oder
  plattformbedingte Skips;
- Phase-7 Candidate-/Learning-/API-Fokussuite: 204 bestanden;
- Frontend: 19/19 bestanden;
- Frontend-Produktionsbuild: bestanden;
- Ruff, Formatprüfung, Compile-/Importprüfung und `git diff --check`:
  bestanden;
- Offline-/Socket-Guard: bestanden;
- keine externen Modelle und kein Codex-Live-Turn.

## Externe Review-Artefakte

Der bestandene externe Review-Satz enthält mindestens:

- `note-type-inventory.json`;
- `parser-status-report.json`;
- `retrieval-classification-report.json`;
- `authority-boundary-report.json`;
- `pilot-summary-v2.json`;
- `rollback-proof-v2.txt`;
- `cleanup-proof-v2.json`;
- unveränderte Mapping-, Before-/After-, Diff- und Referenznachweise.

Die Inventur enthält 23 metadata-only Datensätze, keine Notizkörper und keine
absoluten privaten Pfade. Der Parserstatus enthält 46 metadata-only Datensätze.
Alle Cleanup-Felder sind `true`. Der verifizierte Backup-Datensatz ist nach dem
Pilot weiterhin bytegleich und besitzt 59 Dateien.

## Technische Bereitschaft und verbleibende Grenzen

Die Vault-Schemakonvertierung ist technisch für eine spätere reale Migration
vorbereitet: ID-/Schema-Mapping, Legacy-Typen, Trust-/Retrievalgrenzen,
Authority-Sperren, Reindex, Restart, Idempotenz und Rollback sind im isolierten
Backup-Pilot vollständig grün.

Eine reale Vault-Migration ist damit nicht automatisch freigegeben. Sie bleibt
bis zu einer separaten ausdrücklichen Nutzerfreigabe gesperrt und muss erneut
mit unverändertem Backup-/Source-Stability-Nachweis beginnen. Website-Staging,
Cutover, Altprojekt-Ablösung und Browser-/Account-Konfiguration bleiben
außerhalb dieses Arbeitsblocks.
