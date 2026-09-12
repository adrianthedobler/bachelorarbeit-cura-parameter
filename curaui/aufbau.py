# -*- coding: utf-8 -*-
"""Zusammenbau einer Maschine aus Definition, Profil, Material und Duese.

Cura setzt die Werte einer Maschine aus mehreren Ebenen zusammen. Von oben
nach unten sind das (cura/Settings/CuraContainerStack.py, _ContainerIndexes):

    Benutzeraenderungen
    eigenes Profil          -- hier nicht benutzt
    Absicht                 -- hier nicht benutzt
    Qualitaetsprofil
    Material
    Variante (Duese)
    Aenderungen an der Definition
    Definitionsdatei

Dieses Modul stellt die Ebenen in derselben Reihenfolge zusammen, damit ein
frisch geladener Drucker dieselben Werte zeigt wie Cura nach dem Hinzufuegen.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import cura_env, definitionen, material as material_modul
from . import profile as profil_modul
from . import werte as werte_modul
from .cura_env import CuraInstallation


class Maschine:
    """Ein geladener Drucker mit allen Ebenen."""

    def __init__(self, inst: CuraInstallation, name: str,
                 materialien: Optional[Dict[str, material_modul.Material]] = None) -> None:
        self.inst = inst
        self.drucker = definitionen.lade_drucker(inst, name)
        (self.definitionen, self.kategorien,
         self.nur_extruder) = definitionen.baue_definitionen(self.drucker)

        # Der globale Stapel; die Extruderstapel greifen auf ihn zurueck.
        self.einstellungen = werte_modul.Einstellungen(self.definitionen, "global")
        self.einstellungen.maschine = self
        cura_env.registriere_formelfunktionen(self.einstellungen)

        self.anzahl_extruder = self._anzahl_extruder()
        self.extruder: List[werte_modul.Einstellungen] = [
            werte_modul.Einstellungen(self.definitionen, f"Extruder {i}",
                                      unten=self.einstellungen)
            for i in range(self.anzahl_extruder)]
        for nummer, stapel in enumerate(self.extruder):
            stapel.maschine = self
            # Jeder Extruder kennt seine eigene Nummer; einige Formeln fragen
            # sie ab (etwa die Zuordnung von Stuetzmaterial zu Extrudern).
            stapel._benutzer["extruder_nr"] = nummer

        self.profile = profil_modul.finde_profile(inst, self.drucker)
        self.profil = profil_modul.bevorzugtes_profil(self.drucker, self.profile)
        self.varianten = profil_modul.finde_varianten(inst, self.drucker)
        self.variante = profil_modul.bevorzugte_variante(self.drucker, self.varianten)

        self.materialien = (materialien if materialien is not None
                            else material_modul.lade_materialien(inst))
        # Je Extruder ein Material und eine Duese. Das Material haengt an der
        # Filamentstaerke des jeweiligen Extruders: die CR-X etwa fuehrt eine
        # Definition mit 2,85 mm, ihre beiden Extruder aber 1,75 mm.
        self.materialien_je_extruder = [
            self._bevorzugtes_material(nummer)
            for nummer in range(self.anzahl_extruder)]
        self.material = self.materialien_je_extruder[0]
        self.varianten_je_extruder = [self.variante] * self.anzahl_extruder

        #: Vorgabewerte des gewaehlten Parameterumfangs (etwa der
        #: Beton-Auswahl). Sie liegen ueber dem Qualitaetsprofil, aber unter
        #: den eigenen Aenderungen: der Parameter bleibt frei einstellbar.
        self.auswahlvorgaben: Dict[str, Any] = {}

        self.ebenen_setzen()

    def _anzahl_extruder(self) -> int:
        """Wie viele Extruder dieser Drucker hat.

        Massgeblich ist machine_extruder_count aus der Definition; die Anzahl
        der hinterlegten Extruderdateien dient als Gegenprobe.
        """
        definition = self.definitionen.get("machine_extruder_count")
        try:
            anzahl = max(1, int(float(getattr(definition, "default_value", 1))))
        except (TypeError, ValueError):
            anzahl = 1
        return max(anzahl, len(self.drucker.extruderliste) or 1)

    # ------------------------------------------------------- Extruderzugriff

    def extruderstapel(self, nummer: int) -> Optional[werte_modul.Einstellungen]:
        """Der Stapel eines Extruders, oder None bei ungueltiger Nummer."""
        if 0 <= nummer < len(self.extruder):
            return self.extruder[nummer]
        return None

    def aktive_extruderstapel(self) -> List[werte_modul.Einstellungen]:
        """Die Stapel der eingeschalteten Extruder.

        extruderValues() in den Formeln bezieht sich auf genau diese. Wie
        viele eingeschaltet sind, sagt extruders_enabled_count.
        """
        anzahl = len(self.extruder)
        definition = self.definitionen.get("extruders_enabled_count")
        if definition is not None:
            roh = self.einstellungen._explizit("extruders_enabled_count")
            if roh is not None:
                try:
                    anzahl = max(1, min(len(self.extruder), int(float(roh))))
                except (TypeError, ValueError):
                    pass
        return self.extruder[:anzahl]

    def erster_extruder(self) -> str:
        return "0"

    # ------------------------------------------------------------- Material

    def _bevorzugtes_material(self, extruder: int = 0) -> Optional[material_modul.Material]:
        meta = self.drucker.daten.get("metadata", {})
        bevorzugt = str(meta.get("preferred_material", "")).strip()
        return material_modul.waehle(self.materialien, bevorzugt,
                                     self.durchmesser(extruder))

    def durchmesser(self, extruder: int = 0) -> float:
        """Die Filamentstaerke eines Extruders.

        Vorrang hat die Angabe in der Extruderdefinition; erst wenn dort
        nichts steht, gilt die der Druckerdefinition.
        """
        if 0 <= extruder < len(self.drucker.extruderliste):
            eigene = definitionen.vorgabewerte(self.drucker.extruderliste[extruder])
            if "material_diameter" in eigene:
                try:
                    return float(eigene["material_diameter"])
                except (TypeError, ValueError):
                    pass
        definition = self.definitionen.get("material_diameter")
        try:
            return float(getattr(definition, "default_value", 1.75))
        except (TypeError, ValueError):
            return 1.75

    def _durchmesser_aus_definition(self) -> float:
        return self.durchmesser(0)

    def materialliste(self) -> List[material_modul.Material]:
        """Die Materialien, die zur Filamentstaerke dieses Druckers passen."""
        grob = round(self.durchmesser(0))
        passend = [m for m in self.materialien.values()
                   if m.grober_durchmesser == grob]
        return sorted(passend, key=lambda m: (m.marke.lower(), m.art.lower(),
                                              m.kennung))

    # --------------------------------------------------------------- Ebenen

    def ebenen_setzen(self) -> None:
        """Legt die Ebenen des globalen Stapels und aller Extruder ein.

        Wichtig ist die Aufteilung: Material und Duese gehoeren zum Extruder,
        nicht zur Maschine. Curas globaler Stapel fuehrt an diesen Stellen
        leere Behaelter (in den Stapeldateien als empty_material und
        empty_variant zu sehen). Wuerde man das Material auch global
        einlegen, entstuenden dort andere Temperaturen und Einzugswerte als
        bei Cura.
        """
        global_ebenen: List[Tuple[str, Dict[str, Any]]] = []
        if self.auswahlvorgaben:
            global_ebenen.append(("Auswahl", self._deuten(self.auswahlvorgaben)))
        if self.profil is not None:
            global_ebenen.append(
                ("Qualitaetsprofil",
                 profil_modul.uebersetze_werte(self.profil, self.definitionen)))
        # Der globale Stapel fuehrt kein Material. Cura legt dort einen leeren
        # Behaelter ein, dessen Angaben trotzdem uebergeben werden.
        global_ebenen.append(("leeres Material", {
            "material_guid": "", "material_brand": "empty_brand",
            "material_type": "empty"}))
        self.einstellungen.setze_ebenen(global_ebenen)

        for nummer, stapel in enumerate(self.extruder):
            ebenen: List[Tuple[str, Dict[str, Any]]] = []
            if self.auswahlvorgaben:
                ebenen.append(("Auswahl", self._deuten(self.auswahlvorgaben)))
            if self.profil is not None:
                ebenen.append(("Qualitaetsprofil",
                               profil_modul.uebersetze_werte(self.profil,
                                                             self.definitionen)))
            material = self.materialien_je_extruder[nummer]
            variante = self.varianten_je_extruder[nummer]
            if material is not None:
                werte = material.werte(profil_modul.kennungen(self.drucker),
                                       variante.name if variante else "")
                ebenen.append(("Material", self._deuten(werte)))
            if variante is not None:
                ebenen.append(("Duese", self._deuten(variante.werte)))
            # Zuunterst die Definition dieses Extruders. Sie beschreibt, was
            # nur ihn betrifft: Duesenversatz, eigener Start- und End-G-Code,
            # Filamentstaerke.
            if nummer < len(self.drucker.extruderliste):
                eigene = definitionen.vorgabewerte(self.drucker.extruderliste[nummer])
                ebenen.append(("Extruderdefinition", self._deuten(eigene)))
            stapel.setze_ebenen(ebenen)

    def _deuten(self, werte: Dict[str, str]) -> Dict[str, Any]:
        """Wandelt Textangaben einer Ebene in Werte des passenden Typs."""
        ergebnis: Dict[str, Any] = {}
        for schluessel, text in werte.items():
            definition = self.definitionen.get(schluessel)
            if definition is None:
                continue
            try:
                ergebnis[schluessel] = werte_modul.aus_text(definition, str(text))
            except (ValueError, TypeError):
                continue
        return ergebnis

    # ------------------------------------------------------------ Auswahlen

    def vorgaben_setzen(self, vorgaben: Dict[str, Any]) -> None:
        """Legt die Vorgabewerte des gewaehlten Parameterumfangs ein.

        Sie werden als eigene Ebene gefuehrt und nicht als Benutzeraenderung,
        damit sie beim Umschalten des Umfangs restlos wieder verschwinden und
        in der Liste nicht wie ein selbst gesetzter Wert aussehen.
        """
        self.auswahlvorgaben = dict(vorgaben or {})
        self.ebenen_setzen()

    def profil_waehlen(self, profil: profil_modul.Profil) -> None:
        self.profil = profil
        self.ebenen_setzen()

    def material_waehlen(self, material: material_modul.Material,
                         extruder: Optional[int] = None) -> None:
        if extruder is None:
            self.material = material
            self.materialien_je_extruder = [material] * self.anzahl_extruder
        else:
            self.materialien_je_extruder[extruder] = material
        self.ebenen_setzen()

    def variante_waehlen(self, variante: profil_modul.Variante,
                         extruder: Optional[int] = None) -> None:
        if extruder is None:
            self.variante = variante
            self.varianten_je_extruder = [variante] * self.anzahl_extruder
        else:
            self.varianten_je_extruder[extruder] = variante
        self.ebenen_setzen()

    @property
    def definitionsdatei(self) -> str:
        import os
        return os.path.join(self.inst.definitionen, self.drucker.name + ".def.json")

    def __repr__(self) -> str:
        return f"<Maschine {self.drucker.anzeigename}>"
