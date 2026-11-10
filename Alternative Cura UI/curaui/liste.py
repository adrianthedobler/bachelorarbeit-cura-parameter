# -*- coding: utf-8 -*-
"""Eine blaetterbare Auswahlliste.

Fast jeder Bildschirm dieses Programms ist eine Liste: Drucker, Kategorien,
Parameter, Auswahlmoeglichkeiten, gespeicherte Einstellungen. Diese Klasse
uebernimmt das Gemeinsame -- Blaettern, Suchen, Auswaehlen -- und ueberlaesst
das Aussehen einer einzelnen Zeile dem Aufrufer.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

from . import terminal as t


class Auswahlliste:
    """Zeigt Eintraege an und laesst einen davon auswaehlen."""

    def __init__(self, eintraege: Sequence[Any],
                 zeichner: Callable[[Any, int, bool], str],
                 suchtext: Optional[Callable[[Any], str]] = None,
                 auswaehlbar: Optional[Callable[[Any], bool]] = None,
                 explizite_suche: bool = False) -> None:
        self.alle = list(eintraege)
        self.zeichner = zeichner
        self.suchtext = suchtext
        self.auswaehlbar = auswaehlbar
        #: Auf Bildschirmen, die eigene Buchstabenbefehle anbieten, darf das
        #: blosse Tippen nicht in die Suche laufen -- sonst waeren die Befehle
        #: nicht mehr erreichbar. Dort wird die Suche mit "/" geoeffnet.
        self.explizite_suche = explizite_suche
        self.suchmodus = not explizite_suche
        self.suche = ""
        self.zeiger = 0
        self.oben = 0
        self._gefiltert: List[Any] = list(self.alle)

    # ------------------------------------------------------------ Zustand

    @property
    def sichtbare(self) -> List[Any]:
        return self._gefiltert

    @property
    def aktueller(self) -> Optional[Any]:
        if 0 <= self.zeiger < len(self._gefiltert):
            return self._gefiltert[self.zeiger]
        return None

    def filtern(self) -> None:
        """Wendet den Suchtext an und haelt die Auswahl im gueltigen Bereich."""
        if not self.suche or self.suchtext is None:
            self._gefiltert = list(self.alle)
        else:
            begriffe = self.suche.lower().split()
            self._gefiltert = [
                e for e in self.alle
                if all(b in self.suchtext(e).lower() for b in begriffe)]
        self.zeiger = min(self.zeiger, max(0, len(self._gefiltert) - 1))
        self.oben = min(self.oben, self.zeiger)

    def eintraege_setzen(self, eintraege: Sequence[Any]) -> None:
        self.alle = list(eintraege)
        self.filtern()

    # ----------------------------------------------------------- Anzeigen

    def zeichnen(self, bildschirm: "t.Bildschirm", breite: int,
                 hoehe: int) -> None:
        """Schreibt die sichtbaren Zeilen in den Bildschirmpuffer."""
        if hoehe <= 0:
            return
        # Der Ausschnitt wandert erst mit, wenn die Auswahl ihn verlaesst.
        if self.zeiger < self.oben:
            self.oben = self.zeiger
        elif self.zeiger >= self.oben + hoehe:
            self.oben = self.zeiger - hoehe + 1
        self.oben = max(0, min(self.oben, max(0, len(self._gefiltert) - hoehe)))

        if not self._gefiltert:
            bildschirm.zeile("  " + bildschirm.f(t.GRAU, "(keine Eintraege)"))
            return

        for nummer in range(hoehe):
            stelle = self.oben + nummer
            if stelle >= len(self._gefiltert):
                bildschirm.zeile("")
                continue
            eintrag = self._gefiltert[stelle]
            ist_aktuell = stelle == self.zeiger
            zeile = self.zeichner(eintrag, breite - 2, ist_aktuell)
            if ist_aktuell:
                zeile = (bildschirm.f(t.HELLCYAN, "▸ ")
                         + (t.INVERS + t.fuellen(zeile, breite - 2) + t.NORMAL
                            if bildschirm.farbig else zeile))
            else:
                zeile = "  " + zeile
            bildschirm.zeile(zeile)

    def blaetteranzeige(self) -> str:
        """Kurzer Hinweis, an welcher Stelle der Liste man sich befindet."""
        if not self._gefiltert:
            return "0/0"
        return f"{self.zeiger + 1}/{len(self._gefiltert)}"

    # ---------------------------------------------------------- Bedienung

    def taste_verarbeiten(self, gedrueckt: str, seitenhoehe: int) -> str:
        """Verarbeitet einen Tastendruck.

        Rueckgabe: "weiter" (Liste hat die Taste verbraucht), "waehlen"
        (Eingabetaste auf einem Eintrag), "zurueck" (Escape) oder "unbekannt"
        (der Aufrufer soll sich darum kuemmern).
        """
        if gedrueckt == t.HOCH:
            self.zeiger = max(0, self.zeiger - 1)
        elif gedrueckt == t.RUNTER:
            self.zeiger = min(len(self._gefiltert) - 1, self.zeiger + 1)
        elif gedrueckt == t.BILD_HOCH:
            self.zeiger = max(0, self.zeiger - seitenhoehe)
        elif gedrueckt == t.BILD_RUNTER:
            self.zeiger = min(len(self._gefiltert) - 1, self.zeiger + seitenhoehe)
        elif gedrueckt == t.ANFANG:
            self.zeiger = 0
        elif gedrueckt == t.ENDE:
            self.zeiger = max(0, len(self._gefiltert) - 1)
        elif gedrueckt == t.EINGABE:
            if self.explizite_suche and self.suchmodus:
                # Erste Eingabetaste beendet nur die Sucheingabe; der Filter
                # bleibt bestehen, die Buchstabenbefehle wirken wieder.
                self.suchmodus = False
                return "weiter"
            eintrag = self.aktueller
            if eintrag is None:
                return "weiter"
            if self.auswaehlbar is not None and not self.auswaehlbar(eintrag):
                return "weiter"
            return "waehlen"
        elif gedrueckt == t.ESC:
            if self.suche or (self.explizite_suche and self.suchmodus):
                self.suche = ""
                self.suchmodus = not self.explizite_suche
                self.filtern()
                return "weiter"
            return "zurueck"
        elif gedrueckt == t.RUECK:
            if self.suche:
                self.suche = self.suche[:-1]
                self.filtern()
            return "weiter"
        else:
            return "unbekannt"
        return "weiter"

    def suche_oeffnen(self) -> bool:
        """Schaltet die Sucheingabe ein (nur bei expliziter Suche noetig)."""
        if self.suchtext is None:
            return False
        self.suchmodus = True
        return True

    def suchhinweis(self) -> str:
        """Zeile, die den Zustand der Suche beschreibt."""
        if self.suchmodus and self.explizite_suche:
            return f"Suche: {self.suche}▏  (Enter uebernimmt, Esc verwirft)"
        if self.suche:
            return f"Suche: {self.suche}   (Esc hebt sie auf)"
        return ""

    def suchzeichen(self, zeichen: str) -> bool:
        """Nimmt ein Zeichen in den Suchtext auf, sofern gesucht werden kann."""
        if self.suchtext is None or not self.suchmodus:
            return False
        if len(zeichen) != 1 or not (zeichen.isprintable()):
            return False
        self.suche += zeichen
        self.filtern()
        return True
