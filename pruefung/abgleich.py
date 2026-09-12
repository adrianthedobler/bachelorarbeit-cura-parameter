# -*- coding: utf-8 -*-
"""Vergleicht die Werte des eigenen Programms mit denen, die Cura uebergab."""
import json, os, sys
sys.path.insert(0, "/Users/adriandobler/Library/Mobile Documents/com~apple~CloudDocs/Claude/Alternative Cura UI")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cura_werte import laeufe
from curaui import cura_env, aufbau, engine, werte as werte_modul

def gleich(a, b):
    a, b = str(a).strip(), str(b).strip()
    if a == b:
        return True
    if a.lower() in ("true", "false") or b.lower() in ("true", "false"):
        return a.lower() == b.lower()
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return False

def pruefe(titel, zeitmarke, drucker, global_aenderungen, extruder_aenderungen,
           materialien=None):
    treffer = [l for l in laeufe() if l[0].startswith(zeitmarke)]
    if not treffer:
        print(f"{titel}: kein Protokolleintrag zu {zeitmarke}"); return
    _zeit, cura_global, cura_extruder = treffer[-1]
    # Der letzte Block ohne -l ist die Objektangabe, kein Extruder
    cura_extruder = [b for b in cura_extruder if len(b) > 5]

    inst = cura_env.vorbereiten()
    m = aufbau.Maschine(inst, drucker)
    for nummer, kennung in enumerate(materialien or []):
        if kennung and kennung in m.materialien:
            m.material_waehlen(m.materialien[kennung], nummer)
    for k, v in global_aenderungen.items():
        m.einstellungen.setze(k, werte_modul.aus_text(m.definitionen[k], v))
    for nummer, aenderungen in enumerate(extruder_aenderungen):
        for k, v in aenderungen.items():
            m.extruder[nummer].setze(k, werte_modul.aus_text(m.definitionen[k], v))
    g, saetze = engine.teile_werte(m.einstellungen)

    print(f"\n{'='*76}\n{titel}   ({drucker}, {m.anzahl_extruder} Extruder)")
    _block("global", cura_global, g)
    for nummer, satz in enumerate(saetze):
        if nummer < len(cura_extruder):
            _block(f"Extruder {nummer}", cura_extruder[nummer], satz)

def _block(name, cura, meine):
    gemeinsam = sorted(set(cura) & set(meine))
    abw = [k for k in gemeinsam if not gleich(cura[k], meine[k])]
    quote = 100 * (len(gemeinsam) - len(abw)) / max(len(gemeinsam), 1)
    print(f"  {name:12} {len(gemeinsam)-len(abw):4}/{len(gemeinsam):4} identisch "
          f"({quote:5.1f} %)   abweichend: {len(abw)}")
    for k in abw:
        a = str(cura[k]).replace("\n", "⏎")[:34]
        b = str(meine[k]).replace("\n", "⏎")[:34]
        print(f"      {k:38} Cura {a:<36} Programm {b}")

if __name__ == "__main__":
    pruefe("Test 1 — Generate Support", "2026-09-04 20:59", "creality_ender3",
           {"support_enable": "True"}, [{}])
    pruefe("Test 2 — Fuzzy Skin", "2026-09-04 21:02", "creality_ender3",
           {}, [{"magic_fuzzy_skin_enabled": "True"}])
    pruefe("Test 3 — CR-X, Support ueber rechten Extruder", "2026-09-04 21:04",
           "creality_cr-x",
           {"support_enable": "True", "support_extruder_nr_layer_0": "1"}, [{}, {}],
           materialien=["filo3d_pla_red", "filo3d_pla_green"])
