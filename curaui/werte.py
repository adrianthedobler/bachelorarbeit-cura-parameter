# -*- coding: utf-8 -*-
"""Wertespeicher und Aufloesung der Parameterwerte.

Cura verwaltet Werte in einem achtstufigen Behaelterstapel (Benutzeraenderung,
Qualitaetsprofil, Material, Variante, ... bis zur Definitionsdatei). Fuer
dieses Programm genuegen drei Ebenen:

    1. vom Benutzer gesetzt          (hoechster Rang)
    2. aus dem Qualitaetsprofil      (Startwerte des gewaehlten Druckers)
    3. aus der Definitionsdatei      (value-Formel, sonst default_value)

Die Berechnung der Formeln uebernimmt Curas eigene Klasse SettingFunction.
Diese Klasse verlangt von ihrem Gegenueber nur eine einzige Methode,
getProperty(schluessel, eigenschaft, kontext) -- genau die stellt Einstellungen
bereit. Dadurch muss die Formelsprache nicht nachgebaut werden.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


#: Kennzeichnet "kein Ergebnis" dort, wo None ein gueltiger Wert waere.
_NICHTS = object()


class Einstellungen:
    """Haelt die Werte aller Parameter und loest Formeln auf.

    Die Klasse ist zugleich der Wertelieferant fuer Curas SettingFunction.
    """

    def __init__(self, definitionen: Dict[str, Any],
                 name: str = "global", unten: Optional["Einstellungen"] = None) -> None:
        self._defs = definitionen
        self.name = name
        #: Der Stapel, auf den zurueckgegriffen wird, wenn dieser nichts
        #: hergibt. Bei Cura ist das fuer jeden Extruderstapel der globale
        #: Stapel (UM/Settings/ContainerStack.py, nextStack).
        self._unten = unten
        #: Wird von der Maschine gesetzt; nur der globale Stapel braucht sie,
        #: um limit_to_extruder aufzuloesen.
        self.maschine: Any = None
        self._benutzer: Dict[str, Any] = {}
        #: Die Ebenen unterhalb der Benutzeraenderungen, von oben nach unten:
        #: Qualitaetsprofil, Material, Variante. Cura fuehrt dieselben Ebenen
        #: in seinem Behaelterstapel (cura/Settings/CuraContainerStack.py,
        #: _ContainerIndexes).
        self._ebenen: List[Tuple[str, Dict[str, Any]]] = []
        self._zwischenspeicher: Dict[Tuple[str, str], Any] = {}
        self._in_arbeit: Set[Tuple[str, str]] = set()
        #: Parameter, deren resolve-Funktion gerade ausgewertet wird.
        self._im_resolve: Set[str] = set()

    # ------------------------------------------------------------ Zugriff

    @property
    def definitionen(self) -> Dict[str, Any]:
        return self._defs

    def getProperty(self, schluessel: str, eigenschaft: str,
                    kontext: Any = None) -> Any:
        """Liefert eine Eigenschaft eines Parameters.

        Diese Signatur ist von Curas SettingFunction vorgegeben; der Name ist
        deshalb englisch. Formeln werden bei Bedarf ausgewertet und das
        Ergebnis zwischengespeichert.
        """
        definition = self._defs.get(schluessel)
        if definition is None:
            return None
        if eigenschaft == "value":
            return self._wert_ermitteln(schluessel, definition, kontext)

        merker = (schluessel, eigenschaft)
        if merker in self._zwischenspeicher:
            return self._zwischenspeicher[merker]
        if merker in self._in_arbeit:
            return None

        self._in_arbeit.add(merker)
        try:
            wert = self._eigenschaft(definition, eigenschaft, kontext)
        finally:
            self._in_arbeit.discard(merker)
        self._zwischenspeicher[merker] = wert
        return wert

    def _wert_ermitteln(self, schluessel: str, definition: Any,
                        kontext: Any) -> Any:
        """Der Wert eines Parameters, gegebenenfalls ueber seine resolve-Funktion.

        Hat ein Parameter eine resolve-Funktion, gilt deren Ergebnis. Cura
        macht es ebenso (cura/Settings/GlobalStack.py, getProperty und
        _shouldResolve): nur fuer die Eigenschaft "value", nur bei
        vorhandener resolve-Funktion und nicht, wenn der Benutzer selbst
        einen Wert gesetzt hat.

        Zu beachten ist, was geschieht, wenn die resolve-Formel auf denselben
        Parameter zurueckgreift -- was sie fast immer tut, denn sie fasst ja
        die Werte aller Extruder zusammen. Dann ist nicht der Vorgabewert der
        Definitionsdatei gemeint, sondern der normale Wert dieses Parameters,
        also einschliesslich Qualitaetsprofil und Formel. Genau dafuer gibt es
        die zwei getrennten Vermerke: _im_resolve haelt fest, welche
        Parameter gerade aufgeloest werden, _in_arbeit schuetzt daneben vor
        ringfoermigen Formeln.
        """
        from UM.Settings.SettingFunction import SettingFunction

        if schluessel in self._im_resolve:
            return self._normalwert(schluessel, definition, kontext)

        merker = (schluessel, "value")
        if merker in self._zwischenspeicher:
            return self._zwischenspeicher[merker]
        if merker in self._in_arbeit:
            return getattr(definition, "default_value", None)

        if (schluessel not in self._benutzer
                and isinstance(getattr(definition, "resolve", None), SettingFunction)):
            self._im_resolve.add(schluessel)
            try:
                aufgeloest = self.getProperty(schluessel, "resolve", kontext)
            finally:
                self._im_resolve.discard(schluessel)
            if aufgeloest is not None:
                self._zwischenspeicher[merker] = aufgeloest
                return aufgeloest

        self._in_arbeit.add(merker)
        try:
            wert = self._begrenzt(schluessel, definition, kontext)
            if wert is _NICHTS:
                wert = self._normalwert(schluessel, definition, kontext)
        finally:
            self._in_arbeit.discard(merker)
        self._zwischenspeicher[merker] = wert
        return wert

    def _begrenzt(self, schluessel: str, definition: Any, kontext: Any) -> Any:
        """Wert aus einem bestimmten Extruder, falls limit_to_extruder das sagt.

        Manche Parameter gelten nicht fuer das ganze Modell, sondern werden
        aus einem bestimmten Extruder genommen -- beim Stuetzmaterial etwa aus
        dem, der die Stuetzstruktur druckt. Welcher das ist, steht in der
        Eigenschaft limit_to_extruder. Cura wertet sie im globalen Stapel aus
        (cura/Settings/GlobalStack.py, getProperty).
        """
        if self.maschine is None or self._unten is not None:
            return _NICHTS
        grenze = self.getProperty(schluessel, "limit_to_extruder", kontext)
        if grenze is None:
            return _NICHTS
        try:
            nummer = int(float(grenze))
        except (TypeError, ValueError):
            return _NICHTS
        if nummer < 0:
            return _NICHTS
        stapel = self.maschine.extruderstapel(nummer)
        if stapel is None or stapel is self:
            return _NICHTS
        if not self.getProperty(schluessel, "settable_per_extruder", kontext):
            return _NICHTS
        wert = stapel.getProperty(schluessel, "value", kontext)
        return _NICHTS if wert is None else wert

    def _normalwert(self, schluessel: str, definition: Any, kontext: Any) -> Any:
        """Der Wert ohne resolve: Benutzer, dann Profil, dann Formel, dann Vorgabe."""
        from UM.Settings.SettingFunction import SettingFunction

        if schluessel in self._benutzer:
            return self._auswerten(self._benutzer[schluessel], kontext)
        for _name, ebene in self._ebenen:
            if schluessel in ebene:
                return self._auswerten(ebene[schluessel], kontext)
        if self._unten is not None:
            roh = self._unten._explizit(schluessel)
            if roh is not None:
                return self._auswerten(roh, kontext)
        formel = getattr(definition, "value", None)
        if isinstance(formel, SettingFunction):
            return formel(self, kontext)
        if formel is not None:
            return formel
        return getattr(definition, "default_value", None)

    def _explizit(self, schluessel: str) -> Any:
        """Der ausdruecklich eingetragene Wert dieses Stapels -- oder None.

        Ausdruecklich heisst: vom Benutzer gesetzt oder in einer der Ebenen
        eingetragen. Formeln und Vorgabewerte zaehlen nicht dazu, denn die
        stehen in der Definitionsdatei und gelten fuer jeden Stapel
        gleichermassen; sie werden im Zusammenhang des fragenden Stapels
        ausgewertet.
        """
        if schluessel in self._benutzer:
            return self._benutzer[schluessel]
        for _name, ebene in self._ebenen:
            if schluessel in ebene:
                return ebene[schluessel]
        if self._unten is not None:
            return self._unten._explizit(schluessel)
        return None

    def _eigenschaft(self, definition: Any, eigenschaft: str, kontext: Any) -> Any:
        """Eine andere Eigenschaft als "value" -- Formeln werden ausgewertet."""
        from UM.Settings.SettingFunction import SettingFunction
        roh = getattr(definition, eigenschaft, None)
        if isinstance(roh, SettingFunction):
            return roh(self, kontext)
        return roh

    def _auswerten(self, wert: Any, kontext: Any) -> Any:
        """Wertet gesetzte Werte aus, die selbst eine Formel sind.

        Qualitaetsprofile duerfen Formeln enthalten (in den Profildateien mit
        einem Gleichheitszeichen eingeleitet). Solche Eintraege werden beim
        Laden in eine SettingFunction umgewandelt und hier berechnet.
        """
        from UM.Settings.SettingFunction import SettingFunction
        if isinstance(wert, SettingFunction):
            return wert(self, kontext)
        return wert

    # --------------------------------------------------------- Veraenderung

    def setze(self, schluessel: str, wert: Any) -> None:
        """Setzt einen Wert als Benutzeraenderung."""
        if schluessel not in self._defs:
            raise KeyError(schluessel)
        self._benutzer[schluessel] = wert
        self._verwerfen()

    def zuruecksetzen(self, schluessel: str) -> None:
        """Nimmt eine Benutzeraenderung zurueck."""
        self._benutzer.pop(schluessel, None)
        self._verwerfen()

    def alles_zuruecksetzen(self) -> None:
        self._benutzer.clear()
        self._verwerfen()

    def setze_ebenen(self, ebenen: List[Tuple[str, Dict[str, Any]]]) -> None:
        """Legt die Ebenen unterhalb der Benutzeraenderungen fest.

        Erwartet wird eine Liste von oben nach unten, also etwa
        [("Qualitaetsprofil", ...), ("Material", ...), ("Duese", ...)].
        """
        self._ebenen = [(name, dict(werte)) for name, werte in ebenen]
        self._verwerfen()

    def setze_profil(self, werte: Dict[str, Any]) -> None:
        """Legt eine einzelne Ebene fest (Kurzform fuer das Qualitaetsprofil)."""
        self.setze_ebenen([("Qualitaetsprofil", werte)])

    def _verwerfen(self) -> None:
        """Leert den Zwischenspeicher -- dieses und aller verbundenen Stapel.

        Weil eine Aenderung ueber die Formeln beliebig weit ausstrahlen kann,
        wird nicht versucht, nur die betroffenen Eintraege zu bestimmen. Bei
        rund 700 Parametern ist die vollstaendige Neuberechnung schnell genug.

        Die Stapel einer Maschine greifen aufeinander zu: Ein Extruder faellt
        auf den globalen Stapel zurueck, und extruderValues() im globalen
        Stapel liest die Extruder. Eine Aenderung an einem Stapel muss deshalb
        auch die Zwischenspeicher der anderen leeren. Sonst schnitte die
        Engine nach einer geaenderten Duesentemperatur weiter mit dem
        zuvor im Extruder zwischengespeicherten Wert.
        """
        self._zwischenspeicher.clear()
        maschine = getattr(self, "maschine", None)
        if maschine is None:
            return
        for stapel in [getattr(maschine, "einstellungen", None)] + list(
                getattr(maschine, "extruder", []) or []):
            if stapel is not None and stapel is not self:
                stapel._zwischenspeicher.clear()

    # ------------------------------------------------------------- Abfragen

    def wert(self, schluessel: str) -> Any:
        return self.getProperty(schluessel, "value")

    def ist_geaendert(self, schluessel: str) -> bool:
        """Ob der Benutzer diesen Parameter selbst gesetzt hat."""
        return schluessel in self._benutzer

    def herkunft(self, schluessel: str) -> Optional[str]:
        """Name der Ebene, aus der der Wert stammt -- oder None.

        Beruecksichtigt nur die eingelegten Ebenen; ein Wert aus einer Formel
        oder der Vorgabewert der Definitionsdatei liefern None.
        """
        if schluessel in self._benutzer:
            return None
        for name, ebene in self._ebenen:
            if schluessel in ebene:
                return name
        return None

    def aus_profil(self, schluessel: str) -> bool:
        """Ob der Wert aus einer der eingelegten Ebenen stammt."""
        return self.herkunft(schluessel) is not None

    #: Name der Ebene, die ein Parameterumfang mitbringt (siehe auswahl.py).
    AUSWAHLEBENE = "Auswahl"

    def aus_auswahl(self, schluessel: str) -> bool:
        """Ob der Wert aus der Vorgabe des gewaehlten Umfangs stammt."""
        return self.herkunft(schluessel) == self.AUSWAHLEBENE

    def benutzeraenderungen(self) -> Dict[str, Any]:
        return dict(self._benutzer)

    def aktiviert(self, schluessel: str) -> bool:
        """Wertet die enabled-Bedingung aus.

        Ist keine Bedingung hinterlegt, gilt der Parameter als aktiv.
        Ein Parameter, dessen Elternteil abgeschaltet ist, gilt ebenfalls als
        abgeschaltet -- so verhaelt sich auch Curas Oberflaeche.
        """
        definition = self._defs.get(schluessel)
        if definition is None:
            return False
        eltern = getattr(definition, "parent", None)
        if eltern is not None and getattr(eltern, "key", None) in self._defs:
            if not self.aktiviert(eltern.key):
                return False
        zustand = self.getProperty(schluessel, "enabled")
        if zustand is None:
            return True
        return bool(zustand)

    def grenzen(self, schluessel: str) -> Tuple[Any, Any, Any, Any]:
        """Liefert (Minimum, Maximum, Warnminimum, Warnmaximum).

        Die harten Grenzen minimum_value/maximum_value wertet ausschliesslich
        Curas Oberflaeche aus; CuraEngine beachtet sie nicht. Deshalb kann das
        Programm sie auf Wunsch uebergehen, ohne dass am Schnittvorgang etwas
        umgangen werden muesste.
        """
        return (self.getProperty(schluessel, "minimum_value"),
                self.getProperty(schluessel, "maximum_value"),
                self.getProperty(schluessel, "minimum_value_warning"),
                self.getProperty(schluessel, "maximum_value_warning"))

    def benutzte_schluessel(self, schluessel: str) -> Set[str]:
        """Welche anderen Parameter in der wirksamen value-Formel vorkommen."""
        from UM.Settings.SettingFunction import SettingFunction
        formel = self.wirksame_formel(schluessel)
        if isinstance(formel, SettingFunction):
            return set(formel.getUsedSettingKeys())
        return set()

    def profil_ist_formel(self, schluessel: str) -> bool:
        """Ob die zustaendige Ebene fuer diesen Parameter eine Formel angibt."""
        from UM.Settings.SettingFunction import SettingFunction
        for _name, ebene in self._ebenen:
            if schluessel in ebene:
                return isinstance(ebene[schluessel], SettingFunction)
        return False

    def wirksame_formel(self, schluessel: str) -> Any:
        """Die Formel, die den Wert gerade bestimmt -- oder None.

        Ein Qualitaetsprofil kann eine eigene Formel mitbringen, die die der
        Definitionsdatei verdraengt. Fuer die Anzeige ist die tatsaechlich
        wirksame gemeint.
        """
        from UM.Settings.SettingFunction import SettingFunction
        if schluessel in self._benutzer:
            wert = self._benutzer[schluessel]
            return wert if isinstance(wert, SettingFunction) else None
        for _name, ebene in self._ebenen:
            if schluessel in ebene:
                wert = ebene[schluessel]
                return wert if isinstance(wert, SettingFunction) else None
        formel = getattr(self._defs[schluessel], "value", None)
        return formel if isinstance(formel, SettingFunction) else None

    def haengt_ab_von(self, schluessel: str) -> bool:
        """Ob der Wert dieses Parameters aus anderen berechnet wird."""
        from UM.Settings.SettingFunction import SettingFunction
        return isinstance(getattr(self._defs[schluessel], "value", None), SettingFunction)


# ------------------------------------------------------- Ausgabe zur Engine

def als_text(wert: Any) -> str:
    """Wandelt einen Wert in die Schreibweise, die CuraEngine erwartet.

    Wahrheitswerte muessen klein geschrieben werden; Fliesskommazahlen werden
    ohne Exponentialschreibweise ausgegeben, weil CuraEngine sonst nichts
    damit anfangen kann.
    """
    if isinstance(wert, bool):
        return "true" if wert else "false"
    if isinstance(wert, float):
        text = repr(wert)
        if "e" in text or "E" in text:
            text = f"{wert:.10f}".rstrip("0").rstrip(".")
        return text
    if wert is None:
        return ""
    return str(wert)


def alle_werte(einstellungen: Einstellungen,
               nur_aktive: bool = False) -> Dict[str, str]:
    """Erzeugt die flache Liste Name -> Wert fuer CuraEngine.

    Das entspricht dem, was Cura selbst an die Engine uebergibt: in
    plugins/CuraEngineBackend/StartSliceJob.py werden ueber
    stack.getAllKeys() alle Schluessel durchlaufen und je Schluessel die
    Eigenschaft "value" abgefragt. Formeln sind zu diesem Zeitpunkt bereits
    aufgeloest; die Engine erhaelt nur noch fertige Werte.
    """
    ergebnis: Dict[str, str] = {}
    for schluessel in einstellungen.definitionen:
        if nur_aktive and not einstellungen.aktiviert(schluessel):
            continue
        wert = einstellungen.wert(schluessel)
        if wert is None:
            continue
        ergebnis[schluessel] = als_text(wert)
    return ergebnis


def aus_text(definition: Any, text: str) -> Any:
    """Wandelt eine Texteingabe in den Wert des passenden Typs um.

    Benutzt Curas eigene Umwandlung (SettingDefinition.settingValueFromString),
    damit dieselben Regeln gelten wie in Curas Oberflaeche. Fuer Wahrheitswerte
    wird zusaetzlich die in den Profildateien uebliche Schreibweise
    (True/False, yes/no, 1/0) zugelassen.
    """
    from UM.Settings.SettingDefinition import SettingDefinition

    typ = getattr(definition, "type", "str")
    if typ != "str":
        # Bei Texten darf nichts entfernt werden: der Start-G-Code mancher
        # Extruder beginnt mit einem Zeilenumbruch, und der gehoert dazu.
        text = text.strip()

    if typ == "bool":
        klein = text.strip().lower()
        if klein in ("true", "yes", "on", "1"):
            return True
        if klein in ("false", "no", "off", "0"):
            return False
        raise ValueError(f"{text!r} ist kein Wahrheitswert")

    if typ in ("str", "enum", "extruder", "optional_extruder", "polygon",
               "polygons", "[int]"):
        if typ == "enum":
            erlaubt = getattr(definition, "options", {}) or {}
            if text not in erlaubt:
                raise ValueError(f"{text!r} ist keine der moeglichen Angaben")
        return text

    try:
        return SettingDefinition.settingValueFromString(typ, text)
    except ValueError:
        # Fuer Typen ohne eigene Umwandlung bleibt der Text stehen.
        return text
