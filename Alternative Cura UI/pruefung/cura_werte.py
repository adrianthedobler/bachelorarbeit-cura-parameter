# -*- coding: utf-8 -*-
"""Liest Curas eigene Angaben zu einem Schnitt: Protokoll und G-Code.

Protokoll: Cura schreibt vor jedem Schnitt eine Zeile "All settings: -s ...
-e0 -s ..." in seine Protokolldatei cura.log. Das ist die vollstaendige
Wertuebergabe an CuraEngine, getrennt nach globalem Stapel und
Extruderstapeln. Mehrzeilige Werte -- vor allem der Start-G-Code -- verteilen
sich ueber mehrere Protokollzeilen, die alle dasselbe Praefix tragen.

G-Code: An jede gespeicherte G-Code-Datei haengt Cura die selbst geaenderten
Werte an (Zeilen ";SETTING_3"), ebenfalls getrennt nach global und je Extruder.
"""
import configparser
import datetime
import json
import os
import platform
import re

CURA_VERSION = "5.13"

_PRAEFIX = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ - \w+ - .*?\[Backend\] ?")
_ENGINEZEILE = re.compile(r"^\[\d{4}-\d\d-\d\d [\d:.]+\] \[")


def protokollpfad():
    """Ort von cura.log, so wie Cura ihn bestimmt (UM/Resources.py).

    Unter Windows liegt die Datei in %APPDATA%\\cura\\5.13, unter macOS in
    ~/Library/Application Support/cura/5.13.
    """
    if platform.system() == "Windows":
        basis = os.getenv("APPDATA") or os.path.expanduser("~")
    else:
        basis = os.path.expanduser("~/Library/Application Support")
    return os.path.join(basis, "cura", CURA_VERSION, "cura.log")


def laeufe(pfad=None):
    """Alle protokollierten Engine-Aufrufe als (Zeitstempel, global, [extruder])."""
    pfad = pfad or protokollpfad()
    if not os.path.isfile(pfad):
        raise FileNotFoundError(f"Curas Protokolldatei nicht gefunden: {pfad}")
    zeilen = open(pfad, encoding="utf-8", errors="replace").read().splitlines()
    aus = []
    for i, zeile in enumerate(zeilen):
        if "All settings:" not in zeile:
            continue
        zeit = zeile[:19]
        block = [zeile.split("All settings:", 1)[1]]
        for weiter in zeilen[i + 1:]:
            ohne = _PRAEFIX.sub("", weiter)
            if ohne is weiter or not _PRAEFIX.match(weiter):
                break
            if _ENGINEZEILE.match(ohne):
                break
            block.append(ohne)
        glob, extruder = _zerlege("\n".join(block))
        # Der letzte Block ohne Einstellungen ist die Objektangabe, kein Extruder.
        extruder = [b for b in extruder if len(b) > 5]
        aus.append((zeit, glob, extruder))
    return aus


def zeitpunkt(zeit):
    """Zeitstempel eines Protokolleintrags als datetime."""
    return datetime.datetime.strptime(zeit, "%Y-%m-%d %H:%M:%S")


def _zerlege(text):
    teile = re.split(r" -e(\d+) ", text)
    glob = _paare(teile[0])
    extruder = [_paare(teile[i + 1]) for i in range(1, len(teile), 2)]
    return glob, extruder


def _paare(text):
    return dict(re.findall(
        r'-s ([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"]|\n)*?)"(?= -s | -e\d+ | -l | -o |$)', text))


def gcode_aenderungen(pfad):
    """Die in Cura geaenderten Werte, wie sie am Ende der G-Code-Datei stehen.

    Rueckgabe: {"definition": Druckerdefinition, "qualitaet": quality_type,
    "global": {schluessel: text}, "extruder": {position: {schluessel: text}}}
    """
    text = open(pfad, encoding="utf-8", errors="replace").read()
    daten = "".join(z[len(";SETTING_3 "):] for z in text.splitlines()
                    if z.startswith(";SETTING_3 "))
    if not daten:
        raise ValueError(
            "Die Datei enthaelt keinen Einstellungsblock (;SETTING_3). "
            "Wurde sie mit Cura gespeichert?")
    inhalt = json.loads(daten)

    def lies(profiltext):
        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str
        cp.read_string(profiltext.replace("\\n", "\n"))
        werte = dict(cp.items("values")) if cp.has_section("values") else {}
        return (cp.get("general", "definition", fallback=""),
                cp.get("metadata", "quality_type", fallback=""),
                cp.get("metadata", "position", fallback=""),
                werte)

    _def, qualitaet, _pos, glob = lies(inhalt.get("global_quality", ""))
    ergebnis = {"definition": "", "qualitaet": qualitaet, "global": glob,
                "extruder": {}}
    for eintrag in inhalt.get("extruder_quality", []):
        definition, _q, position, werte = lies(eintrag)
        ergebnis["extruder"][int(position or 0)] = werte
        # Die Druckerdefinition steht im Extruderprofil; im globalen Profil
        # steht nur deren Grunddefinition (etwa creality_base).
        if definition and not ergebnis["definition"]:
            ergebnis["definition"] = definition
    return ergebnis


if __name__ == "__main__":
    print("Protokoll:", protokollpfad())
    for zeit, g, e in laeufe():
        print(f"{zeit}  global {len(g):4}  Extruder {[len(x) for x in e]}  "
              f"{g.get('machine_name', '?')}")
