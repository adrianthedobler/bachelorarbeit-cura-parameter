#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueft an einem echten Cura-Schnitt, ob das Tool dieselben Werte uebergibt.

Ablauf:

  1. In Cura einen Druckauftrag einstellen, schneiden und den G-Code speichern.
  2. python3 pruefung/abgleich.py <G-Code-Datei>

Das Skript liest aus dem G-Code, welche Werte in Cura geaendert wurden, und
sucht in Curas Protokolldatei den zugehoerigen Schnitt. Anschliessend stellt es
Drucker, Qualitaetsprofil, Material und Duese im Tool ein und setzt die
geaenderten Werte auf demselben Weg, den die Oberflaeche des Tools benutzt.
Zum Schluss wird jeder an die Engine uebergebene Wert mit Curas Protokoll
verglichen -- global und je Extruder.

Weitere Aufrufe:

  python3 pruefung/abgleich.py --beispiele     die drei Faelle aus Abschnitt 5.4
                                              (nur mit dem Protokoll, in dem
                                              diese Schnitte stehen)
  python3 pruefung/abgleich.py DATEI --protokoll PFAD   andere Protokolldatei
"""
import argparse
import datetime
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
sys.path.insert(0, HIER)

from cura_werte import gcode_aenderungen, laeufe, protokollpfad, zeitpunkt  # noqa: E402


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


def _block(name, cura, meine):
    gemeinsam = sorted(set(cura) & set(meine))
    abw = [k for k in gemeinsam if not gleich(cura[k], meine[k])]
    quote = 100 * (len(gemeinsam) - len(abw)) / max(len(gemeinsam), 1)
    print(f"  {name:12} {len(gemeinsam) - len(abw):4}/{len(gemeinsam):4} identisch "
          f"({quote:5.1f} %)   abweichend: {len(abw)}")
    for k in abw:
        a = str(cura[k]).replace("\n", "⏎")[:34]
        b = str(meine[k]).replace("\n", "⏎")[:34]
        print(f"      {k:38} Cura {a:<36} Tool {b}")
    return len(abw)


def _material(maschine, angabe, nummer):
    """Materialprofil zu einer Kennung oder einer GUID aus dem Protokoll."""
    if angabe in maschine.materialien:
        return maschine.materialien[angabe]
    passende = [m for m in maschine.materialien.values() if m.guid == angabe]
    durchmesser = maschine.durchmesser(nummer)
    for m in passende:
        try:
            if abs(float(m.durchmesser) - durchmesser) < 0.3:
                return m
        except (TypeError, ValueError):
            continue
    return passende[0] if passende else None


def _variante(maschine, groesse):
    for v in maschine.varianten:
        try:
            if abs(float(v.werte.get("machine_nozzle_size", "nan")) - float(groesse)) < 1e-6:
                return v
        except (TypeError, ValueError):
            continue
    return None


def pruefe(titel, cura_global, cura_extruder, definition,
           global_aenderungen, extruder_aenderungen,
           profilname=None, materialien=None, cura_pfad=None):
    """Stellt den Druckauftrag im Tool nach und vergleicht jeden Wert."""
    from curaui import engine, tui
    from curaui import werte as werte_modul

    a = tui.Anwendung(cura_pfad)
    a._drucker_laden(definition)
    m = a.maschine

    print(f"\n{'=' * 76}\n{titel}   ({definition}, {m.anzahl_extruder} Extruder)")

    if profilname:
        for p in m.profile:
            if p.name == profilname:
                m.profil_waehlen(p)
                a.profil = m.profil
                break
        else:
            print(f"  Hinweis: Qualitaetsprofil {profilname!r} nicht gefunden")

    for nummer in range(m.anzahl_extruder):
        angabe = (materialien[nummer] if materialien and nummer < len(materialien)
                  else (cura_extruder[nummer].get("material_guid")
                        if nummer < len(cura_extruder) else None))
        if angabe:
            material = _material(m, angabe, nummer)
            if material is None:
                print(f"  Hinweis: Material {angabe!r} nicht gefunden")
            else:
                m.material_waehlen(material, None if m.anzahl_extruder == 1 else nummer)
        if nummer < len(cura_extruder) and "machine_nozzle_size" in cura_extruder[nummer]:
            variante = _variante(m, cura_extruder[nummer]["machine_nozzle_size"])
            if variante is not None:
                m.variante_waehlen(variante, None if m.anzahl_extruder == 1 else nummer)

    def setzen(schluessel, text, nummer):
        definition_ = a.definitionen.get(schluessel)
        if definition_ is None:
            print(f"  Hinweis: {schluessel} gibt es in dieser Definition nicht")
            return
        if str(text).startswith("="):
            print(f"  Hinweis: {schluessel} ist in Cura als Formel gesetzt und wird uebersprungen")
            return
        wert = werte_modul.aus_text(definition_, text)
        if nummer is None or nummer == 0:
            # Derselbe Weg wie eine Eingabe in der Oberflaeche.
            a._eingabe_setzen(schluessel, wert)
            weg = "Oberflaeche"
        else:
            # Weitere Extruder lassen sich in der Oberflaeche nicht einzeln einstellen.
            m.extruder[nummer].setze(schluessel, wert)
            weg = f"Extruder {nummer} direkt"
        ort = "global" if nummer is None else f"Extruder {nummer}"
        print(f"  gesetzt: {schluessel} = {text}   (in Cura: {ort}, im Tool: {weg})")

    for schluessel, text in global_aenderungen.items():
        setzen(schluessel, text, None)
    for nummer, aenderungen in sorted(extruder_aenderungen.items()):
        for schluessel, text in aenderungen.items():
            setzen(schluessel, text, nummer)

    meine_global, meine_extruder = engine.teile_werte(a.einstellungen)
    abweichungen = _block("global", cura_global, meine_global)
    for nummer, satz in enumerate(meine_extruder):
        if nummer < len(cura_extruder):
            abweichungen += _block(f"Extruder {nummer}", cura_extruder[nummer], satz)
    return abweichungen


def _passender_lauf(eintraege, aenderungen, bis):
    """Der juengste Protokolleintrag vor dem Speichern, der zu den Aenderungen passt."""
    kandidaten = [e for e in eintraege if zeitpunkt(e[0]) <= bis]
    for zeit, glob, extruder in reversed(kandidaten):
        passt = all(gleich(glob.get(k), v) for k, v in aenderungen["global"].items()
                    if k in glob)
        for nummer, werte in aenderungen["extruder"].items():
            if nummer < len(extruder):
                passt = passt and all(gleich(extruder[nummer].get(k), v)
                                      for k, v in werte.items() if k in extruder[nummer])
        if passt:
            return zeit, glob, extruder
    return kandidaten[-1] if kandidaten else None


def aus_gcode(pfad, protokoll=None, cura_pfad=None):
    aenderungen = gcode_aenderungen(pfad)
    gespeichert = datetime.datetime.fromtimestamp(os.path.getmtime(pfad))
    lauf = _passender_lauf(laeufe(protokoll), aenderungen,
                           gespeichert + datetime.timedelta(minutes=1))
    if lauf is None:
        print("Kein passender Schnitt in Curas Protokolldatei gefunden.")
        return 1
    zeit, cura_global, cura_extruder = lauf
    print(f"G-Code:     {pfad}")
    print(f"Protokoll:  {protokoll or protokollpfad()}  (Schnitt vom {zeit})")
    return pruefe(f"Cura-Schnitt vom {zeit}", cura_global, cura_extruder,
                  aenderungen["definition"], aenderungen["global"],
                  aenderungen["extruder"],
                  profilname=cura_global.get("quality_name"), cura_pfad=cura_pfad)


def beispiele(protokoll=None, cura_pfad=None):
    """Die drei Faelle aus Abschnitt 5.4 (Schnitte vom 4. September 2026)."""
    eintraege = laeufe(protokoll)
    faelle = [
        ("Test 1 — Generate Support", "2026-09-04 20:59", "creality_ender3",
         {"support_enable": "True"}, {}, None),
        ("Test 2 — Fuzzy Skin", "2026-09-04 21:02", "creality_ender3",
         {}, {0: {"magic_fuzzy_skin_enabled": "True"}}, None),
        ("Test 3 — CR-X, Support ueber rechten Extruder", "2026-09-04 21:04",
         "creality_cr-x", {"support_enable": "True", "support_extruder_nr_layer_0": "1"},
         {}, ["filo3d_pla_red", "filo3d_pla_green"]),
    ]
    summe = 0
    for titel, zeitmarke, drucker, glob, extr, mat in faelle:
        treffer = [e for e in eintraege if e[0].startswith(zeitmarke)]
        if not treffer:
            print(f"\n{titel}: kein Protokolleintrag zu {zeitmarke}")
            continue
        _zeit, cura_global, cura_extruder = treffer[-1]
        summe += pruefe(titel, cura_global, cura_extruder, drucker, glob, extr,
                        materialien=mat, cura_pfad=cura_pfad)
    return summe


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gcode", nargs="?", help="mit Cura gespeicherte G-Code-Datei")
    parser.add_argument("--beispiele", action="store_true",
                        help="die drei Faelle aus Abschnitt 5.4 pruefen")
    parser.add_argument("--protokoll", help="Pfad zu Curas cura.log")
    parser.add_argument("--cura", help="Ordner der Cura-Installation")
    args = parser.parse_args()
    if args.beispiele:
        abweichungen = beispiele(args.protokoll, args.cura)
    elif args.gcode:
        abweichungen = aus_gcode(args.gcode, args.protokoll, args.cura)
    else:
        parser.print_help()
        return 2
    print(f"\nErgebnis: {'keine Abweichung' if abweichungen == 0 else f'{abweichungen} abweichende Werte'}")
    return 0 if abweichungen == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
