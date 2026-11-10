# Alternative Cura-Oberfläche — Kurzbeschreibung

Begleitprogramm zur Bachelorarbeit. Eine textbasierte Bedienoberfläche für den
Slicer UltiMaker Cura 5.13, die den Parametersatz auf die im Rahmen der Arbeit
als wirksam nachgewiesenen Einstellungen beschränkt und eine eigene Auswahl für
den Beton-3D-Druck anbietet.

## Was es tut

Aus einem STL-Modell wird über CuraEngine G-Code erzeugt. Bedient wird
ausschließlich über die Tastatur; eine grafische Oberfläche gibt es nicht.

## Der Ansatz

Das Programm ist **kein Nachbau von Cura**, sondern eine zweite Oberfläche auf
derselben Installation. Es liest deren Definitionsdateien, benutzt deren
Python-Klassen zur Auflösung der Parameterwerte und ruft deren CuraEngine auf.
An der Cura-Installation wird nichts verändert; geschrieben wird nur in die
eigenen Ordner `ausgabe` und `einstellungen`.

Möglich ist das, weil CuraEngine die Formeln der Definitionsdateien nicht
selbst auswertet: Cura löst sie im Programm auf und übergibt der Engine eine
flache Liste aus Namen und fertigen Werten. Genau diese Auflösung übernimmt
hier Curas eigene Klasse `SettingFunction`. Damit gelten dieselben Formeln,
Bedingungen, Grenzen und Beschriftungen wie in Cura selbst.

## Die drei Parameterumfänge

| Umfang | Anzahl | Grundlage |
|---|---|---|
| Wirksame Parameter | 246 | im Sweep nachgewiesene Wirkung auf den G-Code |
| Beton-3D-Druck | 109 | die in Kapitel 6 herausgearbeitete Auswahl |
| Alle Parameter | 644 | sämtliche Druckeinstellungen der Definition |

Die jeweils nicht angebotenen Parameter bleiben geladen, weil die Formeln der
angebotenen auf sie zugreifen. Maschinenparameter werden nicht angeboten; der
Drucker wird als Ganzes gewechselt.

## Zwei Besonderheiten gegenüber Cura

**Herkunft jedes Wertes sichtbar.** Jede Zeile zeigt an, wer den Wert gerade
bestimmt: selbst gesetzt, Vorgabe der Auswahl, aus dem Qualitätsprofil, aus
einer Formel berechnet oder Vorgabewert der Definitionsdatei. Dazu die
`enabled`-Bedingung im Wortlaut, die wirksame Formel, worauf sie zugreift und
welche Parameter von diesem abhängen.

**Abschaltbare Grenzen.** Die Werte `minimum_value`/`maximum_value` werden
ausschließlich von Curas Oberfläche geprüft, nicht von CuraEngine. Der Schalter
hebt daher keine Sicherung der Engine auf, sondern nur die Prüfung in diesem
Programm. Nötig ist das für Anwendungen außerhalb des Kunststoffdrucks, etwa
Bahnbreiten im Zentimeterbereich beim Betondruck.

## Nachweis der Übereinstimmung

Cura schreibt vor jedem Schnitt den vollständigen Wertesatz in sein Protokoll.
Der Abgleich damit ergab in vier Fällen vollständige Übereinstimmung aller
übergebenen Werte — Ender-3 mit Schichthöhe 4 mm, mit Stützstruktur, mit Fuzzy
Skin sowie Creality CR-X mit zwei Extrudern und Stützstruktur über den rechten
Extruder. Der erzeugte G-Code stimmt ebenfalls überein: gleiche Schichtzahl,
gleiche Anzahl Bewegungen und Einzüge, gleicher Druckweg, gleicher
Materialverbrauch.

## Voraussetzungen und Start

* UltiMaker Cura 5.13 (macOS oder Windows), installiert
* Python 3.9 oder neuer; keine weiteren Pakete

macOS: Doppelklick auf `Starten (macOS).command`
Windows: Doppelklick auf `Starten (Windows).bat`

Einzelheiten zu Bedienung und Aufbau stehen in `README.md`.
