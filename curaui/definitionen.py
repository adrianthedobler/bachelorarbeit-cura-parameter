# -*- coding: utf-8 -*-
"""Einlesen der Druckerdefinitionen.

Eine Druckerdefinition (z. B. creality_ender3.def.json) enthaelt selbst nur
wenige Werte und verweist ueber "inherits" auf eine Grunddefinition, die
ihrerseits weiter verweist, bis am Ende fdmprinter.def.json steht. Erst die
Verschmelzung dieser Kette ergibt den vollstaendigen Satz von Parametern.

Dieselbe Verschmelzung fuehrt auch CuraEngine durch, wenn ihr ueber
CURA_ENGINE_SEARCH_PATH die Ordner definitions und extruders bekannt gemacht
werden. Die Umsetzung hier folgt Curas eigener in
UM/Settings/DefinitionContainer.py (_resolveInheritance, _mergeDicts,
_preprocessParsedJson).
"""
from __future__ import annotations

import collections
import copy
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .cura_env import CuraInstallation


class DefinitionsFehler(RuntimeError):
    pass


# --------------------------------------------------------- Verschmelzung

def _lade_json(ordner: Any, name: str) -> Dict[str, Any]:
    """Liest eine Definitionsdatei; ordner darf auch mehrere Orte nennen.

    Mehrere Orte sind noetig, weil die inherits-Kette einer Extruderdefinition
    den Ordner wechselt: creality_base_extruder_0.def.json liegt in extruders,
    die davon geerbte fdmextruder.def.json aber in definitions. Auch
    CuraEngine bekommt aus diesem Grund beide Ordner genannt.
    """
    orte = [ordner] if isinstance(ordner, str) else list(ordner)
    for ort in orte:
        pfad = os.path.join(ort, name + ".def.json")
        if os.path.isfile(pfad):
            with open(pfad, "r", encoding="utf-8") as fh:
                return json.load(fh, object_pairs_hook=collections.OrderedDict)
    raise DefinitionsFehler(
        f"Definitionsdatei {name}.def.json nicht gefunden in: "
        + ", ".join(orte))


def _verschmelze(unten: Dict[str, Any], oben: Dict[str, Any],
                 neu: bool = True) -> Dict[str, Any]:
    """Legt oben ueber unten. Teilbaeume werden zusammengefuehrt, Werte ersetzt.

    Entspricht DefinitionContainer._mergeDicts.
    """
    ergebnis = copy.deepcopy(unten) if neu else unten
    for schluessel, wert in oben.items():
        if schluessel in ergebnis and isinstance(wert, dict) and isinstance(ergebnis[schluessel], dict):
            ergebnis[schluessel] = _verschmelze(ergebnis[schluessel], wert, neu=neu)
        else:
            ergebnis[schluessel] = wert
    return ergebnis


def _suche_tief(baum: Dict[str, Any], schluessel: str) -> Optional[Dict[str, Any]]:
    """Sucht einen Parameter irgendwo im verschachtelten Kategorienbaum.

    Entspricht DefinitionContainer._findInDict.
    """
    if schluessel in baum:
        return baum[schluessel]
    for wert in baum.values():
        if isinstance(wert, dict):
            treffer = _suche_tief(wert, schluessel)
            if treffer is not None:
                return treffer
    return None


def _loese_vererbung(ordner: Any, name: str, kette: Optional[List[str]] = None) -> Dict[str, Any]:
    """Loest die inherits-Kette einer Definition vollstaendig auf."""
    kette = kette or []
    if name in kette:
        raise DefinitionsFehler("Ringschluss in der inherits-Kette: "
                                + " -> ".join(kette + [name]))
    daten = _lade_json(ordner, name)
    if "inherits" in daten:
        eltern = _loese_vererbung(ordner, daten["inherits"], kette + [name])
        daten = _verschmelze(eltern, daten)
    return daten


def _wende_overrides_an(daten: Dict[str, Any]) -> List[str]:
    """Traegt den Abschnitt "overrides" in den Parameterbaum ein.

    Entspricht DefinitionContainer._preprocessParsedJson. Nicht zuordenbare
    Eintraege werden gemeldet statt uebergangen, damit sie sichtbar bleiben.
    """
    unbekannt: List[str] = []
    for schluessel, wert in daten.get("overrides", {}).items():
        ziel = _suche_tief(daten.get("settings", {}), schluessel)
        if ziel is None:
            unbekannt.append(schluessel)
        else:
            ziel.update(wert)
    return unbekannt


# ------------------------------------------------------------- Uebersicht

class Druckerdefinition:
    """Eine vollstaendig aufgeloeste Druckerdefinition."""

    def __init__(self, name: str, daten: Dict[str, Any],
                 unbekannte_overrides: List[str],
                 extruder: Optional[Dict[str, Any]] = None,
                 vererbungskette: Optional[List[str]] = None,
                 extruderliste: Optional[List[Dict[str, Any]]] = None) -> None:
        self.name = name
        self.daten = daten
        self.extruder = extruder
        #: Die Definitionen aller Extruder, nach Position geordnet.
        self.extruderliste = extruderliste or ([extruder] if extruder else [])
        self.anzeigename = daten.get("name", name)
        self.hersteller = daten.get("metadata", {}).get("manufacturer", "")
        self.unbekannte_overrides = unbekannte_overrides
        #: Die Kette der geerbten Definitionen, von der naechsten bis zur
        #: Grunddefinition. Material- und Variantendateien verweisen teils
        #: auf diese Zwischenstufen statt auf den Drucker selbst.
        self.vererbungskette = vererbungskette or []

    def __repr__(self) -> str:
        return f"<Druckerdefinition {self.name} ({self.anzeigename})>"


def lade_drucker(inst: CuraInstallation, name: str) -> Druckerdefinition:
    """Laedt eine Druckerdefinition samt aller geerbten Ebenen."""
    daten = _loese_vererbung(inst.definitionen, name)
    unbekannt = _wende_overrides_an(daten)
    extruder = _lade_extruder(inst, daten)
    return Druckerdefinition(name, daten, unbekannt, extruder,
                             _vererbungskette(inst.definitionen, name),
                             _lade_alle_extruder(inst, daten))


def _vererbungskette(ordner: Any, name: str) -> List[str]:
    """Die Namen aller Definitionen, von denen eine Definition erbt."""
    kette: List[str] = []
    aktuell = name
    while True:
        try:
            daten = _lade_json(ordner, aktuell)
        except DefinitionsFehler:
            break
        eltern = daten.get("inherits")
        if not eltern or eltern in kette:
            break
        kette.append(eltern)
        aktuell = eltern
    return kette


def _extruderdateien(daten: Dict[str, Any]) -> Dict[int, str]:
    """Welche Datei welchen Extruder beschreibt.

    Die Zuordnung steht in metadata.machine_extruder_trains und kann aus
    einer geerbten Ebene stammen (beim Ender-3 aus creality_base.def.json).
    """
    trains = daten.get("metadata", {}).get("machine_extruder_trains") or {}
    zuordnung: Dict[int, str] = {}
    for schluessel, wert in trains.items():
        try:
            zuordnung[int(schluessel)] = str(wert)
        except (TypeError, ValueError):
            continue
    return zuordnung


def _lade_alle_extruder(inst: CuraInstallation,
                        daten: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Die Definitionen aller Extruder, nach Position geordnet.

    Bei mehreren Extrudern koennen sich deren Angaben unterscheiden -- der
    zweite Extruder der CR-X bringt zum Beispiel eigenen Start- und
    End-G-Code mit und eine andere Filamentstaerke.
    """
    zuordnung = _extruderdateien(daten)
    if not zuordnung:
        zuordnung = {0: "fdmextruder"}
    geladen: List[Dict[str, Any]] = []
    for position in sorted(zuordnung):
        try:
            eintrag = _loese_vererbung([inst.extruder, inst.definitionen],
                                       zuordnung[position])
        except DefinitionsFehler:
            continue
        _wende_overrides_an(eintrag)
        geladen.append(eintrag)
    return geladen


def vorgabewerte(eintrag: Dict[str, Any]) -> Dict[str, Any]:
    """Die Vorgabewerte aller Parameter einer Definition, flach.

    Wird gebraucht, um die Definition eines einzelnen Extruders als unterste
    Ebene seines Stapels einzulegen.
    """
    gefunden: Dict[str, Any] = {}

    def rek(knoten: Dict[str, Any]) -> None:
        for schluessel, angaben in knoten.items():
            if not isinstance(angaben, dict):
                continue
            if "label" in angaben and "default_value" in angaben:
                gefunden[schluessel] = angaben["default_value"]
            rek(angaben.get("children", {}))

    for kategorie in eintrag.get("settings", {}).values():
        rek(kategorie.get("children", {}))
    return gefunden


def _lade_extruder(inst: CuraInstallation,
                   daten: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Laedt die Definition des ersten Extruders.

    Cura fuehrt je Maschine zwei Behaelterstapel: einen globalen und einen je
    Extruder. Einige Parameter stehen nur im zweiten, etwa
    machine_nozzle_offset_x. Werden sie nicht geladen, schlagen die Formeln
    fehl, die darauf zugreifen -- unter anderem die Lage des Reinigungsturms.

    Welche Datei zustaendig ist, steht in metadata.machine_extruder_trains;
    diese Angabe kann aus einer geerbten Ebene stammen (beim Ender-3 aus
    creality_base.def.json).
    """
    trains = _extruderdateien(daten)
    name = trains.get(0)
    if not name:
        name = "fdmextruder"
    try:
        extruder = _loese_vererbung([inst.extruder, inst.definitionen], name)
    except DefinitionsFehler:
        return None
    _wende_overrides_an(extruder)
    return extruder


def liste_drucker(inst: CuraInstallation) -> List[Tuple[str, str, str]]:
    """Alle waehlbaren Drucker als (Dateiname, Anzeigename, Hersteller).

    Ausgelassen werden die Grunddefinitionen, die nur zum Erben da sind
    (metadata.visible == false), sowie fdmextruder.
    """
    eintraege: List[Tuple[str, str, str]] = []
    for datei in sorted(os.listdir(inst.definitionen)):
        if not datei.endswith(".def.json"):
            continue
        name = datei[:-len(".def.json")]
        if name == "fdmextruder":
            continue
        try:
            with open(os.path.join(inst.definitionen, datei), "r", encoding="utf-8") as fh:
                roh = json.load(fh)
        except (OSError, ValueError):
            continue
        meta = roh.get("metadata", {})
        # "visible": false kennzeichnet reine Grunddefinitionen wie
        # creality_base.def.json, die in Curas Druckerauswahl ebenfalls
        # nicht erscheinen.
        if meta.get("visible") is False:
            continue
        if name != "fdmprinter" and "inherits" not in roh and "settings" not in roh:
            continue
        eintraege.append((name, roh.get("name", name), meta.get("manufacturer", "")))
    return eintraege


# ------------------------------------------- Umwandlung in SettingDefinition

#: Kategorien, die keine Schnitteinstellungen enthalten. "machine_settings"
#: bleibt bewusst erhalten, weil die Maschine frei einstellbar sein soll.
NICHT_SCHNEIDEND = {"command_line_settings"}


def baue_definitionen(drucker: Druckerdefinition) -> Tuple[Dict[str, Any], List[Any]]:
    """Erzeugt aus dem Parameterbaum Curas eigene SettingDefinition-Objekte.

    Rueckgabe: (Abbildung Schluessel -> Definition, Liste der Kategorien,
    Liste der nur in der Extruderdefinition vorkommenden Parameter).
    Ausgewertet werden dabei Curas eigener Parser und Curas eigene
    Formelklasse; hier wird nichts nachgebaut.
    """
    from UM.Settings.SettingDefinition import SettingDefinition

    definitionen: Dict[str, Any] = {}
    kategorien: List[Any] = []
    #: Parameter, die es nur in der Extruderdefinition gibt. Sie gehoeren zu
    #: keiner Kategorie der Druckerdefinition und werden der Oberflaeche
    #: gesondert gemeldet, damit sie bei der Maschine erscheinen koennen.
    nur_extruder: List[str] = []

    for kat_schluessel, kat_daten in drucker.daten.get("settings", {}).items():
        if kat_schluessel in NICHT_SCHNEIDEND:
            continue
        kategorie = SettingDefinition(kat_schluessel, None, None)
        kategorie.deserialize(kat_daten)
        kategorien.append(kategorie)
        for definition in _flach(kategorie):
            definitionen[definition.key] = definition

    # Die Parameter des Extruders ergaenzen, soweit sie global nicht
    # vorkommen. Bei einem Extruder genuegt ein gemeinsamer Namensraum;
    # die Trennung fuer die Uebergabe an die Engine erfolgt spaeter anhand
    # der Eigenschaft settable_per_extruder.
    for kat_schluessel, kat_daten in (drucker.extruder or {}).get("settings", {}).items():
        if kat_schluessel in NICHT_SCHNEIDEND:
            continue
        kategorie = SettingDefinition(kat_schluessel, None, None)
        kategorie.deserialize(kat_daten)
        for definition in _flach(kategorie):
            if definition.key not in definitionen:
                definitionen[definition.key] = definition
                nur_extruder.append(definition.key)

    return definitionen, kategorien, nur_extruder


def _flach(definition: Any) -> List[Any]:
    """Alle Parameter unterhalb einer Kategorie, Ebenen aufgeloest."""
    gesammelt: List[Any] = []
    for kind in definition.children:
        gesammelt.append(kind)
        gesammelt.extend(_flach(kind))
    return gesammelt
