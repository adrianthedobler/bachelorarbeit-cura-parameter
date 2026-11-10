# -*- coding: utf-8 -*-
"""Platzhalter im Start- und End-G-Code ersetzen.

Im Start- und End-G-Code eines Druckers duerfen Parameter in geschweiften
Klammern stehen, zum Beispiel

    M104 S{material_print_temperature_layer_0}
    G1 X0 Y{machine_depth} ;Present print

Diese Ersetzung nimmt Cura selbst vor, bevor es die Werte an die Engine
uebergibt; CuraEngine kennt die Schreibweise nicht und wuerde die Klammern
unveraendert in den G-Code schreiben. Beim Ender-3 entstuende so die
unbrauchbare Zeile "G1 X0 Y{machine_depth}".

Umgesetzt ist dasselbe Verhalten wie in Curas GcodeStartEndFormatter
(share/cura/plugins/CuraEngineBackend/StartSliceJob.py): einfache Ausdruecke,
Bedingungen mit if/elif/else/endif und die Angabe eines Extruders nach einem
Komma. Da dieses Programm mit einem Extruder arbeitet, wird die Extruderangabe
gelesen, aber nicht unterschieden.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: Erkennt {ausdruck}, {ausdruck, extruder} sowie {if ...} {elif ...}
#: {else} {endif}. Uebernommen aus GcodeStartEndFormatter._instruction_regex.
_MUSTER = re.compile(
    r"{(?P<bedingung>if|else|elif|endif)?\s*(?P<ausdruck>[^{}]*?)\s*"
    r"(?:,\s*(?P<extruder>[^{}]*))?\s*}(?P<zeilenende>\n?)")

#: Diese Angaben stehen erst nach dem Schneiden fest und bleiben deshalb
#: unveraendert stehen; sie werden spaeter von der Nachbearbeitung ersetzt.
NACH_DEM_SCHNEIDEN = ("filament_cost", "print_time", "filament_amount",
                      "filament_weight", "jobname")

#: Die G-Code-Felder, in denen ersetzt wird.
FELDER = ("machine_start_gcode", "machine_end_gcode",
          "machine_extruder_start_code", "machine_extruder_end_code",
          "machine_extruder_prestart_code")

# Zustaende der Bedingungsauswertung
_AUSSERHALB, _WAHR, _FALSCH, _ERLEDIGT = range(4)


def ersetze(text: str, werteliefernd: Any) -> str:
    """Ersetzt alle Platzhalter in einem Stueck G-Code."""
    if not text or "{" not in text:
        return text

    from UM.Settings.SettingFunction import SettingFunction

    ergebnis: List[str] = []
    rest = text
    zustand = _AUSSERHALB

    while rest:
        treffer = _MUSTER.search(rest)
        if treffer is None:
            if zustand in (_AUSSERHALB, _WAHR):
                ergebnis.append(rest)
            break

        anfang, ende = treffer.span()
        if anfang > 0 and zustand in (_AUSSERHALB, _WAHR):
            ergebnis.append(rest[:anfang])

        stueck, zustand = _verarbeite(treffer, zustand, werteliefernd,
                                      SettingFunction)
        ergebnis.append(stueck)
        rest = rest[ende:]

    return "".join(ergebnis)


def _verarbeite(treffer: "re.Match[str]", zustand: int, werteliefernd: Any,
                SettingFunction: Any) -> Any:
    bedingung = treffer.group("bedingung")
    ausdruck = treffer.group("ausdruck")
    zeilenende = treffer.group("zeilenende") or ""

    if bedingung is None:
        if zustand not in (_AUSSERHALB, _WAHR):
            return "", zustand
        if ausdruck in NACH_DEM_SCHNEIDEN:
            return "{" + ausdruck + "}" + zeilenende, zustand
        wert = _auswerten(ausdruck, werteliefernd, SettingFunction)
        return str(wert) + zeilenende, zustand

    if bedingung == "if":
        wahr = bool(_auswerten(ausdruck, werteliefernd, SettingFunction))
        return "", (_WAHR if wahr else _FALSCH)

    if zustand == _WAHR:
        # Eine zutreffende Bedingung wurde bereits abgearbeitet; alles
        # Weitere bis zum endif wird uebergangen.
        zustand = _ERLEDIGT

    if bedingung == "elif":
        if zustand == _FALSCH:
            wahr = bool(_auswerten(ausdruck, werteliefernd, SettingFunction))
            return "", (_WAHR if wahr else _FALSCH)
        return "", zustand

    if bedingung == "else":
        return "", (_WAHR if zustand == _FALSCH else zustand)

    if bedingung == "endif":
        return "", _AUSSERHALB

    return "", zustand


def _auswerten(ausdruck: str, werteliefernd: Any, SettingFunction: Any) -> Any:
    """Berechnet einen Ausdruck mit Curas eigener Formelklasse."""
    if not ausdruck:
        return ""
    try:
        return SettingFunction(ausdruck)(werteliefernd)
    except Exception:
        # Laesst sich ein Ausdruck nicht deuten, bleibt er stehen. Das ist
        # besser als ihn stillschweigend zu verschlucken: im G-Code faellt er
        # auf und laesst sich zurueckverfolgen.
        return "{" + ausdruck + "}"


def temperaturen_voranstellen(start_gcode: str, werte: Dict[str, str]) -> None:
    """Entscheidet, ob die Engine die Temperaturbefehle selbst voranstellt.

    Enthaelt der Start-G-Code bereits einen Temperaturbefehl, darf die Engine
    keinen zweiten davorsetzen -- sonst wuerde zweimal geheizt und gewartet.
    Cura prueft das anhand der noch nicht ersetzten Platzhalter; deshalb ist
    diese Pruefung vor der Ersetzung durchzufuehren.

    Vorbild: StartSliceJob._buildGlobalSettingsMessage.
    """
    ohne_kommentare = re.sub(r";.+?(\n|$)", "\n", start_gcode)

    if werte.get("material_bed_temp_prepend") == "true":
        bett = ["material_bed_temperature", "material_bed_temperature_layer_0"]
        muster = r"\{(%s)(,\s?\w+)?\}" % "|".join(bett)
        if re.search(muster, ohne_kommentare) is not None:
            werte["material_bed_temp_prepend"] = "false"

    if werte.get("material_print_temp_prepend") == "true":
        duese = ["material_print_temperature", "material_print_temperature_layer_0",
                 "default_material_print_temperature", "material_initial_print_temperature",
                 "material_final_print_temperature", "material_standby_temperature",
                 "print_temperature"]
        muster = r"\{(%s)(,\s?\w+)?\}" % "|".join(duese)
        if re.search(muster, ohne_kommentare) is not None:
            werte["material_print_temp_prepend"] = "false"


def anwenden(werte: Dict[str, str], werteliefernd: Any) -> Dict[str, str]:
    """Ersetzt die Platzhalter in allen G-Code-Feldern einer Wertetabelle."""
    start = werte.get("machine_start_gcode", "")
    if start:
        temperaturen_voranstellen(start, werte)
    for feld in FELDER:
        if feld in werte and werte[feld]:
            werte[feld] = ersetze(werte[feld], werteliefernd)
    return werte
