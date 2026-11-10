#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alternative textbasierte Nutzeroberflaeche fuer UltiMaker Cura 5.13.

Aufruf ohne Angaben startet die Oberflaeche:

    python3 cura-ui.py

Weitere Moeglichkeiten:

    python3 cura-ui.py --cura <Ordner>        Cura-Installation vorgeben
    python3 cura-ui.py --sprache de_DE        Bezeichnungen auf Deutsch
    python3 cura-ui.py --pruefen              nur pruefen, ob alles bereitsteht
    python3 cura-ui.py --schneiden E.curaui.json -m Modell.stl -o aus.gcode
                                              ohne Oberflaeche schneiden

Anbindung an das 3DCP-Programm des Lehrstuhls (Repo dvdschdt/3DCP):

    python3 cura-ui.py --setup 3DCP/user_input/setup.json
                                              Oberflaeche im 3DCP-Modus
    python3 cura-ui.py --setup … --argumente-schreiben
                                              cura_arguments zurueckschreiben
    python3 cura-ui.py --drucker-datei printer.def.json
                                              eigene Druckerdefinition laden
"""
from __future__ import annotations

import argparse
import os
import sys

# Der Programmordner muss im Suchpfad liegen, damit das Paket curaui auch dann
# gefunden wird, wenn das Programm aus einem anderen Ordner heraus aufgerufen
# wird (etwa per Doppelklick auf die Startdatei).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from curaui import cura_env  # noqa: E402


def pruefen(cura_pfad):
    """Gibt aus, ob die Cura-Installation gefunden und benutzbar ist."""
    inst = cura_env.vorbereiten(cura_pfad)
    from curaui import definitionen, profile as profil_modul, werte

    print(f"Cura-Installation : {inst.wurzel}")
    print(f"CuraEngine        : {inst.engine}")
    print(f"Suchpfad          : {inst.such_pfad()}")

    drucker_liste = definitionen.liste_drucker(inst)
    print(f"Druckerdefinitionen: {len(drucker_liste)}")

    from curaui import aufbau
    m = aufbau.Maschine(inst, "creality_ender3")
    defs = m.definitionen
    einstellungen = m.einstellungen
    print(f"Beispieldrucker   : {m.drucker.anzeigename} "
          f"({len(defs)} Parameter in {len(m.kategorien)} Kategorien, "
          f"{m.anzahl_extruder} Extruder)")
    if m.profil:
        print(f"Qualitaetsprofil  : {m.profil.name}")
    if m.material:
        print(f"Material          : {m.material.anzeigename} "
              f"({m.material.durchmesser} mm)")
    if m.variante:
        print(f"Duese             : {m.variante.name}")

    # Kurze Gegenproben. Die erste prueft die Formelauswertung, die zweite,
    # ob die Materialebene wirkt: sie liegt beim Extruder, nicht in der
    # Maschine, weshalb sich die Temperaturen dort unterscheiden muessen.
    einstellungen.setze("wall_thickness", 1.2)
    ergebnis = einstellungen.wert("wall_line_count")
    print(f"Formelprobe       : wall_thickness=1.2 ergibt "
          f"wall_line_count={ergebnis} "
          f"({'in Ordnung' if ergebnis == 3 else 'ERWARTET WAR 3'})")
    global_temp = einstellungen.wert("material_print_temperature")
    extruder_temp = m.extruder[0].wert("material_print_temperature")
    print(f"Materialprobe     : Duesentemperatur global {global_temp}, "
          f"im Extruder {extruder_temp} "
          f"({'in Ordnung' if global_temp != extruder_temp else 'MATERIAL WIRKT NICHT'})")

    from curaui import auswahl
    for umfang in auswahl.lade_umfaenge():
        fehlend = auswahl.fehlende(umfang, defs)
        zusatz = f", davon {len(fehlend)} hier nicht vorhanden" if fehlend else ""
        print(f"Umfang            : {umfang.name}{zusatz}")

    meldungen = cura_env.gesammelte_meldungen()
    print(f"Hinweise von Cura : {len(meldungen)}")
    for meldung in meldungen[:5]:
        print(f"  {meldung}")
    return 0 if ergebnis == 3 else 1


def _maschine_aufbauen(inst, inhalt, setup=None, drucker_datei=None,
                       ohne_material=False):
    """Stellt die Maschine her, wahlweise mit Angaben aus einer setup.json."""
    from curaui import aufbau
    datei = drucker_datei or (setup.druckerdatei_pfad() if setup else None)
    name = (inhalt or {}).get("drucker", "creality_ender3")
    if datei:
        name = os.path.basename(datei)
    m = aufbau.Maschine(inst, name, drucker_datei=datei,
                        ohne_material=bool(ohne_material) or setup is not None)
    if setup is not None:
        m.feste_werte_setzen(setup.feste_werte())
    return m


def argumente_schreiben(setup, ziel, einstellungsdatei, cura_pfad,
                        drucker_datei=None, ohne_material=False,
                        in_place=False):
    """Schreibt die Werte einer Einstellung als cura_arguments zurueck."""
    if setup is None:
        print("--argumente-schreiben benoetigt --setup.", file=sys.stderr)
        return 2
    inst = cura_env.vorbereiten(cura_pfad)
    from curaui import dreidcp, projekt, werte as werte_modul

    inhalt = projekt.laden(einstellungsdatei) if einstellungsdatei else {}
    m = _maschine_aufbauen(inst, inhalt, setup, drucker_datei, ohne_material)
    for schluessel, wert in setup.vorschlaege().items():
        if schluessel in m.definitionen and not m.einstellungen.ist_fest(schluessel):
            m.einstellungen.setze(schluessel, wert)
    if inhalt:
        projekt.anwenden(inhalt, m.einstellungen, m)
    werte = dreidcp.geaenderte_werte(m)
    pfad = dreidcp.schreibe_cura_arguments(setup, werte, ziel, in_place=in_place)
    for zeile in dreidcp.bericht(m, setup, werte):
        print("  " + zeile)
    if in_place:
        print(f"In setup.json geschrieben (nur cura_arguments): {pfad}")
        print(f"Sicherung der Vorlage      : {pfad}.orig")
    else:
        print(f"Geschrieben: {pfad}")
    return 0


def schneiden(einstellungsdatei, modell, ausgabe, cura_pfad, setup=None,
              drucker_datei=None, ohne_material=False):
    """Schneidet ohne Oberflaeche mit einer gespeicherten Einstellung."""
    inst = cura_env.vorbereiten(cura_pfad)
    from curaui import definitionen, engine, profile as profil_modul
    from curaui import projekt, werte

    from curaui import aufbau, auswahl
    inhalt = projekt.laden(einstellungsdatei)
    m = _maschine_aufbauen(inst, inhalt, setup, drucker_datei, ohne_material)
    einstellungen = m.einstellungen

    # Vorgabewerte des gespeicherten Umfangs wie in der Oberflaeche einlegen,
    # etwa Build Plate Adhesion Type = None bei der Beton-Auswahl.
    umfang = auswahl.finde(auswahl.lade_umfaenge(),
                           inhalt.get("umfang", auswahl.WIRKSAM))
    m.vorgaben_setzen({k: v for k, v in umfang.vorgaben.items()
                       if k in m.definitionen})

    if setup is not None:
        for schluessel, wert in setup.vorschlaege().items():
            if schluessel in m.definitionen and not einstellungen.ist_fest(schluessel):
                einstellungen.setze(schluessel, wert)
    uebernommen, misslungen = projekt.anwenden(inhalt, einstellungen, m)
    print(f"Drucker: {m.drucker.anzeigename}; Umfang: {umfang.name}; "
          f"{uebernommen} eigene Werte")
    if misslungen:
        print("Nicht uebernommen: " + ", ".join(misslungen))

    modell = modell or inhalt.get("modell")
    if not modell:
        print("Es ist kein Modell angegeben (-m).", file=sys.stderr)
        return 2

    ergebnis = engine.schneide(inst, m.definitionsdatei, modell, ausgabe,
                               einstellungen)
    kennzahlen = ergebnis.kennzahlen
    print(f"Geschrieben: {ergebnis.pfad}")
    print(f"  Schichten     : {kennzahlen.get('schichten')}")
    print(f"  Bewegungen    : {kennzahlen.get('bewegungen')}")
    print(f"  Filament      : {kennzahlen.get('filament_mm', 0) / 1000:.2f} m")
    print(f"  Dauer         : {ergebnis.dauer:.1f} s")
    return 0


def main():
    zerleger = argparse.ArgumentParser(
        description="Textbasierte Nutzeroberflaeche fuer UltiMaker Cura 5.13",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    zerleger.add_argument("--cura", metavar="ORDNER",
                          help="Ordner der Cura-Installation")
    zerleger.add_argument("--sprache", default="en", metavar="KUERZEL",
                          help="Sprache der Parameterbezeichnungen (Vorgabe: en, "
                               "also die Originaltexte der Definitionsdateien; "
                               "de_DE schaltet auf Curas deutsche Uebersetzung)")
    zerleger.add_argument("--pruefen", action="store_true",
                          help="nur pruefen, ob alles bereitsteht")
    zerleger.add_argument("--schneiden", metavar="DATEI",
                          help="gespeicherte Einstellung ohne Oberflaeche "
                               "anwenden")
    zerleger.add_argument("--setup", nargs="?", const="__standard__",
                          metavar="DATEI",
                          help="setup.json des 3DCP-Programms einlesen; ohne "
                               "Pfadangabe die mitgelieferte data/3dcp/setup.json")
    zerleger.add_argument("--drucker-datei", metavar="DATEI",
                          dest="drucker_datei",
                          help="Druckerdefinition ausserhalb der "
                               "Cura-Installation laden")
    zerleger.add_argument("--ohne-material", action="store_true",
                          dest="ohne_material",
                          help="kein Materialprofil einlegen")
    zerleger.add_argument("--argumente-schreiben", nargs="?", const="",
                          metavar="ZIEL", dest="argumente_schreiben",
                          help="geaenderte Werte als cura_arguments in eine "
                               "setup.json schreiben (nur mit --setup)")
    zerleger.add_argument("--in-place", action="store_true", dest="in_place",
                          help="cura_arguments direkt in die Original-setup.json "
                               "zurueckschreiben (nur dieses Feld; Sicherung "
                               ".orig); nur mit --setup")
    zerleger.add_argument("-m", "--modell", metavar="DATEI")
    zerleger.add_argument("-o", "--ausgabe", metavar="DATEI",
                          default="ausgabe/ausgabe.gcode")
    angaben = zerleger.parse_args()

    sprache = "" if angaben.sprache.lower() in ("en", "en_us", "-") \
        else angaben.sprache

    try:
        if angaben.pruefen:
            return pruefen(angaben.cura)
        setup = None
        if angaben.setup:
            from curaui import dreidcp
            setup_pfad = angaben.setup
            if setup_pfad == "__standard__":
                setup_pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "data", "3dcp", "setup.json")
            setup = dreidcp.lade_setup(setup_pfad)
        if angaben.argumente_schreiben is not None or angaben.in_place:
            return argumente_schreiben(setup, angaben.argumente_schreiben or None,
                                       angaben.schneiden, angaben.cura,
                                       angaben.drucker_datei,
                                       angaben.ohne_material,
                                       angaben.in_place)
        if angaben.schneiden:
            return schneiden(angaben.schneiden, angaben.modell,
                             angaben.ausgabe, angaben.cura, setup,
                             angaben.drucker_datei, angaben.ohne_material)
        from curaui import tui
        tui.starten(angaben.cura, sprache, setup, angaben.drucker_datei,
                    angaben.ohne_material)
        return 0
    except cura_env.CuraNichtGefunden as fehler:
        print(str(fehler), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
