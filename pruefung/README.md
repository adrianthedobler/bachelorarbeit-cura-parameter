# Prüfwerkzeuge

Diese beiden Skripte belegen, dass das Programm dieselben Werte an CuraEngine
übergibt wie Cura selbst.

`cura_werte.py` liest die Wertesätze aus Curas Protokoll
(`~/Library/Application Support/cura/5.13/cura.log`). Cura schreibt dort vor
jedem Schnitt die vollständige Übergabe an die Engine mit — global und je
Extruder.

```
python3 cura_werte.py          # listet alle protokollierten Schnitte
```

`abgleich.py` stellt diese Werte denen des eigenen Programms gegenüber und
zeigt jede Abweichung einzeln an.

```
python3 abgleich.py
```

Die drei dort hinterlegten Fälle beziehen sich auf bestimmte Schnitte vom
4. September 2026. Für eigene Vergleiche sind Zeitmarke, Drucker und die
geänderten Werte am Ende der Datei anzupassen; welche Werte in Cura geändert
wurden, steht im erzeugten G-Code in den Zeilen `;SETTING_3`.
