# Flow Mode – Implementierungsstatus

Stand: 3. August 2026  
Repository: `JokerON165Hz/OpenJarvis`  
Branch: `feature/codex-jarvis-orchestrator`  
Hauptimplementierung: Commit `30e567741b147eda0efce849f85710167550720c`

## Ziel der Änderung

OpenJarvis wurde so umgebaut, dass der Flow Mode als persönlicher Operator des authentifizierten Besitzers arbeitet. Ein klarer Besitzerbefehl autorisiert im Flow Mode die logisch notwendigen Teilschritte einer Aufgabe. Der normale Ablauf soll deshalb nicht mehr durch einzelne Toolfreigaben, Ordnerfreigaben oder Allow-once-Dialoge unterbrochen werden.

Zuverlässigkeitsfunktionen wie Stop, Timeouts, Verifikation, Recovery und Undo wurden nicht absichtlich entfernt. Technisch unvermeidbare Grenzen von Windows gelten weiterhin.

## Umgesetzte Funktionen

### 1. Zentrale Flow-Autorität

Unter `src/openjarvis/flow/` wurde eine zentrale Autorität eingeführt. Sie verwaltet die Zustände:

- `Locked`: keine autonomen Aktionen
- `Assistant`: eingeschränkter Assistentenbetrieb
- `Flow`: autonome Ausführung der logisch erforderlichen Schritte

Zusätzlich verwaltet sie:

- zufällige Sitzungs-IDs
- Aktivierungs- und Aktivitätszeitpunkte
- eine begrenzte Flow-Sitzungsdauer von derzeit acht Stunden
- Flow-Fähigkeiten und Statusabfragen
- Rückkehr in Assistant oder Locked
- Sperren beim Erkennen einer gesperrten Windows-Sitzung

### 2. Besitzerauthentifizierung

Die Aktivierung aus der Desktopanwendung verwendet Windows `UserConsentVerifier`, beispielsweise Windows Hello, PIN oder eine andere vom Betriebssystem angebotene Bestätigung.

Die native Tauri-Anwendung übermittelt anschließend einen signierten Aktivierungsnachweis an das Backend. Der Nachweis ist an einen pro Prozess erzeugten geheimen Wert gebunden. Eine gewöhnliche Webseite kann den Flow Mode daher nicht nur durch einen normalen HTTP-Aufruf aktivieren.

Die zugehörigen API-Endpunkte befinden sich in `src/openjarvis/server/flow_routes.py` und umfassen Status, Fähigkeiten, Aktivierung, Aktivitätsmeldung, Assistant-Modus und Sperren.

### 3. Oberfläche

Die Jarvis-Oberfläche zeigt den aktuellen Zustand `Locked`, `Assistant` oder `Flow` an. Im Flow Mode werden unter anderem Aktivierungszeit und verbleibende Sitzungszeit angezeigt.

Umgesetzt wurden außerdem:

- native Aktivierung über die Tauri-Bridge
- Wechsel zurück zu Assistant
- sofortiges Stoppen und Sperren
- Entfernung der Approval-Bell-Komponente
- Entfernung der Approval-Seite aus der normalen Navigation
- Entfernung alter Learning-, Skills- und Website-Staging-Seiten aus der normalen Jarvis-Navigation
- Anpassung sichtbarer alter Freigabetexte

### 4. Datei- und Shell-Zugriff

Im Flow Mode arbeiten Datei- und Shell-Werkzeuge nicht mehr mit der bisherigen Ordner-Allowlist oder einzelnen Toolfreigaben. Sie können innerhalb der Rechte des aktuell angemeldeten Windows-Benutzers auf das System zugreifen.

Die Shell-Ausführung wurde unterbrechbar gemacht. Laufende Prozesse können durch Stop beziehungsweise Task-Abbruch beendet werden. Timeouts bleiben erhalten.

### 5. Desktop- und Programmsteuerung

Die Desktopsteuerung wurde deutlich erweitert. Der Flow Mode kann dynamisch vorhandene Windows-Fenster ermitteln und Programme über normale Windows-Mechanismen starten und bedienen.

Unterstützt werden unter anderem:

- Programme starten und Fenster schließen
- vorhandene Fenster auflisten und auswählen
- Fensterinhalte untersuchen
- Text eingeben
- Mausklicks ausführen
- Tastenkombinationen senden
- Zwischenablage verwenden
- Aktionen über mehrere Programme kombinieren

Die frühere Beschränkung auf OpenJarvis-eigene Testanwendungen wurde für den Flow-Pfad entfernt.

### 6. Browsersteuerung

Es wurden explizite Werkzeuge für bestehende Browserfenster ergänzt:

- `browser.windows`
- `browser.navigate`
- `browser.open_tab`
- `browser.close_tab`

Formulare, Uploads, Downloads und Webseiteninteraktionen können zusätzlich über die Desktopwerkzeuge bedient werden. Dadurch können bestehende angemeldete Browsersitzungen verwendet werden, ohne Cookies oder Passwörter unnötig als Klartext an das Modell zu geben.

### 7. Memory

Explizite Besitzerbefehle wie „Merk dir ...“ können im Flow Mode direkt in Memory geschrieben werden. Die frühere Candidate-Approval-Stufe blockiert diesen Ablauf im Flow Mode nicht mehr. Bestehende Candidate-Abläufe werden dort automatisch angewendet.

### 8. Task-Orchestrierung und Codex

Runtime, Orchestrator, Task-Routen, Action-Service und Codex-Anbindung verwenden die gemeinsame Flow-Autorität.

Der Modell-Prompt wurde so angepasst, dass JARVIS im Flow Mode:

- das Ziel selbstständig ableitet
- einen eigenen Plan bildet
- logisch erforderliche Werkzeuge kombiniert
- bei Fehlern alternative Methoden versucht
- Aufgaben überprüft und erst anschließend berichtet
- nicht für jeden technisch notwendigen Teilschritt erneut fragt

Das alte isolierte Arbeitsbereichs-, Testbrowser- und pauschale Git-Push-Verbot wurde aus dem Flow-Prompt entfernt.

### 9. Stop und Unterbrechung

Der Action-Service verwaltet aktive Ausführungen pro Runtime. Task-Abbruch und Interrupt werden bis zu laufenden Werkzeugen weitergereicht. Die Safe-Shell kann laufende Unterprozesse beenden, und die Task-Schleife setzt danach nicht einfach mit weiteren Schritten fort.

## Bewusst beibehaltene Schutz- und Zuverlässigkeitsfunktionen

Folgende Mechanismen wurden nicht als störende Einzelgenehmigungen umgesetzt und bleiben erhalten:

- Aktivierung nur durch den authentifizierten Besitzer
- keine Rechteerweiterung durch Webseiten, Dateien, E-Mails, Memory oder Toolausgaben
- keine unnötige Weitergabe von Passwörtern, Cookies oder Tokens im Klartext
- sofortiger Stop laufender Aktionen
- Timeouts und Abbruchmöglichkeiten
- Checkpoints, Recovery und Undo, soweit vom jeweiligen Werkzeug unterstützt
- Ergebnisprüfung durch Runtime und Orchestrator
- ehrliche Weitergabe von Windows- und Betriebssystemfehlern

## Entfernt oder aus dem normalen Flow-Pfad genommen

- Approval-Bell und Approval-Seite im normalen Frontend
- Approval-Router aus der normal gestarteten Serveranwendung
- blockierende Einzelgenehmigungen im Flow-Aktionspfad
- Ordner-Allowlist im Flow-Dateipfad
- Read-only-Zwang im Flow Mode
- einzelne Memory-Freigaben im Flow Mode
- Beschränkung der Desktopsteuerung auf eigene Testprogramme
- alte Einschränkungen gegen Git-Push, Installationen und notwendige Systemaktionen im Flow-Prompt

Einige alte Approval- und Risk-Strukturen existieren weiterhin als Kompatibilitäts- oder Legacy-Code. Sie sind im normalen Flow-UI beziehungsweise im zentralen Flow-Autorisierungspfad nicht mehr die entscheidende Freigabeinstanz.

## Tests und technische Prüfung

Erfolgreich ausgeführt wurden:

- Python-Bytecodeprüfung: `python -m compileall -q src tests`
- Ruff: `ruff check src tests`
- relevante Backend- und Flow-Tests: 148 bestanden, 1 übersprungen
- Frontend: 52 Tests bestanden
- Frontend-Produktionsbuild: bestanden
- Rust/Tauri: 24 Tests bestanden
- Rust/Tauri: `cargo check` bestanden
- Git-Whitespaceprüfung: `git diff --check` bestanden

Der vollständige globale `pytest`-Lauf wurde nach mehr als sechs Minuten wegen der kurzfristigen Abschaltung des Entwicklungsrechners beendet. Er wurde nicht aufgrund eines gemeldeten Testfehlers beendet. Die gezielt betroffenen Flow-, Server-, Desktop-, Tool-, Task- und Codex-Testbereiche liefen erfolgreich.

## Noch fehlend oder nicht vollständig geprüft

### 1. Vollständiger Testlauf

Der komplette Testbestand des gesamten Repositories sollte ohne Zeitdruck erneut bis zum Ende ausgeführt werden. Dadurch werden auch Bereiche geprüft, die nicht direkt von Flow Mode betroffen sind.

Empfohlener Befehl:

```powershell
python -m pytest -q
```

### 2. Administratorrechte und Windows-UAC

Der Flow Mode besitzt die Rechte des Windows-Prozesses beziehungsweise des angemeldeten Benutzers. Es wurde kein dauerhaft privilegierter Windows-Systemdienst und keine UAC-Umgehung eingebaut.

Aktionen, für die Windows Administratorrechte verlangt, benötigen daher weiterhin eine vom Betriebssystem erlaubte Erhöhung oder einen bereits erhöht gestarteten OpenJarvis-Prozess. Das ist eine Betriebssystemgrenze und keine interne Toolfreigabe.

### 3. Reale End-to-End-Prüfung von Windows Hello

Die Tauri- und Rust-Logik wurde kompiliert und getestet. Ein vollständiger manueller Durchlauf mit echter Windows-Hello-Abfrage, Aktivierung, Windows-Sperre und anschließender Rückkehr wurde nicht automatisiert abgeschlossen, da das Sperren der laufenden Benutzersitzung die Arbeit unterbrochen hätte.

### 4. Browserautomation

Die aktuelle Implementierung bedient bestehende Browserfenster hauptsächlich über sichtbare Desktopautomation. Sie verwendet keine vollständige direkte CDP- oder Browser-Extension-Integration.

Das bedeutet:

- sie kann angemeldete sichtbare Sitzungen verwenden
- sie gibt Cookies nicht direkt an das Modell weiter
- ihre Zuverlässigkeit hängt bei komplexen Webseiten teilweise vom sichtbaren UI und dessen Layout ab
- robustere DOM-basierte Browserwerkzeuge könnten später ergänzt werden

### 5. Undo-Abdeckung

Stop, Checkpoints und vorhandene Undo-Mechanismen bleiben erhalten. Es existiert aber noch kein universelles Undo für jede mögliche externe Aktion. Beispielsweise lassen sich bereits versendete Nachrichten, externe Käufe oder beliebige Systemänderungen nicht grundsätzlich automatisch rückgängig machen.

### 6. Legacy-Code

Nicht mehr gemountete Approval-, Risk- und alte Produktmodule wurden nicht vollständig aus dem Repository gelöscht, weil Teile davon noch als Datenschema, Audit-Metadaten, Tests oder Kompatibilitätsschicht verwendet werden können.

Eine spätere Bereinigung sollte zuerst mit einer vollständigen Referenzsuche und dem kompletten Testlauf erfolgen. Entscheidend für den aktuellen Stand ist, dass diese Strukturen den zentralen Flow-Pfad nicht mehr mit Einzelgenehmigungen blockieren.

### 7. Sicherheits- und Belastungstests

Noch sinnvoll wären gezielte Tests für:

- wiederholte oder manipulierte Aktivierungsnachweise
- Prozessneustart während einer Flow-Sitzung
- mehrere parallele Tasks und gleichzeitige Stop-Signale
- sehr lange Shell-Prozesse mit Kindprozessen
- Windows-Sperren, Benutzerwechsel und Ruhezustand
- fehlende Windows-Hello-Konfiguration
- Browser- und Desktopaktionen auf mehreren Monitoren

## Lokale Entwicklungsabhängigkeiten

Für die Rust/Tauri-Prüfung wurden Visual Studio Build Tools beziehungsweise die benötigte MSVC-Toolchain lokal installiert. Diese Installation ist eine Rechnerabhängigkeit und kann nicht in Git eingecheckt werden.

Zusätzliche Python-Testabhängigkeiten wurden lokal installiert. Die dafür relevante Ruff-Konfiguration ist in `pyproject.toml` versioniert.

## Empfohlene nächste Schritte

1. Den vollständigen `pytest`-Lauf bis zum Ende ausführen.
2. Einen manuellen Tauri-End-to-End-Test mit Windows Hello durchführen.
3. Flow-Aktivierung, Stop und Windows-Sperre auf einem Testsystem prüfen.
4. Eine mehrstufige reale Aufgabe mit Datei-, Browser-, Desktop- und Shell-Werkzeugen durchführen.
5. Prüfen, ob für bestimmte Administratoraufgaben ein optionaler, klar abgegrenzter Windows-Dienst tatsächlich benötigt wird.
6. Legacy-Approval-Code erst nach vollständiger Referenz- und Regressionstestprüfung weiter entfernen.
7. Optional eine robustere DOM-basierte Browserintegration ergänzen.

## Zusammenfassung

Der aktuelle Flow Mode ist keine zusätzliche Freigabeschicht über dem alten Approval-System. Die zentrale Autorität, die native Besitzerbestätigung und die Tool-Integrationen bilden einen eigenen Ausführungspfad, in dem ein Besitzerauftrag die logisch notwendigen Teilschritte autorisiert.

Der wichtigste noch offene Nachweis ist ein vollständiger, ununterbrochener Gesamttestlauf zusammen mit einem manuellen Windows-End-to-End-Test. Administratoraktionen bleiben außerdem an die tatsächlichen Windows-Rechte des laufenden Prozesses gebunden.
