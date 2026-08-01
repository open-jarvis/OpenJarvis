# Phase 8 – Final Production Acceptance

Stand: 1. August 2026, korrigierter Nachweis nach dem Chat-Lifecycle-Fehler

## Endentscheidung

**B. MANUELLE FREIGABE ERFORDERLICH**

Der Python-Chatpfad beantwortet normale Fragen wieder zuverlässig über das
Codex Python SDK mit explizit bestätigtem `gpt-5.6-terra` und `xhigh`. Der
laufende finale Server ist gesund und die vorhandene native App ist sichtbar
verbunden. Die aktuelle Release-EXE enthält jedoch noch nicht die neue
Frontend-Lifecycle-Korrektur, weil die einzige installierte Rust-Toolchain ihre
eigenen `std`-/`core`-Artefakte nicht kompilieren kann. Eine automatische
Reparatur oder Neuinstallation der Toolchain ist nicht freigegeben.

Die erweiterte Definition of Done für Desktop-, Browser- und
Programmieraufgaben ist außerdem noch nicht vollständig durch reale E2E-Smokes
nachgewiesen. Deshalb darf der frühere Produktiv-Bereit-Status nicht als
aktuelle Abnahme verwendet werden.

## Behobene Abschlussblocker

Nach dem reproduzierbaren normalen Chatfehler wurden zusätzlich behoben:

- Text-Streaming-Deltas zählen nicht mehr einzeln gegen das Turn-Schrittlimit;
  nur begonnene Arbeits-Items werden gezählt.
- Gleichzeitige SDK-/App-Server-Starts werden serialisiert, sodass nicht zwei
  Leser denselben App-Server-Stream konsumieren.
- Ein Streamfehler hinterlässt keinen dauerhaft `running` markierten Task,
  sondern terminalisiert ihn fail-closed als `failed`.
- Der finale Runtimepfad fordert für jeden Turn ausdrücklich
  `gpt-5.6-terra`/`xhigh` an und verwirft einen unbestätigten oder abweichenden
  Runtime-Nachweis.
- Ein pausierter, risikofreier Chat-Task ohne offene Approval kann in der neuen
  UI durch einen neuen Task ersetzt werden. Riskante oder approval-gebundene
  pausierte Tasks bleiben gesperrt.

Die folgenden kleinen, getrennten Korrekturen waren für den realen
Windows-Produktstart erforderlich:

- Der Launcher startet standardmäßig die repository-relative Release-EXE.
- `netstat.exe` wird direkt ausgewertet; ein leerer Wrapper-Exitcode kann nicht
  mehr als `code .` erscheinen.
- Die vom Health-Endpunkt und Listener gemeinsam bestätigte Nachfahren-PID ist
  die kanonische Server-PID; eine Wrapper-PID wird nicht persistiert.
- Ein nach dem geschlossenen Listener verbleibender Windows-Serverthread wird
  nur nach erneuter Prüfung von PID, Startzeit und Executable beendet. Es gibt
  kein Beenden nach Prozessnamen.
- Der native Tauri-Build deaktiviert den PWA-Service-Worker. Eine vorhandene
  alte Registration wird im Attach-Modus abgemeldet und höchstens einmal neu
  geladen; Cache-, Cookie- und Profildaten werden nicht geöffnet oder gelöscht.
- Unvollständige Live-DTOs können die Jarvis-Timeline nicht mehr über
  `.replace()`/`.includes()` in den ErrorBoundary bringen.
- Die Task-Summary wird periodisch und ohne Webview-Cache aktualisiert.
- Der Secret-Redactor bewahrt die kanonischen Task-, Session- und
  Correlation-IDs. Zuvor wurde der Teil `sk-` in IDs des Formats `task-…`
  fälschlich als API-Key erkannt, wodurch die UI bestätigte Turndaten verwarf.

Die zugehörigen lokalen Commits sind `25706fda`, `e05c2dc6`, `8d76e65f`,
`94fcf1fa`, `0ce8d250`, `87975cfa` und `6fff70ce`. Es gab keinen Push oder
Merge.

## Produktiver Laufzeitnachweis

Für den aktuell laufenden Launcherzustand gilt:

- Status `ready`, Marker `OPENJARVIS-FINAL-RUNTIME`, Runtime `phase8-final`.
- Server-PID/Health-PID/Port-Owner: `3622456`.
- Sichtbare Release-UI-PID: `3625076`.
- Backend `python_sdk`, ChatGPT-Anmeldung vorhanden.
- Sandbox `read_only`, Approval-Modus `deny_all`, CLI-Fallback aus.
- Browser-Sessions deaktiviert, 0 wartende Approvals, 0 Tool-Aktionen.
- Tool-Health gesund (1 registriertes Tool); Browser und weitere optionale,
  bewusst nicht gestartete Komponenten erklären den aggregierten Status
  `degraded`, nicht ein Kernsystemfehler.
- Kein Qwen-, Ollama- oder `uv`-Setup war sichtbar oder aktiv.

Der bekannte Windows-Prozess-/Thread-Shutdown-Hänger trat beim kontrollierten
Stop reproduzierbar auf. Der Listener war bereits geschlossen; anschließend
griff ausschließlich die erneut verifizierte kanonische PID-Recovery. Stop,
Start und Restart waren danach vollständig und hinterließen keinen fremden
Prozess oder offenen zweiten Listener.

## Chat-, Task- und Modellnachweis

Der reproduzierbare Fehler bei `was kannst du` war kein fehlendes
Sprachverständnis. Die Antwort wurde als viele Text-Deltas gestreamt und lief
dadurch fälschlich in `turn step limit exceeded`. Dieser Task wurde nach der
Reparatur kontrolliert als `canceled` terminalisiert, ohne ihn fortzusetzen.

Danach wurde genau eine normale Wissensfrage ohne Toolaufruf verarbeitet:

```text
Erkläre mir einfach, wie ein Elektromotor funktioniert.
[vollständige, verständliche Erklärung eines Elektromotors]
```

Genau eine Rückfrage im selben Task und Thread wurde im Kontext verstanden:

```text
Und warum bleibt er nach einer halben Umdrehung nicht stehen?
[kontextbezogene Erklärung von Kommutator beziehungsweise elektronischer Umschaltung]
```

Die persistierte Task-Summary bestätigt für diese tatsächlichen Turns:

- angefordertes und aufgelöstes Modell `gpt-5.6-terra`;
- Reasoning-Effort `xhigh`;
- Modell und Effort jeweils `App Server confirmed`;
- Backend `python_sdk`;
- Python-SDK-Version `0.144.4`;
- gepinnte App-Server-/CLI-Runtime `0.144.4`;
- persistierte, in der UI gekürzte Codex-Thread-ID.

Die Anmeldung erfolgt über die vorhandene ChatGPT-Anmeldung; die Anwendung
nutzt das Python Codex SDK gegen die gepinnte App-Server-/CLI-Runtime, nicht
Ollama oder ein externes Modell. Ein stiller Modell-Fallback ist im finalen
Pfad jetzt verboten.

## Finaler Codex-Live-Smoke

Der bereits früher genehmigte finale Marker-Turn bleibt historisch dokumentiert:

```text
Return exactly: JARVIS-FINAL-LIVE-OK
JARVIS-FINAL-LIVE-OK
```

Es entstanden damals genau ein User- und ein Assistant-Event. Der Antwort-Hash ist
`1c4b014fb0d1689000c2de13253e190ba3b675bf58b1d994c50c472d14479367`.
Tool-, Browser-, Datei-, Vault- und externe Aktionen: 0. Dieser Marker-Turn
wurde bei der aktuellen Reparatur nicht wiederholt. Die normale Wissensfrage
und ihre eine Kontextfolge waren die einzigen aktuellen Modell-Turns.

## Bestandene fokussierte Gates

Aktuelle Reparaturgates:

- Python-Transport-, SDK-, Orchestrator-, Konfigurations- und
  Final-Runtime-Fokustests: 30/30.
- Betroffene Frontend-Lifecycle-Tests: 16/16.
- Frontend-Tauri-Webview-Produktionsbuild: bestanden.
- Ruff, Compileprüfung und `git diff --check`: bestanden.

Historisch bestandene Gates vor der aktuellen Reparatur:

- Frontend Vitest: 37/37.
- Neue API-/Lifecycle-Fokustests: 23/23.
- Rust/Tauri Unit-Tests: 24/24.
- Launcher-/Tauri-Pytests: 17/17.
- Task-Route-Suite einschließlich Identity-Regression: 14/14.
- Server-Lifespan-/Shutdown-Fokus: 3/3.
- Final-Product-Pilot/Offline-Socket-Guard: 6/6.
- Hermetischer Live-Smoke-Vertrag: 3/3.
- Recovery-Bundle-Test: 1/1.
- Frontend-Produktionsbuild: bestanden.
- Tauri-Webview-Build ohne Service-Worker: bestanden.
- Der frühere serielle native Tauri-Release-Build war bestanden;
  die unveränderte alte Binary hat SHA-256
  `527ed3548d04d96e70c46e2da43d383115789757ffc3c5a8a0d90be60d8c1ab7`.
- Ruff, Compile-/Importprüfung, `git diff --check` und Secret-Scan: bestanden.

Der komplette `BuildFinal`-Wrapper erreichte einmal nach 304 Sekunden sein
Zeitlimit und wird nicht als grün gezählt. Seine Child-Prozesse waren beendet
und MSI/NSIS-Artefakte waren erzeugt; kanonischer nativer Nachweis bleibt der
separat mit Exitcode 0 beendete serielle Release-Build. `cargo fmt --check`
war nicht verfügbar, weil die bestehende Toolchain keine `rustfmt`-Komponente
enthält; es wurde nichts installiert.

Der frühere breite Windows-Legacy-/Server-Sammellauf bleibt als
Prozess-/Thread-Shutdown-Hänger, Timeout/Abbruch ohne verwertbares Endergebnis
und nicht bestanden dokumentiert. Er wurde nicht wiederholt und ist kein
nachgewiesener Phase-7- oder Phase-8-Funktionsfehler.

## Offenes natives Build-Gate

Der aktuelle native Release-Build ist **nicht bestanden** und wird nicht als
grün gezählt:

- `rustc 1.97.1` und `cargo 1.97.1` werden über die einzige installierte
  Toolchain `stable-x86_64-pc-windows-msvc` gefunden.
- `rust-std` ist als installiert registriert und der Sysroot enthält Dateien
  für `std` und `core`.
- Ein direktes minimales `rustc`-Programm scheitert dennoch außerhalb jedes
  Cargo-Target-Caches mit `only metadata stub found` beziehungsweise einer als
  `staticlib` statt `rlib` erkannten Standardbibliothek.
- Ein neuer externer Target-Ordner reproduziert denselben Fehler. Das Problem
  ist deshalb kein repository-lokaler `target`-Cache.
- Es existiert keine zweite bereits installierte Toolchain als zulässige
  Ausweichmöglichkeit.

Die alte native EXE blieb byte-identisch und die laufende App verwendet sie
weiterhin. Für einen korrekten Neubau ist eine ausdrücklich genehmigte manuelle
Reparatur oder Neuinstallation der Rust-Toolchain notwendig. Danach müssen
Release-Build, betroffene Rust-/Tauri-Tests sowie Start/Close/Restart erneut
bestanden werden.

## Noch offene Definition-of-Done-Nachweise

Nicht als bestanden gemeldet werden:

- die neue Frontend-Lifecycle-Korrektur in einer neu gebauten nativen EXE;
- ein sicherer Desktop-E2E-Smoke mit sichtbarer Ausführung und Verifikation;
- ein Browserrecherche-E2E-Smoke mit Quellen und Prompt-Injection-Abwehr;
- ein isolierter Programmier-E2E-Smoke;
- reale Approval-/Ablehnungs- und Timeout-/Prozess-Cleanup-Smokes für diese
  vier Assistentenpfade.

## Daten-, Vault- und Recovery-Grenzen

- Das reale Vault wurde in diesem Abschluss nicht migriert, beschrieben,
  umbenannt, neu geordnet oder zurückgerollt.
- Sein reine-Metadaten-Fingerprint blieb exakt unverändert: 59 Dateien,
  46 Markdown-Dateien, SHA-256
  `60ac7361cdf51b97b27c9e34c625cfbbfcbe37fd3580f1a79a524d78dedbaab6`.
- Der genehmigte After-Manifest-Hash bleibt
  `f88cf67aeb89e878c39bfcdc2ff6adf230a387c716b8fd258e4cef161573bda2`.
- Altprojekt, Vault-Backup, Pre-Write-Bundle und Mapping-Artefakte bleiben
  unverändert.
- Kein Netzwerkdownload, keine globale PATH-/Registry-/Policy-Änderung, keine
  Installation, kein Zugriff auf Browserprofile/Cookies/Tokens und kein Push.
- Der aktuelle Cargo-Pfad wurde ausschließlich pro Buildprozess ergänzt.

Das externe Recovery-Bundle wird nach diesem Dokumentationscommit auf den
aktuellen nachweisbaren Stand aktualisiert. Es darf die offenen Gates nicht als
bestanden kennzeichnen.

OpenJarvis bleibt sichtbar geöffnet; der Python-Chatpfad ist betriebsbereit.
Die vollständige Produktabnahme bleibt bis zur Toolchain-Freigabe, zum nativen
Neubau und zu den noch offenen sicheren E2E-Smokes ausgesetzt. Es gibt keine
neue Phase und keine weitere Roadmap.
