# Tasmota Console Skill

Ein Agent-Skill für generische Tasmota-HTTP-Befehle, Web-Konsolenlogs und die sichere Bearbeitung komplexer Rules. Entworfen für OpenCode und andere Agenten mit Unterstützung für `SKILL.md`. Das Skript benötigt Python 3.9+ und keine zusätzlichen Pakete. Zielplattformen sind Windows und Linux, einschließlich OpenCode in einem HAOS-Container.

> **Status:** Anhand des Tasmota-15.1-Quellcodes entwickelt und mit einem simulierten HTTP-Gerät getestet. Ein erster lesender Test mit einem ESP8285 und Tasmota 15.0.1 bestätigte Firmware- und Rule-Abfragen sowie inkrementelles Konsolenlog-Polling. Schreibvorgänge, Firmware 15.1 und die HA-Installation wurden noch nicht an echten Geräten getestet. Vor produktiven Änderungen zunächst rein lesend am eigenen Gerät testen.

## Sicherheit

HTTP überträgt Inhalte und gegebenenfalls Basic-Auth-Zugangsdaten unverschlüsselt. Nur in vertrauenswürdigen, abgeschotteten Netzen verwenden. Der Client führt jeden angeforderten Befehl aus und kann nicht selbst zwischen sicheren und gefährlichen Befehlen unterscheiden; Freigaben liegen beim Agenten beziehungsweise Benutzer. Keine automatischen Wiederholungen nach Zeitüberschreitungen. Konsolenlogs und Rule-Sicherungen können vertrauliche Daten enthalten. Ausgaben werden nur bestmöglich, nicht vollständig bereinigt; Sicherungen sind absichtlich unbereinigt. Siehe `references/safety.md`.

## Lokal verwenden

Unter Linux `python3`, unter Windows beispielsweise `python` verwenden. Im Repository-Ordner:

```bash
python3 scripts/tasmota_console.py diagnose
python3 scripts/tasmota_console.py --host 192.0.2.10 command 'Status 2'
python3 scripts/tasmota_console.py --host 192.0.2.10 command 'Rule1'
python3 scripts/tasmota_console.py --host 192.0.2.10 logs --seconds 10
python3 scripts/tasmota_console.py --host 192.0.2.10 rules-snapshot --output /private/device-rules.json
```

`192.0.2.10` ist ein Dokumentationsplatzhalter. Den Snapshot in einem bestehenden privaten Ordner **außerhalb** des Repositorys anlegen; eine vorhandene Datei wird nicht überschrieben. Unter Windows gelten die geerbten Dateiberechtigungen; diese selbst prüfen. Die Sicherung enthält nur die drei Rule-Antworten, keine vollständige Gerätekonfiguration.

Für längere Befehle `command --file /privater/pfad/befehl.txt` oder `command --stdin` verwenden. Die Datei enthält einen einzelnen vollständigen Befehl in einer Zeile. Der Client teilt `Backlog`-Semikolons nicht auf und quotiert Sonderzeichen für HTTP. Lange Rules können durch Geräte- oder Build-Limits abgewiesen werden; ein erfolgreicher HTTP-Status ist keine Bestätigung. Siehe `references/rules.md`.

Optional kann das Web-Passwort über `--password-env NAME` oder `--password-file PFAD` eingelesen werden. Der Name beziehungsweise Dateipfad ist kein Passwort. Niemals das Passwort selbst als Argument, im Chat oder in einer Datei im Repository angeben. Einrichtung und Schutz des Secret-Speichers sind Sache der lokalen Umgebung.

## Installation als Skill

Dieses Repository als Verzeichnis `tasmota-console` unter einem unterstützten Skill-Suchpfad ablegen, zum Beispiel `~/.agents/skills/tasmota-console`. `SKILL.md`, `scripts/` und `references/` müssen zusammenbleiben. In OpenCode kann der Skill mit `@tasmota-console` aufgerufen werden. Suchpfade und Berechtigungen: [OpenCode Skills](https://opencode.ai/docs/skills).

### OpenCode V2: GitHub-Pages-Katalog

1. Repository unter eigener Kontrolle auf GitHub veröffentlichen. Die enthaltene MIT-Lizenz nur verwenden, wenn sie den eigenen Veröffentlichungswünschen entspricht.
2. Unter **Settings → Pages** als Build-Quelle **GitHub Actions** wählen. Den Workflow **Deploy skill catalog** manuell starten. Der Workflow ist absichtlich nicht auf automatisches Deployment bei jedem Push eingestellt.
3. Die veröffentlichte Katalog-Basisadresse hat üblicherweise die Form `https://<github-user>.github.io/<repository>/`. Prüfen, dass `index.json` und die dort aufgeführten Dateien abrufbar sind. Für Organisationsseiten oder eigene Domains kann die Adresse abweichen.
4. In eine tatsächlich geladene und persistente OpenCode-V2-Konfiguration folgenden Eintrag aufnehmen; bestehende Einträge erhalten:

   ```jsonc
   {
     "$schema": "https://opencode.ai/config.json",
     "skills": ["https://<github-user>.github.io/<repository>/"]
   }
   ```

   Das ist ein Beispiel, keine vollständige Ersatzkonfiguration. `/run/opencode-v2/home` ist in der untersuchten HA-Umgebung nicht nachweislich persistent. Den tatsächlich geladenen, persistenten Konfigurationspfad dort vor Änderungen prüfen. OpenCode lädt Konfigurationsänderungen neu; falls nötig `/reload` verwenden. Prüfen, dass `@tasmota-console` gefunden wird und sein Basisordner die Skripte und Referenzen enthält.

Katalogquellen laden Code über das Netzwerk. Nur einem eigenen, vertrauenswürdigen Repository und dessen Berechtigten vertrauen. `catalog/index.json` bei jeder Änderung veröffentlichter Skill-Dateien versionieren, damit OpenCode den Cache aktualisiert. Keine persönlichen Daten, Geräteadressen, Passwörter oder Rule-Sicherungen veröffentlichen.

## Tests und Katalog lokal erstellen

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build_catalog.py --output /pfad/zu/neuem-katalog
```

Der Katalog-Builder erstellt nur ein neues, noch nicht existierendes Zielverzeichnis und kopiert die in `catalog/index.json` aufgeführten Dateien. Keine Netzwerkanfragen an Tasmota-Geräte sind für die Tests nötig.
