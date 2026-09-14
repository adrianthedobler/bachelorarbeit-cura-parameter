# Alternative Nutzeroberfläche für UltiMaker Cura 5.13

Eine textbasierte Oberfläche, die aus einem Modell über CuraEngine G-Code
erzeugt. Sie ist auf die 246 Parameter beschränkt, für die im automatisierten
Vergleich (`cura_setting_sweep.py`) eine nachweisbare Veränderung am G-Code
festgestellt wurde, und lässt sich auf die Beton-Auswahl oder den vollen
Umfang umschalten.

## Aufbau der Oberfläche

Das Hauptmenü führt fünf Einträge; jeder zeigt seinen aktuellen Zustand an.

| Eintrag | Inhalt |
|---|---|
| Hardware | Drucker und Düse |
| Material | Materialprofil je Extruder |
| Modell | STL-Datei (mit Ordnerwechsel) |
| Profil | Qualitätsprofil des Druckers |
| Parameter | vier Geltungsbereiche, darunter Curas Kategorien |

Unter **Parameter** stehen die vier Geltungsbereiche, nach denen Curas
Definitionsdateien die Einstellungen ordnen:

| Bereich | Bedeutung | Ender-3, Umfang 246 |
|---|---|---|
| Mesh | je Modell einstellbar (`settable_per_mesh`) | 149 |
| Extruder | je Extruder einstellbar (`settable_per_extruder`) | 69 |
| Global | gilt für den gesamten Druck | 28 |
| Machine Settings | beschreiben den Drucker selbst | 87 |

Die beiden Eigenschaften schließen einander nicht aus — fast alles, was je
Modell einstellbar ist, ist es auch je Extruder. Es gilt deshalb die Rangfolge
Machine Settings, Mesh, Extruder, Global; jeder Parameter erscheint in genau
einem Bereich. Die Machine Settings folgen dem gewählten Umfang nicht, weil der
Sweep aus Kapitel 4 nur Schnitteinstellungen geprüft hat.

**Die Cura-Installation wird nicht verändert.** Das Programm liest deren
Definitionsdateien, benutzt deren Python-Klassen zur Berechnung der Werte und
ruft deren CuraEngine auf. Es schreibt ausschließlich in die eigenen Ordner
`ausgabe` und `einstellungen`.

## Voraussetzungen

* UltiMaker Cura 5.13, installiert
* macOS (geprüft) oder Windows (vorgesehen, bisher nicht erprobt)
* Python 3.9 oder neuer
* keine weiteren Pakete — die Oberfläche kommt ohne zusätzliche Bibliotheken aus

## Starten

macOS: Doppelklick auf `Starten (macOS).command`
Windows: Doppelklick auf `Starten (Windows).bat`

Oder im Terminal:

```
python3 cura-ui.py
```

Wird Cura nicht am üblichen Ort gefunden, hilft `--cura`:

```
python3 cura-ui.py --cura "C:\Program Files\UltiMaker Cura 5.13.0"
```

Weitere Aufrufe:

| Aufruf | Wirkung |
|---|---|
| `--pruefen` | prüft, ob alles bereitsteht, und gibt eine Übersicht aus |
| `--sprache de_DE` | Curas deutsche Übersetzung statt der Originalbezeichnungen |
| `--schneiden DATEI -m Modell.stl -o aus.gcode` | schneidet ohne Oberfläche mit einer gespeicherten Einstellung |

## Bedienung

| Taste | Wirkung |
|---|---|
| ↑ ↓ Bild↑ Bild↓ Pos1 Ende | in Listen bewegen |
| Enter | öffnen oder ändern |
| `/` | suchen; Enter übernimmt den Filter, Esc verwirft ihn |
| Esc | zurück |
| `i` | Einzelheiten zum Parameter (Formel, Abhängigkeiten, Grenzen) |
| `r` | einen eigenen Wert zurücknehmen |
| `s` | schneiden |
| `u` | Umfang · `g` Grenzen |
| `f` | über alle Parameter suchen |
| Strg+S / Strg+O | Einstellung speichern / laden |
| `?` | Hilfe |

Kennzeichnung in der Parameterliste — sie sagt, wer den Wert bestimmt.
Es gilt die Rangfolge eigener Wert vor Umfangsvorgabe vor Profil vor Formel
vor Vorgabewert:

| Zeichen | Bedeutung |
|---|---|
| `*` | selbst gesetzt |
| `a` | Vorgabewert des gewählten Umfangs (etwa der Beton-Auswahl) |
| `p` | aus Qualitätsprofil, Materialprofil oder Düsenvariante |
| `f` | von Cura aus anderen Parametern berechnet |
| ohne | Vorgabewert der Definitionsdatei |
| grau | die `enabled`-Bedingung ist nicht erfüllt |

Angezeigt wird immer der Wert, der tatsächlich an CuraEngine geht. Bei
Parametern mit `settable_per_extruder` ist das der Wert des Extruderstapels,
in dem Material und Düse liegen — beim Ender-3 mit Generic PLA also 200 °C
Düsentemperatur, nicht der Vorgabewert 210 °C des globalen Stapels. Bei
mehreren Extrudern zeigt die Liste den ersten.

## Bezeichnungen

Angezeigt werden die englischen Originalbezeichnungen aus den
Definitionsdateien — dieselben Begriffe wie in der Arbeit und im Sweep.
`--sprache de_DE` schaltet auf Curas eigene deutsche Übersetzung um.

## Die beiden Sonderfunktionen

**Umfang** (`u`). Zur Wahl stehen drei Listen:

| Umfang | Anzahl | Grundlage |
|---|---|---|
| Wirksame Parameter | 246 | im Sweep nachgewiesene Wirkung auf den G-Code |
| Beton-3D-Druck | 105 | die in Kapitel 6 herausgearbeitete Auswahl |
| Alle Parameter | 644 | sämtliche Druckeinstellungen der Definition |

Die nicht angebotenen bleiben in allen Fällen geladen, weil die Formeln der
angebotenen auf sie zugreifen. Die Machine Settings folgen dem Umfang
nicht und werden stets vollständig angeboten.

Ein Umfang kann eigene Vorgabewerte mitbringen (`vorgaben` in der zugehörigen
JSON-Datei). Diese Werte liegen als eigene Ebene **unter** den eigenen
Änderungen — ein Parameter bleibt also voll einstellbar, startet aber mit dem
für den Anwendungsfall sinnvollen Wert, und beim Umschalten des Umfangs
verschwindet die Vorgabe restlos wieder. Vorgabewerte dürfen auch für
Parameter gelten, die der Umfang nicht anbietet; sie sind dann festgesetzt.

Die Beton-Auswahl bringt zwölf Vorgabewerte mit, darunter `adhesion_type =
none`, abgeschalteten Einzug und abgeschaltete Kühlung. Vier davon —
Enable Print Cooling, Fan Speed, Printing Temperature und Build Plate
Temperature — werden nicht zur Bearbeitung angeboten. Die Begründung steht in
Kapitel 6 der Arbeit.

**Grenzen** (`g`). Die Definitionsdateien kennen zwei Arten von Grenzen:
harte Grenzen (`minimum_value`, `maximum_value`) und Warnschwellen
(`minimum_value_warning`, `maximum_value_warning`). In `fdmprinter.def.json`
tragen 439 der 719 Parameter eine harte Grenze und 386 eine Warnschwelle.

Bei eingeschalteter Prüfung weist das Programm eine Eingabe außerhalb einer
harten Grenze zurück; eine Eingabe außerhalb einer Warnschwelle wird mit einem
Hinweis angenommen. Der Schalter hebt nur die Prüfung der harten Grenzen auf.

CuraEngine selbst prüft keine der beiden Arten. Nachgemessen mit dem Ender-3:

| Parameter | Grenze | übergeben | im G-Code |
|---|---|---|---|
| Printing Temperature | hart: höchstens 365 °C | 500 °C | `M104 S500` |
| Print Speed | hart: höchstens 707 mm/s | 2000 mm/s | Vorschübe bis 1585 mm/s |
| Layer Height | nur Warnung ab 0,32 mm | 20 mm | Druck mit 20 mm Schichthöhe |

Der Schalter hebt also keine Sicherung der Engine auf, sondern nur die
Eingabeprüfung dieses Programms.

Viele Grenzen hängen als Formel vom Düsendurchmesser ab — die Warnschwelle der
Schichthöhe liegt beim 0,8-fachen, die der Bahnbreite beim Zweifachen. Vor dem
Abschalten sollte deshalb unter *Parameter → Machine Settings* der
tatsächliche Düsendurchmesser gesetzt werden: Bei einer 24-mm-Düse liegen
dieselben Schwellen bei 19,2 mm und 48 mm, und die Abschaltung ist für diese
Größen gar nicht nötig.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `cura-ui.py` | Einstiegspunkt, Befehlszeile |
| `curaui/cura_env.py` | findet Cura und macht dessen Klassen benutzbar |
| `curaui/definitionen.py` | löst die `inherits`-Kette einer Druckerdefinition auf |
| `curaui/werte.py` | Wertespeicher; ruft Curas Formelauswertung auf |
| `curaui/profile.py` | Qualitätsprofile und Düsenvarianten |
| `curaui/material.py` | Materialprofile (XML) |
| `curaui/aufbau.py` | setzt Maschine, Extruder und alle Ebenen zusammen |
| `curaui/startcode.py` | Platzhalter im Start- und End-G-Code |
| `curaui/engine.py` | Aufruf der CuraEngine, Auswertung des G-Codes |
| `curaui/auswahl.py` | Umfang der angebotenen Parameter |
| `curaui/sprache.py` | Bezeichnungen, wahlweise übersetzt |
| `curaui/projekt.py` | Speichern und Laden eigener Einstellungen |
| `curaui/terminal.py` | Tastatur und Bildschirm ohne Fremdbibliotheken |
| `curaui/liste.py` | die überall verwendete Auswahlliste |
| `curaui/tui.py` | die Bildschirme |
| `data/parameter_246.json` | die Liste der wirksamen Parameter |
| `data/parameter_beton.json` | die Beton-Auswahl samt ihrer Vorgabewerte |

## Die Ebenen einer Maschine

Cura setzt jeden Wert aus mehreren Ebenen zusammen und führt dafür zwei
Stapel: einen globalen und einen je Extruder. Dieses Programm bildet beide
nach, weil sich sonst falsche Werte ergeben — Material und Düse liegen
**nur** im Extruderstapel, im globalen führt Cura dort leere Behälter.

| Ebene | global | je Extruder |
|---|---|---|
| Benutzeränderungen | ✓ | ✓ |
| Vorgaben des Umfangs | ✓ | ✓ |
| Qualitätsprofil | ✓ | ✓ |
| Material | leer | ✓ |
| Düse (Variante) | leer | ✓ |
| Definitionsdatei | Drucker | Extruder |

Findet ein Extruderstapel einen Wert nicht, greift er auf den globalen zurück.
Parameter mit einer `resolve`-Funktion (etwa `prime_tower_mode`) fassen die
Werte aller Extruder zusammen; Parameter mit `limit_to_extruder` (etwa beim
Stützmaterial) holen ihren Wert aus einem bestimmten Extruder.

## Nachweis der Übereinstimmung

Cura schreibt vor jedem Schnitt den vollständigen Wertesatz in sein Protokoll
(`~/Library/Application Support/cura/5.13/cura.log`, unter Windows
`%APPDATA%\cura\5.13\cura.log`). Das Skript `pruefung/abgleich.py` stellt
diese Werte denen des Programms gegenüber — an jedem eigenen Cura-Schnitt:

```
python3 pruefung/abgleich.py Datei.gcode
```

Es liest die in Cura geänderten Werte aus dem G-Code und setzt sie auf
demselben Weg wie die Oberfläche des Tools. Einzelheiten in
`pruefung/README.md`. Für die drei Fälle aus der Arbeit
(`python3 pruefung/abgleich.py --beispiele`) ergab es **vollständige
Übereinstimmung aller übergebenen Werte** (zuletzt geprüft am 14.09.2026):

| Fall | global | Extruder |
|---|---|---|
| Ender-3, Generate Support | 714/714 | 583/583 |
| Ender-3, Fuzzy Skin | 714/714 | 583/583 |
| CR-X (2 Extruder), Support über den rechten Extruder | 714/714 | 584/584 und 583/583 |

Auch der erzeugte G-Code stimmt überein: gleiche Schichtzahl, gleiche Anzahl
Bewegungen und Einzüge, gleicher Druckweg, gleicher Materialverbrauch. Es
bleibt eine Abweichung einzelner Koordinaten um Bruchteile eines Millimeters
— dieselbe Streuung tritt zwischen zwei Läufen **desselben** Programms auf und
geht auf CuraEngine selbst zurück.

Mit `vergleich.py` lassen sich zwei G-Code-Dateien gegenüberstellen:

```
python3 vergleich.py meine.gcode cura.gcode --name-a Programm --name-b Cura
```

Die Verschiebung des Körpers wird dabei herausgerechnet.

## Warum das ohne Nachbau auskommt

CuraEngine wertet die `value`-Formeln der Definitionsdateien **nicht** aus.
Cura löst sie im Programm auf und übergibt der Engine eine flache Liste aus
Namen und fertigen Werten (`plugins/CuraEngineBackend/StartSliceJob.py`).
Genau diese Auflösung übernimmt hier Curas eigene Klasse `SettingFunction`.
Dazu sind vier kleine Anpassungen nötig, alle in `cura_env.py` und alle nur
im Arbeitsspeicher:

1. eine Attrappe für PyQt6, das Cura nur für die grafische Oberfläche braucht,
2. die Anmeldung der von Cura zusätzlich eingeführten Eigenschaften
   (`settable_per_extruder`, `resolve` …), übernommen aus
   `CuraApplication._initializeSettingDefinitions`,
3. zwei Ausgleiche für Python 3.12+, wo `ast.Str` und `Constant.s` entfernt
   wurden, auf die Curas Formelprüfer noch zugreift,
4. die Anmeldung der Formel-Hilfsfunktionen (`resolveOrValue`,
   `extruderValues` …), die auf die Stapel dieses Programms zugreifen.

Nicht aus Cura übernommen, sondern nachgebildet sind drei kleinere Dinge, die
in Curas Oberfläche stecken und nicht in wiederverwendbaren Klassen: das
Ersetzen der Platzhalter im Start- und End-G-Code, das Einlesen der
Materialprofile aus dem XML-Format und das mittige Setzen des Modells auf die
Druckplatte.

Damit gelten in diesem Programm dieselben Formeln, Bedingungen, Grenzen und
Beschriftungen wie in Cura selbst.

## Hinweis zur Druckzeit

CuraEngine lässt beim Aufruf über die Befehlszeile die Kopfzeilen `;TIME:` und
`;Filament used:` auf ihren Platzhaltern stehen; in Cura trägt sie die
Oberfläche nachträglich ein. Dieses Programm berechnet Materialbedarf und
Abmessungen deshalb aus den Bewegungsbefehlen selbst und schätzt die Druckzeit
aus Wegstrecke und Vorschub. Die Schätzung berücksichtigt keine
Beschleunigungen und fällt daher etwas zu niedrig aus.
