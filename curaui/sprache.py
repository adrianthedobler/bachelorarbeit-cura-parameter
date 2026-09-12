# -*- coding: utf-8 -*-
"""Bezeichnungen der Parameter.

Angezeigt werden standardmaessig die englischen Originalbezeichnungen aus den
Definitionsdateien -- dieselben Begriffe, unter denen die Parameter in der
Bachelorarbeit und im Sweep gefuehrt werden. Auf Wunsch laesst sich Curas
eigene Uebersetzung zuschalten.

Die Definitionsdateien enthalten nur englische Beschriftungen. Cura uebersetzt
sie zur Laufzeit ueber Katalogdateien unter resources/i18n. Dabei wird nicht
der englische Text allein nachgeschlagen, sondern zusammen mit einem
Zusammenhang: fuer die Beschriftung eines Parameters lautet dieser
"<schluessel> label", fuer den Hilfetext "<schluessel> description".

Dadurch traegt dieses Programm dieselben Bezeichnungen wie Curas Oberflaeche,
ohne dass eine eigene Uebersetzung gepflegt werden muesste.
"""
from __future__ import annotations

import gettext
import os
from typing import Any, List, Optional

from .cura_env import CuraInstallation


class Sprache:
    """Nachschlagen deutscher Beschriftungen; faellt auf Englisch zurueck."""

    def __init__(self, inst: CuraInstallation, kuerzel: str = "") -> None:
        self.kuerzel = kuerzel
        # Zwei Kataloge: der erste deckt die Parameter der Druckerdefinition
        # ab, der zweite die der Extruderdefinition (Duesenversatz,
        # Anfahrpositionen). Cura benutzt ebenfalls beide.
        self._kataloge: List[gettext.NullTranslations] = []
        ordner = os.path.join(inst.ressourcen, "i18n")
        if kuerzel and os.path.isdir(ordner):
            for name in ("fdmprinter.def.json", "fdmextruder.def.json"):
                try:
                    self._kataloge.append(gettext.translation(
                        name, localedir=ordner, languages=[kuerzel]))
                except (OSError, ValueError):
                    pass

    @property
    def vorhanden(self) -> bool:
        return bool(self._kataloge)

    def _hole(self, zusammenhang: str, englisch: str) -> str:
        if not englisch:
            return englisch
        for katalog in self._kataloge:
            uebersetzt = katalog.pgettext(zusammenhang, englisch)
            if uebersetzt != englisch:
                return uebersetzt
        return englisch

    def beschriftung(self, definition: Any) -> str:
        return self._hole(f"{definition.key} label",
                          getattr(definition, "label", "") or definition.key)

    def beschreibung(self, definition: Any) -> str:
        return self._hole(f"{definition.key} description",
                          getattr(definition, "description", "") or "")

    def auswahl(self, definition: Any, wert: str) -> str:
        """Beschriftung einer Auswahlmoeglichkeit (enum)."""
        moeglichkeiten = getattr(definition, "options", {}) or {}
        englisch = moeglichkeiten.get(wert, wert)
        return self._hole(f"{definition.key} option {wert}", englisch)

    def einheit(self, definition: Any) -> str:
        return getattr(definition, "unit", "") or ""
