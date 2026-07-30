# Phase 4: Memory- und Obsidian-Integrationsaudit

Stand: 2026-07-30
Auditbasis: `9b70235b538b48ff6841846ffcd193d87d748c22`
Branch: `feature/codex-jarvis-orchestrator`

## Zweck und Sicherheitsgrenze

Dieser Audit wurde vor jeder Phase-4-Produktivcodeänderung erstellt. Untersucht
wurden ausschließlich der aktuelle OpenJarvis-Quellcode, vorhandene Tests und
die isolierte Python-Umgebung des Zielrepositorys.

Nicht untersucht oder berührt wurden:

- das echte Obsidian-Vault;
- die vorhandenen 46 echten Notizen;
- das alte `jarvis-desktop`-Projekt;
- echte Nutzer-, Task- oder Laufzeitdaten.

Alle späteren Phase-4-Tests müssen temporäre Vaults, temporäre SQLite-Dateien,
Fakes und externe Test-State-Verzeichnisse verwenden.

## Sicherer Startnachweis

Vor dem Audit wurden folgende Zustände read-only geprüft:

| Prüfung | Ergebnis |
|---|---|
| Repository | `C:\Users\Playe\Documents\JARVIS\openjarvis-codex` |
| Branch | `feature/codex-jarvis-orchestrator` |
| HEAD | `9b70235b538b48ff6841846ffcd193d87d748c22` |
| Arbeitsbaum | sauber |
| Upstream Fetch | `https://github.com/open-jarvis/OpenJarvis.git` |
| Upstream Push | `DISABLED` |
| stabile OpenJarvis-Basis | `1fa80d8ecd2e043cb61fdc8310f9f7ffef83698c` ist Vorfahr von HEAD |
| Phase-3-Stand | erwarteter HEAD ist Vorfahr von HEAD |
| Recovery-Bundle | vollständige Historie, `git bundle verify` erfolgreich |
| Bundle SHA-256 | `946FE5103D618FD27F5569BCD23B5FC7A015207100180614FF8E9E3D8CD30064` |
| Python / SQLite | Python 3.11.9, SQLite 3.45.1 |
| FTS5 | in der Windows-Python-Umgebung verfügbar |

## Ist-Architektur

### Automatisch extrahierte Fakten

`openjarvis.memory` besteht aus:

- `FactExtractor`: modellgestützte Extraktion kurzer Faktstrings;
- `MemoryService`: asynchroner Worker für abgeschlossene Chat-Austausche;
- `LocalFactStore`: atomar neu geschriebene JSONL-Datei
  `memory_facts.jsonl`.

Die Identität eines Fakts ist implizit sein case-insensitiver Text. Es gibt
keine stabile ID, kein Versionsschema, keine Konfliktauflösung, keine
Task-/Session-Korrelation und keine Approval-Grenze. Der Store kann Fakten
automatisch persistieren, sobald der Service aktiviert ist. Dieses Verhalten
ist für den kontrollierten Obsidian-Write-Workflow ungeeignet.

### Persona- und Memory-Dateien

Neben dem JSONL-Faktenspeicher existieren `SOUL.md`, `MEMORY.md` und `USER.md`.
`SystemPromptBuilder` und mehrere Agenten lesen diese Dateien direkt.
`MemoryManageTool` ändert `MEMORY.md` mit einfachen `read_text`/`write_text`-
Operationen. Es gibt dabei keine Pfadwurzelprüfung, Versionsprüfung,
Approval-Korrelation, atomare Replace-Operation oder Konflikterkennung.

### Generische Retrieval-Backends

Unter `openjarvis.tools.storage` existieren:

- `SQLiteMemory`: persistente Volltextsuche über die native Rust-Erweiterung;
- `BM25Memory`: in-memory BM25 über die native Rust-Erweiterung;
- `DenseMemory`: in-memory Dense Retrieval;
- `FAISSMemory` und `ColBERTMemory`: optionale embeddingbasierte Backends;
- `HybridMemory`: RRF-Fusion zweier Backends;
- Chunking, Ingestion und Context Injection.

`RetrievalResult` enthält nur `content`, `score`, `source` und freie
`metadata`. Es fehlen Retrieval-ID, stabile Notiz-ID, Textspanne,
Content-Hash, Indexzeit, Auswahlgrund und Evidenzstatus.

`SQLiteMemory` ist ein generischer Dokument-/Chunk-Store. Der derzeitige
Python-Wrapper verlangt die native Rust-Erweiterung. Ohne sie ist auch der
konfigurierte Standard `sqlite` nicht verfügbar. Seine gespeicherten
Dokument-IDs werden pro `store()` erzeugt und modellieren weder eine stabile
Obsidian-Notiz noch Moves, Links, Backlinks, Parserfehler oder Rebuild-Status.

### Obsidian-Connector

`ObsidianConnector` läuft read-only durch `.md`, `.markdown` und `.txt`,
überspringt versteckte beziehungsweise bekannte technische Verzeichnisse und
liefert `Document`-Objekte.

Aktuelle Grenzen:

- `doc_id` ist `obsidian:<relativer Pfad>` und damit pfadbasiert;
- ein Rename oder Move erzeugt eine neue Identität;
- es gibt keine stabile Frontmatter-ID;
- der Frontmatter-Parser verarbeitet nur einfache `key: value`-Zeilen und
  flache Listen;
- Wikilinks, Backlinks, Linkauflösung und Konflikte fehlen;
- Dateilöschungen und Moves werden nicht als solche erkannt;
- es gibt nur einen vollständigen Walk beziehungsweise einen mtime-Filter;
- der Connector besitzt keine kontrollierte Write-Schnittstelle.

### CLI und API

Die bestehende Memory-CLI bietet:

- generisches `index`, `search` und `stats`;
- `list` und `clear` für den separaten JSONL-Faktenspeicher.

Sie besitzt keine Vault-Health-, Reindex-, Graph-, Candidate-, Conflict- oder
Migration-Dry-Run-Kommandos.

Die bestehende `/v1/memory`-API bietet `store`, `search`, `stats`, `config` und
`index`. `store` kann direkt in den generischen Backend-Store schreiben.
`index` nimmt einen Pfad entgegen und speichert Chunks. Die Auth-Middleware
kann `/v1/*` mit Bearer-Token schützen, doch die Memory-Mutationen verwenden
noch nicht die strengere Phase-3-Grenze aus lokaler Herkunft,
`X-Correlation-ID`, `Idempotency-Key`, Task-ID, Capability-/Risk-Prüfung und
Approval.

### Graph

`KnowledgeGraphMemory` ist eine separate SQLite-Datenbank mit generischen
Entities und Relations. Sie nutzt `entity_id`, führt aber keine
Obsidian-Wikilinkauflösung aus, ist nicht aus dem Vaultindex rekonstruierbar
und ist nicht die geeignete Source of Truth. Für Phase 4 kann ihr
Entity-/Relation-Konzept als Referenz dienen; die kanonischen Memory-Kanten
müssen im rekonstruierbaren Vaultindex liegen.

### Tasks, Quellen und Traces aus Phase 3

Phase 3 stellt bereits wiederverwendbare Autoritäten bereit:

- stabile `task_id`, `session_id`, `correlation_id`, Codex `thread_id`,
  `turn_id` und geordnete Task-Events;
- idempotentes `TaskStore.append_event(...)`;
- `TaskSource` und `TaskStore.add_source(...)`;
- persistente Approvals mit Risiko, Ziel, Wirkung, Sandbox, CWD und
  Restore-Hinweis;
- redigierte Task-Event-Projektion in `TraceStore`.

Es fehlt derzeit ein lesender
`GET /v1/tasks/{task_id}/sources`-Endpunkt. Memory-Retrieval erzeugt noch
keine Phase-3-Task-Events und fügt keine tatsächlich ausgewählten
Memory-Quellen als `TaskSource` hinzu.

## Antworten auf die Pflichtfragen

### 1. Was kann direkt wiederverwendet werden?

- Phase-3-Taskidentität, Eventreihenfolge, Source-Tabelle, Trace-Projektion,
  zentrale Risk Policy und Approval-Persistenz;
- die lokale API-Authentifizierung und die strengere
  `_mutation_context`-Struktur der Task-Routen;
- Python `sqlite3` mit dem auf Windows bestätigten FTS5;
- Markdown-Dateiwalk, Skip-Regeln und Obsidian-URL-Erzeugung als begrenzte
  read-only Bausteine;
- Chunking-Hilfen und die Grundidee eines strukturierten
  `RetrievalResult`;
- RRF als optionales, austauschbares Rankingverfahren;
- bestehende MemoryBrowser-, Quellen-/Citation- und Approval-Komponenten der
  vorhandenen Oberfläche;
- Hashing, Redaction und die in Phase 3 verwendeten atomaren/idempotenten
  Persistenzmuster.

Direkte Wiederverwendung bedeutet nicht, dass die bestehenden generischen
Stores zur kanonischen Vault-Wahrheit werden. Markdown bleibt die Wahrheit,
der neue Index bleibt daraus vollständig rekonstruierbar.

### 2. Welche Komponenten müssen erweitert werden?

- ein kanonisches `MemoryNote`- und `MemorySource`-Modell;
- vollständiges, versioniertes YAML-Frontmatter;
- read-only Legacy-Identität und dauerhafte UUID-Identität;
- ein Obsidian-spezifischer, rekonstruierbarer SQLite-/FTS5-Index;
- Move-/Delete-/Duplicate-ID- und Parserfehlererkennung;
- Wikilinkauflösung, Backlinks, Ordner-/Projektbeziehungen und Graphansicht;
- Retrieval mit Filtern, gewichteten Feldern, Evidenzstatus, Diversität,
  Deduplizierung und ausgewählten Quellen;
- Task-/Session-/Trace-/Source-Korrelation;
- Candidate-, Conflict-, Approval- und atomarer Write-Workflow;
- Health-, Reindex-, Search-, Note-, Link-, Graph-, Candidate- und
  Conflict-API;
- Memory-CLI um Reindex und `migration --dry-run`;
- bestehende UI um Health, Quellen, Evidenz, Kandidaten, Konflikte und Diffs;
- manueller/ereignisbasierter inkrementeller Reindex mit sicherem
  Windows-Polling-Fallback.

### 3. Welche Komponenten verwenden pfadbasierte Identität?

- `ObsidianConnector` setzt `doc_id` auf `obsidian:<relativer Pfad>`;
- generische Ingestion und Chunks verwenden den absoluten Dateipfad als
  `source`;
- `/v1/memory/index` übernimmt diese Pfadquelle in freie Metadaten;
- `MemoryManageTool` identifiziert die gesamte Memory-Wahrheit über einen
  einzelnen konfigurierten Dateipfad;
- der generische SQLite-Store erzeugt neue Dokument-IDs pro gespeicherten
  Chunk und kann Pfadänderungen nicht als dieselbe Notiz erkennen.

Phase 4 muss Kanten und Quellen über `note_id` verbinden. Der relative Pfad
bleibt ein veränderbares, historisierbares Attribut.

### 4. Welche Parser sind für echtes YAML unzureichend?

`openjarvis.connectors.obsidian._parse_frontmatter` ist ein eigener
Zeilenparser. Er unterstützt weder verschachtelte Strukturen noch Blockwerte,
mehrzeilige Strings, YAML-Typen, Quotes mit Sonderfällen, Kommentare,
Anchors/Aliases oder verlässliche Fehlerpositionen. Er kann echte
Frontmatter-Daten still falsch interpretieren.

In der aktuellen Umgebung ist kein Round-trip-YAML-Parser installiert. Phase
4 benötigt einen vollständigen Safe-/Round-trip-Parser, damit unbekannte
Felder und Kommentare möglichst erhalten bleiben. Ungültiges YAML muss als
Indexfehler erfasst und darf nicht still repariert werden.

### 5. Wo entstehen aktuell Embedding-Pflichten?

- `DenseMemory` erzeugt bei der ersten Store-/Retrieve-Operation
  standardmäßig einen `OllamaEmbedder` für `nomic-embed-text`;
- `OllamaEmbedder.dim()` kann eine Netzwerkprobe an
  `localhost:11434/api/embed` auslösen;
- `FAISSMemory` erzeugt ohne expliziten Provider einen
  `SentenceTransformerEmbedder`;
- `ColBERTMemory` lädt sein eigenes embeddingbasiertes Modell;
- ein `HybridMemory` mit einem dieser Backends erbt deren Pflicht.

Das generische `SQLiteMemory` und `BM25Memory` benötigen keine Embeddings,
verlangen derzeit aber die native Rust-Erweiterung. Der Phase-4-MVP wird
deshalb einen eigenständigen Python-`sqlite3`-FTS5-Pfad im Vaultindex
verwenden. Embeddings bleiben explizit optional und standardmäßig
deaktiviert; deaktivierter Code darf weder Provider importieren noch Ollama
kontaktieren.

### 6. Welche Memory-Stores überschneiden sich?

| Store | Wahrheit/Verwendung | Überlappung/Risiko |
|---|---|---|
| `memory_facts.jsonl` | automatisch extrahierte Faktstrings | konkurriert mit Vault-Fakten; keine stabile ID oder Approval |
| `MEMORY.md` | Persona-/Prompt-Kontext und direktes Tool-Ziel | konkurriert mit JSONL und Vault; unsichere direkte Writes |
| generisches `memory.db` | Chunk-/Retrieval-Store | kann Vault-Inhalte duplizieren; nicht aus Notizmodell rekonstruierbar |
| `knowledge_graph.db` | generische Entities/Relations | separater Graph kann von Vault und Retrieval abweichen |
| neuer Phase-4-Vaultindex | rekonstruierbare Projektion aus Markdown | darf keine neue Source of Truth werden |

Für Phase 4 ist das synthetische Markdown-Vault die einzige kanonische
Memory-Wahrheit. Der Vaultindex projiziert diese Wahrheit. Bestehende Stores
werden nicht automatisch zusammengeführt oder mit echten Daten befüllt.
Automatische JSONL-Extraktion bleibt standardmäßig deaktiviert und wird nicht
als stiller Obsidian-Write-Pfad verwendet.

### 7. Wie wird Memory mit Task, Session, Trace und Quellen verbunden?

Geplanter kanonischer Ablauf:

1. Ein Phase-3-Task liefert `task_id`, `session_id`, `correlation_id` und,
   soweit vorhanden, `thread_id`/`turn_id`.
2. Jede Suche erzeugt eine `retrieval_id` und ein redigiertes
   `memory.query_started`-Event.
3. Kandidaten werden nur mit Vorschau, Digest, `note_id`, Pfad, Span und
   Rankingmetadaten in Events gehalten.
4. Nur tatsächlich ausgewählte Quellen erhalten
   `memory.source_selected`-Events und idempotente `TaskSource`-Datensätze.
5. Das strukturierte Retrieval-Ergebnis enthält genau dieselben ausgewählten
   Quellen. Fehlende, widersprüchliche oder zu schwache Evidenz erzeugt den
   passenden Evidence-Status und ein explizites Timeline-Event.
6. Ein „Merke dir“-Wunsch erzeugt zuerst einen persistenten Kandidaten und
   ein `memory.write_candidate_created`-Event.
7. Markdown-Änderungen durchlaufen Phase-3-Risk-/Approval-Policy und werden
   erst nach einer einmaligen Zustimmung atomar ausgeführt.
8. Write- und Indexereignisse werden über die bestehende
   `TaskStore`-zu-`TraceStore`-Projektion redigiert gespiegelt.

Damit bleiben OpenJarvis Task-, Policy-, Approval- und
Persistenzautorität; Codex darf ausgewählte Quellen formulieren, aber keine
zusätzlichen Vault-Quellen erfinden.

### 8. Welche Änderungen werden ausdrücklich erst in Phase 8 durchgeführt?

Phase 4 führt ausschließlich synthetische Dry-Runs aus. Für Phase 8 oder eine
separate ausdrückliche Freigabe zurückgestellt sind:

- Lesen, Analysieren oder Migrieren des echten Vaults und der 46 Notizen;
- Schreiben dauerhafter IDs in echte Legacy-Notizen;
- tatsächliche Frontmatter-Schema-Upgrades echter Notizen;
- Bulk-Renames, Moves, Ordnerbereinigung oder Neuordnung;
- Zusammenführung paralleler echter Ordnerschemata;
- Auflösung echter Duplicate-IDs, Dubletten oder inhaltlicher Konflikte;
- Import echter `jarvis-desktop`-, Nutzer-, Task- oder Laufzeitdaten;
- Aktivierung eines Watchers oder eines schreibfähigen Modus für das echte
  Vault;
- Löschung oder automatische Konsolidierung bestehender Memory-Stores;
- produktive Aktivierung optionaler Embeddings oder lokaler LLM-Provider.

Der Phase-4-Befehl `memory migration --dry-run` muss standardmäßig read-only
bleiben und ausschließlich einen Bericht, geplante Diffs und einen
Rollback-Plan erzeugen.

## Architekturentscheidung für die Implementierung

Phase 4 erweitert die bestehende Memory-Fläche um einen
Obsidian-spezifischen `VaultMemoryService`, statt den generischen
`SQLiteMemory`-Chunkstore oder `KnowledgeGraphMemory` zur kanonischen
Vault-Wahrheit zu erklären.

Die Grenzen lauten:

- Markdown-Dateien sind Source of Truth;
- `note_id` ist Identität, Pfad ist veränderliches Attribut;
- Legacy-Dateien ohne ID erhalten im Index eine klar markierte,
  deterministische provisorische Identität;
- eine echte UUID entsteht nur bei einem genehmigten kontrollierten Write;
- SQLite enthält nur rekonstruierbare Notizen, Historie, Links, Quellen,
  Kandidaten, Konflikte, Write-Audits und Indexfehler;
- FTS5/BM25 über Python `sqlite3` ist der verpflichtungsfreie Standard;
- optionale Embeddings und Codex-Reranking liegen hinter explizit
  deaktivierten Providergrenzen;
- alle Dateimutationen sind rootgebunden, approvalpflichtig, atomar,
  hash-/versionsgeschützt und auditierbar.

## Implementierungsreihenfolge nach diesem Commit

1. kanonische Modelle und versioniertes YAML-Schema;
2. Round-trip-Frontmatter und stabile/provisorische Identität;
3. rekonstruierbarer SQLite-/FTS5-Index;
4. Wikilinks, Backlinks und Beziehungen;
5. strukturiertes Retrieval, Evidenz und Task Sources;
6. Kandidaten, Konflikte, Approvals und atomare Writes;
7. lokale API und vorhandene UI;
8. Windows-sicherer inkrementeller Reindex;
9. synthetische Tests, lokaler Smoke und maximal ein kontrollierter
   read-only Codex-Smoke;
10. Verifikation, Recovery-Bundle und Phase-4-Abschlussbericht.
