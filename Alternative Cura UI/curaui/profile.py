# -*- coding: utf-8 -*-
"""Qualitaetsprofile des gewaehlten Druckers.

Eine Definitionsdatei allein gibt noch nicht die Werte wieder, die Cura beim
Hinzufuegen eines Druckers anzeigt. Fuer den Ender-3 steht in der Definition
zum Beispiel layer_height = 0.1, waehrend Cura 0.2 zeigt. Der Unterschied
stammt aus den Qualitaetsprofilen unter resources/quality.

Cura waehlt daraus anhand dreier Angaben aus der Definition aus:
  * metadata.quality_definition  -- auf welche Grunddefinition sich die
                                    Profile beziehen (Ender-3: creality_base)
  * metadata.preferred_quality_type   -- z. B. "standard"
  * metadata.preferred_variant_name / preferred_material

Dieses Modul bildet diese Auswahl nach. Findet es nichts Passendes, bleibt es
bei den Vorgabewerten der Definitionsdatei; das Programm ist dann trotzdem
benutzbar.
"""
from __future__ import annotations

import configparser
import os
from typing import Any, Dict, List, Optional, Tuple

from .cura_env import CuraInstallation
from .definitionen import Druckerdefinition
from . import werte as _werte


class Profil:
    """Ein gefundenes Qualitaetsprofil."""

    def __init__(self, name: str, quality_type: str, dateien: List[str],
                 werte: Dict[str, str]) -> None:
        self.name = name
        self.quality_type = quality_type
        self.dateien = dateien
        self.werte = werte

    def __repr__(self) -> str:
        return f"<Profil {self.name!r} ({len(self.werte)} Werte)>"


def _lies_cfg(pfad: str) -> Optional[Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]]:
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(pfad, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None
    allgemein = dict(cp.items("general")) if cp.has_section("general") else {}
    meta = dict(cp.items("metadata")) if cp.has_section("metadata") else {}
    werte = dict(cp.items("values")) if cp.has_section("values") else {}
    return allgemein, meta, werte


def _sammle_metadaten(drucker: Druckerdefinition) -> Dict[str, Any]:
    return drucker.daten.get("metadata", {})


def _qualitaetsbezug(drucker: Druckerdefinition) -> str:
    """Auf welche Definition sich die Qualitaetsprofile beziehen.

    Steht quality_definition in den Metadaten, gilt diese Angabe. Sonst
    entscheidet has_machine_quality: bringt der Drucker eigene Profile mit,
    sind es seine eigenen, andernfalls die allgemeinen von fdmprinter. Die
    CR-X ist ein Beispiel fuer den zweiten Fall.
    """
    meta = _sammle_metadaten(drucker)
    if meta.get("quality_definition"):
        return str(meta["quality_definition"])
    if meta.get("has_machine_quality"):
        return drucker.name
    return "fdmprinter"


def finde_profile(inst: CuraInstallation,
                  drucker: Druckerdefinition) -> List[Profil]:
    """Alle Qualitaetsprofile, die zu diesem Drucker passen.

    Zurueckgegeben wird je Qualitaetsstufe (quality_type) ein Profil, in dem
    die passenden Dateien bereits in der richtigen Reihenfolge verrechnet
    sind: erst die allgemeinen (ohne Duesen- und Materialangabe), dann die
    duesenspezifischen, zuletzt die material- und duesenspezifischen.
    """
    meta = _sammle_metadaten(drucker)
    bezug = _qualitaetsbezug(drucker)
    duese = str(meta.get("preferred_variant_name", "")).strip().lower()
    material = str(meta.get("preferred_material", "")).strip().lower()

    quality_wurzel = os.path.join(inst.ressourcen, "quality")
    if not os.path.isdir(quality_wurzel):
        return []

    # (quality_type) -> Liste (Rang, Dateiname, Werte, Anzeigename)
    gefunden: Dict[str, List[Tuple[int, str, Dict[str, str], str]]] = {}

    for ordner, _, dateien in os.walk(quality_wurzel):
        for datei in dateien:
            if not datei.endswith(".inst.cfg"):
                continue
            pfad = os.path.join(ordner, datei)
            gelesen = _lies_cfg(pfad)
            if gelesen is None:
                continue
            allgemein, m, werte = gelesen
            if allgemein.get("definition") != bezug:
                continue
            if m.get("type") not in (None, "quality"):
                continue
            qt = m.get("quality_type", "")
            if not qt:
                continue

            hat_variante = "variant" in m
            hat_material = "material" in m
            if hat_variante and duese and m["variant"].strip().lower() != duese:
                continue
            if hat_material and material and m["material"].strip().lower() != material:
                continue

            # Je genauer eine Datei zutrifft, desto spaeter wird sie
            # verrechnet und desto staerker wirkt sie.
            rang = (1 if hat_variante else 0) + (2 if hat_material else 0)
            gefunden.setdefault(qt, []).append(
                (rang, pfad, werte, allgemein.get("name", qt)))

    profile: List[Profil] = []
    for qt, eintraege in gefunden.items():
        eintraege.sort(key=lambda e: (e[0], e[1]))
        zusammen: Dict[str, str] = {}
        dateien: List[str] = []
        anzeigename = qt
        for rang, pfad, werte, name in eintraege:
            zusammen.update(werte)
            dateien.append(pfad)
            if rang == 0 or anzeigename == qt:
                anzeigename = name
        profile.append(Profil(anzeigename, qt, dateien, zusammen))

    reihenfolge = ["draft", "low", "fast", "standard", "normal", "dynamic",
                   "super", "high", "ultra", "adaptive"]

    def sortierung(p: Profil) -> Tuple[int, str]:
        try:
            return (reihenfolge.index(p.quality_type), p.quality_type)
        except ValueError:
            return (len(reihenfolge), p.quality_type)

    profile.sort(key=sortierung)
    return profile


def bevorzugtes_profil(drucker: Druckerdefinition,
                       profile: List[Profil]) -> Optional[Profil]:
    """Das Profil, das Cura beim Hinzufuegen des Druckers voreinstellt."""
    if not profile:
        return None
    bevorzugt = _sammle_metadaten(drucker).get("preferred_quality_type")
    for p in profile:
        if p.quality_type == bevorzugt:
            return p
    return profile[0]


def uebersetze_werte(profil: Profil, definitionen: Dict[str, Any]) -> Dict[str, Any]:
    """Wandelt die Textangaben eines Profils in benutzbare Werte um.

    Werte, die mit einem Gleichheitszeichen beginnen, sind Formeln. Sie werden
    in Curas SettingFunction umgewandelt und spaeter genauso berechnet wie die
    Formeln aus der Definitionsdatei. Der Sweep hatte solche Eintraege noch
    uebergangen, weil CuraEngine sie nicht auswerten kann -- hier ist das
    nicht noetig.
    """
    from UM.Settings.SettingFunction import SettingFunction

    ergebnis: Dict[str, Any] = {}
    for schluessel, text in profil.werte.items():
        definition = definitionen.get(schluessel)
        if definition is None:
            continue
        text = text.strip()
        if text.startswith("="):
            ergebnis[schluessel] = SettingFunction(text[1:].strip())
            continue
        try:
            ergebnis[schluessel] = _werte.aus_text(definition, text)
        except Exception:
            # Laesst sich ein Eintrag nicht deuten, wird der Vorgabewert der
            # Definitionsdatei benutzt statt das Programm abzubrechen.
            continue
    return ergebnis


# ------------------------------------------------------------- Varianten

class Variante:
    """Eine Duesenvariante (in Curas Oberflaeche die Duesenauswahl)."""

    def __init__(self, name: str, pfad: str, werte: Dict[str, str]) -> None:
        self.name = name
        self.pfad = pfad
        self.werte = werte
        self._rang = 0

    def __repr__(self) -> str:
        return f"<Variante {self.name!r}>"


def finde_varianten(inst: CuraInstallation,
                    drucker: Druckerdefinition) -> List[Variante]:
    """Alle Duesenvarianten, die zu diesem Drucker gehoeren.

    Eine Variante gilt als zugehoerig, wenn ihre Angabe "definition" auf den
    Drucker selbst oder auf eine seiner geerbten Ebenen zeigt.
    """
    # Drucker ohne wechselbare Duesen fuehren gar keine Variante; Cura legt
    # bei ihnen einen leeren Behaelter ein (in den Stapeldateien als
    # empty_variant zu sehen).
    if not _sammle_metadaten(drucker).get("has_variants"):
        return []
    wurzel = os.path.join(inst.ressourcen, "variants")
    if not os.path.isdir(wurzel):
        return []
    # Die Reihenfolge gibt an, wie genau eine Angabe zutrifft: der Drucker
    # selbst zuerst, dann seine Grunddefinitionen. Zu einer Duesengroesse
    # gibt es oft beides; Cura nimmt die genauere.
    rangfolge = [k.lower() for k in kennungen(drucker)]
    zugehoerig = set(rangfolge)
    gefunden: List[Variante] = []
    for ordner, _, dateien in os.walk(wurzel):
        for datei in dateien:
            if not datei.endswith(".inst.cfg"):
                continue
            pfad = os.path.join(ordner, datei)
            gelesen = _lies_cfg(pfad)
            if gelesen is None:
                continue
            allgemein, meta, werte = gelesen
            if meta.get("type") not in (None, "variant"):
                continue
            bezug = (allgemein.get("definition") or "").lower()
            if bezug not in zugehoerig:
                continue
            variante = Variante(allgemein.get("name", datei), pfad, werte)
            variante._rang = rangfolge.index(bezug)
            gefunden.append(variante)

    # Je Duesenname bleibt die genaueste Datei uebrig.
    beste: Dict[str, Variante] = {}
    for variante in gefunden:
        vorhanden = beste.get(variante.name)
        if vorhanden is None or variante._rang < vorhanden._rang:
            beste[variante.name] = variante
    return sorted(beste.values(), key=lambda v: v.name)


def bevorzugte_variante(drucker: Druckerdefinition,
                        varianten: List[Variante]) -> Optional[Variante]:
    """Die Duese, die Cura beim Hinzufuegen des Druckers einstellt."""
    if not varianten:
        return None
    bevorzugt = str(_sammle_metadaten(drucker).get("preferred_variant_name", "")).strip()
    for variante in varianten:
        if variante.name.strip().lower() == bevorzugt.lower():
            return variante
    return varianten[0]


def kennungen(drucker: Druckerdefinition) -> List[str]:
    """Alle Namen, unter denen dieser Drucker angesprochen wird.

    Materialdateien und Varianten verweisen mal auf die Kennung der
    Definitionsdatei, mal auf eine geerbte Grunddefinition, mal auf den
    angezeigten Namen. Deshalb werden alle drei zurueckgegeben.
    """
    meta = _sammle_metadaten(drucker)
    aus = [drucker.name, drucker.anzeigename]
    if meta.get("quality_definition"):
        aus.append(str(meta["quality_definition"]))
    aus.extend(drucker.vererbungskette)
    gesehen, ergebnis = set(), []
    for k in aus:
        if k and k not in gesehen:
            gesehen.add(k)
            ergebnis.append(k)
    return ergebnis
