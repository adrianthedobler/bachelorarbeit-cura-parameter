# -*- coding: utf-8 -*-
"""Materialprofile.

Cura fuehrt je Extruder einen Behaelterstapel, in dem zwischen Qualitaets-
profil und Druckerdefinition zwei weitere Ebenen liegen: das Material und die
Variante (die Duese). Ohne sie fehlen unter anderem die Temperaturen und die
Einzugswerte -- beim Ender-3 zum Beispiel 200 °C statt 210 °C und ein Einzug
von 5 mm statt 6,5 mm.

Materialien liegen als XML unter resources/materials. Der Aufbau ist
geschachtelt: zuerst Grundwerte, die fuer jeden Drucker gelten, darin
Bloecke fuer einzelne Drucker und darin noch Bloecke fuer einzelne Duesen.
Der jeweils genauere Block hat Vorrang.

Die Namen im XML sind nicht die Parameternamen; die Zuordnung stammt aus
Curas eigenem Modul (share/cura/plugins/XmlMaterialProfile/XmlMaterialProfile.py,
__material_settings_setting_map).
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .cura_env import CuraInstallation

#: Zuordnung der XML-Namen zu den Parameternamen. Uebernommen aus
#: XmlMaterialProfile.__material_settings_setting_map.
XML_ZU_PARAMETER = {
    "print temperature": "default_material_print_temperature",
    "heated bed temperature": "default_material_bed_temperature",
    "standby temperature": "material_standby_temperature",
    "processing temperature graph": "material_flow_temp_graph",
    "print cooling": "cool_fan_speed",
    "retraction amount": "retraction_amount",
    "retraction speed": "retraction_speed",
    "adhesion tendency": "material_adhesion_tendency",
    "surface energy": "material_surface_energy",
    "build volume temperature": "build_volume_temperature",
    "anti ooze retract position": "material_anti_ooze_retracted_position",
    "anti ooze retract speed": "material_anti_ooze_retraction_speed",
    "break preparation position": "material_break_preparation_retracted_position",
    "break preparation speed": "material_break_preparation_speed",
    "break preparation temperature": "material_break_preparation_temperature",
    "break position": "material_break_retracted_position",
    "flush purge speed": "material_flush_purge_speed",
    "flush purge length": "material_flush_purge_length",
    "end of filament purge speed": "material_end_of_filament_purge_speed",
    "end of filament purge length": "material_end_of_filament_purge_length",
    "maximum park duration": "material_maximum_park_duration",
    "no load move factor": "material_no_load_move_factor",
    "break speed": "material_break_speed",
    "break temperature": "material_break_temperature",
}

#: Zuordnung der Eigenschaften aus dem Abschnitt <properties>.
EIGENSCHAFT_ZU_PARAMETER = {"diameter": "material_diameter"}


class Material:
    """Ein eingelesenes Materialprofil."""

    def __init__(self, kennung: str, pfad: str, wurzel: ET.Element,
                 namensraum: Dict[str, str]) -> None:
        self.kennung = kennung
        self.pfad = pfad
        self._wurzel = wurzel
        self._ns = namensraum

        metadaten = wurzel.find("m:metadata", namensraum)
        name = metadaten.find("m:name", namensraum) if metadaten is not None else None
        self.marke = _text(name, "m:brand", namensraum)
        self.art = _text(name, "m:material", namensraum)
        self.farbe = _text(name, "m:color", namensraum)
        self.guid = _text(metadaten, "m:GUID", namensraum)

        self.eigenschaften: Dict[str, str] = {}
        abschnitt = wurzel.find("m:properties", namensraum)
        if abschnitt is not None:
            for eintrag in abschnitt:
                self.eigenschaften[eintrag.tag.split("}")[-1]] = (eintrag.text or "").strip()

        try:
            self.durchmesser = float(self.eigenschaften.get("diameter", "2.85"))
        except ValueError:
            self.durchmesser = 2.85
        #: Cura unterscheidet Materialien grob nach 1,75 mm und 2,85 mm.
        self.grober_durchmesser = round(self.durchmesser)

    @property
    def anzeigename(self) -> str:
        teile = [t for t in (self.marke, self.art) if t]
        return " ".join(teile) or self.kennung

    def werte(self, druckerkennungen: Sequence[str],
              duesenname: str = "") -> Dict[str, str]:
        """Die Parameterwerte dieses Materials fuer einen bestimmten Drucker.

        Zuerst gelten die Grundwerte, danach der Block des Druckers und
        zuletzt der Block der Duese -- der jeweils genauere hat Vorrang.
        Erkannt wird ein Druckerblock ueber machine_identifier; dort steht
        je nach Datei der Name des Druckers oder die Kennung seiner
        Definitionsdatei, weshalb beides uebergeben wird.
        """
        ergebnis: Dict[str, str] = {}
        for schluessel, wert in EIGENSCHAFT_ZU_PARAMETER.items():
            if schluessel in self.eigenschaften:
                ergebnis[wert] = self.eigenschaften[schluessel]
        ergebnis["material_guid"] = self.guid
        ergebnis["material_brand"] = self.marke
        ergebnis["material_type"] = self.art

        abschnitt = self._wurzel.find("m:settings", self._ns)
        if abschnitt is None:
            return ergebnis

        ergebnis.update(self._einstellungen(abschnitt))

        gesucht = {k.strip().lower() for k in druckerkennungen if k}
        for block in abschnitt.findall("m:machine", self._ns):
            kennungen = set()
            for eintrag in block.findall("m:machine_identifier", self._ns):
                for merkmal in ("product", "name", "id"):
                    wert = eintrag.get(merkmal)
                    if wert:
                        kennungen.add(wert.strip().lower())
            if not (kennungen & gesucht):
                continue
            ergebnis.update(self._einstellungen(block))
            if duesenname:
                for duese in block.findall("m:hotend", self._ns):
                    if (duese.get("id") or "").strip().lower() == duesenname.strip().lower():
                        ergebnis.update(self._einstellungen(duese))
        return ergebnis

    def _einstellungen(self, knoten: ET.Element) -> Dict[str, str]:
        gefunden: Dict[str, str] = {}
        for eintrag in knoten.findall("m:setting", self._ns):
            schluessel = eintrag.get("key")
            if schluessel not in XML_ZU_PARAMETER:
                continue
            if schluessel == "processing temperature graph":
                punkte = []
                for punkt in eintrag.findall("m:point", self._ns):
                    try:
                        punkte.append([float(punkt.get("flow")),
                                       float(punkt.get("temperature"))])
                    except (TypeError, ValueError):
                        pass
                gefunden[XML_ZU_PARAMETER[schluessel]] = str(punkte)
            else:
                gefunden[XML_ZU_PARAMETER[schluessel]] = (eintrag.text or "").strip()
        return gefunden

    def __repr__(self) -> str:
        return f"<Material {self.kennung} ({self.anzeigename}, {self.durchmesser} mm)>"


def _text(knoten: Optional[ET.Element], pfad: str,
          namensraum: Dict[str, str]) -> str:
    if knoten is None:
        return ""
    treffer = knoten.find(pfad, namensraum)
    return (treffer.text or "").strip() if treffer is not None else ""


def lade_materialien(inst: CuraInstallation) -> Dict[str, Material]:
    """Liest alle Materialprofile ein.

    Beruecksichtigt werden die mitgelieferten Profile und die im
    Benutzerordner abgelegten; letztere haben Vorrang.
    """
    materialien: Dict[str, Material] = {}
    for ordner in _materialordner(inst):
        if not os.path.isdir(ordner):
            continue
        for datei in sorted(os.listdir(ordner)):
            if not datei.endswith(".xml.fdm_material"):
                continue
            pfad = os.path.join(ordner, datei)
            try:
                wurzel = ET.parse(pfad).getroot()
            except (ET.ParseError, OSError):
                continue
            namensraum = {"m": wurzel.tag.split("}")[0].strip("{")}
            kennung = datei[:-len(".xml.fdm_material")]
            materialien[kennung] = Material(kennung, pfad, wurzel, namensraum)
    return materialien


def _materialordner(inst: CuraInstallation) -> List[str]:
    ordner = [inst.materialien]
    eigene = os.path.expanduser(
        "~/Library/Application Support/cura/5.13/materials")
    if os.name == "nt":
        eigene = os.path.expandvars(r"%APPDATA%\cura\5.13\materials")
    ordner.append(eigene)
    return ordner


def waehle(materialien: Dict[str, Material], bevorzugt: str,
           durchmesser: float) -> Optional[Material]:
    """Sucht das Material, das Cura beim Hinzufuegen des Druckers einstellt.

    Cura fuehrt je Materialsorte mehrere Dateien, eine je Filamentstaerke
    (generic_pla fuer 2,85 mm und generic_pla_175 fuer 1,75 mm). Gewaehlt wird
    die Datei, deren Staerke zur Angabe des Druckers passt.
    """
    if not bevorzugt:
        return None
    grob = round(durchmesser)
    kandidaten = [m for kennung, m in materialien.items()
                  if kennung == bevorzugt or kennung.startswith(bevorzugt + "_")]
    passend = [m for m in kandidaten if m.grober_durchmesser == grob]
    if passend:
        # Die kuerzeste Kennung ist die Grundfassung der Sorte.
        return sorted(passend, key=lambda m: (len(m.kennung), m.kennung))[0]
    if kandidaten:
        return sorted(kandidaten, key=lambda m: (len(m.kennung), m.kennung))[0]
    return None
