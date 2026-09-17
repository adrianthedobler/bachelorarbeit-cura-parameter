# -*- coding: utf-8 -*-
"""Die textbasierte Nutzeroberflaeche."""
from __future__ import annotations

import html
import os
import re
import textwrap
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import aufbau
from . import auswahl as auswahl_modul
from . import cura_env, definitionen, engine, projekt
from . import profile as profil_modul
from . import terminal as t
from . import werte as werte_modul
from .liste import Auswahlliste
from .sprache import Sprache

PROGRAMMORDNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUSGABEORDNER = os.path.join(PROGRAMMORDNER, "ausgabe")
EINSTELLUNGSORDNER = os.path.join(PROGRAMMORDNER, "einstellungen")


def klartext(text: str, ) -> str:
    """Entfernt die HTML-Auszeichnung aus Curas Hilfetexten.

    Einige Beschreibungen in fdmprinter.def.json sind als HTML abgefasst
    (Aufzaehlungen bei den Fuellmustern zum Beispiel). Im Terminal wuerde das
    unlesbar dargestellt.
    """
    if not text:
        return ""
    text = re.sub(r"<\s*li\s*>", "\n  - ", text, flags=re.I)
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<\s*/\s*(p|ul|ol)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class Anwendung:
    """Haelt den Zustand und steuert die Bildschirme."""

    def __init__(self, cura_pfad: Optional[str] = None,
                 sprachkuerzel: str = "") -> None:
        self.inst = cura_env.vorbereiten(cura_pfad)
        self.sprache = Sprache(self.inst, sprachkuerzel)
        self.farbig = t.farben_moeglich()

        self.maschine: Optional[aufbau.Maschine] = None
        #: Die Materialprofile werden einmal eingelesen und weiterverwendet.
        self._materialien = None
        self.drucker: Optional[definitionen.Druckerdefinition] = None
        self.definitionen: Dict[str, Any] = {}
        self.kategorien: List[Any] = []
        self.nur_extruder: List[str] = []
        #: Zwischenspeicher fuer _maschinenparameter(); je Drucker neu.
        self._maschinen_zwischenspeicher: Optional[Set[str]] = None
        self.einstellungen: Optional[werte_modul.Einstellungen] = None
        self.profile: List[profil_modul.Profil] = []
        self.profil: Optional[profil_modul.Profil] = None

        self.umfaenge = auswahl_modul.lade_umfaenge()
        self.umfang = self.umfaenge[0]
        self.grenzen_beachten = True

        self.modell: Optional[str] = None
        self.letztes_ergebnis: Optional[engine.Ergebnis] = None
        self.meldung = ""
        self.meldung_farbe = t.GRUEN

    # ------------------------------------------------------------ Anzeige

    def _neu(self) -> t.Bildschirm:
        return t.Bildschirm(self.farbig)

    def _kopf(self, b: t.Bildschirm, titel: str, unterzeile: str = "") -> None:
        breite, _ = t.groesse()
        links = f" {titel}"
        rechts = ""
        if self.drucker:
            rechts = f"{self.drucker.anzeigename} "
            if self.maschine and self.maschine.material:
                rechts = f"{self.maschine.material.anzeigename} · " + rechts
            if self.profil:
                rechts = f"{self.profil.name} · " + rechts
        platz = breite - t.sichtbare_laenge(links) - t.sichtbare_laenge(rechts)
        b.zeile(b.f(t.FETT + t.HELLCYAN, links) + " " * max(1, platz)
                + b.f(t.GRAU, rechts))
        if unterzeile:
            b.zeile(b.f(t.GRAU, " " + unterzeile))
        b.zeile(b.f(t.GRAU, "─" * breite))

    def _fuss(self, b: t.Bildschirm, tasten: Sequence[Tuple[str, str]],
              zusatz: str = "") -> None:
        breite, _ = t.groesse()
        b.zeile(b.f(t.GRAU, "─" * breite))
        if self.meldung:
            b.zeile(" " + b.f(self.meldung_farbe, self.meldung))
        else:
            b.zeile(" " + b.f(t.GRAU, zusatz))
        teile = [f"{b.f(t.HELLGELB, k)} {n}" for k, n in tasten]
        b.zeile(" " + b.f(t.GRAU, "  ").join(teile))

    def _sagen(self, text: str, farbe: str = t.GRUEN) -> None:
        self.meldung = text
        self.meldung_farbe = farbe

    def _warte_unten(self, text: str, farbe: str = t.GRAU) -> str:
        breite, hoehe = t.groesse()
        import sys
        sys.stdout.write(f"\x1b[{hoehe};1H" + t.ZEILE_LOESCHEN
                         + (farbe + " " + text + t.NORMAL if self.farbig
                            else " " + text))
        sys.stdout.flush()
        return t.taste()

    def _bestaetigen(self, frage: str, farbe: str = t.GRAU) -> bool:
        """Rueckfrage in der untersten Zeile.

        Ueber farbe laesst sich eine folgenschwere Rueckfrage hervorheben;
        in der grauen Vorgabe geht sie sonst in der Fusszeile unter.
        """
        antwort = self._warte_unten(frage + " [j/n] ", farbe)
        return antwort.lower() in ("j", "y")

    # -------------------------------------------------------------- Start

    def starten(self) -> None:
        t.start()
        try:
            if not self._drucker_waehlen(erstmalig=True):
                return
            self._hauptschleife()
        except KeyboardInterrupt:
            pass
        finally:
            t.ende()

    # ---------------------------------------------------- Druckerauswahl

    def _drucker_waehlen(self, erstmalig: bool = False) -> bool:
        eintraege = definitionen.liste_drucker(self.inst)
        # Der Drucker der Bachelorarbeit steht oben, danach alle uebrigen.
        eintraege.sort(key=lambda e: (e[0] != "creality_ender3",
                                      e[2].lower(), e[1].lower()))

        def zeichnen(eintrag: Tuple[str, str, str], breite: int,
                     aktuell: bool) -> str:
            name, anzeige, hersteller = eintrag
            links = t.fuellen(anzeige, min(46, breite - 24))
            return t.kuerzen(f"{links}  {hersteller}", breite)

        liste = Auswahlliste(
            eintraege, zeichnen,
            suchtext=lambda e: f"{e[1]} {e[2]} {e[0]}")

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Drucker waehlen",
                       f"{len(eintraege)} Definitionen aus {self.inst.definitionen}")
            listenhoehe = hoehe - 8
            liste.zeichnen(b, breite, listenhoehe)
            b.zeile()
            zusatz = (liste.suchhinweis()
                      or "Tippen sucht im Namen · " + liste.blaetteranzeige())
            tasten = [("↑↓", "waehlen"), ("Enter", "uebernehmen")]
            if not erstmalig:
                tasten.append(("Esc", "zurueck"))
            self._fuss(b, tasten, zusatz)
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
            if ergebnis == "waehlen":
                name = liste.aktueller[0]
                self._drucker_laden(name)
                return True
            if ergebnis == "zurueck":
                if erstmalig:
                    return False
                return True
            if ergebnis == "unbekannt":
                liste.suchzeichen(gedrueckt)

    def _drucker_laden(self, name: str) -> None:
        """Laedt eine Druckerdefinition und setzt alle Werte neu auf."""
        alte_aenderungen = (self._eigene_aenderungswerte()
                            if self.einstellungen else {})

        self.maschine = aufbau.Maschine(self.inst, name, self._materialien)
        self._materialien = self.maschine.materialien
        self.drucker = self.maschine.drucker
        self.definitionen = self.maschine.definitionen
        self.kategorien = self.maschine.kategorien
        self.nur_extruder = self.maschine.nur_extruder
        self._maschinen_zwischenspeicher = None
        self.einstellungen = self.maschine.einstellungen
        self.profile = self.maschine.profile
        self.profil = self.maschine.profil

        self._vorgaben_anwenden()

        uebernommen = 0
        for schluessel, wert in alte_aenderungen.items():
            if schluessel in self.definitionen:
                self._eingabe_setzen(schluessel, wert)
                uebernommen += 1

        fehlend = auswahl_modul.fehlende(self.umfang, self.definitionen)
        hinweis = f"{self.drucker.anzeigename} geladen"
        if self.maschine.anzahl_extruder > 1:
            hinweis += f" ({self.maschine.anzahl_extruder} Extruder)"
        if uebernommen:
            hinweis += f", {uebernommen} Aenderungen uebernommen"
        if fehlend:
            hinweis += f" ({len(fehlend)} Parameter der Auswahl fehlen hier)"
        self._sagen(hinweis)

    # ------------------------------------------------------- Hauptbildschirm

    def _kategorie_zeilen(self, bereich: Optional[str] = None) -> List[Any]:
        """Die Kategorien mit Angabe, wie viele Parameter sichtbar sind."""
        zeilen = []
        for kategorie in self._alle_kategorien():
            schluessel = self._parameter_der_kategorie(kategorie, bereich)
            if not schluessel:
                continue
            aktiv = sum(1 for s in schluessel if self._stapel(s).aktiviert(s))
            geaendert = sum(1 for s in schluessel
                            if self._geaendert(s))
            zeilen.append((kategorie, len(schluessel), aktiv, geaendert))
        return zeilen

    #: Diese Kategorie beschreibt den Drucker selbst (Bauraum, Duese,
    #: Start- und End-G-Code). Sie bildet einen eigenen Geltungsbereich und
    #: folgt nicht dem gewaehlten Umfang: Im Sweep von Kapitel 4 wurde sie
    #: nicht geprueft, weil dort nur Schnitteinstellungen untersucht wurden.
    MASCHINENKATEGORIE = "machine_settings"

    #: Die vier Geltungsbereiche, nach denen die Parameter geordnet werden.
    #: Curas Definitionsdateien fuehren dafuer zwei Eigenschaften:
    #: settable_per_mesh (je Modell einstellbar) und settable_per_extruder
    #: (darf sich zwischen Extrudern unterscheiden). Sie schliessen einander
    #: nicht aus -- fast alles, was je Modell einstellbar ist, ist es auch je
    #: Extruder. Es gilt deshalb die hier festgelegte Rangfolge; jeder
    #: Parameter erscheint in genau einem Bereich.
    BEREICHE = (
        ("mesh", "Mesh",
         "Je Modell einstellbar (settable_per_mesh). Diese Parameter lassen "
         "sich in Cura fuer ein einzelnes Objekt abweichend setzen."),
        ("extruder", "Extruder",
         "Je Extruder einstellbar (settable_per_extruder). Der Wert darf "
         "sich zwischen zwei Extrudern unterscheiden."),
        ("global", "Global",
         "Gilt fuer den gesamten Druck. Weder je Modell noch je Extruder "
         "einstellbar."),
        ("maschine", "Machine Settings",
         "Beschreiben den Drucker selbst: Bauraum, Duese, Achsen, Start- "
         "und End-G-Code. Sie folgen nicht dem gewaehlten Umfang."),
    )

    def _geltungsbereich(self, schluessel: str) -> str:
        """Der Bereich, in dem ein Parameter angeboten wird."""
        if schluessel in self._maschinenparameter():
            return "maschine"
        definition = self.definitionen.get(schluessel)
        if getattr(definition, "settable_per_mesh", False):
            return "mesh"
        if getattr(definition, "settable_per_extruder", False):
            return "extruder"
        return "global"

    def _maschinenparameter(self) -> Set[str]:
        """Alle Parameter, die den Drucker beschreiben.

        Das sind die der Kategorie machine_settings und diejenigen, die es
        nur in der Extruderdefinition gibt (Duesenversatz, Anfahrpositionen).
        """
        if self._maschinen_zwischenspeicher is None:
            gesammelt = set(self.nur_extruder)
            for kategorie in self.kategorien:
                if kategorie.key != self.MASCHINENKATEGORIE:
                    continue
                for definition in definitionen._flach(kategorie):
                    gesammelt.add(definition.key)
            self._maschinen_zwischenspeicher = gesammelt
        return self._maschinen_zwischenspeicher

    def _parameter_der_kategorie(self, kategorie: Any,
                                 bereich: Optional[str] = None) -> List[str]:
        """Die anzubietenden Parameter einer Kategorie.

        Mit bereich wird zusaetzlich auf einen Geltungsbereich eingeschraenkt.
        Die Maschinenparameter folgen dem gewaehlten Umfang nicht.
        """
        gefunden = []
        for definition in definitionen._flach(kategorie):
            if definition.type == "category":
                continue
            eigener = self._geltungsbereich(definition.key)
            if bereich is not None and eigener != bereich:
                continue
            if eigener != "maschine" and not self.umfang.enthaelt(definition.key):
                continue
            gefunden.append(definition.key)
        if (kategorie.key == self.MASCHINENKATEGORIE
                and bereich in (None, "maschine")):
            # Die Parameter aus der Extruderdefinition (Duesenversatz,
            # Anfahrpositionen) gehoeren zu keiner Kategorie der
            # Druckerdefinition und werden hier angehaengt.
            gefunden.extend(s for s in self.nur_extruder if s not in gefunden)
        return gefunden

    def _parameter_des_bereichs(self, bereich: str) -> List[str]:
        """Alle Parameter eines Geltungsbereichs, ueber alle Kategorien."""
        gefunden: List[str] = []
        for kategorie in self._alle_kategorien():
            gefunden.extend(self._parameter_der_kategorie(kategorie, bereich))
        return gefunden

    def _alle_kategorien(self) -> List[Any]:
        """Curas Kategorien; die Maschinenkategorie steht hinten."""
        return ([k for k in self.kategorien if k.key != self.MASCHINENKATEGORIE]
                + [k for k in self.kategorien if k.key == self.MASCHINENKATEGORIE])

    # ------------------------------------------------------- Hauptmenue

    def _hauptmenue_zeilen(self) -> List[Tuple[str, str, str]]:
        """Die fuenf Eintraege des Hauptmenues mit ihrem Zustand."""
        drucker = self.drucker.anzeigename if self.drucker else "keiner"
        duesen = {v.name for v in self.maschine.varianten_je_extruder if v}
        if duesen:
            drucker += " · " + " / ".join(sorted(duesen))

        materialien = [m.anzeigename if m else "keines"
                       for m in self.maschine.materialien_je_extruder]
        material = " / ".join(dict.fromkeys(materialien))

        modell = os.path.basename(self.modell) if self.modell else "keines"
        profil = self.profil.name if self.profil else "keines"

        angeboten = sum(len(self._parameter_des_bereichs(kennung))
                        for kennung, _name, _text in self.BEREICHE)
        geaendert = len(self._eigene_aenderungen())
        parameter = f"{angeboten} angeboten"
        if geaendert:
            parameter += f", {geaendert} geaendert"

        return [
            ("hardware", "Hardware", drucker),
            ("material", "Material", material),
            ("modell", "Modell", modell),
            ("profil", "Profil", profil),
            ("parameter", "Parameter", parameter),
        ]

    def _hauptschleife(self) -> None:
        def zeichnen(zeile: Tuple[str, str, str], breite: int,
                     aktuell: bool) -> str:
            _kennung, name, zustand = zeile
            links = t.fuellen(name, 16)
            return t.kuerzen(f"{links}  {zustand}", breite)

        liste = Auswahlliste([], zeichnen,
                             suchtext=lambda z: z[1],
                             explizite_suche=True)
        liste.eintraege_setzen(self._hauptmenue_zeilen())

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            grenzen = "beachtet" if self.grenzen_beachten else "AUSGESCHALTET"
            self._kopf(b, "Alternative Cura-Oberflaeche",
                       f"Umfang: {self.umfang.name} · Grenzen: {grenzen}")
            b.zeile()
            liste.zeichnen(b, breite, len(liste.alle))
            b.zeile()
            self._fuss(b, [("Enter", "oeffnen"), ("s", "Slicen"),
                           ("u", "Umfang"), ("g", "Grenzen"),
                           ("f", "Parameter suchen"),
                           ("^s", "speichern"), ("^o", "laden"),
                           ("?", "Hilfe"), ("Esc", "Ende")],
                       liste.suchhinweis() or "Enter oeffnet den Eintrag")
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, len(liste.alle))
            if ergebnis == "waehlen":
                self._hauptmenue_oeffnen(liste.aktueller[0])
                liste.eintraege_setzen(self._hauptmenue_zeilen())
                continue
            if ergebnis == "zurueck":
                if self._bestaetigen("Programm beenden?"):
                    return
                continue
            if ergebnis != "unbekannt":
                continue

            if liste.suchzeichen(gedrueckt):
                continue
            if gedrueckt == "/":
                liste.suche_oeffnen()
                continue

            if gedrueckt == "s":
                self._slicen()
            elif gedrueckt == "u":
                self._umfang_waehlen()
            elif gedrueckt == "g":
                self._grenzen_umschalten()
            elif gedrueckt == "f":
                self._parameter_suchen()
            elif gedrueckt == "\x13":                     # Strg+S
                self._speichern()
            elif gedrueckt == "\x0f":                     # Strg+O
                self._laden()
            elif gedrueckt == "?":
                self._hilfe()
            liste.eintraege_setzen(self._hauptmenue_zeilen())

    def _hauptmenue_oeffnen(self, kennung: str) -> None:
        if kennung == "hardware":
            self._hardware_menue()
        elif kennung == "material":
            self._material_waehlen()
        elif kennung == "modell":
            self._modell_waehlen()
        elif kennung == "profil":
            self._profil_waehlen()
        elif kennung == "parameter":
            self._bereich_menue()

    # ------------------------------------------------------------ Hardware

    def _hardware_menue(self) -> None:
        """Drucker und Duese -- was das Geraet ausmacht."""
        def zeilen() -> List[Tuple[str, str, str]]:
            duesen = {v.name for v in self.maschine.varianten_je_extruder if v}
            return [
                ("drucker", "Drucker",
                 self.drucker.anzeigename if self.drucker else "keiner"),
                ("duese", "Duese",
                 " / ".join(sorted(duesen)) if duesen
                 else "keine wechselbare Duese"),
            ]

        def zeichnen(zeile: Tuple[str, str, str], breite: int,
                     aktuell: bool) -> str:
            return t.kuerzen(f"{t.fuellen(zeile[1], 12)}  {zeile[2]}", breite)

        liste = Auswahlliste(zeilen(), zeichnen)
        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Hardware",
                       "Das Geraet: Druckerdefinition und Duese")
            b.zeile()
            liste.zeichnen(b, breite, len(liste.alle))
            b.zeile()
            b.zeile("  " + b.f(t.GRAU,
                    "Die Parameter des Geraets stehen unter "
                    "Parameter → Machine Settings."))
            self._fuss(b, [("Enter", "waehlen"), ("Esc", "zurueck")])
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, len(liste.alle))
            if ergebnis == "waehlen":
                if liste.aktueller[0] == "drucker":
                    self._drucker_waehlen()
                else:
                    self._duese_waehlen()
                liste.eintraege_setzen(zeilen())
                continue
            if ergebnis == "zurueck":
                return

    # ----------------------------------------------------- Geltungsbereiche

    def _bereich_menue(self) -> None:
        """Die vier Geltungsbereiche als Zwischenebene."""
        def zeilen() -> List[Any]:
            gesammelt = []
            for kennung, name, beschreibung in self.BEREICHE:
                schluessel = self._parameter_des_bereichs(kennung)
                if not schluessel:
                    continue
                geaendert = sum(1 for s in schluessel
                                if self._geaendert(s))
                gesammelt.append((kennung, name, beschreibung,
                                  len(schluessel), geaendert))
            return gesammelt

        def zeichnen(zeile: Any, breite: int, aktuell: bool) -> str:
            _kennung, name, _text, anzahl, geaendert = zeile
            rechts = f"{anzahl:>3} Parameter"
            if geaendert:
                rechts += f", {geaendert} geaendert"
            return t.kuerzen(f"{t.fuellen(name, 18)}  {rechts}", breite)

        liste = Auswahlliste(zeilen(), zeichnen, suchtext=lambda z: z[1])
        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Parameter",
                       f"Umfang: {self.umfang.name}")
            b.zeile()
            liste.zeichnen(b, breite, len(liste.alle))
            b.zeile()
            aktuell = liste.aktueller
            if aktuell:
                for zeile in textwrap.wrap(aktuell[2], breite - 4)[:3]:
                    b.zeile("  " + b.f(t.GRAU, zeile))
            self._fuss(b, [("Enter", "oeffnen"), ("f", "ueber alles suchen"),
                           ("Esc", "zurueck")])
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, len(liste.alle))
            if ergebnis == "waehlen":
                self._kategorie_menue(liste.aktueller[0], liste.aktueller[1])
                liste.eintraege_setzen(zeilen())
                continue
            if ergebnis == "zurueck":
                return
            if ergebnis == "unbekannt" and gedrueckt == "f":
                self._parameter_suchen()
                liste.eintraege_setzen(zeilen())

    def _kategorie_menue(self, bereich: str, bereichsname: str) -> None:
        """Curas Kategorien innerhalb eines Geltungsbereichs."""
        def zeichnen(zeile: Any, breite: int, aktuell: bool) -> str:
            kategorie, gesamt, aktiv, geaendert = zeile
            name = self.sprache.beschriftung(kategorie)
            links = t.fuellen(name, min(40, breite - 34))
            rechts = f"{gesamt:>3} Parameter, {aktiv:>3} zurzeit wirksam"
            if geaendert:
                rechts += f", {geaendert} geaendert"
            return t.kuerzen(f"{links}  {rechts}", breite)

        liste = Auswahlliste(self._kategorie_zeilen(bereich), zeichnen,
                             suchtext=lambda z: self.sprache.beschriftung(z[0]),
                             explizite_suche=True)
        if not liste.alle:
            self._sagen("In diesem Bereich ist kein Parameter des gewaehlten "
                        "Umfangs enthalten.", t.GELB)
            return

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, f"Parameter · {bereichsname}",
                       f"Umfang: {self.umfang.name}")
            listenhoehe = hoehe - 8
            liste.zeichnen(b, breite, listenhoehe)
            b.zeile()
            self._fuss(b, [("Enter", "oeffnen"), ("/", "suchen"),
                           ("s", "Slicen"), ("Esc", "zurueck")],
                       liste.suchhinweis() or "Enter oeffnet eine Kategorie")
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
            if ergebnis == "waehlen":
                self._kategorie_anzeigen(liste.aktueller[0], bereich,
                                         bereichsname)
                liste.eintraege_setzen(self._kategorie_zeilen(bereich))
                continue
            if ergebnis == "zurueck":
                return
            if ergebnis != "unbekannt":
                continue
            if liste.suchzeichen(gedrueckt):
                continue
            if gedrueckt == "/":
                liste.suche_oeffnen()
            elif gedrueckt == "s":
                self._slicen()

    # ------------------------------------------------------ Parameterliste

    def _stapel(self, schluessel: str) -> werte_modul.Einstellungen:
        """Der Stapel, dessen Wert fuer diesen Parameter an die Engine geht.

        Parameter mit settable_per_extruder werden aus dem Extruderstapel
        uebergeben (engine.teile_werte). Dort liegen Material und Duese; der
        globale Stapel fuehrt an diesen Stellen leere Behaelter. Angezeigt
        werden muss deshalb der Wert des Extruders -- sonst stuende etwa bei
        Printing Temperature der Vorgabewert der Definition (210 °C) in der
        Liste, geschnitten wuerde aber mit dem Wert des Materials (200 °C).
        Bei mehreren Extrudern gilt die Anzeige dem ersten; so verfaehrt auch
        Curas Oberflaeche, die den gerade aktiven Extruder zeigt.
        """
        definition = self.definitionen.get(schluessel)
        if (self.maschine is not None and self.maschine.extruder
                and getattr(definition, "settable_per_extruder", False)):
            return self.maschine.extruder[0]
        return self.einstellungen

    def _eingabe_setzen(self, schluessel: str, wert: Any) -> None:
        """Uebernimmt eine Eingabe aus der Oberflaeche.

        Alle Aenderungen der Oberflaeche laufen ueber diese Methode; das
        Pruefskript pruefung/abgleich.py benutzt sie ebenfalls, damit es
        denselben Eingabeweg prueft.

        Parameter mit settable_per_extruder legt Cura im Stapel des Extruders
        ab, nicht im globalen (nachweisbar am Einstellungsblock ;SETTING_3 im
        G-Code). Das ist mehr als eine Formsache: Traegt der Extruderstapel
        selbst einen Wert -- etwa Wall Thickness aus dem Qualitaetsprofil --,
        dann verdeckt dieser eine Eingabe im globalen Stapel, und die Engine
        erhielte den alten Wert. Die Oberflaeche zeigt den ersten Extruder;
        dorthin geht die Eingabe.
        """
        stapel = self._stapel(schluessel)
        if stapel is self.einstellungen:
            self.einstellungen.setze(schluessel, wert)
            return
        stapel.setze(schluessel, wert)
        # Eine aeltere Eingabe im globalen Stapel entfernen, damit dort
        # wieder derselbe Wert steht wie in Cura.
        if self.einstellungen.ist_geaendert(schluessel):
            self.einstellungen.zuruecksetzen(schluessel)

    def _eingabe_zuruecksetzen(self, schluessel: str) -> None:
        """Nimmt eine eigene Eingabe zurueck -- global und im Extruder."""
        for stapel in (self.einstellungen, self._stapel(schluessel)):
            if schluessel != "extruder_nr" and stapel.ist_geaendert(schluessel):
                stapel.zuruecksetzen(schluessel)

    def _eigene_aenderungswerte(self) -> Dict[str, Any]:
        """Alle eigenen Eingaben mit Wert, globale und die des ersten Extruders."""
        werte = dict(self.einstellungen.benutzeraenderungen())
        if self.maschine is not None and self.maschine.extruder:
            for schluessel, wert in self.maschine.extruder[0].benutzeraenderungen().items():
                # extruder_nr setzt der Zusammenbau selbst, keine Eingabe.
                if schluessel != "extruder_nr":
                    werte[schluessel] = wert
        return werte

    def _eigene_aenderungen(self) -> List[str]:
        return sorted(self._eigene_aenderungswerte())

    def _alle_eingaben_zuruecksetzen(self) -> None:
        """Verwirft alle eigenen Eingaben in allen Stapeln."""
        self.einstellungen.alles_zuruecksetzen()
        if self.maschine is not None:
            for stapel in self.maschine.extruder:
                for schluessel in list(stapel.benutzeraenderungen()):
                    if schluessel != "extruder_nr":
                        stapel.zuruecksetzen(schluessel)

    def _geaendert(self, schluessel: str) -> bool:
        """Ob der Wert selbst gesetzt wurde -- global oder im Extruder."""
        if schluessel == "extruder_nr":
            return self.einstellungen.ist_geaendert(schluessel)
        return (self.einstellungen.ist_geaendert(schluessel)
                or self._stapel(schluessel).ist_geaendert(schluessel))

    def _wert_anzeige(self, schluessel: str) -> str:
        """Der Wert eines Parameters in lesbarer Form."""
        definition = self.definitionen[schluessel]
        wert = self._stapel(schluessel).wert(schluessel)
        if definition.type == "bool":
            return "ja" if wert else "nein"
        if definition.type == "enum":
            return self.sprache.auswahl(definition, str(wert))
        if isinstance(wert, float):
            text = f"{wert:.4f}".rstrip("0").rstrip(".")
            return text or "0"
        if wert is None:
            return ""
        text = str(wert).replace("\n", "⏎")
        return text

    def _zeichne_parameter(self, schluessel: str, breite: int,
                           aktuell: bool) -> str:
        definition = self.definitionen[schluessel]
        stapel = self._stapel(schluessel)
        aktiv = stapel.aktiviert(schluessel)
        name = self.sprache.beschriftung(definition)
        einheit = self.sprache.einheit(definition)
        wert = self._wert_anzeige(schluessel)
        if einheit:
            wert = f"{wert} {einheit}"

        # Kennzeichnung: was bestimmt diesen Wert gerade?
        # Reihenfolge wie bei der Aufloesung selbst: eigener Wert vor
        # Umfangsvorgabe vor Profil (Qualitaet, Material, Duese) vor Formel.
        if self._geaendert(schluessel):
            zeichen, farbe = "*", t.HELLGRUEN
        elif stapel.aus_auswahl(schluessel):
            zeichen, farbe = "a", t.HELLGELB
        elif stapel.aus_profil(schluessel):
            zeichen, farbe = "p", t.CYAN
        elif stapel.haengt_ab_von(schluessel):
            zeichen, farbe = "f", t.HELLBLAU
        else:
            zeichen, farbe = " ", t.GRAU

        namensbreite = max(20, min(38, breite - 46))
        zeile = (t.fuellen(t.kuerzen(name, namensbreite), namensbreite) + " "
                 + t.fuellen(t.kuerzen(schluessel, 30), 30) + " "
                 + t.fuellen(t.kuerzen(wert, 16), 16) + " ")
        if not self.farbig:
            return t.kuerzen(zeile + zeichen, breite)
        if aktuell:
            return t.kuerzen(zeile + zeichen, breite)
        if not aktiv:
            return t.GRAU + t.kuerzen(zeile + zeichen, breite) + t.NORMAL
        return t.kuerzen(zeile, breite - 2) + farbe + zeichen + t.NORMAL

    def _parameterschleife(self, titel: str, schluessel: List[str],
                           unterzeile: str = "") -> None:
        """Zeigt eine Parameterliste und laesst Werte aendern."""
        if not schluessel:
            self._sagen("In dieser Kategorie ist kein Parameter des gewaehlten "
                        "Umfangs enthalten.", t.GELB)
            return

        liste = Auswahlliste(
            schluessel, self._zeichne_parameter,
            suchtext=lambda s: f"{self.sprache.beschriftung(self.definitionen[s])} {s}",
            explizite_suche=True)

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, titel, unterzeile)
            listenhoehe = hoehe - 11
            liste.zeichnen(b, breite, listenhoehe)
            b.zeile()

            # Der Hilfetext des gerade markierten Parameters, gekuerzt.
            aktueller = liste.aktueller
            if aktueller:
                definition = self.definitionen[aktueller]
                text = klartext(self.sprache.beschreibung(definition))
                erste = text.split("\n")[0]
                for zeile in (textwrap.wrap(erste, breite - 4)[:2] or [""]):
                    b.zeile("  " + b.f(t.GRAU, zeile))
                if not self._stapel(aktueller).aktiviert(aktueller):
                    b.zeile("  " + b.f(t.GELB,
                            "Zurzeit nicht wirksam: die Bedingung dieses "
                            "Parameters ist nicht erfuellt."))
            else:
                b.zeile()

            zusatz = (liste.suchhinweis()
                      or "* eigener Wert · a aus der Auswahl · p aus "
                         "Profil/Material/Duese · f berechnet · grau = Bedingung "
                         "nicht erfuellt · " + liste.blaetteranzeige())
            self._fuss(b, [("Enter", "aendern"), ("i", "Einzelheiten"),
                           ("r", "zuruecksetzen"), ("/", "suchen"),
                           ("s", "Slicen"), ("Esc", "zurueck")], zusatz)
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
            if ergebnis == "waehlen":
                self._parameter_aendern(liste.aktueller)
                continue
            if ergebnis == "zurueck":
                return
            if ergebnis != "unbekannt":
                continue

            if liste.suchzeichen(gedrueckt):
                continue
            if gedrueckt == "/":
                liste.suche_oeffnen()
                continue
            if gedrueckt == "i" and liste.aktueller:
                self._parameter_einzelheiten(liste.aktueller)
            elif gedrueckt == "r" and liste.aktueller:
                if self._geaendert(liste.aktueller):
                    self._eingabe_zuruecksetzen(liste.aktueller)
                    self._sagen(f"{liste.aktueller} zurueckgesetzt")
                else:
                    self._sagen("Dieser Parameter wurde nicht veraendert.", t.GRAU)
            elif gedrueckt == "s":
                self._slicen()

    def _kategorie_anzeigen(self, kategorie: Any, bereich: Optional[str] = None,
                            bereichsname: str = "") -> None:
        schluessel = self._parameter_der_kategorie(kategorie, bereich)
        titel = self.sprache.beschriftung(kategorie)
        if bereichsname:
            titel = f"{bereichsname} · {titel}"
        self._parameterschleife(
            titel, schluessel,
            klartext(self.sprache.beschreibung(kategorie))[:110])

    def _parameter_suchen(self) -> None:
        alle = [s for s in self.definitionen
                if self.definitionen[s].type != "category"
                and (self._geltungsbereich(s) == "maschine"
                     or self.umfang.enthaelt(s))]
        alle.sort(key=lambda s: self.sprache.beschriftung(self.definitionen[s]))
        self._parameterschleife(
            "Alle Parameter des gewaehlten Umfangs", alle,
            "Mit / laesst sich in Bezeichnung und Schluessel suchen")

    # ------------------------------------------------------ Wert aendern

    def _parameter_aendern(self, schluessel: str) -> None:
        definition = self.definitionen[schluessel]
        if definition.type == "bool":
            self._bool_umschalten(schluessel)
            return
        if definition.type == "enum":
            self._enum_waehlen(schluessel)
            return
        self._wert_eingeben(schluessel)

    def _bool_umschalten(self, schluessel: str) -> None:
        neu = not bool(self._stapel(schluessel).wert(schluessel))
        self._eingabe_setzen(schluessel, neu)
        self._sagen(f"{schluessel} = {'ja' if neu else 'nein'}")

    def _enum_waehlen(self, schluessel: str) -> None:
        definition = self.definitionen[schluessel]
        moeglichkeiten = list((getattr(definition, "options", {}) or {}).keys())
        if not moeglichkeiten:
            self._sagen("Fuer diesen Parameter sind keine Auswahlmoeglichkeiten "
                        "hinterlegt.", t.GELB)
            return
        jetzt = str(self._stapel(schluessel).wert(schluessel))

        def zeichnen(wert: str, breite: int, aktuell: bool) -> str:
            marke = "●" if wert == jetzt else "○"
            return t.kuerzen(
                f"{marke} {t.fuellen(self.sprache.auswahl(definition, wert), 34)} "
                f"{wert}", breite)

        liste = Auswahlliste(moeglichkeiten, zeichnen,
                             suchtext=lambda w: f"{self.sprache.auswahl(definition, w)} {w}")
        liste.zeiger = max(0, moeglichkeiten.index(jetzt)) if jetzt in moeglichkeiten else 0

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, self.sprache.beschriftung(definition), schluessel)
            listenhoehe = hoehe - 8
            liste.zeichnen(b, breite, listenhoehe)
            b.zeile()
            self._fuss(b, [("Enter", "uebernehmen"), ("Esc", "abbrechen")],
                       f"jetzt: {self.sprache.auswahl(definition, jetzt)}")
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
            if ergebnis == "waehlen":
                self._eingabe_setzen(schluessel, liste.aktueller)
                self._sagen(f"{schluessel} = {liste.aktueller}")
                return
            if ergebnis == "zurueck":
                return
            if ergebnis == "unbekannt":
                liste.suchzeichen(gedrueckt)

    def _wert_eingeben(self, schluessel: str) -> None:
        definition = self.definitionen[schluessel]
        jetzt = werte_modul.als_text(self._stapel(schluessel).wert(schluessel))
        einheit = self.sprache.einheit(definition)
        beschriftung = self.sprache.beschriftung(definition)

        minimum, maximum, warn_min, warn_max = self._stapel(schluessel).grenzen(schluessel)
        hinweis = f" {beschriftung}"
        if einheit:
            hinweis += f" [{einheit}]"
        if minimum is not None or maximum is not None:
            hinweis += f" (zulaessig {minimum}…{maximum})"
        hinweis += ": "

        eingabe = t.eingabezeile(hinweis, jetzt)
        if eingabe is None:
            return
        eingabe = eingabe.strip()
        if eingabe == "":
            self._eingabe_zuruecksetzen(schluessel)
            self._sagen(f"{schluessel} zurueckgesetzt")
            return

        try:
            wert = werte_modul.aus_text(definition, eingabe)
        except ValueError as fehler:
            self._sagen(f"Eingabe nicht verwendbar: {fehler}", t.ROT)
            return

        verletzt = self._grenzverletzung(wert, minimum, maximum)
        if verletzt and self.grenzen_beachten:
            self._sagen(
                f"{eingabe} liegt ausserhalb der in Cura hinterlegten Grenzen "
                f"({minimum}…{maximum}). Mit g lassen sich die Grenzen "
                f"abschalten.", t.ROT)
            return

        self._eingabe_setzen(schluessel, wert)
        if verletzt:
            self._sagen(
                f"{schluessel} = {eingabe} — ausserhalb der Cura-Grenzen "
                f"({minimum}…{maximum}); CuraEngine wertet diese Grenzen nicht aus.",
                t.GELB)
        elif self._grenzverletzung(wert, warn_min, warn_max):
            self._sagen(
                f"{schluessel} = {eingabe} — ausserhalb des empfohlenen "
                f"Bereichs ({warn_min}…{warn_max}).", t.GELB)
        else:
            self._sagen(f"{schluessel} = {eingabe}")

    @staticmethod
    def _grenzverletzung(wert: Any, minimum: Any, maximum: Any) -> bool:
        """Prueft, ob ein Zahlenwert eine Grenze verletzt."""
        try:
            zahl = float(wert)
        except (TypeError, ValueError):
            return False
        for grenze, zu_klein in ((minimum, True), (maximum, False)):
            if grenze is None:
                continue
            try:
                schranke = float(grenze)
            except (TypeError, ValueError):
                continue
            if zu_klein and zahl < schranke:
                return True
            if not zu_klein and zahl > schranke:
                return True
        return False

    # -------------------------------------------------------- Einzelheiten

    def _parameter_einzelheiten(self, schluessel: str) -> None:
        definition = self.definitionen[schluessel]
        breite, hoehe = t.groesse()
        b = self._neu()
        self._kopf(b, self.sprache.beschriftung(definition), schluessel)
        b.zeile()

        def feld(name: str, inhalt: str) -> None:
            for nummer, zeile in enumerate(
                    textwrap.wrap(inhalt, breite - 24) or [""]):
                b.zeile("  " + b.f(t.HELLCYAN, t.fuellen(name if nummer == 0 else "", 20))
                        + zeile)

        wert = self._wert_anzeige(schluessel)
        einheit = self.sprache.einheit(definition)
        feld("Wert", wert + (f" {einheit}" if einheit else ""))

        stapel = self._stapel(schluessel)
        ebene = stapel.herkunft(schluessel)
        if self._geaendert(schluessel):
            herkunft = "von Ihnen gesetzt"
        elif stapel.aus_auswahl(schluessel):
            herkunft = f"Vorgabe des Umfangs ({self.umfang.name})"
        elif ebene == "Material":
            material = self.maschine.materialien_je_extruder[0]
            herkunft = ("aus dem Materialprofil"
                        + (f" ({material.anzeigename})" if material else ""))
        elif ebene == "Duese":
            variante = self.maschine.varianten_je_extruder[0]
            herkunft = ("aus der Duesenvariante"
                        + (f" ({variante.name})" if variante else ""))
        elif ebene == "Extruderdefinition":
            herkunft = "aus der Extruderdefinition"
        elif stapel.aus_profil(schluessel):
            herkunft = f"aus dem Qualitaetsprofil ({self.profil.name})"
            if stapel.profil_ist_formel(schluessel):
                herkunft += ", dort als Formel hinterlegt"
        elif stapel.haengt_ab_von(schluessel):
            herkunft = "aus der Formel der Definitionsdatei berechnet"
        else:
            herkunft = "Vorgabewert der Definitionsdatei"
        feld("Herkunft", herkunft)
        feld("Typ", str(definition.type))
        bereiche = dict((k, n) for k, n, _ in self.BEREICHE)
        feld("Geltungsbereich", bereiche[self._geltungsbereich(schluessel)])
        feld("Vorgabewert", werte_modul.als_text(
            getattr(definition, "default_value", None)))

        minimum, maximum, warn_min, warn_max = self._stapel(schluessel).grenzen(schluessel)
        if minimum is not None or maximum is not None:
            feld("Grenzen", f"{minimum} bis {maximum}"
                 + ("" if self.grenzen_beachten
                    else "   (zurzeit nicht beachtet)"))
        if warn_min is not None or warn_max is not None:
            feld("Empfohlen", f"{warn_min} bis {warn_max}")

        feld("Wirksam", "ja" if stapel.aktiviert(schluessel) else
             "nein, die Bedingung ist nicht erfuellt")

        from UM.Settings.SettingFunction import SettingFunction
        bedingung = getattr(definition, "enabled", None)
        if isinstance(bedingung, SettingFunction):
            feld("Bedingung", str(bedingung))
        formel = stapel.wirksame_formel(schluessel)
        if isinstance(formel, SettingFunction):
            feld("Formel", str(formel))
            benutzt = sorted(stapel.benutzte_schluessel(schluessel))
            if benutzt:
                feld("greift zu auf", ", ".join(benutzt))

        abhaengige = sorted(
            s for s in self.definitionen
            if schluessel in self.einstellungen.benutzte_schluessel(s))
        if abhaengige:
            feld("beeinflusst", ", ".join(abhaengige[:24])
                 + (f"  (und {len(abhaengige) - 24} weitere)"
                    if len(abhaengige) > 24 else ""))

        b.zeile()
        text = klartext(self.sprache.beschreibung(definition))
        for absatz in text.split("\n"):
            for zeile in (textwrap.wrap(absatz, breite - 4) or [""]):
                b.zeile("  " + zeile)
        b.zeichnen()
        self._warte_unten("Weiter mit einer beliebigen Taste")

    # ------------------------------------------------------------- Umfang

    def _umfang_waehlen(self) -> None:
        def zeichnen(umfang: auswahl_modul.Umfang, breite: int,
                     aktuell: bool) -> str:
            marke = "●" if umfang is self.umfang else "○"
            anzahl = umfang.anzahl(self.definitionen)
            return t.kuerzen(f"{marke} {t.fuellen(umfang.name, 34)} "
                             f"{anzahl:>4} Parameter", breite)

        liste = Auswahlliste(self.umfaenge, zeichnen)
        liste.zeiger = self.umfaenge.index(self.umfang)

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Umfang der angebotenen Parameter")
            liste.zeichnen(b, breite, len(self.umfaenge))
            b.zeile()
            aktuell = liste.aktueller
            if aktuell:
                for zeile in textwrap.wrap(aktuell.beschreibung, breite - 4):
                    b.zeile("  " + b.f(t.GRAU, zeile))
                fehlend = auswahl_modul.fehlende(aktuell, self.definitionen)
                if fehlend:
                    b.zeile()
                    b.zeile("  " + b.f(t.GELB,
                            f"{len(fehlend)} Parameter dieser Liste gibt es in "
                            f"der Definition des gewaehlten Druckers nicht: "
                            + ", ".join(fehlend[:6])
                            + (" …" if len(fehlend) > 6 else "")))
            b.zeile()
            b.zeile("  " + b.f(t.GRAU,
                    "Die nicht angebotenen Parameter bleiben geladen; die "
                    "Formeln der angebotenen greifen weiterhin auf sie zu."))
            if aktuell is not None and aktuell.vorgaben:
                b.zeile("  " + b.f(t.GRAU,
                        "Diese Auswahl bringt eigene Vorgabewerte mit ("
                        + ", ".join(f"{k} = {werte_modul.als_text(v)}"
                                    for k, v in sorted(aktuell.vorgaben.items()))
                        + "). Sie liegen unter den eigenen Aenderungen und "
                          "lassen sich jederzeit ueberschreiben."))
            self._fuss(b, [("Enter", "uebernehmen"), ("Esc", "abbrechen")])
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, len(self.umfaenge))
            if ergebnis == "waehlen":
                self.umfang = liste.aktueller
                gesetzt = self._vorgaben_anwenden()
                hinweis = f"Umfang: {self.umfang.name}"
                if gesetzt:
                    hinweis += (f", {gesetzt} Vorgabewert"
                                + ("e" if gesetzt != 1 else "")
                                + " dieser Auswahl eingelegt")
                self._sagen(hinweis)
                return
            if ergebnis == "zurueck":
                return

    def _vorgaben_anwenden(self) -> int:
        """Legt die Vorgabewerte des gewaehlten Umfangs als Ebene ein.

        Rueckgabe: wie viele davon in dieser Druckerdefinition vorkommen.
        Ein selbst gesetzter Wert bleibt unberuehrt -- die Benutzeraenderungen
        liegen ueber dieser Ebene.
        """
        if self.maschine is None:
            return 0
        vorgaben = {schluessel: wert
                    for schluessel, wert in self.umfang.vorgaben.items()
                    if schluessel in self.definitionen}
        self.maschine.vorgaben_setzen(vorgaben)
        return len(vorgaben)

    def _grenzen_umschalten(self) -> None:
        if self.grenzen_beachten:
            b = self._neu()
            breite, _ = t.groesse()
            self._kopf(b, "Grenzen abschalten")
            b.zeile()
            for zeile in [
                "Die Werte minimum_value und maximum_value aus den "
                "Definitionsdateien werden ausschliesslich von Curas "
                "Oberflaeche geprueft. CuraEngine wertet sie nicht aus.",
                "",
                "Das laesst sich nachweisen: eine Duesenbreite von 30 mm wird "
                "von der Engine verarbeitet, obwohl in der Definitionsdatei "
                "10 mm als Hoechstwert steht.",
                "",
                "Abgeschaltet werden also keine Sicherungen der Engine, "
                "sondern nur die Pruefung in diesem Programm. Das ist noetig, "
                "wenn Werte weit ausserhalb des fuer Kunststoffdruck "
                "vorgesehenen Bereichs gebraucht werden -- beim Betondruck "
                "etwa Duesen- und Bahnbreiten im Zentimeterbereich.",
                "",
                "Ob ein derart eingestellter Druck sinnvoll ist, prueft dann "
                "niemand mehr.",
            ]:
                for teil in (textwrap.wrap(zeile, breite - 4) or [""]):
                    b.zeile("  " + teil)
            b.zeile()
            b.zeichnen()
            if not self._bestaetigen("Grenzen wirklich abschalten?",
                                     t.INVERS + t.ROT):
                self._sagen("Die Grenzen bleiben in Kraft.", t.GRAU)
                return
            self.grenzen_beachten = False
            self._sagen("Die Grenzen werden nicht mehr geprueft.", t.GELB)
        else:
            self.grenzen_beachten = True
            self._sagen("Die Grenzen werden wieder geprueft.")

    def _profil_waehlen(self) -> None:
        if not self.profile:
            self._sagen("Fuer diesen Drucker sind keine Qualitaetsprofile "
                        "hinterlegt.", t.GELB)
            return

        def zeichnen(profil: profil_modul.Profil, breite: int,
                     aktuell: bool) -> str:
            marke = "●" if profil is self.profil else "○"
            return t.kuerzen(
                f"{marke} {t.fuellen(profil.name, 26)} "
                f"{t.fuellen(profil.quality_type, 12)} "
                f"{len(profil.werte):>3} Werte", breite)

        liste = Auswahlliste(self.profile, zeichnen)
        if self.profil in self.profile:
            liste.zeiger = self.profile.index(self.profil)

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Qualitaetsprofil",
                       "Startwerte, die Cura beim Hinzufuegen des Druckers setzt")
            liste.zeichnen(b, breite, min(len(self.profile), hoehe - 10))
            b.zeile()
            aktuell = liste.aktueller
            if aktuell:
                for pfad in aktuell.dateien:
                    b.zeile("  " + b.f(t.GRAU, os.path.relpath(
                        pfad, self.inst.ressourcen)))
            b.zeile()
            b.zeile("  " + b.f(t.GRAU, "Eigene Aenderungen bleiben erhalten "
                                       "und gehen dem Profil vor."))
            self._fuss(b, [("Enter", "uebernehmen"), ("Esc", "abbrechen")])
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, len(self.profile))
            if ergebnis == "waehlen":
                self.profil = liste.aktueller
                self.maschine.profil_waehlen(self.profil)
                self._sagen(f"Qualitaetsprofil: {self.profil.name}")
                return
            if ergebnis == "zurueck":
                return

    # ----------------------------------------------------- Material und Duese

    def _extruder_waehlen(self, zweck: str) -> Optional[int]:
        """Fragt bei mehreren Extrudern, welcher gemeint ist.

        Bei nur einem Extruder entfaellt die Frage; None bedeutet Abbruch.
        """
        anzahl = self.maschine.anzahl_extruder
        if anzahl <= 1:
            return 0

        def zeichnen(nummer: int, breite: int, aktuell: bool) -> str:
            material = self.maschine.materialien_je_extruder[nummer]
            duese = self.maschine.varianten_je_extruder[nummer]
            return t.kuerzen(
                f"Extruder {nummer + 1}   "
                f"{t.fuellen(material.anzeigename if material else '-', 24)} "
                f"{duese.name if duese else 'ohne Duesenauswahl'}", breite)

        liste = Auswahlliste(list(range(anzahl)), zeichnen)
        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, zweck, "Fuer welchen Extruder?")
            liste.zeichnen(b, breite, anzahl)
            b.zeile()
            self._fuss(b, [("Enter", "waehlen"), ("Esc", "abbrechen")])
            b.zeichnen()
            self.meldung = ""
            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, anzahl)
            if ergebnis == "waehlen":
                return liste.aktueller
            if ergebnis == "zurueck":
                return None

    def _material_waehlen(self) -> None:
        nummer = self._extruder_waehlen("Material")
        if nummer is None:
            return
        eintraege = self.maschine.materialliste()
        if not eintraege:
            self._sagen("Es wurden keine passenden Materialprofile gefunden.", t.GELB)
            return
        jetzt = self.maschine.materialien_je_extruder[nummer]

        def zeichnen(material: Any, breite: int, aktuell: bool) -> str:
            marke = "●" if material is jetzt else "○"
            return t.kuerzen(
                f"{marke} {t.fuellen(material.marke, 16)} "
                f"{t.fuellen(material.art, 14)} "
                f"{t.fuellen(material.farbe, 14)} {material.durchmesser} mm", breite)

        liste = Auswahlliste(
            eintraege, zeichnen,
            suchtext=lambda m: f"{m.marke} {m.art} {m.farbe} {m.kennung}")
        if jetzt in eintraege:
            liste.zeiger = eintraege.index(jetzt)

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Material",
                       f"{len(eintraege)} Profile fuer "
                       f"{self.maschine.durchmesser(nummer)} mm Filament")
            listenhoehe = hoehe - 9
            liste.zeichnen(b, breite, listenhoehe)
            b.zeile()
            b.zeile("  " + b.f(t.GRAU,
                    "Das Material liefert Temperaturen und Einzugswerte. Cura "
                    "legt es als eigene Ebene im Extruder ab, nicht in der "
                    "Maschine."))
            self._fuss(b, [("Enter", "uebernehmen"), ("Esc", "abbrechen")],
                       liste.suchhinweis() or "Tippen sucht in Marke und Sorte")
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
            if ergebnis == "waehlen":
                self.maschine.material_waehlen(
                    liste.aktueller,
                    None if self.maschine.anzahl_extruder == 1 else nummer)
                self._sagen(f"Material: {liste.aktueller.anzeigename}")
                return
            if ergebnis == "zurueck":
                return
            if ergebnis == "unbekannt":
                liste.suchzeichen(gedrueckt)

    def _duese_waehlen(self) -> None:
        if not self.maschine.varianten:
            self._sagen("Dieser Drucker kennt keine wechselbaren Duesen.", t.GELB)
            return
        nummer = self._extruder_waehlen("Duese")
        if nummer is None:
            return
        eintraege = self.maschine.varianten
        jetzt = self.maschine.varianten_je_extruder[nummer]

        def zeichnen(variante: Any, breite: int, aktuell: bool) -> str:
            marke = "●" if variante is jetzt else "○"
            werte = ", ".join(f"{k} = {v}" for k, v in variante.werte.items())
            return t.kuerzen(f"{marke} {t.fuellen(variante.name, 22)} {werte}", breite)

        liste = Auswahlliste(eintraege, zeichnen)
        if jetzt in eintraege:
            liste.zeiger = eintraege.index(jetzt)

        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Duese")
            liste.zeichnen(b, breite, min(len(eintraege), hoehe - 8))
            b.zeile()
            self._fuss(b, [("Enter", "uebernehmen"), ("Esc", "abbrechen")])
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, len(eintraege))
            if ergebnis == "waehlen":
                self.maschine.variante_waehlen(
                    liste.aktueller,
                    None if self.maschine.anzahl_extruder == 1 else nummer)
                self._sagen(f"Duese: {liste.aktueller.name}")
                return
            if ergebnis == "zurueck":
                return

    # ------------------------------------------------------------- Modell

    def _modell_waehlen(self) -> None:
        ordner = (os.path.dirname(self.modell) if self.modell
                  else os.path.join(PROGRAMMORDNER, "modelle"))
        while True:
            eintraege = self._modelle_im_ordner(ordner)
            def zeichnen(eintrag: Tuple[str, str, int], breite: int,
                         aktuell: bool) -> str:
                pfad, name, groesse = eintrag
                if groesse < 0:
                    return t.kuerzen(f"[Ordner] {name}", breite)
                return t.kuerzen(f"{t.fuellen(name, 46)} "
                                 f"{groesse / 1024:>8.0f} kB", breite)

            liste = Auswahlliste(eintraege, zeichnen, suchtext=lambda e: e[1],
                                 explizite_suche=True)
            while True:
                b = self._neu()
                breite, hoehe = t.groesse()
                self._kopf(b, "Modell waehlen", ordner)
                listenhoehe = hoehe - 9
                liste.zeichnen(b, breite, listenhoehe)
                b.zeile()
                jetzt = self.modell or "keines"
                self._fuss(b, [("Enter", "waehlen"), ("p", "Pfad eingeben"),
                               ("/", "suchen"), ("Esc", "zurueck")],
                           liste.suchhinweis() or f"jetzt: {jetzt}")
                b.zeichnen()
                self.meldung = ""

                gedrueckt = t.taste()
                ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
                if ergebnis == "waehlen":
                    pfad, name, groesse = liste.aktueller
                    if groesse < 0:
                        ordner = pfad
                        break
                    self.modell = pfad
                    self._sagen(f"Modell: {name}")
                    return
                if ergebnis == "zurueck":
                    return
                if ergebnis != "unbekannt":
                    continue
                if liste.suchzeichen(gedrueckt):
                    continue
                if gedrueckt == "/":
                    liste.suche_oeffnen()
                    continue
                if gedrueckt == "p":
                    eingabe = t.eingabezeile(" Pfad zur Modelldatei: ",
                                             self.modell or "")
                    if eingabe:
                        pfad = os.path.expanduser(eingabe.strip().strip('"\''))
                        if os.path.isdir(pfad):
                            ordner = pfad
                            break
                        if os.path.isfile(pfad):
                            self.modell = pfad
                            self._sagen(f"Modell: {os.path.basename(pfad)}")
                            return
                        self._sagen("Diese Datei gibt es nicht.", t.ROT)

    @staticmethod
    def _modelle_im_ordner(ordner: str) -> List[Tuple[str, str, int]]:
        """Unterordner und Modelldateien eines Ordners."""
        endungen = (".stl", ".obj", ".3mf", ".ply")
        eintraege: List[Tuple[str, str, int]] = []
        oben = os.path.dirname(os.path.abspath(ordner))
        if oben and oben != os.path.abspath(ordner):
            eintraege.append((oben, "..", -1))
        try:
            namen = sorted(os.listdir(ordner))
        except OSError:
            return eintraege
        for name in namen:
            if name.startswith("."):
                continue
            pfad = os.path.join(ordner, name)
            if os.path.isdir(pfad):
                eintraege.append((pfad, name, -1))
        for name in namen:
            if name.lower().endswith(endungen):
                pfad = os.path.join(ordner, name)
                try:
                    eintraege.append((pfad, name, os.path.getsize(pfad)))
                except OSError:
                    pass
        return eintraege

    # ------------------------------------------------------------- Slicen

    def _slicen(self) -> None:
        if not self.modell:
            self._sagen("Es ist noch kein Modell gewaehlt (Taste m).", t.GELB)
            return

        name = os.path.splitext(os.path.basename(self.modell))[0]
        zeitmarke = time.strftime("%Y%m%d_%H%M%S")
        ausgabe = os.path.join(AUSGABEORDNER, f"{name}_{zeitmarke}.gcode")

        b = self._neu()
        breite, _ = t.groesse()
        self._kopf(b, "Schneiden laeuft")
        b.zeile()
        b.zeile("  Modell:   " + self.modell)
        b.zeile("  Drucker:  " + self.drucker.anzeigename)
        b.zeile("  Ausgabe:  " + ausgabe)
        b.zeile()
        b.zeile("  " + b.f(t.GRAU, "CuraEngine wird aufgerufen; das dauert je "
                                   "nach Modell einige Sekunden."))
        b.zeichnen()

        drucker_datei = os.path.join(self.inst.definitionen,
                                     self.drucker.name + ".def.json")
        try:
            ergebnis = engine.schneide(self.inst, drucker_datei, self.modell,
                                       ausgabe, self.einstellungen)
        except engine.SchnittFehler as fehler:
            self._schnittfehler(fehler)
            return

        self.letztes_ergebnis = ergebnis
        self._ergebnis_anzeigen(ergebnis)

    def _schnittfehler(self, fehler: engine.SchnittFehler) -> None:
        b = self._neu()
        breite, hoehe = t.groesse()
        self._kopf(b, "Der Schnittvorgang ist fehlgeschlagen")
        b.zeile()
        for zeile in textwrap.wrap(str(fehler), breite - 4):
            b.zeile("  " + b.f(t.ROT, zeile))
        b.zeile()
        if fehler.ausgabe:
            b.zeile("  " + b.f(t.HELLCYAN, "Letzte Meldungen der Engine:"))
            wichtig = [z for z in fehler.ausgabe.splitlines()
                       if "error" in z.lower() or "warn" in z.lower()]
            for zeile in (wichtig or fehler.ausgabe.splitlines())[-12:]:
                b.zeile("    " + b.f(t.GRAU, t.kuerzen(zeile.strip(), breite - 6)))
        b.zeichnen()
        self._warte_unten("Weiter mit einer beliebigen Taste")

    def _ergebnis_anzeigen(self, ergebnis: engine.Ergebnis) -> None:
        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "G-Code erzeugt")
            b.zeile()
            kennzahlen = ergebnis.kennzahlen

            def feld(name: str, inhalt: str) -> None:
                b.zeile("  " + b.f(t.HELLCYAN, t.fuellen(name, 22)) + inhalt)

            feld("Datei", ergebnis.pfad)
            feld("Groesse", f"{kennzahlen.get('groesse_b', 0) / 1024:.0f} kB")
            feld("Dauer des Schnitts", f"{ergebnis.dauer:.1f} s")
            b.zeile()
            feld("Schichten", str(kennzahlen.get("schichten", "?")))
            feld("Bewegungsbefehle", str(kennzahlen.get("bewegungen", "?")))

            filament = kennzahlen.get("filament_mm")
            if filament:
                durchmesser = float(self._stapel("material_diameter").wert("material_diameter") or 1.75)
                masse = engine.material_gramm(filament, durchmesser)
                feld("Filament", f"{filament / 1000:.2f} m  "
                                 f"(rund {masse:.0f} g bei PLA)")
            zeit = kennzahlen.get("zeit_s")
            if zeit:
                feld("Druckzeit", f"rund {zeit // 3600} h {(zeit % 3600) // 60} min")
            masse_xyz = kennzahlen.get("abmessung")
            if masse_xyz:
                feld("Verfahrbereich",
                     "X %.1f…%.1f   Y %.1f…%.1f   Z %.1f…%.1f mm" % masse_xyz)

            b.zeile()
            b.zeile("  " + b.f(t.GRAU,
                    "Druckzeit und Materialbedarf sind aus dem G-Code "
                    "berechnet. CuraEngine laesst die entsprechenden "
                    "Kopfzeilen beim Aufruf ueber die Befehlszeile leer; in "
                    "Cura traegt sie die Oberflaeche nachtraeglich ein."))
            b.zeile()
            geaendert = len(self._eigene_aenderungen())
            b.zeile("  " + b.f(t.GRAU,
                    f"Verwendet wurden {len(self.definitionen)} Parameterwerte, "
                    f"davon {geaendert} von Ihnen gesetzt."))

            self._fuss(b, [("a", "Aenderungen zeigen"), ("c", "Befehlszeile"),
                           ("Esc", "zurueck")])
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            if gedrueckt == t.ESC:
                return
            if gedrueckt == "a":
                self._aenderungen_anzeigen()
            elif gedrueckt == "c":
                self._befehlszeile_anzeigen(ergebnis)

    def _befehlszeile_anzeigen(self, ergebnis: engine.Ergebnis) -> None:
        b = self._neu()
        breite, hoehe = t.groesse()
        self._kopf(b, "Aufruf der CuraEngine")
        b.zeile()
        b.zeile("  " + b.f(t.GRAU,
                "So wurde die Engine aufgerufen. Jeder Parameter wird einzeln "
                "mit -s uebergeben; die Formeln sind zu diesem Zeitpunkt "
                "bereits ausgerechnet. Genauso verfaehrt Cura selbst."))
        b.zeile()
        b.zeile("  " + b.f(t.HELLCYAN, "CURA_ENGINE_SEARCH_PATH"))
        for teil in self.inst.such_pfad().split(os.pathsep):
            b.zeile("    " + t.kuerzen(teil, breite - 6))
        b.zeile()
        text = engine.befehl_als_text(ergebnis.befehl)
        b.zeile("  " + b.f(t.HELLCYAN,
                f"Befehl ({len(ergebnis.befehl)} Bestandteile, "
                f"{len(text)} Zeichen), Anfang:"))
        platz = hoehe - 14
        for zeile in textwrap.wrap(text, breite - 6)[:platz]:
            b.zeile("    " + b.f(t.GRAU, zeile))
        b.zeichnen()
        self._warte_unten("Weiter mit einer beliebigen Taste")

    def _aenderungen_anzeigen(self) -> None:
        aenderungen = self._eigene_aenderungen()
        if not aenderungen:
            self._sagen("Es wurde noch kein Wert von Hand gesetzt.", t.GRAU)
            return

        def zeichnen(schluessel: str, breite: int, aktuell: bool) -> str:
            definition = self.definitionen[schluessel]
            vorgabe = werte_modul.als_text(
                getattr(definition, "default_value", None))
            return t.kuerzen(
                f"{t.fuellen(self.sprache.beschriftung(definition), 30)} "
                f"{t.fuellen(schluessel, 28)} "
                f"{t.fuellen(self._wert_anzeige(schluessel), 14)} "
                f"(vorher {vorgabe})", breite)

        liste = Auswahlliste(aenderungen, zeichnen, suchtext=lambda s: s)
        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, f"Eigene Aenderungen ({len(aenderungen)})")
            listenhoehe = hoehe - 8
            liste.zeichnen(b, breite, listenhoehe)
            b.zeile()
            self._fuss(b, [("r", "zuruecksetzen"), ("Esc", "zurueck")])
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
            if ergebnis == "zurueck":
                return
            if gedrueckt == "r" and liste.aktueller:
                self._eingabe_zuruecksetzen(liste.aktueller)
                aenderungen = self._eigene_aenderungen()
                liste.eintraege_setzen(aenderungen)
                if not aenderungen:
                    return

    # -------------------------------------------------------- Speichern

    def _speichern(self) -> None:
        vorschlag = time.strftime("Einstellung_%Y%m%d_%H%M")
        eingabe = t.eingabezeile(" Name der Einstellung: ", vorschlag)
        if not eingabe:
            return
        pfad = os.path.join(EINSTELLUNGSORDNER, eingabe.strip())
        try:
            geschrieben = projekt.speichern(
                pfad, self.drucker.name, self.umfang.kennung,
                self.einstellungen, self.grenzen_beachten, self.modell,
                self.profil.name if self.profil else None, self.maschine)
        except OSError as fehler:
            self._sagen(f"Speichern nicht moeglich: {fehler}", t.ROT)
            return
        anzahl = len(self._eigene_aenderungen())
        self._sagen(f"{anzahl} Aenderungen gespeichert: "
                    f"{os.path.basename(geschrieben)}")

    def _laden(self) -> None:
        eintraege = projekt.gespeicherte(EINSTELLUNGSORDNER)
        if not eintraege:
            self._sagen("Im Ordner einstellungen liegt noch nichts.", t.GELB)
            return

        def zeichnen(eintrag: Tuple[str, str], breite: int,
                     aktuell: bool) -> str:
            return t.kuerzen(eintrag[1], breite)

        liste = Auswahlliste(eintraege, zeichnen, suchtext=lambda e: e[1])
        while True:
            b = self._neu()
            breite, hoehe = t.groesse()
            self._kopf(b, "Gespeicherte Einstellung laden", EINSTELLUNGSORDNER)
            listenhoehe = hoehe - 12
            liste.zeichnen(b, breite, listenhoehe)
            b.zeile()
            if liste.aktueller:
                try:
                    inhalt = projekt.laden(liste.aktueller[0])
                    b.zeile("  " + b.f(t.GRAU,
                            f"{inhalt.get('erstellt', '')} · "
                            f"Drucker {inhalt.get('drucker', '?')} · "
                            f"{len(inhalt.get('aenderungen', {}))} Aenderungen"))
                except (OSError, ValueError) as fehler:
                    b.zeile("  " + b.f(t.ROT, f"nicht lesbar: {fehler}"))
            self._fuss(b, [("Enter", "laden"), ("Esc", "zurueck")],
                       "Vorhandene eigene Aenderungen werden ersetzt.")
            b.zeichnen()
            self.meldung = ""

            gedrueckt = t.taste()
            ergebnis = liste.taste_verarbeiten(gedrueckt, listenhoehe)
            if ergebnis == "zurueck":
                return
            if ergebnis != "waehlen":
                if ergebnis == "unbekannt":
                    liste.suchzeichen(gedrueckt)
                continue

            try:
                inhalt = projekt.laden(liste.aktueller[0])
            except (OSError, ValueError) as fehler:
                self._sagen(f"Nicht lesbar: {fehler}", t.ROT)
                return

            # Die gespeicherten Werte gehoeren zu genau einem Drucker; ohne
            # ihn liessen sich Profil, Material und Duese nicht zuordnen.
            gespeicherter_drucker = inhalt.get("drucker")
            if (gespeicherter_drucker and self.drucker
                    and gespeicherter_drucker != self.drucker.name):
                try:
                    self._drucker_laden(gespeicherter_drucker)
                except definitionen.DefinitionsFehler as fehler:
                    self._sagen(str(fehler), t.ROT)
                    return

            self._alle_eingaben_zuruecksetzen()
            uebernommen, misslungen = projekt.anwenden(inhalt, self.einstellungen,
                                                       self.maschine)
            self.profil = self.maschine.profil
            self.umfang = auswahl_modul.finde(
                self.umfaenge, inhalt.get("umfang", auswahl_modul.WIRKSAM))
            self._vorgaben_anwenden()
            self.grenzen_beachten = bool(inhalt.get("grenzen_beachten", True))
            if inhalt.get("modell") and os.path.isfile(inhalt["modell"]):
                self.modell = inhalt["modell"]

            hinweis = f"{uebernommen} Werte uebernommen"
            if misslungen:
                hinweis += (f"; nicht uebernommen: "
                            + ", ".join(misslungen[:5])
                            + (" …" if len(misslungen) > 5 else ""))
            self._sagen(hinweis, t.GELB if misslungen else t.GRUEN)
            return

    # --------------------------------------------------------------- Hilfe

    def _hilfe(self) -> None:
        b = self._neu()
        breite, hoehe = t.groesse()
        self._kopf(b, "Hilfe")
        b.zeile()

        def absatz(ueberschrift: str, zeilen: Sequence[str]) -> None:
            b.zeile("  " + b.f(t.HELLCYAN, ueberschrift))
            for zeile in zeilen:
                b.zeile("    " + zeile)
            b.zeile()

        absatz("Aufbau", [
            "Das Hauptmenue fuehrt fuenf Eintraege:",
            "  Hardware    Drucker und Duese",
            "  Material    Materialprofil je Extruder",
            "  Modell      STL-Datei",
            "  Profil      Qualitaetsprofil des Druckers",
            "  Parameter   Mesh · Extruder · Global · Machine Settings,",
            "              darunter jeweils Curas Kategorien",
        ])
        absatz("Bedienung", [
            "↑ ↓  Bild↑ Bild↓  Pos1 Ende   in Listen bewegen",
            "Enter                         oeffnen oder aendern",
            "Esc                           zurueck; loescht zuerst die Suche",
            "/                             suchen; Enter uebernimmt den Filter",
            "Buchstaben                    Befehle der Fusszeile; in der",
            "                              Druckerauswahl unmittelbar die Suche",
        ])
        absatz("Kennzeichnung der Werte", [
            "*   von Ihnen gesetzt",
            "a   Vorgabewert des gewaehlten Umfangs (etwa der Beton-Auswahl)",
            "f   von Cura aus anderen Parametern berechnet",
            "p   aus Qualitaetsprofil, Materialprofil oder Duese",
            "grau  die enabled-Bedingung ist nicht erfuellt; der Wert wird "
            "trotzdem uebergeben",
        ])
        absatz("Umfang", [
            "u waehlt, welche Parameter angeboten werden: die 246 wirksamen,",
            "die Beton-Auswahl oder alle. Die uebrigen bleiben geladen, weil",
            "die Formeln der angebotenen auf sie zugreifen.",
            "Die Machine Settings folgen dem Umfang nicht -- dort stehen immer",
            "alle 87 Parameter, weil der Sweep sie nicht geprueft hat.",
        ])
        absatz("Geltungsbereiche", [
            "Mesh              je Modell einstellbar (settable_per_mesh)",
            "Extruder          je Extruder einstellbar (settable_per_extruder)",
            "Global            gilt fuer den gesamten Druck",
            "Machine Settings  beschreiben den Drucker selbst",
            "Beide Eigenschaften schliessen einander nicht aus; es gilt die",
            "Rangfolge Machine Settings, Mesh, Extruder, Global. Jeder",
            "Parameter erscheint dadurch in genau einem Bereich.",
        ])
        absatz("Bezeichnungen", [
            "Angezeigt werden die Originalbezeichnungen aus den",
            "Definitionsdateien. Curas deutsche Uebersetzung erhaelt man mit",
            "dem Aufruf  python3 cura-ui.py --sprache de_DE",
        ])
        absatz("Woher die Werte stammen", [
            "Die Beschriftungen, Formeln, Bedingungen und Grenzen kommen "
            "unveraendert aus der",
            "Cura-Installation. Dieses Programm liest sie nur; es schreibt "
            "nichts dorthin zurueck.",
            f"Ort: {self.inst.wurzel}",
        ])
        b.zeichnen()
        self._warte_unten("Weiter mit einer beliebigen Taste")


def starten(cura_pfad: Optional[str] = None, sprachkuerzel: str = "") -> None:
    Anwendung(cura_pfad, sprachkuerzel).starten()
