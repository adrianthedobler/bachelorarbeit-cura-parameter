# -*- coding: utf-8 -*-
"""Anbindung an das 3DCP-Programm des Lehrstuhls (Repo dvdschdt/3DCP).

Das dortige Programm liest seine Angaben aus user_input/setup.json, ergaenzt
sie um feste Argumente aus slicer/cura/preset_arguments.py und ruft damit die
CuraEngine auf -- also denselben Aufruf, den auch dieses Programm erzeugt
(curaui/engine.py).

Dieses Modul stellt drei Verbindungen her:

  * setup.json einlesen: Druckerdefinition, Bauraum, Filamentstaerke,
    Foerdermengen und die bereits gesetzten cura_arguments,
  * die festen Argumente nachbilden und als unveraenderliche Ebene einlegen
    (siehe werte.Einstellungen.setze_feste),
  * die im Programm vorgenommenen Aenderungen als cura_arguments
    zurueckschreiben -- und zwar aufgeloest, also einschliesslich der
    Kindparameter, die CuraEngine tatsaechlich auswertet.

Der letzte Punkt ist der eigentliche Zweck: Die Engine wertet die
value-Formeln nicht aus. Ein Eintrag wie wall_thickness in cura_arguments
bleibt deshalb wirkungslos, solange nicht auch wall_line_count uebergeben
wird. Dieses Programm loest die Formeln mit Curas eigenen Klassen auf und
kann deshalb die wirksamen Werte liefern.
"""
from __future__ import annotations

import copy
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple


class SetupFehler(RuntimeError):
    pass


# --------------------------------------------------------------- Einlesen

def _wert(abschnitt: Dict[str, Any], name: str, ersatz: Any = None) -> Any:
    eintrag = (abschnitt or {}).get(name)
    if isinstance(eintrag, dict) and "value" in eintrag:
        return eintrag["value"]
    return ersatz


class Setup:
    """Die fuer das Slicing wesentlichen Angaben aus setup.json."""

    def __init__(self, pfad: str, inhalt: Dict[str, Any]) -> None:
        self.pfad = pfad
        self.inhalt = inhalt
        abschnitte = inhalt.get("settings", {})
        self.roboter = abschnitte.get("Robot", {})
        self.pumpe = abschnitte.get("Pump", {})
        self.cura = abschnitte.get("Cura", {})
        self.verzeichnis = abschnitte.get("Directory", {})

        self.name = str(_wert(self.roboter, "id", "3DCP"))
        self.bauraum = dict(_wert(self.roboter, "bed_size",
                                  {"X": 1000, "Y": 1000, "Z": 1000}) or {})
        #: Druckgeschwindigkeit in m/s; Cura rechnet in mm/s.
        self.druckgeschwindigkeit = _wert(self.roboter, "print_speed")
        self.verfahrgeschwindigkeit = _wert(self.roboter, "travel_speed")
        #: Mindestzeit je Schicht in ms; Cura rechnet in s.
        self.mindestzeit_ms = _wert(self.roboter, "min_layer_time")

        self.einzug_moeglich = bool(_wert(self.pumpe, "retract", False))
        self.filamentstaerke = _wert(self.pumpe, "filament_diameter", 22)
        self.foerdermenge = dict(_wert(self.pumpe, "linetype_flow", {}) or {})

        self.druckerdatei = _wert(self.cura, "cura_printer_config_file_path", "")
        self.engine_pfad = _wert(self.cura, "cura_cmd_path", "")
        self.argumente = dict(_wert(self.cura, "cura_arguments", {}) or {})
        self.skalierung = dict(_wert(self.cura, "cura_scaling", {}) or {})

    # -------------------------------------------------- abgeleitete Angaben

    def druckerdatei_pfad(self) -> Optional[str]:
        """Die Druckerdefinition; notfalls die im Repo mitgelieferte.

        Der Eintrag in setup.json ist ein absoluter Windows-Pfad des
        Lehrstuhlrechners. Ist er hier nicht vorhanden, wird die Datei im
        Ordner user_input neben der setup.json benutzt.
        """
        eintrag = str(self.druckerdatei or "")
        if eintrag and os.path.isfile(eintrag):
            return eintrag
        ersatz = os.path.join(os.path.dirname(os.path.abspath(self.pfad)),
                              "printer.def.json")
        return ersatz if os.path.isfile(ersatz) else None

    def feste_werte(self) -> Dict[str, Any]:
        """Die festen Argumente, nachgebildet aus preset_arguments.py.

        Zwei Abweichungen sind bewusst: Der Filamentdurchmesser wird unter
        material_diameter gefuehrt (filament_diameter gibt es in Curas
        Definitionsdateien nicht), und extruders_enabled_count steht auf 1
        statt 0, weil sonst die Formeln mit extruderValues() ins Leere
        greifen.
        """
        fluss = self.foerdermenge
        werte: Dict[str, Any] = {
            "machine_name": self.name,
            "machine_width": self.bauraum.get("X"),
            "machine_depth": self.bauraum.get("Y"),
            "machine_height": self.bauraum.get("Z"),
            "machine_show_variants": False,
            "machine_start_gcode": "",
            "machine_end_gcode": "",
            "machine_center_is_zero": False,
            "machine_extruder_start_code": "",
            "machine_extruder_end_code": "",
            "machine_g_code_flavor": "RepRap (Marlin/Sprinter)",
            "material_guid": "",
            "material_type": "",
            "material_brand": "",
            "machine_shape": "rectangular",
            "machine_extruder_count": 1,
            "extruders_enabled_count": 1,
            "machine_firmware_retract": False,
            "initial_layer_line_width_factor": 100,
            "ironing_enabled": False,
            "roofing_layer_count": 0,
            "prime_tower_flow": 100,
            "material_flow_layer_0": 100,
            "retraction_enable": self.einzug_moeglich,
            "retraction_hop_enabled": False,
            "layer_0_z_overlap": 0,
            "wipe_hop_enable": False,
            "mesh_rotation_matrix": skalierungsmatrix(self.skalierung),
            "material_diameter": self.filamentstaerke,
        }
        zuordnung = {
            "wall_0_material_flow": "wall_outer",
            "wall_x_material_flow": "wall_inner",
            "wall_0_material_flow_roofing": "wall_outer",
            "wall_x_material_flow_roofing": "wall_inner",
            "skin_material_flow": "surface",
            "roofing_material_flow": "surface",
            "infill_material_flow": "infill",
            "skirt_brim_material_flow": "curb",
            "support_material_flow": "support",
            "support_roof_material_flow": "support",
            "support_bottom_material_flow": "support",
        }
        for schluessel, art in zuordnung.items():
            if art in fluss:
                werte[schluessel] = fluss[art]
        return {k: v for k, v in werte.items() if v is not None}

    def vorschlaege(self) -> Dict[str, Any]:
        """Werte aus setup.json, die keine festen Argumente sind.

        Sie werden als Ausgangswerte eingelegt, bleiben aber aenderbar:
        Druck- und Verfahrgeschwindigkeit des Roboters sowie die Mindestzeit
        je Schicht. Der Roboter fuehrt sie in m/s und ms, Cura in mm/s und s.
        """
        werte: Dict[str, Any] = {}
        if isinstance(self.druckgeschwindigkeit, (int, float)):
            werte["speed_print"] = round(float(self.druckgeschwindigkeit) * 1000, 3)
        if isinstance(self.verfahrgeschwindigkeit, (int, float)):
            werte["speed_travel"] = round(float(self.verfahrgeschwindigkeit) * 1000, 3)
        if isinstance(self.mindestzeit_ms, (int, float)) and self.mindestzeit_ms:
            werte["cool_min_layer_time"] = round(float(self.mindestzeit_ms) / 1000, 3)
        return werte


def lade_setup(pfad: str) -> Setup:
    """Liest eine setup.json des 3DCP-Programms ein."""
    pfad = os.path.abspath(os.path.expanduser(pfad))
    if not os.path.isfile(pfad):
        raise SetupFehler(f"setup.json nicht gefunden: {pfad}")
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            inhalt = json.load(datei)
    except ValueError as fehler:
        raise SetupFehler(f"setup.json ist nicht lesbar: {fehler}")
    if "settings" not in inhalt:
        raise SetupFehler("setup.json enthaelt keinen Abschnitt \"settings\".")
    return Setup(pfad, inhalt)


# ------------------------------------------------------- Skalierungsmatrix

def skalierungsmatrix(angabe: Dict[str, Any]) -> str:
    """Dreht und skaliert das Modell, wie scaling_matrix.py des 3DCP-Repos.

    Erst die Drehung in der Reihenfolge ZYX, dann die Skalierung. Das
    Ergebnis ist die Zeichenkette, die CuraEngine als mesh_rotation_matrix
    erwartet.
    """
    def zahl(name: str, ersatz: float) -> float:
        try:
            return float(angabe.get(name, ersatz))
        except (TypeError, ValueError):
            return ersatz

    sx, sy, sz = (zahl("sX", 100) / 100, zahl("sY", 100) / 100,
                  zahl("sZ", 100) / 100)
    rx, ry, rz = (math.radians(zahl("rX", 0)), math.radians(zahl("rY", 0)),
                  math.radians(zahl("rZ", 0)))

    def mal(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
                for i in range(3)]

    dz = [[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0],
          [0, 0, 1]]
    dy = [[math.cos(ry), 0, math.sin(ry)], [0, 1, 0],
          [-math.sin(ry), 0, math.cos(ry)]]
    dx = [[1, 0, 0], [0, math.cos(rx), -math.sin(rx)],
          [0, math.sin(rx), math.cos(rx)]]
    drehung = mal(mal(dz, dy), dx)
    skala = [[sx, 0, 0], [0, sy, 0], [0, 0, sz]]
    return str(mal(drehung, skala))


# ------------------------------------------------------------- Rueckgabe

def geaenderte_werte(maschine: Any) -> Dict[str, str]:
    """Alle Werte, die von der unveraenderten Definition abweichen.

    Verglichen wird die vollstaendige Wertuebergabe der Maschine mit der
    einer zweiten, frisch geladenen Maschine ohne eigene Aenderungen. Das
    Ergebnis enthaelt deshalb auch die Kindparameter, die sich ueber die
    Formeln mitverschoben haben -- genau die Werte, die CuraEngine auswertet.
    """
    from . import aufbau, engine

    eigene, eigene_extruder = engine.teile_werte(maschine.einstellungen)
    vergleich = aufbau.Maschine(
        maschine.inst, maschine.drucker.name,
        materialien=maschine.materialien,
        drucker_datei=getattr(maschine, "drucker_datei", None),
        ohne_material=getattr(maschine, "ohne_material", False))
    if getattr(maschine, "feste_vorgaben", None):
        vergleich.feste_werte_setzen(maschine.feste_vorgaben)
    grund, grund_extruder = engine.teile_werte(vergleich.einstellungen)

    ergebnis: Dict[str, str] = {}
    for schluessel, wert in eigene.items():
        if grund.get(schluessel) != wert:
            ergebnis[schluessel] = wert
    if eigene_extruder and grund_extruder:
        for schluessel, wert in eigene_extruder[0].items():
            if grund_extruder[0].get(schluessel) != wert:
                ergebnis[schluessel] = wert
    # Die festen Argumente stehen im 3DCP-Programm ohnehin in
    # preset_arguments.py; sie gehoeren nicht in die cura_arguments.
    for schluessel in (getattr(maschine, "feste_vorgaben", None) or {}):
        ergebnis.pop(schluessel, None)
    return dict(sorted(ergebnis.items()))


def _ersetze_value_block(roh: str, werte: Dict[str, str]) -> str:
    """Ersetzt im Rohtext einer setup.json nur den value-Block von
    Cura.cura_arguments und laesst alles andere bytegleich.

    So bleibt die Vorlage des Lehrstuhls formatidentisch; nur die
    cura_arguments aendern sich. Loest keine JSON-Formatierung neu aus.
    """
    marke = roh.find('"cura_arguments"')
    if marke < 0:
        raise SetupFehler("cura_arguments nicht in der setup.json gefunden.")
    vpos = roh.find('"value"', marke)
    bpos = roh.find('{', vpos) if vpos >= 0 else -1
    if vpos < 0 or bpos < 0:
        raise SetupFehler("value-Block von cura_arguments nicht gefunden.")
    # Geschweifte Klammern ausgewogen zaehlen (Zeichenketten uebergehen).
    tiefe = 0
    in_str = False
    esc = False
    ende = -1
    i = bpos
    while i < len(roh):
        c = roh[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                tiefe += 1
            elif c == "}":
                tiefe -= 1
                if tiefe == 0:
                    ende = i + 1
                    break
        i += 1
    if ende < 0:
        raise SetupFehler("value-Block von cura_arguments ist unvollstaendig.")
    # Einrueckung der value-Zeile uebernehmen, damit der neue Block passt.
    zeilen_start = roh.rfind("\n", 0, vpos) + 1
    einzug = vpos - zeilen_start
    neu = json.dumps({k: str(v) for k, v in werte.items()},
                     indent=4, ensure_ascii=False)
    neu = neu.replace("\n", "\n" + " " * einzug)
    return roh[:bpos] + neu + roh[ende:]


def schreibe_cura_arguments(setup: Setup, werte: Dict[str, str],
                            ziel: Optional[str] = None,
                            in_place: bool = False) -> str:
    """Schreibt die Werte als Cura.cura_arguments in eine setup.json.

    in_place=False (Vorgabe): schreibt eine neue Datei neben dem Original
    (…_aus_cura_ui.json), die Vorlage bleibt unberuehrt.

    in_place=True: schreibt in die Original-setup.json zurueck und aendert
    dabei ausschliesslich den value-Block von Cura.cura_arguments; alle
    anderen Angaben und die Formatierung bleiben bytegleich. Vor dem ersten
    Schreiben wird eine unveraenderte Sicherung <name>.orig angelegt.
    """
    if in_place:
        ziel = setup.pfad
        sicherung = setup.pfad + ".orig"
        with open(setup.pfad, "r", encoding="utf-8") as datei:
            roh = datei.read()
        if not os.path.exists(sicherung):
            with open(sicherung, "w", encoding="utf-8") as datei:
                datei.write(roh)
        neuer_text = _ersetze_value_block(roh, werte)
        with open(ziel, "w", encoding="utf-8") as datei:
            datei.write(neuer_text)
        return ziel

    inhalt = copy.deepcopy(setup.inhalt)
    abschnitt = inhalt.setdefault("settings", {}).setdefault("Cura", {})
    eintrag = abschnitt.setdefault("cura_arguments", {
        "description": "Additional arguments to quickly change the settings "
                       "for CURA slicing. These overwrite the values in the "
                       "printer and extruder config data",
        "type": "dict[str,str]"})
    eintrag["value"] = {k: str(v) for k, v in werte.items()}
    if ziel is None:
        ordner = os.path.dirname(os.path.abspath(setup.pfad))
        name = os.path.basename(setup.pfad)
        stamm = name[:-5] if name.endswith(".json") else name
        ziel = os.path.join(ordner, stamm + "_aus_cura_ui.json")
    with open(ziel, "w", encoding="utf-8") as datei:
        json.dump(inhalt, datei, indent=4, ensure_ascii=False)
        datei.write("\n")
    return ziel


def bericht(maschine: Any, setup: Optional[Setup],
            werte: Dict[str, str]) -> List[str]:
    """Kurze Zusammenfassung fuer die Ausgabe im Terminal."""
    zeilen = [f"Druckerdefinition : {maschine.drucker.anzeigename}",
              f"Extruder          : {maschine.anzahl_extruder}",
              f"Materialprofil    : "
              + ("keines" if maschine.material is None
                 else maschine.material.kennung)]
    if setup is not None:
        zeilen.append(f"setup.json        : {setup.pfad}")
        zeilen.append(f"feste Argumente   : {len(maschine.feste_vorgaben)}")
    zeilen.append(f"zu uebergeben     : {len(werte)} Werte")
    return zeilen
