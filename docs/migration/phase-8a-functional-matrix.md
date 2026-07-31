# Phase 8A: Legacy-Funktionsmatrix

Stand: 31. Juli 2026

## Grundlage und Sicherheitsstatus

Die Matrix wurde ausschließlich aus dem vollständig verifizierten
Legacy-Content-Archiv erstellt. Es wurden keine Module importiert oder
ausgeführt, keine Legacy-Skills oder -Workflows registriert und keine
Runtime-Daten geöffnet. Die statische Inventur umfasst 223 Dateien,
116 Python-Module, 201 Klassen, 1.078 Funktionen beziehungsweise Methoden und
103 API-Routen. 27 Skilldefinitionen bleiben untrusted metadata.

Die Bezeichnungen `ersetzen`, `Kandidat`, `verwerfen` und `blockiert` sind
Planungsentscheidungen. Sie bewirken weder eine Migration noch eine Aktivierung.

## Matrix

| Legacy-Bereich | Evidenz im Archiv | OpenJarvis-Ziel | Entscheidung für eine spätere Phase | Begründung/Gate |
| --- | --- | --- | --- | --- |
| Chat und Conversation-History | `/api/chat`, `/api/conversation/history` | kanonischer Chat-, Task- und Timeline-Pfad | **ersetzen** | Phase 3 und 6 besitzen bereits die verbindliche Task-/Session-Autorität und UI. Keine API-Kompatibilitätsschicht ohne gesonderten Bedarf. |
| Codex-Provider | `providers/codex_cli.py` | `codex/sdk_backend.py`, App-Server und kontrollierter CLI-Fallback | **ersetzen** | Der Python Codex SDK bleibt bevorzugt. Legacy-CLI-Parsing und Legacy-Prozesszustand werden nicht übernommen. |
| Ollama-/lokale Modellroute | `providers/ollama_local.py`, Modellrouter | aktuelle Backend-Routing-Policy | **verwerfen** | Externe Modelle und Ollama-Live-Nutzung waren für Phase 8A gesperrt; Modellgewichte und Caches bleiben ausgeschlossen. |
| Tasks, Retry, Resume, Cancel | sieben Legacy-Task-Routen und Task-Store | kanonischer Phase-3-Task-Runtime | **ersetzen** | IDs, Zustandsmaschine, Events, Traces, Approvals und Recovery stammen ausschließlich aus Phase 3. |
| Memory-Store und Memory-Routen | elf Legacy-Memory-Routen | Phase-4-Vault-Index, Retrieval, Quellen und Candidates | **blockiert vor Write-Pilot** | 41 ungültige Legacy-IDs, 5 fehlende IDs und 46 fehlende Schema-Versionen erfordern eine Nutzerentscheidung. Keine automatische Neuordnung oder Bereinigung. |
| Legacy-Skill-Registry | 27 JSON-Skilldefinitionen plus Registry | Phase-7-Skill-Lifecycle | **Quarantäne/Kandidat** | Nur statische Metadatenanalyse. Keine Registrierung, Promotion, Aktivierung oder Ausführung. Jede spätere Übernahme ist einzeln zu reviewen. |
| Automations | sechs API-Routen, Service; kein archiviertes aktives Workflow-Payload | aktueller Workflow-/Task-Pfad | **Kandidat** | Semantik und Idempotenz sind einzeln zu portieren. Keine Zeitpläne oder Aktionen werden aus Legacy-State rekonstruiert. |
| Controlled Learning, Demonstrations, Improvement | 18 Routen, acht Feature-Dateien | Phase-7-Evaluation, Candidate-Review und Skill-Lifecycle | **ersetzen** | Legacy-Beobachtungen, Runs und Auto-Improvement-State werden nicht importiert. Nur ausdrücklich reviewte statische Ideen können Kandidaten werden. |
| Browser- und Desktopsteuerung | Browser-/Desktop-Routen und sieben Tooldateien | zentrale Phase-5-Policy, Actions, Approvals und Recovery | **ersetzen** | Browserprofile, Konten, Cookies und Sessions bleiben prohibited. Späterer Betrieb beginnt mit frischer Authentifizierung. |
| Dateioperationen | Read/List sowie Preview/Execute/Undo | Phase-5-Filesystem-/Git-Policy | **ersetzen** | Kein direkter Port alter Mutationspfade; alle Writes bleiben proposal-, policy- und approval-gebunden. |
| Security, PIN und Secrets | PIN-, Secret- und Security-State | zentrale Policy und neue Auth-Grenzen | **verwerfen** | Keine Credentials, PIN-Hashes, Tokens oder Sessions migrieren. Secrets werden später frisch konfiguriert. |
| Audit, Usage und Budgets | Audit-, Usage- und Budget-Routen | Phase-3-Traces, Usage und Budgetautorität | **ersetzen** | Historische Runtime-Datenbanken werden nicht direkt importiert. Nur ein später freigegebenes, schema-definiertes Aggregat wäre zulässig. |
| Speech und Wake | Speech-/Wake-Routen, sieben Speech/Vision/Video-Dateien | Phase-6-Speech-Pfad | **ersetzen; Konfiguration reviewen** | Modellassets, Audio-State und Downloads werden nicht kopiert. Providerkonfiguration benötigt gesonderte Prüfung. |
| Vision und Video | zwölf Routen | vorhandene OpenJarvis-Capabilities plus zentrale Tool-Policy | **Kandidat** | Nur Code-/Vertragsvergleich; keine Medien, Gerätezustände oder Modelle übernehmen. |
| Dokumentanalyse | `/api/documents/analyze` | vorhandene Tool-/Connector-Grenzen | **Kandidat** | Kleiner, offline testbarer späterer Port möglich; noch kein Pilot freigegeben. |
| Website-Staging | zwei Routen und zwei Featuredateien | begrenzte Workspace-/Artifact-Action | **empfohlener späterer Funktionspilot** | Klar begrenzbar und ohne Credential-/Browser-State testbar. Benötigt trotzdem eine eigene Phase-8B-Freigabe. |
| TikTok-Entwürfe und Training | sechs Featuredateien und fünf Routen | noch kein kanonisches Ziel | **Kandidat mit hohem Reviewbedarf** | Geschäftsspezifische Logik, Browserkonto und Veröffentlichungswirkung trennen. Kein Kontozustand und keine Live-Aktion migrieren. |
| Company-/Assistant-Training | zehn Trainingsdateien und fünf Routen | Phase-7-Candidate-/Evaluation-Pfad | **Kandidat** | Datensätze bleiben statische Evidenz. Keine automatische Aufnahme in Learning- oder Skill-Stores. |
| Shared-Brain-Synchronisierung | Preview-/Synchronize-Routen | Vault-Quellen und explizite Connectoren | **blockiert auf Deduplizierungsentscheidung** | Die Vault-Sicherung enthält bereits Shared-Brain-Quellnotizen. Ein erneuter Import könnte Duplikate erzeugen. |
| Legacy-Frontend | drei Dateien und `/api/*`-Verträge | einheitliche Phase-6-UI | **verwerfen** | Kein zweites UI und keine Parallelzustände. Nur fehlende fachliche Anforderungen dürfen einzeln übernommen werden. |

## Reihenfolge für spätere Entscheidungen

1. Vault-ID- und Schema-Mapping festlegen; noch keine echte Vault-Änderung.
2. Entscheiden, ob ein rein isolierter Vault-Konvertierungspilot auf einer Kopie
   oder ein kleiner Website-Staging-Funktionspilot zuerst geprüft werden soll.
3. Für jeden Legacy-Skill, Workflow oder Trainingsdatensatz eine eigene
   Herkunfts-, Sicherheits- und Nutzenprüfung verlangen.
4. Browser-, Credential-, Session-, Modell- und Runtime-State dauerhaft vom
   Content-Migrationspfad getrennt halten.

Phase 8B bleibt gesperrt.
