# Phase 8B: Isolierter Website-Staging-Funktionspilot

Stand: 1. August 2026

## Ergebnis und Grenze

Der hermetische Website-Staging-Pilot ist bestanden. Er erzeugt und verändert
ausschließlich synthetische statische Websites in einem eigens provisionierten
temporären Root. Preview, risikogebundene Einmalfreigabe, Mutation,
Verifikation, Artifact-Manifest, Trace, Restart-Readback, Rollback und Cleanup
laufen über die kanonischen OpenJarvis-Dienste.

Dieser Stand ist technisch für einen späteren, erneut ausdrücklich
freizugebenden kontrollierten Produktivpilot vorbereitet. Er erteilt keine
Freigabe für produktives Website-Staging, Veröffentlichung, Netzwerkzugriff,
reale Projekte, Vault-Migration oder Cutover.

Ausgangs-HEAD war
`aafa868bd75386883165ebf019c6c1a52b532192`. Der Implementierungsstand vor
diesem Berichtscommit ist
`453e159305a3723bfa48573f528f4783fa0bdf07`.

## Legacy-Inventur und Portierungsentscheidung

Die Inventur erfolgte ausschließlich aus dem zuvor verifizierten
Phase-8A-Legacy-Content-Archiv. Das alte Arbeitsprojekt wurde nicht erneut
geöffnet und kein Legacy-Code wurde importiert oder ausgeführt. Die
Detailinventur steht in
`docs/migration/phase-8b-website-staging-inventory.md`.

Die Legacy-Funktion hatte zwei Routen:

- `GET /api/website/status` las eine konfigurierte Projektwurzel und fragte
  lokale Git-Metadaten ab;
- `POST /api/website/stage` kopierte bei sauberem Git-Status rekursiv ein
  konfiguriertes Projekt in einen Stagingpfad.

Selektiv übernommen wurden nur die fachlichen Ideen eines lokalen,
abgegrenzten Stagingbereichs, eines Status-/Readbackpfads und einer
vorhergehenden Sicherheitsentscheidung. Ersetzt wurden sie durch
hashgebundene Requests und Pläne, explizite Dateilisten, Budgets, CAS,
statische Inhaltsprüfung, zentrale Policy, Allow-once, Artefakte und
byte-identischen Rollback.

Verworfen wurden insbesondere die freie Projektkopie, implizite
Konfigurationsroots, Git-Unterprozesse, Legacy-Sitzung/Runtime als
Vertrauensgrenze und alle behaupteten, aber im Legacy-Code nicht vorhandenen
Deploy-, Test-, Preview-, Diff- und Rollbackfähigkeiten. Netzwerk-, Account-,
Hosting-, DNS- und Veröffentlichungssemantik wurde nicht portiert.

## Verträge und isolierter Workspace

Die unveränderlichen, strikt validierten Modelle umfassen:

- `WebsiteStagingRequest` mit Identitäten, Operation, exakten Source-/Output-
  Listen, Dateitypen, Budgets, Overwrite-/Verification-Policy,
  Idempotency-Key, UTC-Zeit und kanonischem Request-Hash;
- `WebsiteFileProposal` mit relativer Datei, Medientyp, Größe, Inhaltshash und
  optionalem Before-Hash;
- `WebsiteStagingPlan` mit Before-/After-Zustand, Diff, Risiko, Warnungen,
  externen URLs, Scriptinventar und Preview-Hash;
- `WebsiteStagingExecution`, `WebsiteArtifactManifest`,
  `WebsiteVerificationResult` und `WebsiteRollbackRecord` mit ihren jeweiligen
  Bindungs- und Gesamthashes.

Erlaubte Vertragsoperationen sind `create_static_site`,
`update_static_site`, `preview_diff`, `validate_static_site`,
`package_artifact` und `rollback_staging`. Deploy, Publish, Upload,
Remote-Synchronisation, DNS-/Hostingänderung, Authentifizierung und entfernte
Kommandos sind nicht modelliert und werden als unbekannte Eingabe abgelehnt.

Der `WebsiteWorkspaceStore` bindet alle Pfade an einen genehmigten Root,
verhindert absolute Pfade, Traversal, versteckte Pfade sowie
Symlink-/Junction-/Reparse-Zugriff und hält Workspace, Restore, Preview und
Record getrennt. Dateitypen, Anzahl und Gesamtgröße sind begrenzt. JavaScript
wird ausschließlich als statischer Text gelesen und niemals ausgeführt.

## Kanonischer Ausführungspfad

`WebsiteStagingService` registriert genau eine vertrauenswürdige Runtime
`website.staging.mutate` samt Manifest beim `ToolActionService`. Der Pfad ist:

`WebsiteStagingPlan -> ToolProposal -> ToolActionService -> CentralRiskPolicy
-> Allow-once -> Lane Scheduler -> Runtime -> Verification -> TraceEvaluation
-> Artifact Manifest`.

Das Manifest erzwingt reversible lokale Writes, Netzwerk `deny`, Secret
`reject`, Approval und einen Idempotency-Key. Der Policy-Kontext bindet die
Stagingwurzel nochmals an den Toolpfad. Fehlender Action Service, fehlende
Runtime-Verifikation und unbekannte Wirkung schlagen geschlossen fehl. API
und UI besitzen keinen direkten Executor- oder Dateisystempfad und bieten kein
`Always Allow`.

OpenJarvis kennt gegenwärtig nur `model_lane` und `interactive_lane`; eine
eigene `filesystem_lane`-Enum existiert nicht. Der Pilot nutzt deshalb die
nicht-interaktive `model_lane` als vorhandene lokale Tool-Lane. Die
Dateisystemautorität stammt ausschließlich aus Capability, Root-Bindung,
Manifest, Policy und Runtime-Registrierung. Eine separate Filesystem-Lane ist
eine mögliche spätere Härtung, kein stiller Fallback dieses Pilots.

## Preview, Apply und Verifikation

Preview liest und hasht nur den isolierten synthetischen Workspace. Es erzeugt
ein vollständiges Before-/After-Modell, Diff, Risikostufe, externe
URL-Metadaten, Scriptinventar und einen kanonischen Preview-Hash, verändert
aber keine Website-Datei.

Apply verlangt Requestidentität, Idempotency-Key und den erwarteten
Preview-Hash. Unmittelbar davor wird das Before-Manifest per CAS geprüft. Die
Runtime erstellt eine getrennte, verifizierte Restore-Kopie, schreibt zunächst
temporär, ersetzt atomar und scannt danach erneut. Der Schreibstatus allein
gilt nie als Erfolg.

Die statische Verifikation prüft den exakten Dateisatz und Manifest-Hash,
Budgets, Erweiterungen, Pfade/Reparse Points, HTML-Struktur, lokale Links und
Assets sowie verbotene URLs, Formulare, Meta Refresh, Secretmuster und
dynamische JavaScript-/Shell-Konstrukte. Externe HTTP(S)-Links werden nicht
aufgerufen, sondern als Warnung erfasst; damit gilt die strikte Verifikation
nicht fälschlich als vollständig bestanden.

Das Artifact-Manifest enthält pro Datei nur relative Pfade, Medientyp, Größe,
SHA-256, Herkunftsklasse, Änderungstyp, Verifikationsstatus, Warnungen und Zeit
sowie einen kanonischen Gesamthash. Es enthält keine absoluten privaten Pfade.

## API und UI

Die bestehende FastAPI-App stellt ausschließlich bei injiziertem
Website-Staging-Service bereit:

- `POST /v1/website-staging/preview`;
- `POST /v1/website-staging/apply`;
- `POST /v1/website-staging/validate`;
- `POST /v1/website-staging/rollback`;
- `GET /v1/website-staging/{workspace_id}`;
- `GET /v1/website-staging/{workspace_id}/artifacts`.

Loopback-, bestehende Auth-, Actor-, Correlation-, Idempotency- und
Hashbindungen gelten an den Mutationsrouten. Ohne injizierten Service wird
fail-closed geantwortet. Die Jarvis-UI zeigt Preview-Diff, Dateien, Größen,
Risiko, Warnungen, Allow once/Deny, Apply, Verifikation, Artefakte und
Rollbackstatus. Ihr dauerhafter Hinweis lautet: „Nur isolierter lokaler
Workspace – keine Veröffentlichung“.

## Hermetische Piloten

Pilot A erstellte HTML/CSS, führte Preview und Allow-once-Apply über den
Action Service aus, verifizierte Dateien und Artefakte, las Zustand und
TraceEvaluation nach neu erzeugtem Serviceobjekt wieder ein, bestätigte einen
zweiten identischen Apply als No-op und rollte byte-identisch zurück.

Pilot B provisionierte eine synthetische Website, änderte HTML und CSS mit
Before-Hashes, prüfte den lokalen Stylesheet-Link, verifizierte Manifest und
Artefakte und stellte anschließend exakt den ursprünglichen Manifest-Hash
wieder her.

Pilot C bestätigte fail-closed für Traversal, absoluten und versteckten Pfad,
unbekannte Binärdatei, Datei- und Größenbudget, eingebettetes Secret, externe
Formaktion, Meta Refresh, `file://`, `eval`, `new Function`, Shellinhalt,
falschen Preview-Hash, fehlenden Action Service, fehlende Verifikation und
unbekannte Wirkung. Ein driftender After-Zustand blockierte den Rollback ohne
Überschreiben. Die doppelte Ausführung blieb idempotent.

Der Host erlaubte ohne erhöhte Rechte keine echte Symlink-Erzeugung
(`WinError 1314`). Die Produktionsprüfung auf Reparse Points ist aktiv und
wurde deshalb im Pilot simuliert sowie in der fokussierten Testsuite durch
einen erzwungenen Reparse-Befund regressionsgetestet. Es gab keine Lockerung
oder Ausnahme im Produktivcode.

Alle Pilotroots, Restore-Verzeichnisse und temporären SQLite-Dateien lagen in
einem `TemporaryDirectory` und waren nach Prozessende entfernt. Sentinel-
Hashes für ein synthetisches „geschütztes Projekt“ und „geschütztes Vault“
blieben identisch. Socket- und DNS-Aufrufe waren im Piloten hart geblockt;
beobachtet wurden null Netzwerkaufrufe. Legacy-Ausführung, externe Modelle und
Codex-Live-Turns blieben `false`.

Zwei frühe Harness-Aufrufe schlugen innerhalb weniger Sekunden geschlossen
fehl, weil die Unknown-Binary-Prüfung zunächst auf der falschen Vertragsebene
angesetzt war. Sie erzeugten kein Review-Bundle. Ein erster grüner
Bundleentwurf wurde nach Ergänzung der ausdrücklich geforderten Größenbudget-,
Rollback-Drift- und Unknown-Effect-Gates kontrolliert ersetzt. Nur das
vollständige finale Bundle gilt als Nachweis.

## Tests und Gates

| Gruppe | Ergebnis |
| --- | --- |
| Website-Service und Website-API | 57 bestanden |
| Phase-5/6 ToolAction, Policy, Approval, Task und Timeline | 62 bestanden |
| Phase-7 Evaluation, Candidates, Skill-Safety/Lifecycle und API | 202 bestanden |
| Phase-8-Migrationssuite | 68 bestanden, 1 bestehender plattformbezogener Skip |
| Frontend Vitest | 7 Dateien, 22 Tests bestanden |
| Frontend-Produktionsbuild | bestanden |

Der Produktionsbuild meldet nur die bestehenden Vite-Hinweise zu einem leeren
React-Chunk, gemischtem statisch/dynamischem Analytics-Import und einem großen
Bundle. Sie sind keine Website-Staging-Funktionsfehler.

Die Abschlussgates umfassen außerdem Ruff, Formatprüfung, Compile-/Importprobe,
`git diff --check`, Secret-/Privatpfadscan, Socket-Guard, sauberen Git-Status,
Prozess-/Temporärdateiprüfung und erneute Integritätsprüfung der unveränderten
Phase-8A-Nachweise.

## Externe Review-Artefakte

Das nicht versionierte externe Review-Bundle enthält genau:

- `legacy-inventory.json`;
- `preview-report.json`;
- `artifact-manifest.json`;
- `verification-report.json`;
- `rollback-proof.txt`;
- `cleanup-proof.json`;
- `pilot-summary.json`.

Keine Pilotworkspace-, Restore-, Runtime-Datenbank-, Vault-, Projekt- oder
Secretdatei wurde committed.

## Bekannte Einschränkungen

- Der Verifikator ist absichtlich ein strikter statischer Prüfer, kein Browser
  und kein vollständiger HTML-/JavaScript-Laufzeitvalidator.
- JavaScript wird nicht ausgeführt; dynamisches Verhalten ist damit nicht als
  funktionsfähig bestätigt.
- Externe Links bleiben reine Metadatenwarnungen; ihre Erreichbarkeit oder
  Sicherheit wurde nicht geprüft.
- `package_artifact` bezeichnet in diesem Pilot die manifestierte
  Artefaktansicht; es wird bewusst kein Archiv oder Deploymentpaket erzeugt.
- Die Runtime wird explizit durch die Anwendung injiziert und ist ohne diese
  Konfiguration nicht verfügbar.
- Eine eigene Filesystem-Lane und ein realer privilegierter Windows-Reparse-
  Test bleiben mögliche Härtungsschritte vor einem Produktivpilot.

Damit ist nur dieser isolierte Phase-8B-Arbeitsblock abgeschlossen. Reale
Vault-Migration, produktive Projekte, Website-Veröffentlichung, Accounts,
Browserkonfiguration, Cutover, Altprojekt-Ablösung und Push bleiben gesperrt.
