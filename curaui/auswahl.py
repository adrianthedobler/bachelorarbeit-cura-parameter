# -*- coding: utf-8 -*-
"""Einschraenkung des Parameterumfangs.

Cura zeigt je nach Einstellung unterschiedlich viele Parameter an. Dieses
Programm geht einen anderen Weg: Grundlage ist die Liste der 246 Parameter,
fuer die im automatisierten Vergleich (cura_setting_sweep.py) eine
nachweisbare Veraenderung am erzeugten G-Code festgestellt wurde. Alle
uebrigen bleiben zwar geladen -- die Formeln der 246 greifen auf sie zu --,
werden aber nicht zur Bearbeitung angeboten.

Der Umfang laesst sich umschalten:

    "wirksam"  die 246 nachweislich wirksamen Parameter (Vorgabe)
    "beton"    die fuer den Betondruck herausgearbeitete Auswahl
    "alle"     saemtliche Parameter der Definitionsdatei

Ein Umfang kann eigene Vorgabewerte mitbringen ("vorgaben" in der Datei).
Sie werden beim Umschalten als oberste Ebene unterhalb der eigenen
Aenderungen eingelegt -- der Parameter bleibt also einstellbar, startet aber
mit dem fuer diesen Anwendungsfall sinnvollen Wert.

Eine spaetere Erweiterung erfordert nur eine weitere Datei im Ordner data;
an der uebrigen Umsetzung aendert sich nichts.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Set

DATENORDNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

WIRKSAM = "wirksam"
BETON = "beton"
ALLE = "alle"


class Umfang:
    """Ein benannter Parameterumfang."""

    def __init__(self, kennung: str, name: str, beschreibung: str,
                 schluessel: Optional[Set[str]],
                 vorgaben: Optional[Dict[str, Any]] = None) -> None:
        self.kennung = kennung
        self.name = name
        self.beschreibung = beschreibung
        #: None bedeutet: keine Einschraenkung.
        self.schluessel = schluessel
        #: Werte, die dieser Umfang mitbringt; leer, wenn keine.
        self.vorgaben: Dict[str, Any] = dict(vorgaben or {})

    def enthaelt(self, schluessel: str) -> bool:
        return self.schluessel is None or schluessel in self.schluessel

    def anzahl(self, definitionen: Dict[str, Any]) -> int:
        if self.schluessel is None:
            return len(definitionen)
        return len(self.schluessel & set(definitionen))

    def __repr__(self) -> str:
        return f"<Umfang {self.kennung}>"


def _lade_liste(datei: str) -> Optional[Dict[str, Any]]:
    pfad = os.path.join(DATENORDNER, datei)
    if not os.path.isfile(pfad):
        return None
    try:
        with open(pfad, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def lade_umfaenge() -> List[Umfang]:
    """Liest die hinterlegten Parameterumfaenge ein."""
    umfaenge: List[Umfang] = []

    wirksam = _lade_liste("parameter_246.json")
    if wirksam:
        umfaenge.append(Umfang(
            WIRKSAM,
            f"Wirksame Parameter ({wirksam.get('anzahl', len(wirksam['parameter']))})",
            "Parameter, die im automatisierten Vergleich eine nachweisbare "
            "Veraenderung am G-Code bewirkt haben.",
            set(wirksam["parameter"])))

    beton = _lade_liste("parameter_beton.json")
    if beton:
        umfaenge.append(Umfang(
            BETON,
            f"Beton-3D-Druck ({len(beton['parameter'])})",
            beton.get("beschreibung", "Engere Auswahl fuer den Betondruck."),
            set(beton["parameter"]),
            beton.get("vorgaben")))

    umfaenge.append(Umfang(
        ALLE, "Alle Parameter",
        "Saemtliche Parameter der gewaehlten Druckerdefinition.",
        None))
    return umfaenge


def finde(umfaenge: List[Umfang], kennung: str) -> Umfang:
    for umfang in umfaenge:
        if umfang.kennung == kennung:
            return umfang
    return umfaenge[-1]


def fehlende(umfang: Umfang, definitionen: Dict[str, Any]) -> List[str]:
    """Parameter der Liste, die es in dieser Druckerdefinition nicht gibt.

    Die Liste der 246 stammt vom Ender-3. Bei einem anderen Drucker koennen
    einzelne Parameter fehlen, etwa weil dessen Grunddefinition sie entfernt.
    """
    if umfang.schluessel is None:
        return []
    return sorted(umfang.schluessel - set(definitionen))
