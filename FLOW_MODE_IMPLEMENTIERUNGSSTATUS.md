# Flow Mode – Übergabe und tatsächlicher Implementierungsstand

Stand: 4. August 2026
Repository: `JokerON165Hz/OpenJarvis`
Branch: `feature/codex-jarvis-orchestrator`

## Kurzfazit

Die grundlegende Flow-Architektur, Besitzeraktivierung und direkte Autorisierung sind implementiert. Mehrere Fehler in Chat-Fortsetzung, Tool-Ketten, Programmauflösung, Datei-Intent und Memory-Erkennung wurden behoben. Der Flow Mode ist trotzdem noch **kein vollständig zuverlässiger persönlicher Operator**. Besonders Browsernavigation, komplexe Desktopbedienung und kombinierte Aufgaben funktionieren in realen Versuchen nur teilweise.

Diese Datei ist bewusst eine ehrliche Übergabe. Grüne Unit-Tests bedeuten nicht, dass alle realen Bedienabläufe funktionieren.

## Heute fertig und gepusht

### 1. Flow-Autorisierung

- Zentrale Zustände `locked`, `assistant` und `flow` unter `src/openjarvis/flow/`.
- Flow wird über Windows `UserConsentVerifier` beziehungsweise Windows Hello/PIN durch den Besitzer aktiviert.
- Das finale Windows-Startskript teilt ein pro Prozess erzeugtes `OPENJARVIS_FLOW_BRIDGE_SECRET` zwischen Backend und Tauri-Anwendung.
- Im Flow Mode autorisiert der Besitzerauftrag die logisch notwendigen Tool-Schritte ohne einzelne Allow-once-Dialoge.
- Der verwendete Codex-SDK-Modus wird korrekt auf `SdkSandbox.full_access` abgebildet.
- Stop, Timeouts, Recovery und vorhandene Verifikation bleiben erhalten.

### 2. Alte sichtbare Freigabewege

- Approval Bell und Approval-Seite aus dem normalen Jarvis-UI entfernt.
- Alte Phase-7-/Website-Staging-Routen und -Komponenten aus dem aktiven Pfad entfernt.
- Memory-Approve-/Reject-Endpunkte und die blockierende Memory-Freigabe entfernt.
- Ordner-Allowlist und Read-only-Zwang blockieren den aktiven Flow-Dateipfad nicht mehr.
- Git-, Installations- und Systemaktionen sind im Flow-Prompt nicht mehr pauschal verboten.

### 3. Unterhaltung und Tool-Ketten

- Tool-Follow-ups erhalten eindeutige Korrelations-IDs. Dadurch kollidieren mehrere Schritte nicht mehr mit demselben Modellturn.
- Nach einem Backend-Fehler wird eine Chat-Task wieder in einen fortsetzbaren Zustand gebracht, statt die Unterhaltung grundsätzlich unbrauchbar zu machen.
- Zwei Modellnachrichten wurden live nacheinander in derselben diagnostischen Task und demselben Thread erfolgreich ausgeführt.
- Noch ausstehende Ergebnisse werden für Desktop-, Browser-, Datei-, Verzeichnis-, Shell-, MCP- und Memory-Tools breiter erkannt.

### 4. Dateien, Programme und Memory

- Datei-, Verzeichnis- und Shell-Tools sind registriert und im Flow Mode auf den Rechner des angemeldeten Benutzers ausgerichtet.
- Semantische Datei-/Ordnerbefehle wie Öffnen, Lesen, Suchen und Durchsuchen werden besser erkannt.
- Windows-Programme werden nicht nur über direkte Pfade, sondern auch über `PATH` und Windows App Paths aufgelöst.
- Chrome und Edge wurden auf dem Testsystem erfolgreich auf ihre installierten EXE-Pfade aufgelöst.
- Direkte Memory-Befehle wie „Merk dir meinen Namen: Bashar“ funktionieren; der gespeicherte Name wurde später korrekt erinnert.
- Memory-Intent wird nicht mehr nur anhand eines exakten Satzanfangs erkannt. Kombinierte Befehle können das Ergebnis eines vorherigen Tool-Schritts als Memory-Kandidat verwenden.

### 5. Normale Chat-Oberfläche

- Interne Werkzeugkarten mit Tool-ID, Ziel, Prüfung, Rohdaten und Fehlerstatus werden nicht mehr mitten in der normalen Text-Unterhaltung angezeigt.
- Tool-Aktionen und Diagnosedaten werden im Backend nicht gelöscht. Die Änderung betrifft nur ihre störende Darstellung im normalen Chat.
- Nutzer- und finale Jarvis-Nachrichten bleiben sichtbar.

## Live bestätigt

- Flow-Aktivierung über die finale Tauri-Anwendung funktioniert nach gemeinsamem Bridge-Secret.
- Ein direkter Memory-Eintrag und späterer Recall funktionierten.
- Zwei aufeinanderfolgende Modellturns in derselben Task funktionierten.
- `browser.windows` konnte vorhandene Browserfenster erfassen.
- `desktop.focus`, `desktop.launch_application`, `desktop.screenshot` und `desktop.inspect` wurden in einem realen Lauf als erfolgreich gemeldet.
- Der finale Windows-Launcher, Backend und Tauri-Anwendung wurden nach den vorherigen Änderungen gebaut und gestartet.

## Bekannt kaputt oder nur teilweise funktionsfähig

### 1. Browserautomation

Das ist derzeit der größte praktische Defekt.

- `browser.open_tab` ist in realen Versuchen trotz aktivem Flow wiederholt fehlgeschlagen.
- Zuverlässiges Navigieren, Auslesen kompletter Webseiten und anschließendes Weiterverarbeiten ist nicht end-to-end bestätigt.
- Die dedizierte Browser-Session-Komponente meldete im finalen Runtime-Health-Status `browser=false` beziehungsweise war nicht konfiguriert.
- Vorhandene Browserwerkzeuge arbeiten überwiegend über sichtbare Windows-/Desktopautomation. Es gibt keine vollständige robuste CDP-, Extension- oder DOM-Integration.
- Angemeldete sichtbare Browserfenster können erkannt werden, aber komplexe Webseitenaktionen hängen von Fokus, Layout, aktiver Registerkarte und Windows-Automation ab.

### 2. Desktopautomation

- Einfache Einzelaktionen können funktionieren, eine vollständige mehrstufige Bedienung ist aber nicht zuverlässig.
- `desktop.hotkey` wurde in einem realen Flow-Lauf als `denied` mit ausstehender Verifikation gemeldet.
- Fokuswechsel und Fensterauswahl können dazu führen, dass nachfolgende Schritte das falsche Ziel oder eine veraltete Window-ID verwenden.
- Die gemeldeten Erfolge bei Screenshot oder Inspect beweisen nicht automatisch, dass das eigentliche Benutzerziel erreicht wurde.

### 3. Fortsetzen einer Unterhaltung

- Die häufige Meldung „Diese Unterhaltung kann nicht fortgesetzt werden“ wurde auf Code-Ebene adressiert.
- Ein einfacher Live-Test mit zwei Modellturns war erfolgreich.
- Mehrstufige reale Tool-Aufgaben können weiterhin scheitern und den Folgekontext unbrauchbar machen. Dieser Ablauf ist noch nicht vollständig reproduziert und behoben.

### 4. „Mach es mal“ und Kontextverständnis

- Die Unterhaltung und Tool-Follow-ups werden jetzt länger im selben Thread gehalten.
- Das konkrete Verhalten bei elliptischen Folgeanweisungen wie „mach es mal“ ist nicht zuverlässig end-to-end bestätigt.
- Wenn der vorherige Browser- oder Desktopschritt kein brauchbares Ergebnis liefert, kann Jarvis auch nichts Sinnvolles weiterverarbeiten oder speichern.

### 5. Kombinierte Aufgabe „Webseite auslesen und alles merken“

- Die Memory-Seite dieses Ablaufs ist implementiert: Ein brauchbares zusammengesetztes Tool-Ergebnis kann gespeichert werden.
- Der komplette Ablauf funktioniert praktisch noch nicht zuverlässig, weil Navigation und Webseiten-Auslesen vorher scheitern können.
- Deshalb darf dieser Punkt nicht als fertig betrachtet werden.

### 6. Dokumente und Ordner

- Tools und Intent-Erkennung sind vorhanden.
- Reale Benutzeraufgaben zum Öffnen und Durchsuchen von Dokumenten/Ordnern wurden nach den letzten Änderungen nicht vollständig unter aktivem Flow end-to-end bestätigt.
- Windows-Berechtigungen, ungültige Pfade, ungeklärte Zielordner oder Orchestrierungsfehler können den Ablauf weiterhin abbrechen.

### 7. Talk und kostenlose männliche Stimme

- Dieser Punkt wurde auf Wunsch bewusst vertagt.
- Lokale Speech-/TTS-Komponenten existieren, aber eine verlässlich ausgewählte kostenlose männliche Stimme, die im Talk-Modus tatsächlich antwortet, wurde nicht fertiggestellt.

### 8. Administratorrechte

- Flow hat die Rechte des laufenden Windows-Benutzers beziehungsweise Prozesses.
- Es wurde keine UAC-Umgehung und kein dauerhaft privilegierter Systemdienst eingebaut.
- Aktionen, die Windows-Administratorrechte verlangen, benötigen weiterhin einen erhöht gestarteten Prozess oder die Betriebssystemfreigabe.

## Tests

Nach den jüngsten Orchestrierungsänderungen bestanden gezielt:

```text
tests/server/test_task_routes.py
tests/memory/test_memory_candidates.py
tests/assistant/test_intent.py
tests/desktop/test_productive_controller.py
tests/codex/test_sdk_lifecycle.py
```

Ergebnis: **85 Tests bestanden**. Ruff bestand für die geänderten Python-Dateien. Zwei echte Modellturns in derselben diagnostischen Task bestanden ebenfalls.

Ein danach gestarteter breiter Python-Testlauf wurde wegen sehr langer stiller Timeout-/Prozesstests manuell beendet. Er ist daher **nicht als bestanden zu werten**. Ein früherer breiter Lauf hatte 617 bestandene und 24 fehlgeschlagene Tests; diese Zahl beschreibt nicht den vollständigen aktuellen Branchstand.

Für das Ausblenden der Tool-Karten existiert ein Frontend-Test, der sicherstellt, dass Tool-ID, Window-ID, Rohdaten und „Strukturiertes Ergebnis“ nicht in der normalen Unterhaltung gerendert werden.

## Relevante Commits

- `ca811318` – direkte Flow-Autorisierung und Rückbau alter Freigabewege
- `35a126f3` – gemeinsames Flow-Bridge-Secret im finalen Windows-Launcher
- `d43d8846` – korrekte SDK-Abbildung auf Full Access
- `89c34ac2` – Chat-Recovery, Tool-Ketten, Programmauflösung, Datei- und Memory-Intent
- aktueller Abschlusscommit – interne Tool-Karten aus Chat entfernt und diese Übergabe aktualisiert

## Empfohlene Reihenfolge für morgen

1. Einen reproduzierbaren Test nur für `browser.open_tab` erstellen und prüfen, ob Window-ID, Fokus oder Tastenkombination die Ursache ist.
2. Entscheiden, ob echte Browsersteuerung über CDP/Playwright oder eine Browser-Extension ergänzt wird. Für verlässliches DOM-Auslesen ist das wahrscheinlich notwendig.
3. Einen kleinen End-to-End-Test „Dokumente öffnen → Datei finden → Inhalt lesen → Ergebnis antworten“ unter aktivem Flow bauen.
4. Einen End-to-End-Test „Webseite öffnen → Inhalt extrahieren → zusammenfassen → Memory speichern → in neuer Unterhaltung erinnern“ bauen.
5. Fehlerhafte Tasks so isolieren, dass ein einzelner Toolfehler die Unterhaltung niemals zum Neustart zwingt.
6. Danach erst Talk/TTS und die kostenlose männliche Stimme fertigstellen.
7. Abschließend den vollständigen Testbestand ausführen und die verbleibenden Windows-/Mock-/Timeout-Fehler einzeln bereinigen.

## Schlussstand

Die Berechtigungsarchitektur wurde klar in Richtung eines autonomen Besitzer-Operators verschoben. Die sichtbaren alten Einzelgenehmigungen sind weitgehend aus dem Flow-Pfad entfernt, und mehrere konkrete Orchestrierungsfehler wurden behoben. Der aktuelle Stand erfüllt das praktische Abnahmekriterium aber noch nicht vollständig: Jarvis besitzt viele Werkzeuge, setzt sie bei realen Browser-, Desktop- und kombinierten Aufgaben jedoch noch nicht durchgehend zuverlässig ein.
