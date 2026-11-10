# -*- coding: utf-8 -*-
"""
Determinismus-Test fuer CuraEngine (Beleg fuer Tabelle 4.5 der Bachelorarbeit).

Schneidet denselben Pruefkoerper (Slicer Test.stl) fuenfmal mit dem Standard-
Thread-Verhalten und einmal mit auf einen Kern beschraenkter Engine (-m1),
jeweils mit exakt identischen Einstellungen, und vergleicht die erzeugten
G-Code-Dateien: Pruefsumme, Anzahl abweichender Bewegungen, Betrag der
Positionsabweichung, betroffene Schichten, Filamentverbrauch.

Ergebnis-Dateien liegen nach dem Lauf in ./determinismus_test/run1.gcode .. run5.gcode
sowie run_m1.gcode (Einzelkern-Vergleichslauf).
"""
import hashlib
import math
import os
import platform
import re
import statistics
import subprocess

PROJ = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(PROJ, "determinismus_test")
MODEL = os.path.join(PROJ, "Slicer Test.stl")
N_RUNS = 5

if platform.system() == "Darwin":
    CURA_DIR = "/Applications/UltiMaker Cura.app/Contents/Resources"
    ENGINE = os.path.join(CURA_DIR, "CuraEngine")
    RES = os.path.join(CURA_DIR, "share", "cura", "resources")
    DEFS = os.path.join(RES, "definitions")
    EXTR = os.path.join(RES, "extruders")
else:
    raise SystemExit("Dieses Skript ist fuer macOS eingerichtet; Pfade fuer andere Systeme anpassen.")

# Dieselbe Maschinendefinition wie cura_setting_sweep.py (nicht fdmprinter.def.json
# direkt!), sonst greifen andere Vorgabewerte (u.a. material_diameter, Bauraum).
DEFINITION = os.path.join(DEFS, "creality_ender3.def.json")

# Dieselben Fixup-Overrides wie cura_setting_sweep.py (FIXUP_OVERRIDES),
# plus dieselben Standard-Quality-Werte (layer_height/layer_height_0 = 0.2),
# damit exakt derselbe Referenzlauf entsteht wie im Sweep (Tabelle 4.1).
OVERRIDES = {
    "roofing_layer_count": "0",
    "flooring_layer_count": "0",
    "support_z_seam_away_from_model": "false",
    "line_width": "0.4",
    "min_wall_line_width": "0.34",
    "support_extruder_nr": "0",
    "reset_flow_duration": "2.0",
    "brim_width": "8.0",
    "layer_height": "0.2",
    "layer_height_0": "0.2",
}


def run_slice(out_path, single_core=False):
    args = [ENGINE, "slice"]
    if single_core:
        args.append("-m1")
    args += ["-j", DEFINITION]
    for k, v in OVERRIDES.items():
        args += ["-s", f"{k}={v}"]
    args += ["-e0", "-s", "extruder_nr=0", "-l", MODEL, "-o", out_path]
    # CuraEngine braucht diesen Suchpfad, um die inherits-Kette von
    # creality_ender3.def.json zu creality_base.def.json/fdmprinter.def.json
    # aufzuloesen -- ohne ihn fallen material_diameter u.a. auf falsche
    # Werte zurueck (vgl. cura_setting_sweep.py: env_with_search_path()).
    env = dict(os.environ)
    env["CURA_ENGINE_SEARCH_PATH"] = DEFS + os.pathsep + EXTR
    subprocess.run(args, check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse(path):
    """Liefert (moves[(x,y)], layer_at_move_index[int], filament_mm, n_layers)."""
    moves = []
    layer_at = []
    absE = True
    prevE = 0.0
    fil = 0.0
    layer = -1
    x = y = None
    for line in open(path, errors="replace"):
        if line.startswith(";LAYER:"):
            layer = int(line.split(":")[1])
            continue
        if line.startswith(";"):
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        parts = code.split()
        if parts[0] == "M82":
            absE = True
        elif parts[0] == "M83":
            absE = False
        elif parts[0] == "G92":
            for p in parts[1:]:
                if p[:1] == "E":
                    try:
                        prevE = float(p[1:])
                    except ValueError:
                        pass
        elif parts[0] in ("G0", "G1"):
            nx, ny, ev = x, y, None
            for p in parts[1:]:
                if p[:1] == "X":
                    try:
                        nx = float(p[1:])
                    except ValueError:
                        pass
                elif p[:1] == "Y":
                    try:
                        ny = float(p[1:])
                    except ValueError:
                        pass
                elif p[:1] == "E":
                    try:
                        ev = float(p[1:])
                    except ValueError:
                        pass
            if ev is not None:
                de = (ev - prevE) if absE else ev
                if de > 1e-9:
                    fil += de
                if absE:
                    prevE = ev
            moves.append((nx, ny))
            layer_at.append(layer)
            x, y = nx, ny
    n_layers = layer + 1 if layer >= 0 else 0
    return moves, layer_at, fil, n_layers


def sha256_no_comments(path):
    h = hashlib.sha256()
    for line in open(path, "rb"):
        if not line.lstrip().startswith(b";"):
            h.update(line)
    return h.hexdigest()


def compare(path_a, path_b):
    mv_a, lay_a, fil_a, nlay_a = parse(path_a)
    mv_b, lay_b, fil_b, nlay_b = parse(path_b)
    same_len = len(mv_a) == len(mv_b)
    diffs = []
    diff_layers = set()
    if same_len:
        for i, ((x1, y1), (x2, y2)) in enumerate(zip(mv_a, mv_b)):
            if None not in (x1, y1, x2, y2):
                d = math.hypot(x1 - x2, y1 - y2)
                if d > 1e-9:
                    diffs.append(d)
                    diff_layers.add(lay_a[i])
    return {
        "same_len": same_len,
        "n_moves": len(mv_a),
        "n_diff": len(diffs),
        "pct_diff": (len(diffs) / len(mv_a) * 100) if mv_a else 0.0,
        "median_diff": statistics.median(diffs) if diffs else 0.0,
        "max_diff": max(diffs) if diffs else 0.0,
        "diff_layers": len(diff_layers),
        "n_layers": nlay_a,
        "fil_a": fil_a,
        "fil_b": fil_b,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(MODEL):
        raise SystemExit(f"Modell nicht gefunden: {MODEL}")

    paths = [os.path.join(OUT_DIR, f"run{i}.gcode") for i in range(1, N_RUNS + 1)]
    print(f"Schneide {MODEL} {N_RUNS}x (Standard-Threading) ...")
    for i, p in enumerate(paths, start=1):
        run_slice(p)
        print(f"  Lauf {i}: {p}")

    m1_path = os.path.join(OUT_DIR, "run_m1.gcode")
    print("Schneide zusaetzlich 1x mit -m1 (ein Rechenkern) ...")
    run_slice(m1_path, single_core=True)

    hashes = [sha256_no_comments(p) for p in paths]
    print(f"\nPruefsumme (SHA-256, ohne Kommentare): {len(set(hashes))} von {N_RUNS} unterschiedlich")

    results = [compare(paths[0], p) for p in paths[1:]]
    n_moves = results[0]["n_moves"]
    n_layers = results[0]["n_layers"]
    print(f"Bewegungsbefehle je Lauf: {n_moves} (alle Laeufe: "
          f"{'identisch' if len(set(compare(paths[0], p)['n_moves'] for p in paths)) == 1 else 'UNTERSCHIEDLICH'})")
    print(f"Schichtanzahl: {n_layers}")

    pct_range = [r["pct_diff"] for r in results]
    n_range = [r["n_diff"] for r in results]
    med_range = [r["median_diff"] for r in results]
    max_range = [r["max_diff"] for r in results]
    lay_range = [r["diff_layers"] for r in results]
    fil_ref = results[0]["fil_a"]
    fil_devs = [abs(r["fil_b"] - r["fil_a"]) for r in results]

    print(f"\nBewegungen mit abweichender Position: {min(pct_range):.2f} – {max(pct_range):.2f} % "
          f"({min(n_range)} bis {max(n_range)} von {n_moves})")
    print(f"Betrag der Positionsabweichung: Median {min(med_range):.4f} – {max(med_range):.4f} mm, "
          f"Maximum {max(max_range):.4f} mm")
    print(f"Betroffene Schichten: {min(lay_range)} – {max(lay_range)} von {n_layers}")
    print(f"Referenz-Filament (Lauf 1): {fil_ref:.4f} mm")
    print(f"Abweichung Filamentverbrauch: max. {max(fil_devs):.4f} mm "
          f"({max(fil_devs)/fil_ref:.2e} relativ)")

    r_m1 = compare(paths[0], m1_path)
    print(f"\nVerhalten bei -m1 (ein Rechenkern) vs. Standard-Lauf 1: "
          f"{r_m1['pct_diff']:.2f} % abweichende Bewegungen "
          f"({r_m1['n_diff']} von {r_m1['n_moves']}), Max {r_m1['max_diff']:.4f} mm")


if __name__ == "__main__":
    main()
