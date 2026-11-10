# Cura Print-Setting-Sweep

Automatischer Test: Verdreifacht jedes numerische Print Setting von Cura
(Creality Ender-3, PLA, 0.4 mm Düse, „Standard Quality") und prüft, ob der
erzeugte G-Code sich ändert.

## Start

```
py cura_setting_sweep.py
```

Optionen:
- `--limit N`   nur die ersten N Settings (Schnelltest)
- `--only a,b`  nur bestimmte Setting-Keys
- `--list`      Settings nur auflisten
- `--calib N`   Anzahl Baseline-Kalibrierläufe (Default 5)

## Ergebnisse

- `cura_setting_sweep_ergebnis.xlsx` – Hauptergebnis (Blatt „Ergebnisse" +
  „Zusammenfassung"). Status je Setting farbig:
  grün = Veränderung, grau = keine, gelb = nicht testbar, rot = Fehler.
- `cura_setting_sweep_ergebnis.csv` – gleiche Daten als CSV.
- `gcode_output/` – `_baseline.gcode` + ein G-Code pro getestetem Setting.

## Modell

Es wird automatisch die erste STL im Ordner verwendet (außer `cube.stl`).
Aktuell: `Slicer Test.stl` (50×75×7 mm, 35 Layer – das Original wurde mit
`scale_stl.py` um Faktor 5 vergrößert; das Original liegt als
`Slicer Test_original.stl` daneben). Größeres Modell = mehr aktivierte Settings
(Infill, mehr Top/Bottom-Layer), aber auch mehr Engine-Rauschen.
`make_cube.py` erzeugt bei Bedarf den Fallback-Würfel; `scale_stl.py` skaliert
eine STL (`py scale_stl.py ein.stl aus.stl <faktor>`).

## Funktionsweise / wichtige Hinweise

1. **CuraEngine headless**: Es wird `CuraEngine.exe` direkt aufgerufen. Die
   Maschinendefinition `creality_ender3.def.json` liefert alle übrigen
   Defaults; das „Standard Quality"-Profil (Layer Height 0,2 mm) wird als
   Baseline angewendet, damit die Defaults den GUI-Werten entsprechen.

2. **Default ×3**: Pro Setting wird nur dieser eine Wert auf das Dreifache
   gesetzt; alle anderen bleiben Default. Der „Default-Slice" (Baseline) ist
   für alle Settings identisch und wird deshalb nur einmal (zur
   Rausch-Kalibrierung mehrfach) erzeugt und wiederverwendet.

3. **Vergleich per robusten Kennzahlen statt Byte-Vergleich**: CuraEngine
   erzeugt nicht-deterministischen G-Code (Reihenfolge der Reisebewegungen
   variiert von Lauf zu Lauf, selbst bei identischen Eingaben). Deshalb werden
   reihenfolge-unabhängige Kennzahlen verglichen: Layer-Anzahl, extrudiertes
   Filament, Extrusions-Distanz und -Bewegungen, geschätzte Druckzeit,
   Maximaltemperaturen (Hotend/Bett), Lüfter. Das Rauschband wird über mehrere
   Baseline-Läufe gemessen; „Veränderung" wird nur gemeldet, wenn eine Kennzahl
   das kalibrierte Rauschen klar überschreitet.

4. **„nicht testbar (Default 0)"**: Settings mit Default 0 lassen sich per ×3
   nicht testen (3 × 0 = 0) und werden gesondert markiert.

4b. **Verifikation gegen Rauschen**: Jeder „Veränderung"-Treffer wird
   nachgeslict (`VERIFY_RUNS`, Default 2). Nur wenn die Abweichung
   reproduzierbar über der Toleranz bleibt (Median), zählt sie. Das eliminiert
   zufällige Rausch-Fehltreffer – wichtig bei größeren Modellen, deren
   nicht-deterministisches Reise-Rauschen deutlich größer ist.

5. **Grenzen**: Reine Pfad-/Reihenfolge-Effekte (z. B. Naht-Position) sind durch
   das Engine-Rauschen nicht sicher nachweisbar. Geometrieabhängige Settings
   (Infill, Support, viele Top/Bottom-Layer) zeigen bei einem dünnen Modell
   „keine Veränderung", weil sie nicht aktiviert werden – für mehr Abdeckung
   ein höheres Modell mit Überhängen verwenden. Eltern-Settings wie `line_width`
   oder `speed_print` schlagen nicht durch, weil die Ender-3-Definition die
   konkreten Kind-Werte fest setzt (das ist korrektes Cura-Verhalten).
