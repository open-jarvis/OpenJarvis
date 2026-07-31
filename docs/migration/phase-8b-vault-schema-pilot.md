# Phase 8B: isolierter Vault-Schemakonvertierungspilot

Stand: 31. Juli 2026

## Entscheidung

Der isolierte Pilot wurde vollständig ausgeführt und ist gemäß den
Pflichtgates **nicht bestanden**. Die freigegebene ID-/Schema-Konvertierung
selbst ist deterministisch, byteerhaltend, idempotent und vollständig
rollbackfähig. Das einzige rote Gate ist `no_parser_errors`: 23 Notizen nutzen
bestehende Legacy-Notiztypen außerhalb des aktuellen Phase-4-Typschemas.

Diese `type`-Felder wurden nicht verändert, weil der Auftrag ausschließlich
ID, `legacy_id`, `schema_version` und eindeutig erkannte strukturierte
ID-Referenzen zur Änderung freigibt. Der Pilot wird deshalb nicht als grün und
nicht als cutover-ready gemeldet.

Das echte Vault wurde weder geöffnet, gescannt, verglichen noch verändert. Die
Pilot-, Restore-, Rollback- und SQLite-Kopien wurden vollständig entfernt.
Phase 8B umfasste keine Website-Staging-Arbeit, keinen produktiven Pilot, keinen
Cutover, keine Skill-/Workflowaktivierung, keine externen Modelle, keinen
Codex-Live-Turn und keinen Push.

## Repository und Commits

- Ausgangs-HEAD: `6c476993e293a78fb6ba9e95cc6ce64caef98825`
- Branch: `feature/codex-jarvis-orchestrator`
- Implementierungscommit: `301c9f72` – `feat: add deterministic vault schema migration pilot`
- Testcommit: `90db3dda` – `test: cover vault schema migration and rollback`
- offizielles OpenJarvis-Repository bleibt Fetch-Upstream; Push bleibt
  deaktiviert.

Der finale Dokumentationscommit und finale HEAD werden im Abschlussstatus des
Tasks ausgewiesen.

## Deterministische UUIDv5-Policy

- Mapping-Version: `openjarvis-vault-schema-migration-v1`
- fester Namespace:
  `4898f42f-c416-5ea1-9e0e-1bafd4d2e206`
- Namespace-Ableitung:
  `UUIDv5(UUID_NAMESPACE_URL, "openjarvis-vault-schema-migration-v1")`
- vorhandene ungültige ID:
  `UUIDv5(namespace, "legacy-id:" + NFC(trim(old_id)))`
- fehlende ID:
  `UUIDv5(namespace, "missing-id:" + NFC(relative_path) + ":" + before_sha256)`

Groß-/Kleinschreibung bestehender IDs bleibt erhalten. Zeilenumbrüche in IDs,
absolute Pfade, Traversal, Reparse Points, Kollisionen und Überschneidungen mit
gültigen UUIDs werden abgewiesen. Der Mappingaufbau wurde vor Apply zweimal
ausgeführt und war bytegleich reproduzierbar.

## Mapping und Manifeste

| Nachweis | Wert |
| --- | --- |
| Mappingeinträge | 46 |
| ungültige vorhandene IDs | 41 |
| fehlende IDs | 5 |
| Namespace-UUID | `4898f42f-c416-5ea1-9e0e-1bafd4d2e206` |
| Mapping-SHA-256 | `9c25e6cb89593922c1971275e2de5e221dfb0d8f8a18e669a85a27bc3eb183c2` |
| Before-Dateien | 59 |
| After-Dateien | 59 |
| Before-Manifest-SHA-256 | `1f5df782ede04759003a4f678c104ce47a1bab313b7aa5b94227924a7e0c2e28` |
| After-Manifest-SHA-256 | `7b5bbed05a5670f5dc104bd06e7456cfbe8ccaae083575bae13948f4b6c0fa3e` |
| geänderte Markdown-Dateien | 46 |
| unveränderte sonstige Dateien | 13 |
| verlorene oder zusätzliche Pfade | 0 |
| Ordner-/Dateiumbenennungen | 0 |

Die Mappingtabelle enthält nur relative Pfade, Before-Hashes, ID-Zustand,
alte ID, neue UUID, Schreibentscheidungen, Referenzzähler und einzelne
Mapping-Hashes. Sie enthält keine Notizkörper und keine absoluten privaten
Pfade. Die Tabelle wurde vor Apply geschrieben und danach nicht verändert.

## Frontmatter- und Body-Ergebnis

- 46/46 Notizen besitzen nach Apply eine gültige UUID.
- 41/41 ungültige Altkennungen sind exakt als `legacy_id` erhalten.
- 5/5 Notizen ohne ID erhielten eine deterministische UUIDv5.
- 46/46 besitzen `schema_version: 1`.
- unbekannte Frontmatter-Felder und Kommentare blieben erhalten.
- vorhandener Quote-Stil wurde beim ID-Ersatz beibehalten, soweit er vorhanden
  war.
- 31 LF- und 15 CRLF-Dateien behielten ihre Zeilenendungsart.
- es waren keine UTF-8-BOM-Dateien im realen Pilotsatz vorhanden; BOM-Erhaltung
  ist synthetisch getestet.
- Markdown-Bodies blieben in 46/46 Fällen bytegleich.
- keine Inhaltskorrektur, YAML-Gesamtneusortierung, Reorganisation, Löschung,
  Zusammenführung oder Archivierung wurde ausgeführt.

Der Writer prüfte je Datei den erwarteten Before-Hash, schrieb eine temporäre
Datei im selben Verzeichnis, synchronisierte sie, führte einen atomaren Replace
aus und validierte anschließend den After-Hash.

## Referenzanalyse

Die vollständige Analyse vor und nach Apply ergab:

| Referenzklasse | Vorher | Nachher | Änderung |
| --- | ---: | ---: | --- |
| strukturierte ID-Referenzen | 0 | 0 | keine |
| unbekannte Frontmatter-Referenzen | 0 | 0 | keine |
| Obsidian-Wikilinks mit Alt-ID | 0 | 0 | keine |
| Markdownlinks mit Alt-ID | 0 | 0 | keine |
| freie Textvorkommen | 0 | 0 | keine |
| Codeblockvorkommen | 0 | 0 | keine |

Wikilinks, Markdownlinks, freie Texte und Codeblöcke wurden grundsätzlich nie
automatisch ersetzt. Für den vorhandenen Datensatz besteht kein ungeklärter
Referenzintegritätsblocker.

## Parser, Reindex und Readback

| Gate | Ergebnis |
| --- | --- |
| Phase-4-Scan | 46 |
| Phase-4-Index | 46 |
| FTS5 verfügbar | ja |
| doppelte IDs | 0 |
| doppelte Inhalte | 0 |
| Prozessneustart und Readback | 46/46 |
| zweiter Sync unverändert | 46/46 |
| Parserfehler | **23** |

Die 23 Parserfehler sind vollständig `unsupported note type`. Betroffen sind
aggregiert:

- `memory_proposal`: 12
- `category`: 6
- `navigation`: 2
- `project_profile`: 1
- `system_policy`: 1
- `system_profile`: 1

Die übrigen 23 Notizen verwenden den bereits unterstützten Typ `capture`.
Eine stillschweigende Erweiterung des Phase-4-Schemas oder Umschreibung dieser
Typen wäre eine neue fachliche Entscheidung und wurde nicht vorgenommen.

## Idempotenz und Rollback

- zweiter Apply: 0 Änderungen, 46 No-ops;
- Mapping bei Wiederholung: identisch;
- separate Restore-Kopie vor Apply: bytegleich zum Before-Manifest;
- Rollback in neues leeres Verzeichnis: 59/59 Dateien bytegleich;
- Rollback-Manifest-SHA entspricht dem Before-Manifest-SHA;
- Rollback-Probe anschließend entfernt;
- Pilotkopie, Restore-Kopie und SQLite-Index anschließend entfernt;
- verifiziertes Vault-Backup nach dem Pilot unverändert.

## Pflichtgates

Bestanden sind:

- 46 Markdown-Dateien vorhanden;
- 46/46 gültige UUID;
- 41/41 exakte `legacy_id`;
- 5/5 deterministische Missing-ID-UUID;
- 46/46 `schema_version: 1`;
- 0 doppelte oder fehlende IDs;
- 0 verlorene oder zusätzliche Dateien;
- 0 unerlaubte Body-Änderungen;
- 0 Umbenennungen oder Ordneränderungen;
- Referenzen konsistent;
- Mapping reproduzierbar;
- zweiter Apply No-op;
- FTS5 46/46;
- Neustart/Readback 46/46;
- Rollback bytegleich.

Nicht bestanden:

- `0 Parserfehler`: Istwert 23 wegen nicht freigegebener Legacy-Notiztypen.

Damit lautet der Gesamtstatus korrekt: **`failed_gates`**.

## Tests

Vor dem realen Pilot:

- neue Phase-8B-Fokussuite: 26/26 bestanden;
- vollständige Migrationssuite: 67 bestanden, 1 Reparse-Test
  plattformbedingt übersprungen;
- Ruff und Formatprüfung: bestanden;
- Compile- und `git diff --check`: bestanden.

Abgedeckt sind unter anderem UUIDv5-Determinismus, Reihenfolgeunabhängigkeit,
Kollisionen, vorhandene UUIDs, `legacy_id`-/Schema-Konflikte, unbekannte Felder,
Kommentare, Body-Bytes, LF/CRLF/BOM, Referenzklassen, CAS, atomarer Replace,
Teilversagen, No-op-Apply, Phase-4-Reindex, Rollback, Real-Vault-Guard sowie
Offline-/Netzwerk-Guard.

## Externe Review-Artefakte

Im separaten Phase-8B-Ausgabeordner liegen:

- `mapping.json`
- `mapping.sha256`
- `before-manifest.jsonl`
- `after-manifest.jsonl`
- `diff-manifest.jsonl`
- `reference-report.json`
- `parser-report.json`
- `rollback-proof.txt`
- `pilot-summary.json`
- `cleanup-proof.json`

Alle Artefakte verwenden relative Pfade und enthalten keine Notizkörper oder
absoluten privaten Pfade. Pilotkopien, Vault-Inhalte und SQLite-Indizes wurden
nicht committed.

## Blocker und technische Bereitschaft

Die ID-/Schema-Konvertierung ist technisch vorbereitet und durch den isolierten
Pilot nachgewiesen. Eine reale Vault-Migration ist insgesamt **noch nicht
technisch freigabefähig**, weil das verpflichtende Parsergate an 23
Legacy-Notiztypen scheitert.

Vor einem weiteren Apply ist eine neue Nutzerentscheidung erforderlich:

1. Phase-4-Typschema um die sechs Legacy-Typen erweitern; oder
2. eine explizite, verlustfreie Typ-Mappingpolicy mit Erhaltung des Altwerts
   definieren; oder
3. die betroffenen 23 Notizen von einer späteren realen Migration ausnehmen.

Keine dieser Entscheidungen wird aus dem aktuellen Auftrag abgeleitet. Es
folgen keine reale Vault-Migration, kein Website-Staging-Pilot, kein Cutover,
keine Altprojekt-Ablösung und keine Browser-/Account-Einrichtung.
