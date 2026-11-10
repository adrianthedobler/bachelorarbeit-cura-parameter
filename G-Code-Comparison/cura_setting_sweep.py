#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cura_setting_sweep.py
=====================

Automatisierter Print-Setting-Sweep fuer Ultimaker Cura (CuraEngine, headless).

Ziel
----
Fuer jedes numerische Print Setting des Druckers *Creality Ender-3* (PLA, 0.4 mm
Duese, Qualitaet "Standard Quality") wird geprueft, ob die Verdreifachung des
Default-Werts einen Einfluss auf den erzeugten G-Code hat:

  1. Default-Wert ermitteln (von CuraEngine aufgeloest, inkl. Standard-Quality).
  2. Baseline-G-Code mit allen Defaults erzeugen (einmalig, mehrfach kalibriert).
  3. Pro Setting einen G-Code mit dem 3-fachen Wert erzeugen
     (alle uebrigen Settings bleiben auf Default).
  4. Den 3x-G-Code mit der Baseline vergleichen.
  5. Festhalten, ob sich der G-Code veraendert hat.

Ergebnis: Excel-Liste (+ CSV) mit dem Status je Setting; alle G-Codes werden
im Unterordner gcode_output/ gespeichert.

Warum Metrik-Vergleich statt Byte-Vergleich?
--------------------------------------------
CuraEngine erzeugt bei komplexen Modellen NICHT-deterministischen G-Code: die
Reihenfolge von Reise-/Combing-Bewegungen variiert von Lauf zu Lauf, auch bei
voellig identischen Eingaben (getestet: zwei identische Slices ergeben leicht
unterschiedliche Dateien). Ein direkter Byte-/Hash-Vergleich wuerde deshalb
ueberall faelschlich "Veraenderung" melden.

Stattdessen werden robuste, reihenfolge-unabhaengige Kennzahlen aus dem G-Code
extrahiert (Layer-Anzahl, extrudiertes Filament, Extrusions-Distanz und
-Bewegungen, geschaetzte Druckzeit, Maximaltemperaturen, Luefter). Das
Programm misst das Rausch-Band dieser Kennzahlen selbst, indem es die Baseline
mehrfach slict, und meldet "Veraenderung" nur, wenn eine Kennzahl das
kalibrierte Rauschen ueberschreitet.

Aufruf
------
    py cura_setting_sweep.py                # kompletter Lauf (alle numer. Settings)
    py cura_setting_sweep.py --limit 10     # nur die ersten 10 (Test)
    py cura_setting_sweep.py --only layer_height,infill_sparse_density
    py cura_setting_sweep.py --list         # Settings nur auflisten
    py cura_setting_sweep.py --calib 6      # Anzahl Baseline-Kalibrierlaeufe
"""

import argparse
import configparser
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time

# --------------------------------------------------------------------------- #
# Konfiguration – plattformabhaengige Pfade
# --------------------------------------------------------------------------- #

_SYSTEM = platform.system()

if _SYSTEM == "Darwin":
    CURA_DIR = "/Applications/UltiMaker Cura.app/Contents/Resources"
    ENGINE = os.path.join(CURA_DIR, "CuraEngine")
    RES = os.path.join(CURA_DIR, "share", "cura", "resources")
    _PATH_SEP = ":"
elif _SYSTEM == "Windows":
    CURA_DIR = r"C:\Program Files\UltiMaker Cura 5.8.0"
    ENGINE = os.path.join(CURA_DIR, "CuraEngine.exe")
    RES = os.path.join(CURA_DIR, "share", "cura", "resources")
    _PATH_SEP = ";"
else:  # Linux
    CURA_DIR = "/usr/share/cura"
    ENGINE = "CuraEngine"
    RES = os.path.join(CURA_DIR, "resources")
    _PATH_SEP = ":"

DEFS = os.path.join(RES, "definitions")
EXTR = os.path.join(RES, "extruders")
DEFINITION      = os.path.join(DEFS, "creality_ender3.def.json")
DEFINITION_DUAL = os.path.join(DEFS, "creality_cr-x.def.json")
FDMPRINTER = os.path.join(DEFS, "fdmprinter.def.json")

# GUI-Qualitaetsprofil "Standard Quality" fuer Ender-3 / PLA / 0.4 mm
QUALITY_GLOBAL = os.path.join(RES, "quality", "creality", "base",
                              "base_global_standard.inst.cfg")
QUALITY_VARIANT = os.path.join(RES, "quality", "creality", "base",
                               "base_0.4_PLA_standard.inst.cfg")

PROJ = os.path.dirname(os.path.abspath(__file__))
GCODE_DIR = os.path.join(PROJ, "gcode_output")
EXCEL_PATH = os.path.join(PROJ, "cura_setting_sweep_ergebnis.xlsx")
CSV_PATH = os.path.join(PROJ, "cura_setting_sweep_ergebnis.csv")

# Settings, die CuraEngine 5.13.0 unter macOS explizit benoetigt.
# Diese werden bei jedem Slice gesetzt (entsprechen den Defaults, vermeiden aber
# "Trying to retrieve setting with no value given"-Abbrueche).
FIXUP_OVERRIDES = {
    "roofing_layer_count":            "0",
    "flooring_layer_count":           "0",
    "support_z_seam_away_from_model": "false",   # benoetigt wenn support_enable=true
    "line_width":                     "0.4",      # benoetigt bei magic_fuzzy_skin_enabled=true
    "min_wall_line_width":            "0.34",     # benoetigt bei support_structure=tree
    "support_extruder_nr":            "0",        # benoetigt bei support_pattern=lightning
    "reset_flow_duration":            "2.0",      # benoetigt bei gradual_flow_enabled=true
    "brim_width":                     "8.0",      # benoetigt bei support_conical_enabled=true
}

# Overrides die bei Dual-Extruder-Settings gesetzt werden, damit CuraEngine
# echte Extruderwechsel durchfuehrt (Support auf E1 → Prime Tower generiert).
# Wird per-Setting um prime_tower_enable / ooze_shield_enabled ergaenzt.
DUAL_EXTRUDER_BASE_CONTEXT = {
    "support_enable":                "true",
    "support_extruder_nr":           "1",
    "support_infill_extruder_nr":    "1",
    "support_interface_extruder_nr": "1",
}

# Ersatz-Testwert fuer Settings mit Default 0 (3*0=0 waere nicht testbar).
# Es wird einfach ein kleiner Wert eingesetzt, damit jedes Setting getestet wird.
SUBSTITUTE_INT = 1
SUBSTITUTE_FLOAT = 1.0

# Kategorien, die KEINE Print Settings sind (Drucker-Hardware / interne Settings).
EXCLUDED_CATEGORIES = {"machine_settings", "command_line_settings"}

# Settings, die als Vorbedingung NICHT per CLI gesetzt werden koennen
# (Szenen-Berechnungswerte oder Netzwerk-/Mesh-Flags).
SKIP_PRECONDITIONS = {
    "support_meshes_present",  # wird von Cura aus der Szene berechnet
}

# Timeout pro Slice (Sekunden). Ein normaler Slice dauert < 1 s; alles
# darueber ist pathologisch (z.B. Endlosschleife durch Extremwert).
SLICE_TIMEOUT = 120

# Anzahl Baseline-Laeufe zur Rausch-Kalibrierung.
CALIB_RUNS = 5

# Zusaetzliche Slices zur Verifikation eines "Veraenderung"-Treffers. Da
# CuraEngine nicht-deterministisch ist (besonders bei grossen/komplexen
# Modellen), wird jeder Treffer nachgeslict: nur wenn die Abweichung
# reproduzierbar ueber der Toleranz bleibt (Median), zaehlt sie. Das
# eliminiert Rausch-Fehltreffer. 0 = aus.
VERIFY_RUNS = 2

# Geometrische Kennzahlen fuer den Vergleich – nur optisch relevante Metriken.
# Nicht-visuelle Groessen (Druckzeit, Temperatur, Luefter) sind bewusst
# ausgeschlossen: sie aendern die Druckbedingungen, nicht die Form.
# Mindesttoleranzen (Floors) aus 12 identischen Baseline-Laeufen bestimmt:
# extr_dist-Rauschen bis ~1.3 mm (-> Floor 5), extr_moves bis ~6 (-> Floor 20).
# Abschnitts-spezifische Metriken ermoeglichen den Nachweis von Aenderungen,
# die sich in globalen Metriken gegenseitig aufheben (z.B. Support-Interface-
# Moves steigen, Support-Moves fallen -> Netto nahezu 0, aber sektionsweise
# klar erkennbar).
DECISION_FLOORS = {
    "layers":              0.5,    # exakt -> jede ganze Layer-Abweichung zaehlt
    "filament":            0.05,   # mm Filament
    "extr_dist":           5.0,    # mm Extrusions-Wegstrecke
    "extr_moves":          20,     # Anzahl Extrusions-Bewegungen (gesamt)
    "wall_start_x":        10.0,   # mittlere X-Position des Aussenwand-Starts (Seam-X)
    "wall_start_y":        10.0,   # mittlere Y-Position des Aussenwand-Starts (Seam-Y)
    # Sektions-spezifische Metriken – erkennen Aenderungen innerhalb eines Abschnitts
    "support_moves":       5,      # Extr.-Bewegungen im SUPPORT-Abschnitt
    "support_intf_moves":  3,      # Extr.-Bewegungen im SUPPORT-INTERFACE-Abschnitt
    "skin_moves":          8,      # Extr.-Bewegungen im SKIN-Abschnitt
    "fill_moves":          5,      # Extr.-Bewegungen im FILL-Abschnitt
    "wall_moves":          10,     # Extr.-Bewegungen in WALL-OUTER + WALL-INNER
}
DECISION_FEATURES = list(DECISION_FLOORS.keys())

# Lesbare deutsche Namen fuer die Kennzahlen (Excel-Spalte "Geaenderte Metriken").
FEATURE_LABELS = {
    "layers":              "Layer-Anzahl",
    "filament":            "Filament",
    "extr_dist":           "Extr.-Distanz",
    "extr_moves":          "Extr.-Bewegungen",
    "wall_start_x":        "Seam-X",
    "wall_start_y":        "Seam-Y",
    "support_moves":       "Stuetzstruktur-Bewegungen",
    "support_intf_moves":  "Support-Interface-Bewegungen",
    "skin_moves":          "Skin-Bewegungen",
    "fill_moves":          "Infill-Bewegungen",
    "wall_moves":          "Wand-Bewegungen",
}


# --------------------------------------------------------------------------- #
# Abhaengigkeiten pruefen / nachruestbar
# --------------------------------------------------------------------------- #

def _ensure(package):
    try:
        __import__(package)
    except ImportError:
        print(f"Paket '{package}' fehlt – wird jetzt installiert ...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"'{package}' erfolgreich installiert.\n")

_ensure("openpyxl")


# --------------------------------------------------------------------------- #
# Hilfsfunktionen / Umgebung
# --------------------------------------------------------------------------- #

def fail(msg):
    print("FEHLER:", msg, file=sys.stderr)
    sys.exit(1)


def get_dual_context(key):
    """Liefert die Dual-Extruder-Kontext-Overrides fuer ein bestimmtes Setting.
    Das Setting selbst wird NIE in den Kontext aufgenommen (kein Selbst-Override).
    """
    ctx = dict(DUAL_EXTRUDER_BASE_CONTEXT)
    # Wenn das Setting selbst eines der Kontext-Keys ist, raus damit
    for k in list(ctx):
        if k == key:
            del ctx[k]
    # prime_tower_* Settings: prime_tower_enable im Kontext aktivieren
    if key.startswith("prime_tower_") and key != "prime_tower_enable":
        ctx["prime_tower_enable"] = "true"
    # ooze_shield_* Settings: ooze_shield_enabled aktivieren
    if key.startswith("ooze_shield_") and key != "ooze_shield_enabled":
        ctx["ooze_shield_enabled"] = "true"
    return ctx


def build_dual_extruder_settings(all_settings_map):
    """Ermittelt alle Settings, die nur mit Dual-Extruder testbar sind."""
    dual = set()
    DUAL_PREFIXES = ("prime_tower_", "ooze_shield_", "switch_extruder_", "interlocking_")
    for key, s in all_settings_map.items():
        en = str(s.get("enabled", ""))
        if ("extruders_enabled_count" in en or
                "prime_tower_enable" in en or
                "ooze_shield_enabled" in en or
                any(key.startswith(p) for p in DUAL_PREFIXES)):
            dual.add(key)
    return dual


def check_environment():
    for path, name in [(ENGINE, "CuraEngine.exe"),
                       (DEFINITION, "creality_ender3.def.json"),
                       (DEFINITION_DUAL, "creality_cr-x.def.json"),
                       (FDMPRINTER, "fdmprinter.def.json")]:
        if not os.path.exists(path):
            fail(f"{name} nicht gefunden: {path}")


def find_model():
    """Bevorzugt eine vom Nutzer abgelegte STL, sonst cube.stl als Fallback."""
    stls = [f for f in os.listdir(PROJ) if f.lower().endswith(".stl")]
    user_stls = [f for f in stls if f.lower() != "cube.stl"]
    if user_stls:
        return os.path.join(PROJ, sorted(user_stls)[0])
    if any(s.lower() == "cube.stl" for s in stls):
        return os.path.join(PROJ, "cube.stl")
    fail("Keine STL-Datei im Projektordner gefunden. Bitte STL ablegen.")


def env_with_search_path():
    e = dict(os.environ)
    e["CURA_ENGINE_SEARCH_PATH"] = DEFS + _PATH_SEP + EXTR
    return e


def load_quality_overrides():
    """
    Literale (nicht-Formel-) Werte aus den 'Standard Quality'-Profilen.
    Formeln (=...) werden uebersprungen, da CuraEngine sie selbst berechnet.
    """
    overrides = {}
    for cfg_path in (QUALITY_GLOBAL, QUALITY_VARIANT):
        if not os.path.exists(cfg_path):
            continue
        cp = configparser.ConfigParser()
        cp.read(cfg_path, encoding="utf-8")
        if not cp.has_section("values"):
            continue
        for key, val in cp.items("values"):
            val = val.strip()
            if val.startswith("="):
                continue
            overrides[key] = val
    return overrides


# --------------------------------------------------------------------------- #
# Setting-Definition (fdmprinter) parsen
# --------------------------------------------------------------------------- #

def collect_settings():
    """Liste numerischer Print Settings: {key,label,category,type,json_default}."""
    with open(FDMPRINTER, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    results = []

    def recurse(node, category):
        for key, spec in node.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("type") in ("float", "int", "enum", "bool", "[int]"):
                results.append({
                    "key": key,
                    "label": spec.get("label", key),
                    "category": category,
                    "type": spec.get("type"),
                    "json_default": spec.get("default_value"),
                    "enabled": spec.get("enabled", True),
                    "options": list(spec.get("options", {}).keys()),
                    "minimum_value":         spec.get("minimum_value"),
                    "maximum_value":         spec.get("maximum_value"),
                    "maximum_value_warning": spec.get("maximum_value_warning"),
                })
            children = spec.get("children")
            if isinstance(children, dict):
                recurse(children, category)

    for cat_key, cat_spec in data.get("settings", {}).items():
        if cat_key in EXCLUDED_CATEGORIES:
            continue
        recurse(cat_spec.get("children", {}), cat_key)

    return results


# --------------------------------------------------------------------------- #
# Abhaengigkeitsgraph & Formel-Kaskadierung
# --------------------------------------------------------------------------- #

def collect_all_settings():
    """Alle Settings aus fdmprinter (alle Typen) mit value-Formeln."""
    with open(FDMPRINTER, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    all_s = {}

    def recurse(node):
        for key, spec in node.items():
            if not isinstance(spec, dict):
                continue
            all_s[key] = {
                "type": spec.get("type", "str"),
                "default_value": spec.get("default_value"),
                "value": spec.get("value"),
                "enabled": spec.get("enabled", True),
            }
            if "children" in spec:
                recurse(spec["children"])

    for cat_key, cat_spec in data.get("settings", {}).items():
        if cat_key not in EXCLUDED_CATEGORIES:
            recurse(cat_spec.get("children", {}))
    return all_s


def build_dep_graph(all_settings):
    """Vorwaertskarte: key -> Menge der Settings, deren value-Formel auf key verweist."""
    token_re = re.compile(r'\b([a-z][a-z0-9_]*)\b')
    fwd = {k: set() for k in all_settings}
    for key, spec in all_settings.items():
        formula = spec.get("value")
        if not formula:
            continue
        for token in token_re.findall(str(formula)):
            if token in all_settings and token != key:
                fwd[token].add(key)
    return fwd


def cascade_overrides(test_key, test_val, all_settings, resolved_defaults, fwd):
    """
    Berechnet, welchen Wert alle transitiv abhaengigen Settings annehmen wuerden,
    wenn test_key auf test_val gesetzt wird (GUI-Verhalten simulieren).
    Gibt {key: wert_str} zurueck – nur numerische Settings.
    """
    # Eval-Namespace aufbauen: fdmprinter-Defaults, dann resolved engine defaults
    ns = {}
    for key, spec in all_settings.items():
        dv = spec.get("default_value")
        if dv is not None:
            try:
                ns[key] = float(dv) if isinstance(dv, (int, float)) else dv
            except (TypeError, ValueError):
                ns[key] = dv
    for key, val in resolved_defaults.items():
        if isinstance(val, str) and val.lower() == "true":
            ns[key] = True
        elif isinstance(val, str) and val.lower() == "false":
            ns[key] = False
        else:
            try:
                ns[key] = float(val)
            except (TypeError, ValueError):
                ns[key] = val
    ns[test_key] = test_val  # Testwert injizieren

    # Stubs fuer Cura-eigene Funktionen
    eval_ns = dict(ns)
    eval_ns.update({
        "__builtins__": {},
        "math": math,
        "True": True, "False": False,
        "extruderValue":        lambda nr, k: ns.get(k, 0),
        "resolveOrValue":       lambda k: ns.get(k, 0),
        "extruderValues":       lambda k: [ns.get(k, 0)],
        "defaultExtruderPosition": lambda: 0,
        "anyExtruder":          lambda nr, k: ns.get(k, 0),
        "valueFromContainer":   lambda *a: 0,
        "min": min, "max": max, "round": round, "abs": abs,
        "int": int, "float": float, "bool": bool, "str": str,
        "sum": sum, "len": len, "map": map, "list": list,
    })

    # BFS vom test_key aus – Eltern werden vor Kindern verarbeitet
    computed = {}
    queue = list(fwd.get(test_key, []))
    seen = set(queue)
    while queue:
        key = queue.pop(0)
        spec = all_settings.get(key, {})
        formula = spec.get("value")
        if formula is not None:
            try:
                result = eval(str(formula), {"__builtins__": {}}, eval_ns)
                if isinstance(result, bool):
                    result = int(result)
                if isinstance(result, (int, float)) and result == result:
                    eval_ns[key] = result
                    ns[key] = result
                    computed[key] = result
            except Exception:
                pass
        for child in fwd.get(key, []):
            if child not in seen:
                seen.add(child)
                queue.append(child)

    # Nur numerische Settings als Overrides zurueckgeben
    result = {}
    for key, val in computed.items():
        spec = all_settings.get(key, {})
        if spec.get("type") in ("float", "int"):
            result[key] = format_number(val, spec["type"])
    return result


# --------------------------------------------------------------------------- #
# Vorbedingungen fuer bedingt-aktive Settings
# --------------------------------------------------------------------------- #

def build_enable_ns(all_settings, resolved_defaults):
    """Namespace zum Auswerten von `enabled`-Ausdruecken (alle Setting-Defaults)."""
    ns = {}
    for key, spec in all_settings.items():
        dv = spec.get("default_value")
        if dv is not None:
            if isinstance(dv, bool):
                ns[key] = dv
            else:
                try:
                    ns[key] = float(dv)
                except (TypeError, ValueError):
                    ns[key] = dv
    for key, val in resolved_defaults.items():
        if isinstance(val, str) and val.lower() == "true":
            ns[key] = True
        elif isinstance(val, str) and val.lower() == "false":
            ns[key] = False
        else:
            try:
                ns[key] = float(val)
            except (TypeError, ValueError):
                ns[key] = val
    ns.update({
        "__builtins__": {},
        "math": math,
        "True": True, "False": False,
        "extruderValue":           lambda nr, k: ns.get(k, 0),
        "resolveOrValue":          lambda k: ns.get(k, 0),
        "extruderValues":          lambda k: [ns.get(k, 0)],
        "defaultExtruderPosition": lambda: 0,
        "anyExtruder":             lambda nr, k: ns.get(k, 0),
        "valueFromContainer":      lambda *a: 0,
        "min": min, "max": max, "round": round, "abs": abs,
        "int": int, "float": float, "bool": bool, "str": str,
        "sum": sum, "len": len, "map": map, "list": list,
    })
    return ns


def get_preconditions(key, all_settings, enable_ns):
    """
    Ermittelt, welche Overrides noetig sind, damit das `enabled`-Feld des
    Settings True ergibt.

    Rueckgabe:
      None  -> permanent deaktiviert (enabled=False, Literal) -> ueberspringen
      {}    -> kein Ausdruck oder bereits aktiv mit Defaults
      {k:v} -> notwendige Overrides als String-Dict
    """
    spec = all_settings.get(key, {})
    enabled = spec.get("enabled", True)

    # Permanent deaktiviert
    if enabled is False or str(enabled).strip() == "False":
        return None

    # Immer aktiv
    if enabled is True or str(enabled).strip() == "True":
        return {}

    expr = str(enabled)
    try:
        result = eval(expr, {"__builtins__": {}}, enable_ns)
        if result:
            return {}
    except Exception:
        return {}  # nicht auswertbar -> trotzdem testen

    preconditions = {}

    # Muster 1: setting == 'enum_wert'  (z.B. z_seam_type == 'back')
    for m in re.finditer(r"\b([a-z][a-z0-9_]*)\s*==\s*['\"]([^'\"]+)['\"]", expr):
        skey, sval = m.group(1), m.group(2)
        if skey in all_settings and skey != key:
            preconditions[skey] = sval

    # Muster 2: setting > 0  (numerisch, aktuell <= 0)
    for m in re.finditer(r"\b([a-z][a-z0-9_]*)\s*>\s*0\b", expr):
        skey = m.group(1)
        if skey not in all_settings or skey == key or skey in preconditions:
            continue
        aspec = all_settings[skey]
        if aspec.get("type") in ("float", "int"):
            try:
                if float(str(enable_ns.get(skey, 0))) <= 0:
                    preconditions[skey] = "1"
            except (TypeError, ValueError):
                preconditions[skey] = "1"

    # Muster 3: einfacher Bool-Token (nicht negiert)
    for m in re.finditer(r"\b([a-z][a-z0-9_]*)\b", expr):
        skey = m.group(1)
        if skey not in all_settings or skey == key or skey in preconditions:
            continue
        if skey in SKIP_PRECONDITIONS:
            continue
        aspec = all_settings[skey]
        if aspec.get("type") != "bool":
            continue
        start = m.start()
        prefix = expr[max(0, start - 4):start].strip()
        if prefix.endswith("not"):
            continue
        cur = enable_ns.get(skey)
        if not cur:
            preconditions[skey] = "true"

    # Muster 4: negierter Bool-Token (not skey) – wenn skey aktuell True ist,
    # muss er auf false gesetzt werden, damit das Setting aktiv wird.
    for m in re.finditer(r"\bnot\s+([a-z][a-z0-9_]*)\b", expr):
        skey = m.group(1)
        if skey not in all_settings or skey == key or skey in preconditions:
            continue
        if skey in SKIP_PRECONDITIONS:
            continue
        aspec = all_settings[skey]
        if aspec.get("type") != "bool":
            continue
        cur = enable_ns.get(skey)
        if cur:  # aktuell True -> fuer 'not skey' muss es False werden
            preconditions[skey] = "false"

    # Bool-Wert-Formel-Kaskade: Wenn wir einen bool Precondition setzen
    # (z.B. support_interface_enable=true), kaskadiert CuraEngine die
    # value-Formeln abhängiger bools NICHT automatisch ueber CLI. Wir
    # berechnen sie daher selbst und fuegen sie zu den Vorbedingungen hinzu.
    # Beispiel: support_interface_enable=true -> support_roof_enable=true
    # (da support_roof_enable.value = extruderValue(...,'support_interface_enable'))
    # Wichtig: nur Einstellungen hinzufuegen, deren Formel-Ergebnis sich durch
    # unsere Vorbedingungen AENDERT (nicht solche, die schon immer so waren).
    _cura_fns_base = {
        "__builtins__": {}, "math": math,
        "True": True, "False": False,
        "min": min, "max": max, "round": round, "abs": abs,
        "int": int, "float": float, "bool": bool, "str": str,
        "sum": sum, "len": len, "map": map, "list": list,
    }

    def _make_eval_ns(ns_dict):
        fn = dict(_cura_fns_base)
        fn.update(ns_dict)
        fn["extruderValue"]           = lambda nr, k, _d=ns_dict: _d.get(k, False)
        fn["resolveOrValue"]          = lambda k, _d=ns_dict: _d.get(k, False)
        fn["extruderValues"]          = lambda k, _d=ns_dict: [_d.get(k, False)]
        fn["defaultExtruderPosition"] = lambda: 0
        fn["anyExtruder"]             = lambda nr, k, _d=ns_dict: _d.get(k, False)
        fn["valueFromContainer"]      = lambda *a: False
        return fn

    # Basis-Namespace (ohne unsere Vorbedingungen) zum Vergleich
    base_fn_ns = _make_eval_ns(enable_ns)
    # Namespace MIT unseren Vorbedingungen
    prec_ns = dict(enable_ns)
    for pk, pv in preconditions.items():
        prec_ns[pk] = (pv.lower() == "true") if pv in ("true", "false") else pv

    changed = True
    while changed:
        changed = False
        prec_fn_ns = _make_eval_ns(prec_ns)
        for sk, spec in all_settings.items():
            if sk in preconditions or sk == key:
                continue
            if spec.get("type") != "bool":
                continue
            value_formula = spec.get("value")
            if not value_formula:
                continue
            try:
                base_res = eval(str(value_formula), {"__builtins__": {}}, base_fn_ns)
                test_res = eval(str(value_formula), {"__builtins__": {}}, prec_fn_ns)
                if not isinstance(test_res, bool) or not isinstance(base_res, bool):
                    continue
                # Nur hinzufuegen wenn die Vorbedingungen das Ergebnis AENDERN
                if test_res != base_res:
                    pv_str = "true" if test_res else "false"
                    preconditions[sk] = pv_str
                    prec_ns[sk] = test_res
                    changed = True
            except Exception:
                pass

    return preconditions


# --------------------------------------------------------------------------- #
# CuraEngine-Aufruf
# --------------------------------------------------------------------------- #

def build_args(model, out_path, overrides, verbose=False, definition=None):
    # Hinweis: KEINE '-m'-Thread-Option. '-m <n>' (zwei Tokens) bringt
    # CuraEngine 5.8 zum Absturz; Default-Threading ist am schnellsten.
    defn = definition if definition is not None else DEFINITION
    args = [ENGINE, "slice"]
    if verbose:
        args.append("-v")
    args += ["-j", defn]
    for k, v in overrides.items():
        args += ["-s", f"{k}={v}"]
    args += ["-e0", "-l", model, "-o", out_path]
    return args


def run_slice(model, out_path, overrides, verbose=False, definition=None):
    """Fuehrt einen Slice aus. Rueckgabe (ok, stderr, elapsed)."""
    if os.path.exists(out_path):
        os.remove(out_path)
    args = build_args(model, out_path, overrides, verbose=verbose, definition=definition)
    t0 = time.time()
    try:
        proc = subprocess.run(args, env=env_with_search_path(),
                              capture_output=True, text=True,
                              timeout=SLICE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", time.time() - t0
    elapsed = time.time() - t0
    ok = (proc.returncode == 0 and os.path.exists(out_path)
          and os.path.getsize(out_path) > 0)
    # CuraEngine-Logs koennen je nach Build in stdout oder stderr landen.
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return ok, output, elapsed


def parse_resolved_defaults(stderr):
    """Aufgeloeste Default-Werte aus der 'All settings:'-Zeile (Verbose-Log)."""
    resolved = {}
    for key, val in re.findall(r'-s (\w+)="([^"]*)"', stderr):
        if key not in resolved:
            resolved[key] = val
    return resolved


# --------------------------------------------------------------------------- #
# Robuste Kennzahlen aus dem G-Code
# --------------------------------------------------------------------------- #

def extract_features(path):
    """
    Reihenfolge-unabhaengige Kennzahlen eines G-Codes. Travel-Distanz wird
    nur informativ ermittelt (zu verrauscht fuer die Entscheidung).
    Abschnitts-spezifische Metriken (support_moves, skin_moves usw.) ermoeglichen
    den Nachweis von Aenderungen, die sich global gegenseitig aufheben.
    """
    absE = True
    prevE = 0.0
    filament = 0.0
    extr_dist = 0.0
    travel_dist = 0.0
    extr_moves = 0
    time_total = 0.0
    layers = 0
    F = 1200.0
    x = y = None
    max_temp = 0.0
    max_bed = 0.0
    max_fan = 0.0
    # Seam-Position: erstes extrudierendes G1 pro WALL-OUTER-Abschnitt
    current_section = ""
    in_wall_outer = False
    wall_outer_captured = False
    wall_outer_xs = []
    wall_outer_ys = []
    # Sektions-spezifische Zaehler
    sec_moves = {
        "SUPPORT": 0, "SUPPORT-INTERFACE": 0,
        "SKIN": 0, "FILL": 0, "WALL-OUTER": 0, "WALL-INNER": 0,
    }

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(";LAYER:"):
                layers += 1
                continue
            if line.startswith(";TYPE:"):
                current_section = line.strip()[6:]
                in_wall_outer = (current_section == "WALL-OUTER")
                wall_outer_captured = False
                continue
            if line.startswith(";"):
                continue
            cmd = line.split(";", 1)[0].strip()
            if not cmd:
                continue
            parts = cmd.split()
            code = parts[0]
            if code == "M82":
                absE = True
            elif code == "M83":
                absE = False
            elif code == "G92":
                for p in parts[1:]:
                    if p[:1] == "E":
                        try: prevE = float(p[1:])
                        except ValueError: pass
            elif code in ("M104", "M109"):
                for p in parts[1:]:
                    if p[:1] == "S":
                        try: max_temp = max(max_temp, float(p[1:]))
                        except ValueError: pass
            elif code in ("M140", "M190"):
                for p in parts[1:]:
                    if p[:1] == "S":
                        try: max_bed = max(max_bed, float(p[1:]))
                        except ValueError: pass
            elif code == "M106":
                for p in parts[1:]:
                    if p[:1] == "S":
                        try: max_fan = max(max_fan, float(p[1:]))
                        except ValueError: pass
            elif code in ("G0", "G1"):
                nx, ny, e_val, has_e = x, y, None, False
                for p in parts[1:]:
                    k = p[:1]
                    try: v = float(p[1:])
                    except ValueError: continue
                    if k == "X": nx = v
                    elif k == "Y": ny = v
                    elif k == "E": e_val = v; has_e = True
                    elif k == "F": F = v
                d = 0.0
                if None not in (x, y, nx, ny):
                    d = math.hypot(nx - x, ny - y)
                extruding = False
                if has_e:
                    de = (e_val - prevE) if absE else e_val
                    if de > 1e-9:
                        filament += de
                        extruding = True
                    if absE:
                        prevE = e_val
                if d > 0 and F > 0:
                    time_total += d / (F / 60.0)
                if extruding and d > 0:
                    extr_dist += d
                    extr_moves += 1
                    if current_section in sec_moves:
                        sec_moves[current_section] += 1
                    if in_wall_outer and not wall_outer_captured and nx is not None and ny is not None:
                        wall_outer_xs.append(nx)
                        wall_outer_ys.append(ny)
                        wall_outer_captured = True
                elif d > 0:
                    travel_dist += d
                if nx is not None: x = nx
                if ny is not None: y = ny

    wall_x = statistics.mean(wall_outer_xs) if wall_outer_xs else 0.0
    wall_y = statistics.mean(wall_outer_ys) if wall_outer_ys else 0.0
    return {
        "layers": layers,
        "filament": round(filament, 4),
        "extr_dist": round(extr_dist, 3),
        "extr_moves": extr_moves,
        "wall_start_x": round(wall_x, 3),
        "wall_start_y": round(wall_y, 3),
        # Sektions-spezifische Metriken
        "support_moves":      sec_moves["SUPPORT"],
        "support_intf_moves": sec_moves["SUPPORT-INTERFACE"],
        "skin_moves":         sec_moves["SKIN"],
        "fill_moves":         sec_moves["FILL"],
        "wall_moves":         sec_moves["WALL-OUTER"] + sec_moves["WALL-INNER"],
        # Informativ (nicht fuer Entscheidung)
        "time_s": round(time_total, 3),
        "max_temp": max_temp,
        "max_bed": max_bed,
        "max_fan": max_fan,
        "travel_dist": round(travel_dist, 2),
    }


def calibrate(baseline_feats):
    """Referenzwerte (Median) und Toleranzen aus mehreren Baseline-Laeufen."""
    ref, tol = {}, {}
    for f in DECISION_FEATURES:
        vals = [bf[f] for bf in baseline_feats]
        ref[f] = statistics.median(vals)
        span = max(vals) - min(vals)
        tol[f] = max(2.0 * span, DECISION_FLOORS[f])
    return ref, tol


def patch_filament_comment(path, filament_mm):
    """Ersetzt ';Filament used: 0m' im G-Code-Header durch den berechneten Wert."""
    filament_m = filament_mm / 1000.0
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        patched = content.replace(
            ";Filament used: 0m",
            f";Filament used: {filament_m:.4f}m"
        )
        if patched != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(patched)
    except OSError:
        pass


def eval_limit(expr, ns):
    """Wertebereichs-Ausdruck aus der JSON-Definition auswerten (z.B. '89', 'support_tree_angle')."""
    if expr is None:
        return None
    if isinstance(expr, (int, float)):
        return float(expr)
    try:
        return float(eval(str(expr), {"__builtins__": {}}, ns))
    except Exception:
        return None


def compare(feat, ref, tol):
    """Liste der Kennzahlen, die ueber die Toleranz hinaus abweichen."""
    changed = []
    for f in DECISION_FEATURES:
        if abs(feat[f] - ref[f]) > tol[f]:
            changed.append(f)
    return changed


def verify_change(model, overrides, first_feat, ref, tol, definition=None):
    """
    Bestaetigt einen "Veraenderung"-Treffer durch Nachslicen. Gibt die Liste
    der Kennzahlen zurueck, deren Abweichung reproduzierbar (Median ueber alle
    Laeufe) ueber der Toleranz liegt -> robust gegen das Engine-Rauschen.
    """
    feats = [first_feat]
    verify_path = os.path.join(GCODE_DIR, "_verify.gcode")
    for _ in range(VERIFY_RUNS):
        ok, _, _ = run_slice(model, verify_path, overrides, definition=definition)
        if ok:
            feats.append(extract_features(verify_path))
    if os.path.exists(verify_path):
        os.remove(verify_path)
    confirmed = []
    for f in DECISION_FEATURES:
        devs = [abs(ff[f] - ref[f]) for ff in feats]
        if statistics.median(devs) > tol[f]:
            confirmed.append(f)
    return confirmed


# --------------------------------------------------------------------------- #
# Ausgabe (Excel / CSV)
# --------------------------------------------------------------------------- #

def _save_with_fallback(save_fn, path):
    """Speichert via save_fn(path). Ist die Datei gesperrt (in Excel offen),
    wird auf einen Zeitstempel-Namen ausgewichen, statt abzubrechen."""
    try:
        save_fn(path)
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        alt = f"{base}_{time.strftime('%Y%m%d_%H%M%S')}{ext}"
        save_fn(alt)
        print(f"  WARNUNG: {os.path.basename(path)} ist gesperrt "
              f"(in Excel offen?). Gespeichert als {os.path.basename(alt)}.",
              file=sys.stderr)
        return alt


def write_excel(rows, meta, ref, tol):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ergebnisse"

    headers = ["Kategorie", "Setting (Key)", "Bezeichnung", "Typ",
               "Default-Wert", "Testwert (3x / Ersatz)", "Status",
               "Geaenderte Metriken", "G-Code-Datei", "Slice-Zeit (s)"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="404040")
        c.alignment = Alignment(horizontal="center")

    fills = {
        "Veraenderung":              PatternFill("solid", fgColor="C6EFCE"),
        "keine Veraenderung":        PatternFill("solid", fgColor="F2F2F2"),
        "nicht testbar (Default 0)": PatternFill("solid", fgColor="FFF2CC"),
        "Fehler/Timeout":            PatternFill("solid", fgColor="FFC7CE"),
        "Permanent deaktiviert":     PatternFill("solid", fgColor="D9D9D9"),
    }

    for r in rows:
        ws.append([r["category"], r["key"], r["label"], r["type"],
                   r["default"], r["tripled"], r["status"],
                   r["changed"], r["gcode_file"], r["elapsed"]])
        fill = fills.get(r["status"])
        if fill:
            ws.cell(row=ws.max_row, column=7).fill = fill

    widths = [22, 32, 40, 6, 14, 22, 24, 32, 26, 13]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # Zusammenfassung
    ws2 = wb.create_sheet("Zusammenfassung")
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    info = [
        ("Drucker", "Creality Ender-3"),
        ("Material", "PLA (Definition-Default 210 C / Bett 60 C)"),
        ("Duese", "0.4 mm"),
        ("Qualitaet", "Standard Quality (Layer Height 0.2 mm)"),
        ("Modell (STL)", os.path.basename(meta["model"])),
        ("CuraEngine", meta["engine_version"]),
        ("Vergleichsmethode", "robuste G-Code-Kennzahlen mit kalibrierter Toleranz"),
        ("Baseline-Kalibrierlaeufe", meta["calib_runs"]),
        ("Getestete Settings gesamt", len(rows)),
        ("", ""),
        ("Status", "Anzahl"),
        ("Veraenderung", counts.get("Veraenderung", 0)),
        ("keine Veraenderung", counts.get("keine Veraenderung", 0)),
        ("Fehler/Timeout", counts.get("Fehler/Timeout", 0)),
        ("Ersatzwert bei Default 0",
         f"int -> {SUBSTITUTE_INT}, float -> {SUBSTITUTE_FLOAT}"),
        ("", ""),
        ("Kennzahl", "Baseline-Referenz / Toleranz (+/-)"),
    ]
    for k, v in info:
        ws2.append([k, v])
    for f in DECISION_FEATURES:
        ws2.append([FEATURE_LABELS[f], f"{ref[f]}  /  {round(tol[f], 4)}"])
    ws2["A1"].font = Font(bold=True)
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 50

    return _save_with_fallback(wb.save, EXCEL_PATH)


def write_csv(rows):
    import csv

    def save_fn(path):
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["Kategorie", "Setting", "Bezeichnung", "Typ", "Default",
                        "Testwert (3x / Ersatz)", "Status", "Geaenderte Metriken",
                        "G-Code-Datei", "Slice-Zeit (s)"])
            for r in rows:
                w.writerow([r["category"], r["key"], r["label"], r["type"],
                            r["default"], r["tripled"], r["status"],
                            r["changed"], r["gcode_file"], r["elapsed"]])

    return _save_with_fallback(save_fn, CSV_PATH)


# --------------------------------------------------------------------------- #
# Hilfen fuer Zahlenformatierung
# --------------------------------------------------------------------------- #

def to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_number(value, stype):
    if stype == "int" and float(value).is_integer():
        return str(int(round(value)))
    return repr(round(value, 6))


# --------------------------------------------------------------------------- #
# Hauptablauf
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Cura Print-Setting-Sweep")
    ap.add_argument("--limit", type=int, default=0,
                    help="Nur die ersten N Settings testen (0 = alle)")
    ap.add_argument("--only", type=str, default="",
                    help="Kommagetrennte Liste konkreter Setting-Keys")
    ap.add_argument("--list", action="store_true",
                    help="Settings nur auflisten, nicht slicen")
    ap.add_argument("--calib", type=int, default=CALIB_RUNS,
                    help="Anzahl Baseline-Kalibrierlaeufe (Default %d)" % CALIB_RUNS)
    ap.add_argument("--no-cascade", action="store_true",
                    help="Formel-Kaskadierung deaktivieren (altes Verhalten)")
    args = ap.parse_args()

    check_environment()
    os.makedirs(GCODE_DIR, exist_ok=True)

    # Abhaengigkeitsgraph und alle Settings fuer Kaskadierung + Vorbedingungen
    print("Abhaengigkeitsgraph wird geladen ...")
    all_settings_map = collect_all_settings()
    if not args.no_cascade:
        dep_graph = build_dep_graph(all_settings_map)
    else:
        dep_graph = {}

    settings = collect_settings()
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        settings = [s for s in settings if s["key"] in wanted]
    if args.limit > 0:
        settings = settings[:args.limit]

    print(f"{len(settings)} numerische Print Settings gefunden.")
    if args.list:
        for s in settings:
            print(f"  [{s['category']:>20}] {s['key']:<34} "
                  f"({s['type']}) default={s['json_default']}")
        return

    model = find_model()
    print(f"Modell: {os.path.basename(model)}")
    quality = load_quality_overrides()
    print(f"Standard-Quality-Overrides: {quality}")

    baseline_overrides = dict(FIXUP_OVERRIDES)
    baseline_overrides.update(quality)

    # ---- 1) Baseline mehrfach slicen (Defaults + Rausch-Kalibrierung) -------
    n_calib = max(2, args.calib)
    print(f"\nBaseline wird {n_calib}x gesliced (Defaults + Rausch-Kalibrierung) ...")
    baseline_feats = []
    resolved = {}
    engine_version = "5.8.0"
    for i in range(n_calib):
        out = os.path.join(GCODE_DIR, "_baseline.gcode" if i == 0
                           else f"_baseline_calib{i}.gcode")
        ok, stderr, el = run_slice(model, out, baseline_overrides,
                                   verbose=(i == 0))
        if not ok:
            print(stderr[-2000:], file=sys.stderr)
            fail(f"Baseline-Slice #{i} fehlgeschlagen.")
        if i == 0:
            resolved = parse_resolved_defaults(stderr)
            m = re.search(r"Cura_SteamEngine (?:version )?([\d.]+)", stderr)
            if m:
                engine_version = m.group(1)
        baseline_feats.append(extract_features(out))
        print(f"  Baseline #{i}: {baseline_feats[-1]['layers']} Layer, "
              f"Filament {baseline_feats[-1]['filament']} mm ({el:.1f}s)")

    ref, tol = calibrate(baseline_feats)
    print(f"\nKalibriert ({len(resolved)} Default-Werte gelesen).")
    print("Referenz/Toleranz:")
    for f in DECISION_FEATURES:
        print(f"  {FEATURE_LABELS[f]:20} ref={ref[f]:<12} tol=+/-{round(tol[f],4)}")

    # Namespace fuer enabled-Ausdruecke (Vorbedingungen)
    enable_ns = build_enable_ns(all_settings_map, resolved)

    # Settings, die nur mit Dual-Extruder-Drucker testbar sind
    dual_settings = build_dual_extruder_settings(all_settings_map)

    # Feature-Baseline-Cache: (merged_overrides_key) -> (ref, tol)
    _feat_baseline_cache = {}

    def get_feature_baseline(preconditions_dict, dual_ctx=None):
        """Kalibriert eine Baseline mit gesetzten Vorbedingungen (gecacht).
        dual_ctx: zusaetzliche Dual-Extruder-Overrides (DEFINITION_DUAL wird verwendet).
        """
        if dual_ctx is None:
            dual_ctx = {}
        merged = {**preconditions_dict, **dual_ctx}
        cache_key = tuple(sorted(merged.items()))
        if cache_key in _feat_baseline_cache:
            return _feat_baseline_cache[cache_key]
        feat_overrides = dict(baseline_overrides)
        feat_overrides.update(merged)
        defn = DEFINITION_DUAL if dual_ctx else None
        mini = max(2, n_calib // 2)
        feats = []
        tmp = os.path.join(GCODE_DIR, "_feat_baseline.gcode")
        prec_str = ", ".join(f"{k}={v}" for k, v in sorted(merged.items()))
        print(f"\n  [Feature-Baseline] {prec_str} ({mini} Laeufe) ...")
        for _ in range(mini):
            ok2, _, _ = run_slice(model, tmp, feat_overrides, definition=defn)
            if ok2:
                feats.append(extract_features(tmp))
        if os.path.exists(tmp):
            os.remove(tmp)
        if feats:
            f_ref, f_tol = calibrate(feats)
            print(f"  [Feature-Baseline] kalibriert.")
            _feat_baseline_cache[cache_key] = (f_ref, f_tol)
            return f_ref, f_tol
        _feat_baseline_cache[cache_key] = (None, None)
        return None, None

    # ---- 2) Sweep -----------------------------------------------------------
    rows = []
    for idx, s in enumerate(settings, start=1):
        key = s["key"]
        raw_default = resolved.get(key, s["json_default"])
        num = to_number(raw_default)
        row = {"category": s["category"], "key": key, "label": s["label"],
               "type": s["type"], "default": raw_default, "tripled": "",
               "status": "", "changed": "", "gcode_file": "", "elapsed": ""}

        # Vorbedingungen des Settings pruefen (enabled-Ausdruck)
        preconditions = get_preconditions(key, all_settings_map, enable_ns)
        if preconditions is None:
            # Permanent deaktiviert (enabled=False literal)
            row["default"] = str(raw_default)
            row["status"] = "Permanent deaktiviert"
            rows.append(row)
            print(f"[{idx}/{len(settings)}] {key}: Permanent deaktiviert")
            continue

        # Dual-Extruder-Kontext (leer fuer Single-Extruder-Settings)
        is_dual = key in dual_settings
        dual_ctx = get_dual_context(key) if is_dual else {}

        # ---- Enum-Branch: ALLE nicht-Standard-Optionen testen -----------------
        if s["type"] == "enum":
            default_val = str(raw_default) if raw_default is not None else ""
            options = s.get("options", [])
            non_default = [o for o in options if o != default_val]
            row["default"] = default_val

            if not non_default:
                row["status"] = "keine Veraenderung"
                row["tripled"] = "(nur eine Option)"
                rows.append(row)
                print(f"[{idx}/{len(settings)}] {key}: nur eine Option -> uebersprungen")
                continue

            # Feature-Baseline fuer Vorbedingungen (gleiche Logik wie numeric branch)
            if preconditions or dual_ctx:
                use_ref, use_tol = get_feature_baseline(preconditions, dual_ctx)
                if use_ref is None:
                    row["status"] = "Fehler/Timeout"
                    rows.append(row)
                    print(f"[{idx}/{len(settings)}] {key}: Feature-Baseline fehlgeschlagen")
                    continue
            else:
                use_ref, use_tol = ref, tol

            # Jede Option einzeln testen; Ergebnis mit Haekchen markieren:
            #   "opt+" = Veraenderung  |  "opt-" = keine Veraenderung  |  "opt?" = Fehler
            all_changed_metrics = []   # vereinigte Metriken ueber alle aendernden Optionen
            last_el      = 0.0
            last_gcode   = ""          # G-Code der ersten Option mit Veraenderung
            n_cascaded   = 0
            result_parts = []          # Anzeigestrings fuer Testwert-Spalte

            for opt in non_default:
                ovr = dict(baseline_overrides)
                for pk, pv in preconditions.items():
                    ovr[pk] = pv
                for dk, dv in dual_ctx.items():
                    if dk not in ovr:
                        ovr[dk] = dv
                ovr[key] = opt

                n_c = 0
                if not args.no_cascade and dep_graph:
                    extra = cascade_overrides(
                        key, opt, all_settings_map, resolved, dep_graph)
                    for ck, cv in extra.items():
                        if (ck not in baseline_overrides or ck in preconditions) \
                                and ck not in preconditions:
                            ovr[ck] = cv
                            n_c += 1
                n_cascaded = max(n_cascaded, n_c)

                out_path = os.path.join(GCODE_DIR, f"{key}_{opt}.gcode")
                ok2, _, el = run_slice(model, out_path, ovr,
                                       definition=DEFINITION_DUAL if is_dual else None)
                last_el = el

                if not ok2:
                    result_parts.append(f"{opt}?")
                    continue

                feat = extract_features(out_path)
                patch_filament_comment(out_path, feat["filament"])
                changed = compare(feat, use_ref, use_tol)
                if changed and VERIFY_RUNS > 0:
                    changed = verify_change(model, ovr, feat, use_ref, use_tol,
                                            definition=DEFINITION_DUAL if is_dual else None)

                if changed:
                    result_parts.append(f"{opt}+")
                    for m in changed:
                        if m not in all_changed_metrics:
                            all_changed_metrics.append(m)
                    if not last_gcode:
                        last_gcode = os.path.relpath(out_path, PROJ)
                else:
                    result_parts.append(f"{opt}-")

            prec_note = (" [" + ", ".join(
                f"{k}={v}" for k, v in sorted(preconditions.items())) + "]"
                         if preconditions else "")
            cascade_note = f" +{n_cascaded} kask." if n_cascaded else ""
            row["tripled"] = " / ".join(result_parts) + cascade_note + prec_note
            row["elapsed"] = round(last_el, 2)
            row["gcode_file"] = last_gcode

            if all_changed_metrics:
                row["status"] = "Veraenderung"
                row["changed"] = ", ".join(FEATURE_LABELS[m]
                                           for m in all_changed_metrics)
            else:
                row["status"] = "keine Veraenderung"

            print(f"[{idx}/{len(settings)}] {key}: {row['status']} "
                  f"({default_val} -> {row['tripled']}; "
                  f"{row['changed'] or '-'}; {last_el:.1f}s)")
            rows.append(row)
            continue
        # ---- Ende Enum-Branch -----------------------------------------------

        # ---- Bool-Branch: Checkbox umschalten (true <-> false) --------------
        if s["type"] == "bool":
            # Default-Wert ermitteln (CuraEngine liefert Strings "true"/"false")
            if isinstance(raw_default, bool):
                default_bool = raw_default
            else:
                default_bool = str(raw_default).lower() == "true"
            test_bool = not default_bool
            test_str  = "true" if test_bool else "false"
            row["default"] = "true" if default_bool else "false"

            # Feature-Baseline fuer Vorbedingungen
            if preconditions or dual_ctx:
                use_ref, use_tol = get_feature_baseline(preconditions, dual_ctx)
                if use_ref is None:
                    row["status"] = "Fehler/Timeout"
                    rows.append(row)
                    print(f"[{idx}/{len(settings)}] {key}: Feature-Baseline "
                          "fehlgeschlagen")
                    continue
            else:
                use_ref, use_tol = ref, tol

            # Overrides aufbauen
            overrides = dict(baseline_overrides)
            for pk, pv in preconditions.items():
                overrides[pk] = pv
            for dk, dv in dual_ctx.items():
                if dk not in overrides:
                    overrides[dk] = dv
            overrides[key] = test_str

            # Numerische Abhaengigkeiten kaskadieren
            n_cascaded = 0
            if not args.no_cascade and dep_graph:
                extra = cascade_overrides(
                    key, test_bool, all_settings_map, resolved, dep_graph)
                for ck, cv in extra.items():
                    if ck not in baseline_overrides or ck in preconditions:
                        if ck not in preconditions:
                            overrides[ck] = cv
                            n_cascaded += 1

            # Bool-Abhaengigkeiten kaskadieren: CuraEngine kaskadiert bool-
            # value-Formeln via CLI NICHT automatisch (z.B. support_interface_enable=true
            # kaskadiert nicht zu support_roof_enable=true via Formel, obwohl
            # support_roof_enable.value = extruderValue(...,'support_interface_enable')).
            if not args.no_cascade:
                _test_ns = dict(enable_ns)
                for pk, pv in preconditions.items():
                    _test_ns[pk] = (pv.lower() == "true") if pv in ("true","false") else pv
                _test_ns[key] = test_bool

                def _mk_fns(d):
                    fn = {"__builtins__": {}, "math": math, "True": True, "False": False,
                          "min": min, "max": max, "round": round, "abs": abs,
                          "int": int, "float": float, "bool": bool, "str": str,
                          "sum": sum, "len": len, "map": map, "list": list}
                    fn.update(d)
                    fn["extruderValue"]           = lambda nr, k, _d=d: _d.get(k, False)
                    fn["resolveOrValue"]          = lambda k, _d=d: _d.get(k, False)
                    fn["extruderValues"]          = lambda k, _d=d: [_d.get(k, False)]
                    fn["defaultExtruderPosition"] = lambda: 0
                    fn["anyExtruder"]             = lambda nr, k, _d=d: _d.get(k, False)
                    fn["valueFromContainer"]      = lambda *a: False
                    return fn

                _base_fns = _mk_fns(enable_ns)
                _bc_changed = True
                while _bc_changed:
                    _bc_changed = False
                    _test_fns = _mk_fns(_test_ns)
                    for sk, spec2 in all_settings_map.items():
                        if sk in overrides or sk == key:
                            continue
                        if spec2.get("type") != "bool":
                            continue
                        vf = spec2.get("value")
                        if not vf:
                            continue
                        try:
                            br = eval(str(vf), {"__builtins__": {}}, _base_fns)
                            tr = eval(str(vf), {"__builtins__": {}}, _test_fns)
                            if isinstance(tr, bool) and isinstance(br, bool) and tr != br:
                                overrides[sk] = "true" if tr else "false"
                                _test_ns[sk] = tr
                                n_cascaded += 1
                                _bc_changed = True
                        except Exception:
                            pass

            prec_note = (" [" + ", ".join(
                f"{k}={v}" for k, v in sorted(preconditions.items())) + "]"
                         if preconditions else "")
            cascade_note = f" +{n_cascaded} kask." if n_cascaded else ""
            row["tripled"] = test_str + cascade_note + prec_note

            out_path = os.path.join(GCODE_DIR, f"{key}.gcode")
            ok, _, el = run_slice(model, out_path, overrides,
                                  definition=DEFINITION_DUAL if is_dual else None)
            row["elapsed"] = round(el, 2)

            if not ok:
                row["status"] = "Fehler/Timeout"
                print(f"[{idx}/{len(settings)}] {key}: FEHLER/TIMEOUT")
                rows.append(row)
                continue

            row["gcode_file"] = os.path.relpath(out_path, PROJ)
            feat = extract_features(out_path)
            patch_filament_comment(out_path, feat["filament"])
            changed = compare(feat, use_ref, use_tol)
            if changed and VERIFY_RUNS > 0:
                changed = verify_change(model, overrides, feat, use_ref, use_tol,
                                        definition=DEFINITION_DUAL if is_dual else None)
            if changed:
                row["status"] = "Veraenderung"
                row["changed"] = ", ".join(FEATURE_LABELS[c] for c in changed)
            else:
                row["status"] = "keine Veraenderung"
            print(f"[{idx}/{len(settings)}] {key}: {row['status']} "
                  f"({'true' if default_bool else 'false'} -> {row['tripled']}; "
                  f"{row['changed'] or '-'}; {el:.1f}s)")
            rows.append(row)
            continue
        # ---- Ende Bool-Branch -----------------------------------------------

        # ---- [int]-Branch: Winkel-/Faktor-Listen (z.B. infill_angles) -------
        if s["type"] == "[int]":
            # Default parsen: entweder Python-Liste aus JSON oder String von CuraEngine
            raw = raw_default
            if isinstance(raw, list):
                default_list = raw
            else:
                try:
                    import ast
                    default_list = ast.literal_eval(str(raw)) if raw else []
                except Exception:
                    default_list = []

            # Testwert: leere Liste -> [45] (Winkelversatz); sonst erstes Element / 2
            if not default_list:
                test_list = [45]
            else:
                test_list = [max(1, int(default_list[0] * 0.5))]

            row["default"] = str(default_list)
            test_str = str(test_list)   # z.B. "[45]" oder "[50]"

            # Feature-Baseline fuer Vorbedingungen
            if preconditions or dual_ctx:
                use_ref, use_tol = get_feature_baseline(preconditions, dual_ctx)
                if use_ref is None:
                    row["status"] = "Fehler/Timeout"
                    rows.append(row)
                    print(f"[{idx}/{len(settings)}] {key}: Feature-Baseline "
                          "fehlgeschlagen")
                    continue
            else:
                use_ref, use_tol = ref, tol

            # Overrides aufbauen
            overrides = dict(baseline_overrides)
            for pk, pv in preconditions.items():
                overrides[pk] = pv
            for dk, dv in dual_ctx.items():
                if dk not in overrides:
                    overrides[dk] = dv
            overrides[key] = test_str

            n_cascaded = 0
            if not args.no_cascade and dep_graph:
                extra = cascade_overrides(
                    key, test_list, all_settings_map, resolved, dep_graph)
                for ck, cv in extra.items():
                    if ck not in baseline_overrides or ck in preconditions:
                        if ck not in preconditions:
                            overrides[ck] = cv
                            n_cascaded += 1

            prec_note = (" [" + ", ".join(
                f"{k}={v}" for k, v in sorted(preconditions.items())) + "]"
                         if preconditions else "")
            cascade_note = f" +{n_cascaded} kask." if n_cascaded else ""
            row["tripled"] = test_str + cascade_note + prec_note

            out_path = os.path.join(GCODE_DIR, f"{key}.gcode")
            ok, _, el = run_slice(model, out_path, overrides,
                                  definition=DEFINITION_DUAL if is_dual else None)
            row["elapsed"] = round(el, 2)

            if not ok:
                row["status"] = "Fehler/Timeout"
                print(f"[{idx}/{len(settings)}] {key}: FEHLER/TIMEOUT")
                rows.append(row)
                continue

            row["gcode_file"] = os.path.relpath(out_path, PROJ)
            feat = extract_features(out_path)
            patch_filament_comment(out_path, feat["filament"])
            changed = compare(feat, use_ref, use_tol)
            if changed and VERIFY_RUNS > 0:
                changed = verify_change(model, overrides, feat, use_ref, use_tol,
                                        definition=DEFINITION_DUAL if is_dual else None)
            if changed:
                row["status"] = "Veraenderung"
                row["changed"] = ", ".join(FEATURE_LABELS[c] for c in changed)
            else:
                row["status"] = "keine Veraenderung"
            print(f"[{idx}/{len(settings)}] {key}: {row['status']} "
                  f"({row['default']} -> {row['tripled']}; "
                  f"{row['changed'] or '-'}; {el:.1f}s)")
            rows.append(row)
            continue
        # ---- Ende [int]-Branch ----------------------------------------------

        if num is None:
            row["status"] = "Fehler/Timeout"
            row["default"] = f"{raw_default} (nicht numerisch)"
            rows.append(row)
            print(f"[{idx}/{len(settings)}] {key}: nicht numerisch -> uebersprungen")
            continue

        row["default"] = format_number(num, s["type"])

        # ---- Wertbereichs-Grenzen aus der JSON-Definition auslesen -----------
        # Vorbedingungen in den Auswerte-Namespace einbauen, damit Ausdruecke
        # wie 'max = support_tree_angle' korrekt aufgeloest werden.
        ev_ns = dict(enable_ns)
        for pk, pv in preconditions.items():
            try:    ev_ns[pk] = float(pv)
            except: ev_ns[pk] = pv

        max_lim = eval_limit(s.get("maximum_value"), ev_ns)
        min_lim = eval_limit(s.get("minimum_value"), ev_ns)
        # maximum_value_warning wird NICHT als Obergrenze verwendet – der Nutzer
        # will alle sichtbaren Aenderungen sehen, auch bei technisch unueblichen Werten.
        # Nur maximum_value (Hard-Limit von CuraEngine) wird respektiert.

        def _clamp(v):
            if max_lim is not None: v = min(v, max_lim)
            if min_lim is not None: v = max(v, min_lim)
            return v

        # ---- Kandidaten-Testwerte (10x, 5x, 3x, 2x, 1.5x – ohne Soft-Cap) --
        if num == 0:
            candidates = [(SUBSTITUTE_INT if s["type"] == "int"
                           else SUBSTITUTE_FLOAT, True)]
        else:
            seen = set()
            candidates = []
            for mult in (10.0, 5.0, 3.0, 2.0, 1.5):
                cv = _clamp(num * mult)
                cv_r = round(cv, 9)
                if cv_r != round(num, 9) and cv_r not in seen:
                    seen.add(cv_r)
                    candidates.append((cv, False))
            # Nach oben kein Spielraum (z.B. Default=100 %, max=100 %)?
            # Dann nach unten testen: Halbierung, dann Minimum.
            if not candidates:
                for cv in (num * 0.5, min_lim if min_lim is not None else 0.0):
                    cv = _clamp(cv)
                    cv_r = round(cv, 9)
                    if cv_r != round(num, 9) and cv_r not in seen:
                        seen.add(cv_r)
                        candidates.append((cv, False))
            if not candidates:
                row["status"] = "nicht testbar (Wertebereich)"
                rows.append(row)
                print(f"[{idx}/{len(settings)}] {key}: Wertebereich zu eng -> "
                      "uebersprungen")
                continue

        # ---- Feature-Baseline (einmalig, vor dem Slice-Loop) ----------------
        if preconditions or dual_ctx:
            use_ref, use_tol = get_feature_baseline(preconditions, dual_ctx)
            if use_ref is None:
                row["status"] = "Fehler/Timeout"
                rows.append(row)
                print(f"[{idx}/{len(settings)}] {key}: Feature-Baseline "
                      "fehlgeschlagen")
                continue
        else:
            use_ref, use_tol = ref, tol

        # ---- Slice-Loop: Kandidaten der Reihe nach probieren ----------------
        out_path = os.path.join(GCODE_DIR, f"{key}.gcode")
        ok = False
        test_val = None
        substitute = False
        n_cascaded = 0
        overrides = {}
        el = 0.0
        failed_vals = []

        for cand_val, is_substitute in candidates:
            ovr = dict(baseline_overrides)
            for pk, pv in preconditions.items():
                ovr[pk] = pv
            for dk, dv in dual_ctx.items():
                if dk not in ovr:
                    ovr[dk] = dv
            ovr[key] = format_number(cand_val, s["type"])

            n_c = 0
            if not args.no_cascade and dep_graph:
                extra = cascade_overrides(
                    key, cand_val, all_settings_map, resolved, dep_graph)
                for ck, cv in extra.items():
                    if ck not in baseline_overrides or ck in preconditions:
                        if ck not in preconditions:
                            ovr[ck] = cv
                            n_c += 1

            ok2, _, el2 = run_slice(model, out_path, ovr,
                                    definition=DEFINITION_DUAL if is_dual else None)
            el = el2

            if ok2:
                ok = True
                test_val = cand_val
                substitute = is_substitute
                n_cascaded = n_c
                overrides = ovr
                break
            else:
                failed_vals.append(format_number(cand_val, s["type"]))
                if len(candidates) > 1:
                    print(f"  [Fallback] {key}: "
                          f"{format_number(cand_val, s['type'])} fehlgeschlagen"
                          f"{', naechster Kandidat ...' if cand_val != candidates[-1][0] else ''}")

        row["elapsed"] = round(el, 2)

        # ---- Labels fuer Ergebnis-Zeile -------------------------------------
        prec_note = (" [" + ", ".join(
            f"{k}={v}" for k, v in sorted(preconditions.items())) + "]"
                     if preconditions else "")
        cascade_note = f" +{n_cascaded} kask." if n_cascaded else ""
        fallback_note = (f" [nach Fallback; {', '.join(failed_vals)} fehlgeschl.]"
                         if failed_vals and ok else "")

        if ok:
            row["tripled"] = (format_number(test_val, s["type"])
                              + (" (Ersatz)" if substitute else "")
                              + cascade_note + fallback_note + prec_note)
        else:
            row["tripled"] = ("–" + f" [{', '.join(failed_vals)} alle fehlgeschl.]"
                              + prec_note)

        if not ok:
            row["status"] = "Fehler/Timeout"
            print(f"[{idx}/{len(settings)}] {key}: FEHLER/TIMEOUT "
                  f"(alle Kandidaten: {failed_vals})")
            rows.append(row)
            continue

        # ---- Metriken vergleichen -------------------------------------------
        row["gcode_file"] = os.path.relpath(out_path, PROJ)
        feat = extract_features(out_path)
        patch_filament_comment(out_path, feat["filament"])
        changed = compare(feat, use_ref, use_tol)
        if changed and VERIFY_RUNS > 0:
            changed = verify_change(model, overrides, feat, use_ref, use_tol,
                                    definition=DEFINITION_DUAL if is_dual else None)
        if changed:
            row["status"] = "Veraenderung"
            row["changed"] = ", ".join(FEATURE_LABELS[c] for c in changed)
        else:
            row["status"] = "keine Veraenderung"
        print(f"[{idx}/{len(settings)}] {key}: {row['status']} "
              f"({row['default']} -> {row['tripled']}; "
              f"{row['changed'] or '-'}; {el:.1f}s)")
        rows.append(row)

    # ---- 3) Ausgabe ---------------------------------------------------------
    meta = {"model": model, "engine_version": engine_version,
            "calib_runs": n_calib}
    excel_path = write_excel(rows, meta, ref, tol)
    csv_path = write_csv(rows)

    changed = sum(1 for r in rows if r["status"] == "Veraenderung")
    nochange = sum(1 for r in rows if r["status"] == "keine Veraenderung")
    print(f"\nFertig. {len(rows)} Settings: {changed} mit Einfluss, "
          f"{nochange} ohne Einfluss.")
    print(f"Excel:   {excel_path}")
    print(f"CSV:     {csv_path}")
    print(f"G-Codes: {GCODE_DIR}")


if __name__ == "__main__":
    main()
