# Prüfwerkzeuge

Diese Skripte weisen nach, dass das Tool dieselben Werte an CuraEngine übergibt
wie Cura selbst. Für den Betrieb des Tools werden sie nicht benötigt.

## Abgleich an einem eigenen Cura-Schnitt

1. In Cura 5.13 einen Drucker, ein Qualitätsprofil, ein Material und eine Düse
   wählen, beliebige Werte ändern, ein Modell schneiden und den G-Code
   speichern.
2. Im Ordner des Tools aufrufen:

```
python3 pruefung/abgleich.py Pfad/zur/Datei.gcode
```

Das Skript

* liest aus dem G-Code, welche Werte in Cura geändert wurden (Cura hängt sie
  als `;SETTING_3` an jede gespeicherte Datei an, getrennt nach global und je
  Extruder),
* sucht in Curas Protokolldatei den zugehörigen Schnitt — Cura schreibt dort
  vor jedem Schnitt die vollständige Wertübergabe an die Engine mit,
* stellt Drucker, Qualitätsprofil, Material und Düse im Tool ein,
* setzt die geänderten Werte **auf demselben Weg wie die Oberfläche des Tools**
  und
* vergleicht jeden übergebenen Wert, global und je Extruder.

Curas Protokolldatei wird am Ort gesucht, den Cura selbst verwendet:

| System | Ort |
|---|---|
| macOS | `~/Library/Application Support/cura/5.13/cura.log` |
| Windows | `%APPDATA%\cura\5.13\cura.log` |

Ein anderer Ort lässt sich mit `--protokoll PFAD` angeben, eine andere
Cura-Installation mit `--cura ORDNER`.

Der Rückgabewert ist 0, wenn alle Werte übereinstimmen, sonst 1.

## Die Fälle aus der Arbeit

```
python3 pruefung/abgleich.py --beispiele
```

prüft die drei Fälle aus Abschnitt 5.4 der Arbeit (Schnitte vom 4. September
2026). Das gelingt nur mit der Protokolldatei, in der diese Schnitte stehen;
auf anderen Rechnern meldet das Skript „kein Protokolleintrag".

## Einzelne Werkzeuge

`cura_werte.py` liest Curas Protokoll und den Einstellungsblock einer
G-Code-Datei. Allein aufgerufen, listet es alle protokollierten Schnitte:

```
python3 pruefung/cura_werte.py
```
