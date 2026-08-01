# Phase 8 - Final Production Acceptance

## Endentscheidung

**A. OPENJARVIS PRODUKTIV BEREIT UND CUTOVER BESTANDEN**

OpenJarvis startet ueber den finalen Windows-Launcher als sichtbare
Desktop-Anwendung und verwendet ausschliesslich den vorhandenen finalen
Runtime-Server mit dem Backend `python_sdk`. Der produktive Modus startet
keinen zweiten API-Server, kein lokales Modell, kein Ollama, kein Qwen und
keine `uv`-Installation.

## Ursache und Korrektur

Die zuvor manuell gestartete Desktop-EXE erhielt die Launcher-Variable
`OPENJARVIS_FINAL_ATTACH_ONLY=1` nicht. Dadurch wurde der bestehende
Legacy-Bootstrap der Upstream-Anwendung ausgefuehrt. Die Release-EXE war nicht
grundsaetzlich veraltet; der direkte manuelle Start war jedoch kein gueltiger
Produktivstart.

Der finale Attach-Modus wurde zusaetzlich fail-closed gehaertet:

- Nur der exakte Variablenwert `1` aktiviert Attach-only.
- Vor dem UI-Start muss `/v1/final/health` den Marker
  `OPENJARVIS-FINAL-RUNTIME`, Runtime `phase8-final`, Status `ready` und
  Backend `python_sdk` melden.
- Im Attach-Modus endet der Tauri-Bootpfad vor jedem Legacy-, Ollama-, Qwen-,
  `uv`- oder Local-Model-Bootstrap.
- Die Frontend-API-Basis ist in diesem Modus fest auf den bestehenden
  Loopback-Server gesetzt; gespeicherte oder Build-Time-URLs koennen ihn nicht
  uebersteuern.
- Ein falscher oder nicht erreichbarer Runtime-Server fuehrt ohne Fallback zur
  Meldung `OpenJarvis Codex Runtime ist nicht erreichbar.`
- Die Setup-Anzeige kennt den Codex-Attach-Zustand und zeigt keine
  Local-AI-Installationsschritte.

Zwei waehrend des realen Windows-Starts reproduzierte Launcher-Probleme wurden
im selben eng begrenzten Abschluss behoben: lokalisierte `netstat.exe`-Ausgabe
wird mit der OEM-Codepage gelesen, und der verwaltete Server schreibt seine
Standardausgaben in Runtime-Logdateien, statt den aufrufenden Prozesskanal
offen zu halten.

## Produktiver Laufzeitnachweis

Nach einem kontrollierten WM_CLOSE-Smoke und genau einem Launcher-Restart galt:

- Launcher-Status: `ready`.
- Health-Marker: `OPENJARVIS-FINAL-RUNTIME`.
- Runtime: `phase8-final`.
- Backend: `python_sdk`.
- Richtlinie: Sandbox `read_only`, Approval `deny_all`.
- Server-PID, Health-PID und Port-Owner waren identisch: `3412392`.
- Die persistierte UI-PID `3422040` gehoerte exakt zur gebauten Release-EXE.
- Es lief genau eine Instanz der Release-UI; die alten Server- und UI-PIDs
  waren beendet.
- Die normale Jarvis-Hauptoberflaeche war sichtbar und zeigte
  `codex-python-sdk`, bestehende ChatGPT-Anmeldung sowie Memory/FTS5.

Der System-Sammelstatus meldet optionale, bewusst nicht gestartete Komponenten
Browser, Desktop-Adapter und Speech als `unavailable`. Server, Codex, Memory,
Task Store, Trace Store und Tools sind gesund; der verbindliche finale
Health-Endpunkt ist `ready`. Das ist kein Qwen-/Ollama-Fallback und kein
zweiter Server.

## Funktionspruefung

- Das reale Vault wurde ausschliesslich read-only geoeffnet: 46 Notizen,
  46 schema-gueltig, 46 FTS5-Dokumente und 0 Parserfehler.
- Eine normale Memory-Abfrage lieferte belegte Quellen; sie enthielt keine
  authority-sensitive Aktivierung.
- Ein kanonischer Task wurde angelegt und seine Timeline war lesbar.
- Learning- und Skills-Seiten wurden in der sichtbaren Release-UI geladen.
- Die Skills-Registry war lesbar; ein leerer Registry-Bestand ist zulaessig.
- Browser-, Modell- und externe Aktionen blieben deaktiviert.
- Die UI akzeptierte WM_CLOSE und beendete sich ohne Force-Kill, waehrend der
  Server zunaechst weiter ready blieb.
- Der anschliessende einzelne Launcher-Restart beendete den verwalteten alten
  Server kontrolliert und startete genau einen neuen Server sowie genau eine
  neue UI.

## Genau ein Codex-Live-Smoke

Nach allen Offline- und Produktgates wurde genau ein ephemeraler Turn ueber das
Codex Python SDK gestartet. Prompt und Antwort waren exakt:

```text
Return exactly: JARVIS-FINAL-LIVE-OK
JARVIS-FINAL-LIVE-OK
```

Der Nachweis hat Status `passed`. Der Turn verwendete `read_only` und
`deny_all`; Tool-, Datei-, Browser- und externe Aktionen: 0. Es gab keinen
zweiten Turn und keinen Retry.

## Bestandene fokussierte Abschlussgates

- Attach-/Launcher-Pytest: 15 bestanden.
- Vollstaendiges Frontend Vitest: 25/25 bestanden.
- Fokussierte Tauri-/Rust-Tests: 2 bestanden, 22 gefiltert.
- Frontend-Produktionsbuild: bestanden.
- Tauri-Webview-Build ohne Updater: bestanden.
- Nativer locked/offline Tauri-Release-Build: bestanden.
- Nativer Start-/WM_CLOSE-Smoke: bestanden, kein Force-Kill.
- PowerShell-Parser: bestanden.
- `git diff --check`: bestanden.
- Finaler Launcher-Status, Health-/Listener-Ownership und Restart: bestanden.
- Einziger Codex-Live-Smoke: bestanden.

Der bekannte breite Windows-Legacy-/Server-Sammellauf wurde nicht erneut
gestartet. Sein frueherer Prozess-/Thread-Shutdown-Haenger bleibt als
abgebrochener Legacy-Sammellauf dokumentiert und ist kein nachgewiesener
Phase-7- oder Phase-8-Funktionsfehler.

## Daten-, Cutover- und Recovery-Grenzen

- Das reale Vault wurde nicht erneut migriert, beschrieben oder
  zurueckgerollt. Sein genehmigtes After-Manifest bleibt
  `f88cf67aeb89e878c39bfcdc2ff6adf230a387c716b8fd258e4cef161573bda2`.
- Altprojekt, Vault-Backup, Pre-Write-Repository-Bundle und genehmigte
  Mapping-Artefakte bleiben unveraendert.
- Es gab keinen Push, Merge oder eine neue Phase.
- Der resultierende Commit traegt den Betreff
  `fix: attach final desktop to codex runtime`.
- Das nach diesem Commit erzeugte kanonische Repository-Bundle wird extern
  geklont, auf exakten HEAD, sauberen Arbeitsbaum und `git fsck --strict`
  geprueft. Sein exakter SHA-256 steht im externen `bundle.sha256` und im
  Cutover-/Cleanup-Nachweis. Der Hash kann nicht sinnvoll in den Commit
  eingebettet werden, dessen Inhalt das Bundle selbst bestimmt.
- Der lokale, nicht versionierte Benutzerstart ruft ausschliesslich den
  finalen Launcher mit den genehmigten Runtime-, Vault- und Desktopparametern
  auf und enthaelt weder Secrets noch eine ExecutionPolicy-Umgehung.

OpenJarvis bleibt nach dem Abschluss sichtbar geoeffnet und betriebsbereit.
Es gibt keine Phase 9 und keine weitere Roadmap.
