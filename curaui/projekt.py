# -*- coding: utf-8 -*-
"""Speichern und Laden eigener Einstellungen.

Gespeichert wird bewusst nur, was der Benutzer selbst geaendert hat, nicht
der gesamte Wertesatz. So bleibt eine gespeicherte Einstellung auch dann
lesbar, wenn sich in Cura ein Vorgabewert aendert -- und die Datei bleibt
ueberschaubar genug, um sie von Hand zu betrachten.

Das Format ist JSON, damit es auf beiden Betriebssystemen gleich und ohne
weitere Hilfsmittel lesbar ist.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .werte import Einstellungen, als_text, aus_text

DATEIENDUNG = ".curaui.json"
FORMATFASSUNG = 1


def speichern(pfad: str, drucker: str, umfang: str, einstellungen: Einstellungen,
              grenzen_aktiv: bool, modell: Optional[str] = None,
              profil: Optional[str] = None,
              maschine: Any = None) -> str:
    """Schreibt die Benutzeraenderungen in eine Datei."""
    if not pfad.endswith(DATEIENDUNG):
        pfad += DATEIENDUNG

    aenderungen: Dict[str, str] = {}
    for schluessel in sorted(einstellungen.benutzeraenderungen()):
        aenderungen[schluessel] = als_text(einstellungen.wert(schluessel))

    # Aenderungen, die nur einen Extruder betreffen, gesondert festhalten.
    je_extruder: List[Dict[str, str]] = []
    materialien: List[Optional[str]] = []
    duesen: List[Optional[str]] = []
    if maschine is not None:
        for nummer, stapel in enumerate(maschine.extruder):
            eigene = {k: als_text(stapel.wert(k))
                      for k in sorted(stapel.benutzeraenderungen())
                      if k != "extruder_nr"}
            je_extruder.append(eigene)
            material = maschine.materialien_je_extruder[nummer]
            materialien.append(material.kennung if material else None)
            variante = maschine.varianten_je_extruder[nummer]
            duesen.append(variante.name if variante else None)

    inhalt = {
        "format": FORMATFASSUNG,
        "erstellt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "drucker": drucker,
        "qualitaetsprofil": profil,
        "materialien": materialien,
        "duesen": duesen,
        "umfang": umfang,
        "grenzen_beachten": grenzen_aktiv,
        "modell": modell,
        "aenderungen": aenderungen,
        "aenderungen_je_extruder": je_extruder,
    }
    ordner = os.path.dirname(os.path.abspath(pfad))
    if ordner:
        os.makedirs(ordner, exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as datei:
        json.dump(inhalt, datei, indent=2, ensure_ascii=False)
    return pfad


def laden(pfad: str) -> Dict[str, Any]:
    """Liest eine gespeicherte Einstellung ein."""
    with open(pfad, "r", encoding="utf-8") as datei:
        inhalt = json.load(datei)
    if inhalt.get("format") != FORMATFASSUNG:
        raise ValueError(
            f"Unbekannte Formatfassung {inhalt.get('format')!r}; "
            f"erwartet wurde {FORMATFASSUNG}.")
    return inhalt


def anwenden(inhalt: Dict[str, Any], einstellungen: Einstellungen,
             maschine: Any = None) -> Tuple[int, List[str]]:
    """Uebertraegt gespeicherte Aenderungen auf den Wertespeicher.

    Rueckgabe: Anzahl uebernommener Werte und die Liste derer, die sich nicht
    uebernehmen liessen -- etwa weil der Parameter in der jetzt gewaehlten
    Druckerdefinition nicht vorkommt.
    """
    uebernommen = 0
    fehlgeschlagen: List[str] = []

    if maschine is not None:
        for nummer, kennung in enumerate(inhalt.get("materialien") or []):
            if kennung and nummer < maschine.anzahl_extruder \
                    and kennung in maschine.materialien:
                maschine.material_waehlen(maschine.materialien[kennung], nummer)
        for nummer, name in enumerate(inhalt.get("duesen") or []):
            if not name or nummer >= maschine.anzahl_extruder:
                continue
            for variante in maschine.varianten:
                if variante.name == name:
                    maschine.variante_waehlen(variante, nummer)
                    break
        for nummer, eigene in enumerate(inhalt.get("aenderungen_je_extruder") or []):
            if nummer >= maschine.anzahl_extruder:
                continue
            for schluessel, text in eigene.items():
                definition = einstellungen.definitionen.get(schluessel)
                if definition is None:
                    fehlgeschlagen.append(schluessel)
                    continue
                try:
                    maschine.extruder[nummer].setze(
                        schluessel, aus_text(definition, text))
                    uebernommen += 1
                except (ValueError, KeyError):
                    fehlgeschlagen.append(schluessel)

    for schluessel, text in inhalt.get("aenderungen", {}).items():
        definition = einstellungen.definitionen.get(schluessel)
        if definition is None:
            fehlgeschlagen.append(schluessel)
            continue
        try:
            einstellungen.setze(schluessel, aus_text(definition, text))
            uebernommen += 1
        except (ValueError, KeyError):
            fehlgeschlagen.append(schluessel)
    return uebernommen, fehlgeschlagen


def gespeicherte(ordner: str) -> List[Tuple[str, str]]:
    """Alle Einstellungsdateien eines Ordners als (Pfad, Anzeigename)."""
    if not os.path.isdir(ordner):
        return []
    eintraege: List[Tuple[str, str]] = []
    for name in sorted(os.listdir(ordner)):
        if name.endswith(DATEIENDUNG):
            eintraege.append((os.path.join(ordner, name),
                              name[:-len(DATEIENDUNG)]))
    return eintraege
