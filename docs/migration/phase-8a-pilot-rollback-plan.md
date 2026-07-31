# Phase 8A: Pilot- und Rollbackplan

Stand: 31. Juli 2026

## Status

Dies ist ausschließlich ein Plan. Es wurde kein Phase-8B-Pilot gestartet, kein
Legacy-Code in den Produktivpfad übernommen, kein Skill oder Workflow aktiviert
und kein echtes Vault verändert.

## Empfohlene Pilotentscheidung

Der fachlich erste Pilot sollte die Vault-Schemakompatibilität auf einer erneut
aus der verifizierten Sicherung erzeugten, isolierten Kopie behandeln. Er ist
kleiner und sicherer als ein Funktionsport, setzt aber eine ausdrückliche
Nutzerentscheidung zu folgenden Punkten voraus:

1. Für 41 vorhandene, aber nicht UUID-konforme IDs: neue UUID erzeugen und die
   alte Kennung als `legacy_id` erhalten, oder eine andere explizite Abbildung
   wählen.
2. Für 5 Notizen ohne ID: neue UUID nur im Pilot erzeugen.
3. Für alle 46 Notizen: `schema_version: 1` ergänzen, ohne unbekannte
   Frontmatter-Felder zu entfernen.
4. Keine Ordner umbenennen, zusammenführen oder neu ordnen; keine der 46
   Markdown-Notizen automatisch löschen oder archivieren.
5. Referenzen auf alte IDs und Wikilinks vor und nach der Konvertierung über eine
   vollständige Mappingtabelle prüfen.

Bis diese Entscheidungen bestätigt sind, ist der Vault-Write-Pilot blockiert.

Als nachfolgender, unabhängiger Funktionspilot wird Website-Staging empfohlen:
ein isolierter Workspace, nur lokale Fixtures, keine Browserkonten, kein Netz,
keine echten Projektdateien und alle Ergebnisse als überprüfbare Artifacts. Auch
dieser Pilot benötigt eine eigene Phase-8B-Freigabe.

## Gate-Reihenfolge für einen späteren Vault-Pilot

1. Bestehende Legacy- und Vault-Sicherungen erneut vollständig verifizieren.
2. Neue Pilotkopie ausschließlich aus `vault-backup/data` erzeugen.
3. Vorher-Manifest mit relativen Pfaden, Größe und SHA-256 erstellen.
4. ID-Mapping deterministisch planen; Konflikte oder Mehrdeutigkeiten stoppen.
5. Änderungen ausschließlich per Compare-and-Swap auf der Pilotkopie anwenden.
6. Nachher-Manifest, Frontmatter-Validierung und vollständigen Phase-4-Reindex
   ausführen.
7. Gate: 46 gescannte Notizen, 0 Parserfehler, 0 verlorene Dateien, 0 zusätzliche
   unmanifestierte Dateien und unveränderte Notizkörper abseits der genehmigten
   Frontmatter-Diffs.
8. Pilotkopie nicht zum echten Vault erklären. Ergebnis und Diffs zuerst zur
   Nutzerentscheidung vorlegen.

## Runtime-Konvertierungsplan

| Kategorie | Phase-8A-Ergebnis | Spätere Regel |
| --- | ---: | --- |
| `runtime_state_metadata_only` | 45 Metadateneinträge | kein Direktimport; nur ein neues, dokumentiertes Zielschema darf aggregierte Werte übernehmen |
| `model_artifact_metadata_only` | 36 Metadateneinträge | keine Gewichte oder Downloads kopieren; einzelne Konfiguration nur nach separatem Review |
| `technical_cache_excluded` | 41 Metadateneinträge | verwerfen und bei Bedarf neu erzeugen |
| `temporary_excluded` | 6 Metadateneinträge | verwerfen |
| `credential_or_session_prohibited` | 2 Metadateneinträge | niemals migrieren; frisch authentifizieren |
| `browser_runtime_prohibited` | 1 nicht rekursiver Root | niemals migrieren; neues isoliertes Profil verwenden |

Ein Runtime-Konverter wurde in Phase 8A bewusst nicht implementiert, weil keine
Zielschema- oder Feldfreigabe vorliegt.

## Rollback für einen späteren Pilot

- Vor jedem Write ein unveränderliches Vorher-Manifest und eine separate
  Restore-Kopie erzeugen.
- Jede Änderung mit Before-Hash, After-Hash, relativem Pfad und genehmigtem
  Mapping protokollieren; keine Inhalte in Logdateien aufnehmen.
- Rollback nur ausführen, wenn der aktuelle After-Hash noch dem protokollierten
  Wert entspricht; bei Drift stoppen.
- Wiederherstellung zunächst in ein neues leeres Verzeichnis durchführen,
  Manifest bytegleich prüfen und erst nach gesonderter Cutover-Freigabe als
  Quelle verwenden.
- Bei Parserfehler, Konflikt, fehlender Datei, Hashabweichung oder Reparse Point
  den gesamten Pilot verwerfen. Keine Teilmenge als erfolgreich melden.
- Credentials, Browserprofile, Caches, Modelle und Legacy-Runtime-State sind
  nicht Teil des Rollbacks, da sie nicht Teil des Backups oder Pilots sein dürfen.

## Cutover-Grenze

Ein späterer Cutover braucht eine neue Freigabe mit definiertem Zeitfenster,
frischem Backup, Stop-the-world-Prüfung, finalem Delta-Manifest, Health-/Smoke-
Gates und explizitem Rückfallpunkt. Phase 8A erteilt diese Freigabe nicht.
