# Phase 8 – Final Production Acceptance

## Endentscheidung

**B. BLOCKIERT DURCH EINEN KONKRETEN, REPRODUZIERBAREN FEHLER**

OpenJarvis wird nicht als produktiv bereit oder als erfolgreich umgeschaltet
markiert. Der erste reale Aufruf des finalen Launchers scheiterte vor dem
Start eines Server- oder UI-Prozesses. Gemäß der begrenzten
Fehlerkorrekturregel wurde weder der Launcher geändert noch derselbe Start
wiederholt. Der einzige freigegebene Codex-Live-Turn wurde nicht begonnen.

## Sicherer Datenzustand

- Branch: `feature/codex-jarvis-orchestrator`.
- Push-URL des Upstream bleibt `DISABLED`; es wurde weder gepusht noch
  gemergt.
- Die Altprojektquelle wurde nicht verändert und bleibt Recovery-Quelle.
- Vor dem realen Write wurden ein vollständiges Git-Bundle, eine frische
  Vault-Sicherung, die secretfreie lokale Konfiguration sowie die genehmigten
  Mapping- und Recovery-Nachweise extern gesichert.
- Die Vault-Sicherung enthält 59 Dateien mit 60.825 Byte, war vor/nach dem
  Kopieren stabil und bestand eine bytegleiche Restore-Probe. Es gab null
  Ausschlüsse.
- Die reale Schemamigration wurde erfolgreich und transaktional angewendet.
  Der aktuelle Vault entspricht exakt dem dokumentierten After-Manifest
  `f88cf67aeb89e878c39bfcdc2ff6adf230a387c716b8fd258e4cef161573bda2`.
- Nach dem blockierten Start existieren kein Laufzeitzustand, kein
  Shutdown-Token, kein OpenJarvis-/Legacy-Prozess und kein Listener auf Port
  8000. Obsidian wurde zuvor normal geschlossen und blieb geschlossen.
- Ein destruktiver Rollback des erfolgreichen Vaults wurde nicht ausgeführt.

## Reale Vault-Migration

Der aktuelle Bestand hatte weiterhin exakt 59 Dateien und 46 genehmigte
Markdownpfade. Notiztypen, Legacy-ID-Zustände und das genehmigte Mapping waren
identisch; es gab keine Reparse Points, unbekannten Typen oder
Referenzkonflikte. Die 46 Markdown-Bodies hatten gegenüber dem genehmigten
Pilotbestand keinen Drift. Ein Nicht-Markdown-Artefakt unterschied den
aktuellen Gesamtbestand vom älteren Pilotmanifest und wurde unverändert
übernommen.

Ergebnis des Apply:

- 41 ungültige IDs wurden durch ihre genehmigten UUIDv5-Werte ersetzt und als
  exakte `legacy_id` erhalten.
- Fünf fehlende IDs erhielten ihre genehmigten UUIDv5-Werte.
- 46/46 Notizen erhielten `schema_version: 1`.
- 46/46 Notizen besitzen eine gültige, eindeutige UUID.
- 46/46 Bodies, Encodings und Zeilenenden blieben gegenüber dem unmittelbaren
  Before-Zustand bytegleich.
- 59/59 Pfade blieben erhalten; es gab keine Umbenennung, Ergänzung oder
  Löschung.
- Parserfehler: 0; schema-valid: 46; type-supported: 46; FTS-Dokumente: 46;
  Restart-Readback: 46.
- Retrievalklassen: 23 normal, 12 review-only, 6 taxonomy-only, 2
  navigation-only, 1 project-scoped und 2 explicit-review-only.
- Runtime-Policy-Aktivierungen, Approval-Grants, Risk-Senkungen,
  Toolfreigaben, Systemprompt-Aktivierungen und automatische
  Learning-Candidates durch die Migration: jeweils 0.

## Rollback-Nachweis

Der frische Before-Backup wurde in einen neuen leeren Root zurückgespielt.
Alle 59 Dateien waren bytegleich zum Before-Manifest; der read-only
Diagnoseindex las 46 Notizen. Der Migrationsplan wurde mit demselben Plan-Hash
deterministisch erneut erzeugt. Restore- und Diagnoseverzeichnisse wurden
anschließend vollständig entfernt. Der externe Notfallplan stellt immer in
einen neuen Root wieder her und wurde nicht auf den erfolgreichen Vault
angewendet.

## Bestandene fokussierte Gates

- Phase 4 Memory/Vault: 260 bestanden, 16 umgebungsbedingte Skips.
- Phase 5 ToolAction/Policy/Approval: 49 bestanden.
- Phase 6 Tasks/Timeline/Desktop: 132 bestanden.
- Phase-7-Kern: 321 bestanden; Skills: 269 bestanden;
  Workflow/SDK: 72 bestanden.
- Phase 8 Migration/Website: 135 bestanden, 1 Windows-Skip.
- Neue finale Migrationstests: 10 bestanden.
- Final-Runtime- und hermetische Live-Smoke-Tests: 7 bestanden.
- Finaler Product-Evidence-Validator: 6 bestanden.
- Explizite Lifespan-/Shutdown-Tests: 3 bestanden.
- Frontend Vitest: 22 bestanden.
- Frontend-Produktionsbuild und updater-freier Tauri-Webview-Build:
  bestanden.
- Nativer locked/offline Release-Build: bestanden in 3:08 Minuten.
- Ruff, Formatprüfung der geänderten Dateien, Compile/Import und
  `git diff --check`: bestanden.

Der bekannte breite Windows-Legacy-/Server-Sammellauf wurde nicht erneut
gestartet. Sein früherer Prozess-/Thread-Shutdown-Hänger bleibt ein
unverwertbarer abgebrochener Legacy-Lauf und ist kein nachgewiesener
Phase-7- oder Phase-8-Funktionsfehler. Ein zusätzlicher Rust-Einzeltest war
wegen eines rustc-ICE in der Abhängigkeit `h2` nicht verwertbar; der
vollständige native Release-Build und `cargo check --offline` bestanden.
Die bekannten Vite-Warnungen zu Chunking und gemischtem Analytics-Import
blieben unverändert.

## Konkreter Blocker

Fehlerhaftes Gate: `final_launcher_start`.

Reproduktion aus dem Repository-Root mit lokalen Platzhaltern:

```powershell
& .\scripts\windows\openjarvis-final.ps1 `
  -Action Start `
  -RuntimeRoot <runtime-root> `
  -VaultPath <vault-root> `
  -RepoRoot <repository-root> `
  -Port 8000 `
  -TimeoutSeconds 30
```

Reproduzierbares Ergebnis:

```text
netstat failed with code .
```

Die begrenzte `netstat.exe`-Abfrage selbst endet, aber der von
`Start-Process` gelieferte Prozesswrapper stellt an dieser Stelle keinen
auswertbaren `ExitCode` bereit. `Get-PortOwner` interpretiert den leeren Wert
als Fehler. Der Abbruch geschieht vor Server-, UI-, Modell- oder
Vault-Zugriffen des Produktpiloten.

## Nicht ausgeführte Gates

- Kein realer Server-Health-Pilot.
- Kein realer Tauri-Start-/Close-Smoke gegen den finalen Server.
- Kein Produkt-Restart.
- Kein produktiver ToolAction-/Website-/Learning-Pilot.
- Kein Codex-Live-Turn; der exakte Prompt wurde nicht gesendet.
- Kein Cutover.

## Ein konkreter manueller nächster Schritt

`Get-PortOwner` im finalen Launcher manuell so korrigieren und fokussiert
testen, dass der `netstat.exe`-Prozess nach `WaitForExit` aktualisiert und nur
ein tatsächlich gesetzter numerischer Exitcode bewertet wird; anschließend
den oben dokumentierten einzelnen Launcher-Start erneut manuell ausführen.

Es gibt keine Phase 9, keine neue Roadmap und keine zusätzliche
Featurefreigabe.
