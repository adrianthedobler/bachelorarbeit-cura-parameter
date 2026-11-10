# Programme zur Bachelorarbeit

Begleitprogramme zur Bachelorarbeit *Systematische Analyse der Prozessparameter
des Slicers UltiMaker Cura und Übertragung auf den Beton-3D-Druck*
(Technische Universität München, Lehrstuhl für Massivbau).

Dieses Repository enthält **zwei voneinander unabhängige Programme**. Sie lösen
verschiedene Aufgaben, laufen getrennt und teilen keinen Code — gemeinsam ist
ihnen nur, dass beide eine vorhandene Installation von UltiMaker Cura 5.13
benutzen.

| Ordner | Was es ist | Kapitel der Arbeit |
|---|---|---|
| [`G-Code-Comparison`](G-Code-Comparison) | **Messprogramm.** Prüft automatisiert, welche Druckparameter den erzeugten G-Code überhaupt verändern. | Kapitel 4 |
| [`Alternative Cura UI`](Alternative%20Cura%20UI) | **Bedienprogramm.** Textbasierte Oberfläche, die genau diese wirksamen Parameter anbietet und auf den Beton-3D-Druck umschaltbar ist. | Kapitel 5 und 6 |

Die beiden hängen inhaltlich zusammen: Das Messprogramm liefert die Liste der
246 wirksamen Parameter, und das Bedienprogramm beschränkt seine Auswahl genau
auf diese Liste.

---

## 1 · G-Code-Comparison — der Parametervergleich

Verdreifacht jeden einzelnen der 623 numerischen Druckparameter, schneidet
denselben Prüfkörper erneut und vergleicht den erzeugten G-Code anhand
reihenfolgeunabhängiger Kennzahlen mit einem Referenzlauf. Vorbedingungen und
abhängige Kindparameter werden dabei automatisch aufgelöst, das Rauschband der
Engine wird vorab selbst gemessen.

```
cd "G-Code-Comparison"
python3 cura_setting_sweep.py
```

Ergebnis sind eine Excel- und eine CSV-Tabelle mit dem Status je Parameter.
Beide liegen als Ergebnis des vollständigen Laufs im Ordner bei. Dazu gehören
der Determinismus-Test, der die Streuung der Engine belegt, und einige
Werkzeuge, die die verwendeten Prüfkörper erzeugen.

Einzelheiten: [`G-Code-Comparison/README.md`](G-Code-Comparison/README.md)

## 2 · Alternative Cura UI — die Nutzeroberfläche

Eine Oberfläche für das Terminal, die aus einem STL-Modell über CuraEngine
G-Code erzeugt. Sie zeigt zu jedem Wert seine Herkunft, seine Formel und seine
Abhängigkeiten, lässt sich zwischen Polymer- und Beton-3D-Druck umschalten und
kann ihre Werte an das 3DCP-Programm des Lehrstuhls übergeben. Die
Cura-Installation wird dabei nicht verändert.

```
cd "Alternative Cura UI"
python3 cura-ui.py
```

Dass die Oberfläche dieselben Werte an die Engine übergibt wie Cura selbst,
weist das Skript `pruefung/abgleich.py` an eigenen Cura-Schnitten nach.

Einzelheiten: [`Alternative Cura UI/README.md`](Alternative%20Cura%20UI/README.md)

---

## Voraussetzungen

* UltiMaker Cura 5.13, installiert (beide Programme rufen dessen CuraEngine auf
  und lesen dessen Definitionsdateien)
* Python 3.9 oder neuer
* macOS oder Windows
* Die Oberfläche kommt ohne zusätzliche Pakete aus; das Messprogramm benötigt
  `openpyxl` für die Excel-Ausgabe und installiert es bei Bedarf selbst.

Die Ergebnisse sind an die Cura-Version gebunden: Definitionen und Formeln
ändern sich zwischen Versionen, weshalb sie nur mit derselben Version
reproduzierbar sind.
