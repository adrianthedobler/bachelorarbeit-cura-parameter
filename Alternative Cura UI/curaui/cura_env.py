# -*- coding: utf-8 -*-
"""Anbindung an eine vorhandene Cura-5.13-Installation.

Dieses Modul macht Curas eigene Einstellungsklassen ausserhalb von Cura
nutzbar. Es aendert nichts an der Installation, sondern

  1. sucht den Installationsort (macOS und Windows),
  2. legt eine Attrappe fuer PyQt6 an, weil Cura Qt nur fuer die grafische
     Oberflaeche braucht, die hier nicht laeuft,
  3. gleicht zwei Unvertraeglichkeiten mit Python 3.12+ aus,
  4. wiederholt Curas eigene Registrierung zusaetzlicher Eigenschaften und
     Einstellungstypen (CuraApplication._initializeSettingDefinitions),
  5. registriert die Hilfsfunktionen, die in den Formeln vorkommen
     (resolveOrValue, extruderValue(s), ...).

Erst danach lassen sich SettingDefinition und SettingFunction importieren.
"""
from __future__ import annotations

import ast
import os
import platform
import sys
import types
from typing import Any, Dict, List, Optional


class CuraNichtGefunden(RuntimeError):
    """Wird ausgeloest, wenn keine benutzbare Cura-Installation gefunden wurde."""


# ---------------------------------------------------------------- 1. Fundort

#: Orte, an denen Cura ueblicherweise installiert ist. Der erste Treffer gewinnt.
_SUCHORTE_MACOS = [
    "/Applications/UltiMaker Cura.app/Contents/Resources",
    os.path.expanduser("~/Applications/UltiMaker Cura.app/Contents/Resources"),
]

_SUCHORTE_WINDOWS = [
    r"C:\Program Files\UltiMaker Cura 5.13.0",
    r"C:\Program Files\UltiMaker Cura 5.13.1",
    r"C:\Program Files\Ultimaker Cura 5.13.0",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\UltiMaker Cura 5.13.0"),
]


class CuraInstallation:
    """Die Pfade einer gefundenen Cura-Installation."""

    def __init__(self, wurzel: str) -> None:
        self.wurzel = os.path.abspath(wurzel)
        self.ressourcen = os.path.join(self.wurzel, "share", "cura", "resources")
        self.definitionen = os.path.join(self.ressourcen, "definitions")
        self.extruder = os.path.join(self.ressourcen, "extruders")
        self.varianten = os.path.join(self.ressourcen, "variants")
        self.materialien = os.path.join(self.ressourcen, "materials")
        self.engine = os.path.join(
            self.wurzel, "CuraEngine.exe" if os.name == "nt" else "CuraEngine")

    def ist_gueltig(self) -> bool:
        return (os.path.isdir(self.definitionen)
                and os.path.isdir(self.extruder)
                and os.path.isdir(os.path.join(self.wurzel, "UM", "Settings"))
                and os.path.isfile(self.engine))

    def fehlende_teile(self) -> List[str]:
        pruefung = [
            (self.definitionen, "Ordner definitions"),
            (self.extruder, "Ordner extruders"),
            (os.path.join(self.wurzel, "UM", "Settings"), "Ordner UM/Settings"),
            (self.engine, "CuraEngine"),
        ]
        return [name for pfad, name in pruefung if not os.path.exists(pfad)]

    def such_pfad(self) -> str:
        """Wert fuer CURA_ENGINE_SEARCH_PATH.

        Beide Ordner sind noetig: ueber definitions wird die inherits-Kette
        einer Druckerdefinition aufgeloest, ueber extruders die zugehoerige
        Extruder-Definition. Fehlt einer davon, fallen Werte wie
        material_diameter still auf falsche Vorgaben zurueck.
        """
        return self.definitionen + os.pathsep + self.extruder

    def __repr__(self) -> str:
        return f"<CuraInstallation {self.wurzel!r}>"


def finde_cura(vorgabe: Optional[str] = None) -> CuraInstallation:
    """Sucht eine Cura-Installation.

    Reihenfolge: ausdrueckliche Angabe, Umgebungsvariable CURA_ROOT, dann die
    ueblichen Installationsorte des jeweiligen Betriebssystems.
    """
    kandidaten: List[str] = []
    if vorgabe:
        kandidaten.append(vorgabe)
    if os.environ.get("CURA_ROOT"):
        kandidaten.append(os.environ["CURA_ROOT"])
    if platform.system() == "Darwin":
        kandidaten += _SUCHORTE_MACOS
    elif os.name == "nt":
        kandidaten += _SUCHORTE_WINDOWS
        kandidaten += _windows_programmordner()
    else:
        kandidaten += ["/usr/share/cura", os.path.expanduser("~/cura")]

    for ort in kandidaten:
        if not ort:
            continue
        inst = CuraInstallation(ort)
        if inst.ist_gueltig():
            return inst
        # Unter macOS darf auch der .app-Ordner selbst angegeben werden.
        if ort.endswith(".app"):
            inst = CuraInstallation(os.path.join(ort, "Contents", "Resources"))
            if inst.ist_gueltig():
                return inst

    hinweis = "\n".join(f"  - {k}" for k in kandidaten if k)
    raise CuraNichtGefunden(
        "Es wurde keine vollstaendige Cura-Installation gefunden.\n"
        "Gesucht wurde an diesen Orten:\n" + hinweis + "\n\n"
        "Abhilfe: Umgebungsvariable CURA_ROOT auf den Installationsordner setzen,\n"
        "z. B. unter Windows auf C:\\Program Files\\UltiMaker Cura 5.13.0 und unter\n"
        "macOS auf /Applications/UltiMaker Cura.app/Contents/Resources")


def _windows_programmordner() -> List[str]:
    """Alle Unterordner der Programmverzeichnisse, die nach Cura aussehen."""
    treffer: List[str] = []
    for basis in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                  os.environ.get("ProgramFiles(x86)", ""),
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs")):
        if not basis or not os.path.isdir(basis):
            continue
        try:
            for name in os.listdir(basis):
                if "cura" in name.lower():
                    treffer.append(os.path.join(basis, name))
        except OSError:
            pass
    return sorted(treffer, reverse=True)


# ------------------------------------------------------- 2. PyQt6-Attrappe

def _pyqt_attrappe_einhaengen() -> None:
    """Legt Platzhalter fuer PyQt6 an.

    UM.Settings importiert PyQt6 nur fuer Signale und Eigenschaften der
    grafischen Oberflaeche. Da hier keine Oberflaeche laeuft, genuegen leere
    Platzhalter. Ist PyQt6 vorhanden, wird nichts veraendert.
    """
    try:
        import PyQt6.QtCore  # noqa: F401
        return
    except Exception:
        pass

    def modul(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    pyqt = modul("PyQt6")
    modul("PyQt6.sip")

    qtcore = modul("PyQt6.QtCore")

    class _Signal:
        """Ersatz fuer pyqtSignal: nimmt Verbindungen an und tut nichts."""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __get__(self, obj: Any, typ: Any = None) -> "_Signal":
            return self

        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def disconnect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def emit(self, *args: Any, **kwargs: Any) -> None:
            pass

    def _dekorator(*args: Any, **kwargs: Any) -> Any:
        """Ersatz fuer pyqtSlot/pyqtProperty: gibt die Funktion unveraendert zurueck."""
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def wrap(f: Any) -> Any:
            return f
        return wrap

    class _QObject:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    qtcore.QObject = _QObject
    qtcore.pyqtSignal = _Signal
    qtcore.pyqtSlot = _dekorator
    qtcore.pyqtProperty = _dekorator
    qtcore.QCoreApplication = _QObject
    qtcore.QUrl = _QObject
    qtcore.QTimer = _QObject
    qtcore.QThread = _QObject
    qtcore.QVariant = _QObject
    qtcore.Qt = types.SimpleNamespace(ItemDataRole=types.SimpleNamespace(UserRole=256))

    qtwidgets = modul("PyQt6.QtWidgets")
    qtwidgets.QMessageBox = _QObject
    qtwidgets.QApplication = _QObject

    qtqml = modul("PyQt6.QtQml")
    qtqml.QQmlEngine = _QObject

    qtgui = modul("PyQt6.QtGui")
    qtgui.QImage = _QObject

    class _Platzhalter:
        """Steht fuer eine beliebige Qt-Klasse, die hier nicht gebraucht wird.

        Alle Aufrufe laufen ins Leere; Abfragen auf Gueltigkeit sind falsch.
        So genuegt es zum Beispiel MimeTypeDatabase, das eine QMimeDatabase
        anlegt, aber im Betrieb nur eigene, selbst angemeldete Typen abfragt.
        """
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __call__(self, *args: Any, **kwargs: Any) -> "_Platzhalter":
            return self

        def __getattr__(self, name: str) -> Any:
            if name == "isValid":
                return lambda *a, **k: False
            return _Platzhalter()

        def __bool__(self) -> bool:
            return False

    def _fehlender_name(name: str) -> Any:
        """Liefert fuer jeden nicht eigens gesetzten Qt-Namen einen Platzhalter.

        Damit muessen nicht alle von Cura benutzten Qt-Klassen einzeln
        nachgebildet werden; entscheidend sind nur die oben ausdruecklich
        gesetzten (Signale, Eigenschaften, QObject).
        """
        if name.startswith("__"):
            raise AttributeError(name)
        return _Platzhalter

    for _m in (qtcore, qtwidgets, qtqml, qtgui):
        _m.__getattr__ = _fehlender_name  # type: ignore[attr-defined]

    pyqt.QtCore = qtcore
    pyqt.QtWidgets = qtwidgets
    pyqt.QtQml = qtqml
    pyqt.QtGui = qtgui


# ------------------------------------------------- 3. Python-Vertraeglichkeit

def _python_pflaster() -> None:
    """Gleicht zwei Aenderungen neuerer Python-Fassungen aus.

    Cura 5.13 bringt eine eigene Python-3.12-Laufzeit mit. Wird das Programm
    mit Python 3.12 oder neuer ausgefuehrt, fehlen zwei Dinge, auf die Curas
    Formelpruefer zurueckgreift:

      * ast.Str wurde entfernt (ersetzt durch ast.Constant); SettingFunction
        vergleicht in visit_Subscript aber noch dagegen.
      * Constant.s wurde entfernt; visit_Str greift noch darauf zu.

    Beides wird hier nachgereicht, ohne eine Datei der Installation zu aendern.
    """
    if not hasattr(ast, "Str"):
        ast.Str = ast.Constant  # type: ignore[attr-defined]

    from UM.Settings.SettingFunction import _SettingExpressionVisitor, IllegalMethodError
    import builtins

    if getattr(_SettingExpressionVisitor, "_curaui_gepflastert", False):
        return

    def visit_Constant(self: Any, node: ast.Constant) -> None:
        """Ersatz fuer visit_Str, das node.s benutzt.

        Uebernimmt dieselbe Pruefung wie Curas Original, greift aber auf
        node.value statt auf das entfernte node.s zu.
        """
        if not isinstance(node.value, str):
            return
        text = node.value
        if text in self._blacklist:
            raise IllegalMethodError(text)
        if text.startswith("_"):
            raise IllegalMethodError(text)
        if text not in self._knownNames and text not in dir(builtins):
            self.keys.add(text)

    _SettingExpressionVisitor.visit_Constant = visit_Constant
    _SettingExpressionVisitor.visit_Str = visit_Constant
    _SettingExpressionVisitor._curaui_gepflastert = True


# --------------------------------------- 4./5. Registrierungen wie in Cura

def _eigenschaften_registrieren() -> None:
    """Wiederholt CuraApplication._initializeSettingDefinitions.

    Ohne diese Registrierungen kennt SettingDefinition die von Cura
    zusaetzlich eingefuehrten Eigenschaften nicht und meldet beim Einlesen
    jeder Definitionsdatei "Unrecognised property".
    Quelle: cura/CuraApplication.py, _initializeSettingDefinitions.
    """
    from UM.Settings.SettingDefinition import (SettingDefinition,
                                               DefinitionPropertyType,
                                               toIntConversion)
    from UM.Settings.Validator import Validator

    if "settable_per_extruder" in SettingDefinition.getPropertyNames():
        return

    SettingDefinition.addSupportedProperty(
        "settable_per_mesh", DefinitionPropertyType.Any, default=True, read_only=True)
    SettingDefinition.addSupportedProperty(
        "settable_per_extruder", DefinitionPropertyType.Any, default=True, read_only=True)
    SettingDefinition.addSupportedProperty(
        "settable_per_meshgroup", DefinitionPropertyType.Any, default=True, read_only=True)
    SettingDefinition.addSupportedProperty(
        "settable_globally", DefinitionPropertyType.Any, default=True, read_only=True)
    SettingDefinition.addSupportedProperty(
        "limit_to_extruder", DefinitionPropertyType.Function, default="-1", depends_on="value")
    SettingDefinition.addSupportedProperty(
        "resolve", DefinitionPropertyType.Function, default=None, depends_on="value")

    SettingDefinition.addSettingType("extruder", None, toIntConversion, Validator)
    SettingDefinition.addSettingType("optional_extruder", None, toIntConversion, None)
    SettingDefinition.addSettingType("[int]", None, str, None)


#: Der Wertespeicher, den die Formel-Hilfsfunktionen befragen. Er wird erst
#: mit registriere_formelfunktionen() gesetzt.
_werteliefernd: Any = None


def _wert(schluessel: str, kontext: Any = None) -> Any:
    """Der Wert eines Parameters im globalen Stapel."""
    if _werteliefernd is None:
        return None
    return _werteliefernd.getProperty(schluessel, "value", kontext)


def _extruder(position: Any):
    """Der Stapel eines Extruders; faellt auf den globalen zurueck.

    Wie Curas CuraFormulaFunctions.getValueInExtruder: Die Nummer -1 steht
    fuer den Standard-Extruder (etwa skirt_brim_extruder_nr = -1), und eine
    nicht vorhandene Nummer fuehrt zu Extruder 0.
    """
    if _werteliefernd is None:
        return None
    maschine = getattr(_werteliefernd, "maschine", None)
    if maschine is None:
        return _werteliefernd
    try:
        nummer = int(float(position))
    except (TypeError, ValueError):
        return _werteliefernd
    if nummer == -1:
        nummer = int(maschine.erster_extruder())
    return (maschine.extruderstapel(nummer) or maschine.extruderstapel(0)
            or _werteliefernd)


def _melde_formelfunktionen_an() -> None:
    """Meldet die in den Formeln benutzten Hilfsfunktionen an.

    In fdmprinter.def.json kommen resolveOrValue (249-mal), extruderValues
    (93-mal), extruderValue (36-mal) und einige seltenere vor. Cura bindet
    dafuer CuraFormulaFunctions an seine Behaelterstapel; hier greifen die
    Funktionen auf dieselben Stapel zu, die dieses Programm fuehrt.

    Die Anmeldung muss geschehen, bevor die erste Definitionsdatei eingelesen
    wird. Curas Formelpruefer merkt sich beim Einlesen, welche Namen in einer
    Formel vorkommen, und haelt jeden noch unbekannten Namen fuer einen
    Parameter. Waeren die Funktionen zu diesem Zeitpunkt nicht angemeldet,
    wuerde spaeter zum Beispiel resolveOrValue als Parameter nachgeschlagen
    und die Auswertung schluege fehl.

    Quelle der Namen: cura/CuraApplication.py, _initializeSettingFunctions.
    """
    from UM.Settings.SettingFunction import SettingFunction

    def extruderValue(position: Any, schluessel: str, kontext: Any = None) -> Any:
        stapel = _extruder(position)
        return stapel.getProperty(schluessel, "value", kontext) if stapel else None

    def extruderValues(schluessel: str, kontext: Any = None) -> List[Any]:
        if _werteliefernd is None:
            return [None]
        maschine = getattr(_werteliefernd, "maschine", None)
        if maschine is None:
            return [_wert(schluessel, kontext)]
        stapel = maschine.aktive_extruderstapel()
        if not stapel:
            return [_wert(schluessel, kontext)]
        return [s.getProperty(schluessel, "value", kontext) for s in stapel]

    def resolveOrValue(schluessel: str, kontext: Any = None) -> Any:
        if _werteliefernd is None:
            return None
        aufgeloest = _werteliefernd.getProperty(schluessel, "resolve", kontext)
        return aufgeloest if aufgeloest is not None else _wert(schluessel, kontext)

    def defaultExtruderPosition(kontext: Any = None) -> str:
        maschine = getattr(_werteliefernd, "maschine", None)
        return maschine.erster_extruder() if maschine else "0"

    def anyExtruderWithMaterial(schluessel: str, kontext: Any = None) -> str:
        return defaultExtruderPosition(kontext)

    def anyExtruderNrWithOrDefault(schluessel: str, kontext: Any = None) -> str:
        return defaultExtruderPosition(kontext)

    def valueFromContainer(schluessel: str, index: int, kontext: Any = None) -> Any:
        return _wert(schluessel, kontext)

    def extruderValueFromContainer(position: Any, schluessel: str, index: int,
                                   kontext: Any = None) -> Any:
        return extruderValue(position, schluessel, kontext)

    for name, funktion in (
            ("extruderValue", extruderValue),
            ("extruderValues", extruderValues),
            ("resolveOrValue", resolveOrValue),
            ("defaultExtruderPosition", defaultExtruderPosition),
            ("anyExtruderWithMaterial", anyExtruderWithMaterial),
            ("anyExtruderNrWithOrDefault", anyExtruderNrWithOrDefault),
            ("valueFromContainer", valueFromContainer),
            ("extruderValueFromContainer", extruderValueFromContainer)):
        SettingFunction.registerOperator(name, funktion)


def registriere_formelfunktionen(werteliefernd: Any) -> None:
    """Legt fest, welcher Stapel die Formeln beantwortet.

    Uebergeben wird der globale Stapel. Traegt dieser einen Verweis auf seine
    Maschine, koennen die Funktionen auch die Extruderstapel befragen.
    """
    global _werteliefernd
    _werteliefernd = werteliefernd


# ------------------------------------------------------------ Gesamtaufruf

_vorbereitet: Optional[CuraInstallation] = None


def vorbereiten(vorgabe: Optional[str] = None) -> CuraInstallation:
    """Bereitet Curas Einstellungsklassen zur Benutzung vor.

    Nach diesem Aufruf lassen sich UM.Settings.SettingDefinition und
    UM.Settings.SettingFunction ganz normal importieren. Mehrfachaufrufe sind
    unschaedlich.
    """
    global _vorbereitet
    if _vorbereitet is not None and (vorgabe is None or _vorbereitet.wurzel == vorgabe):
        return _vorbereitet

    inst = finde_cura(vorgabe)

    # Curas Programmordner vorne einhaengen, damit "import UM.Settings" dessen
    # Dateien findet. Es wird nur gelesen, nichts veraendert.
    if inst.wurzel not in sys.path:
        sys.path.insert(0, inst.wurzel)

    _pyqt_attrappe_einhaengen()
    _stille_protokollierung()
    _eigenschaften_registrieren()
    _python_pflaster()
    # Muss vor dem Einlesen der ersten Definitionsdatei geschehen.
    _melde_formelfunktionen_an()

    _vorbereitet = inst
    return inst


def _stille_protokollierung() -> None:
    """Schaltet Curas Protokollausgabe stumm.

    UM.Logger schreibt Warnungen auf die Standardausgabe. Da dieses Programm
    den Bildschirm selbst zeichnet, wuerden solche Zeilen die Darstellung
    zerstoeren. Die Meldungen werden gesammelt und sind ueber
    gesammelte_meldungen() abrufbar.
    """
    from UM.Logger import Logger

    global _meldungen
    _meldungen = []

    def log(cls: Any, log_type: str, message: str, *args: Any, **kwargs: Any) -> None:
        try:
            _meldungen.append(f"{log_type}: {message % args if args else message}")
        except Exception:
            _meldungen.append(f"{log_type}: {message}")

    Logger.log = classmethod(log)
    Logger.logException = classmethod(
        lambda cls, log_type, message, *a, **k: _meldungen.append(f"{log_type}: {message}"))


_meldungen: List[str] = []


def gesammelte_meldungen() -> List[str]:
    """Die von Cura gemeldeten Hinweise seit dem Start."""
    return list(_meldungen)
