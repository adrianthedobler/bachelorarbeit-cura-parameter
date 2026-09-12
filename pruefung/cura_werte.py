# -*- coding: utf-8 -*-
"""Liest die Wertesaetze, die Cura an CuraEngine uebergeben hat, aus cura.log.

Cura schreibt vor jedem Schnitt eine Zeile "All settings: -s ... -e0 -s ...".
Mehrzeilige Werte -- vor allem der Start-G-Code -- verteilen sich dabei ueber
mehrere Protokollzeilen, die alle dasselbe Praefix tragen.
"""
import json, os, re, sys

C = os.path.expanduser("~/Library/Application Support/cura/5.13")
_PRAEFIX = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ - \w+ - .*?\[Backend\] ?")
_ENGINEZEILE = re.compile(r"^\[\d{4}-\d\d-\d\d [\d:.]+\] \[")


def laeufe(pfad=None):
    """Alle protokollierten Engine-Aufrufe als (Zeitstempel, global, [extruder])."""
    zeilen = open(pfad or os.path.join(C, "cura.log"), errors="replace").read().splitlines()
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
        aus.append((zeit,) + _zerlege("\n".join(block)))
    return aus


def _zerlege(text):
    teile = re.split(r" -e(\d+) ", text)
    glob = _paare(teile[0])
    extruder = [_paare(teile[i + 1]) for i in range(1, len(teile), 2)]
    return glob, extruder


def _paare(text):
    return dict(re.findall(
        r'-s ([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"]|\n)*?)"(?= -s | -e\d+ | -l | -o |$)', text))


if __name__ == "__main__":
    for zeit, g, e in laeufe():
        print(f"{zeit}  global {len(g):4}  Extruder {[len(x) for x in e]}  "
              f"{g.get('machine_name','?'):22} support={g.get('support_enable')} "
              f"fuzzy={g.get('magic_fuzzy_skin_enabled')} "
              f"support_extruder_nr_layer_0={g.get('support_extruder_nr_layer_0')}")
