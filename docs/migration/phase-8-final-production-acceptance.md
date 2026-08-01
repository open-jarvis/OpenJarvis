# Phase 8 – Final Production Acceptance

Stand: 1. August 2026

## Endentscheidung

**A. OPENJARVIS PRODUKTIV BEREIT UND CUTOVER BESTANDEN**

OpenJarvis startet über den finalen Windows-Launcher als sichtbare
Desktop-Anwendung. Die UI verbindet sich im Attach-only-Modus mit genau einem
verwalteten OpenJarvis-Server. Backend ist das Codex Python SDK; Ollama, Qwen,
`uv`-Setup, ein zweiter API-Server und CLI-Fallback bleiben deaktiviert.

## Behobene Abschlussblocker

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

Nach dem abschließenden Launcher-`Restart` galt:

- Status `ready`, Marker `OPENJARVIS-FINAL-RUNTIME`, Runtime `phase8-final`.
- Server-PID/Health-PID/Port-Owner: `3563552`.
- Sichtbare Release-UI-PID: `3568528`.
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

Ein zuvor terminaler Task blieb unverändert. Die erste normale Nachricht legte
einen neuen Task und Codex-Thread an und wurde genau einmal verarbeitet:

```text
Hallo, antworte bitte nur mit: JARVIS HÖRT MICH
JARVIS HÖRT MICH
```

Nach dem kontrollierten Restart wurde derselbe resumierbare Task fortgesetzt.
Auch die Folgefrage wurde genau einmal verarbeitet und sichtbar beantwortet:

```text
Hallo, antworte bitte nur mit: JARVIS RESTART OK
JARVIS RESTART OK
```

Für den tatsächlichen Turn zeigt die sichtbare UI und liefert die persistierte
Task-Summary übereinstimmend:

- Modell `gpt-5.6-sol`;
- Reasoning-Effort `xhigh`;
- Modell und Effort jeweils `App Server confirmed`;
- Backend `python_sdk`;
- Python-SDK-Version `0.144.4`;
- gepinnte App-Server-/CLI-Runtime `0.144.4`;
- persistierte, in der UI gekürzte Codex-Thread-ID.

Damit läuft im Hintergrund Sol, nicht Luna oder Terra. Die Anmeldung erfolgt
über die vorhandene ChatGPT-Anmeldung; die Anwendung nutzt das Python Codex SDK
gegen die gepinnte App-Server-/CLI-Runtime, nicht Ollama oder ein externes
Modell.

## Finaler Codex-Live-Smoke

Erst nach dem grünen normalen Chat und Restart wurde in diesem Abschlusslauf
genau ein finaler Marker-Turn ohne Retry gesendet:

```text
Return exactly: JARVIS-FINAL-LIVE-OK
JARVIS-FINAL-LIVE-OK
```

Es entstanden genau ein User- und ein Assistant-Event. Der Antwort-Hash ist
`1c4b014fb0d1689000c2de13253e190ba3b675bf58b1d994c50c472d14479367`.
Tool-, Browser-, Datei-, Vault- und externe Aktionen: 0. Ein älterer,
separat genehmigter direkter SDK-Proof bleibt als historisches Artefakt im
Recovery-Bestand; er wurde nicht wiederholt oder als Ergebnis dieses Laufs
gezählt.

## Bestandene fokussierte Gates

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
- Serieller nativer Tauri-Release-Build, locked/offline: bestanden;
  Binary-SHA-256
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

Das externe Recovery-Bundle wird nach diesem Dokumentationscommit atomar mit
einem neuen kanonischen Git-Bundle aktualisiert, auf exakten HEAD, sauberen
Restore-Arbeitsbaum und `git fsck --strict` geprüft. Sein SHA-256 wird extern
gespeichert, da ein Commit den Hash seines eigenen Bundles nicht enthalten
kann.

OpenJarvis bleibt nach Abschluss sichtbar geöffnet und betriebsbereit. Es gibt
keine neue Phase und keine weitere Roadmap.
