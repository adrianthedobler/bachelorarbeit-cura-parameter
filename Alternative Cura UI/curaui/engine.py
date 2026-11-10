# -*- coding: utf-8 -*-
"""Aufruf der CuraEngine.

CuraEngine wertet die Wertformeln aus den Definitionsdateien nicht aus. Cura
loest sie im Programm auf und uebergibt der Engine nur noch eine flache Liste
aus Namen und fertigen Werten (plugins/CuraEngineBackend/StartSliceJob.py:
ueber stack.getAllKeys() wird je Schluessel die Eigenschaft "value" abgefragt
und in die Nachricht an die Engine geschrieben).

Genau das tut auch dieses Modul, nur ueber die Befehlszeile statt ueber die
Prozessverbindung: jeder Wert wird einzeln mit -s uebergeben. Werte vor der
Angabe -e0 gelten global, Werte danach fuer den ersten Extruder.
"""
from __future__ import annotations

import math
import os
import re
import shlex
import struct
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .cura_env import CuraInstallation
from . import startcode
from .werte import Einstellungen, alle_werte, als_text


class SchnittFehler(RuntimeError):
    """Der Schnittvorgang ist fehlgeschlagen."""

    def __init__(self, nachricht: str, ausgabe: str = "") -> None:
        super().__init__(nachricht)
        self.ausgabe = ausgabe


class Ergebnis:
    """Das Ergebnis eines Schnittvorgangs."""

    def __init__(self, pfad: str, dauer: float, ausgabe: str,
                 befehl: List[str]) -> None:
        self.pfad = pfad
        self.dauer = dauer
        self.ausgabe = ausgabe
        self.befehl = befehl
        self.kennzahlen = _kennzahlen(pfad)

    @property
    def druckzeit(self) -> Optional[int]:
        return self.kennzahlen.get("zeit_s")

    @property
    def filament_mm(self) -> Optional[float]:
        return self.kennzahlen.get("filament_mm")

    @property
    def schichten(self) -> Optional[int]:
        return self.kennzahlen.get("schichten")


def umgebung(inst: CuraInstallation) -> Dict[str, str]:
    """Umgebungsvariablen fuer den Engine-Aufruf.

    CURA_ENGINE_SEARCH_PATH muss beide Ordner enthalten: ueber definitions
    findet die Engine die geerbten Grunddefinitionen, ueber extruders die
    Extruderdefinition. Fehlt einer davon, greifen stillschweigend falsche
    Vorgaben, ohne dass eine Fehlermeldung erscheint.
    """
    env = dict(os.environ)
    env["CURA_ENGINE_SEARCH_PATH"] = inst.such_pfad()
    return env


def baue_befehl(inst: CuraInstallation, drucker_datei: str, modell: str,
                ausgabe: str, werte: Dict[str, str],
                extruder_werte: Any = None, anfangsextruder: int = 0,
                lage: Optional[Dict[str, str]] = None) -> List[str]:
    """Stellt die vollstaendige Befehlszeile zusammen.

    Werte vor der ersten Angabe -e gelten global, danach jeweils fuer den
    genannten Extruder. Genauso baut Cura seine Nachricht an die Engine auf
    (plugins/CuraEngineBackend/StartSliceJob.py, _buildGlobalSettingsMessage
    und _buildExtruderMessage).
    """
    befehl = [inst.engine, "slice", "-v", "-j", drucker_datei]
    for schluessel, wert in werte.items():
        befehl += ["-s", f"{schluessel}={wert}"]

    if isinstance(extruder_werte, dict):
        extruder_werte = [extruder_werte]
    for nummer, satz in enumerate(extruder_werte or [{}]):
        befehl += [f"-e{nummer}"]
        if "extruder_nr" not in satz:
            befehl += ["-s", f"extruder_nr={nummer}"]
        for schluessel, wert in satz.items():
            befehl += ["-s", f"{schluessel}={wert}"]

    # Ein Modell gehoert dem Extruder, dessen Abschnitt zuletzt geoeffnet
    # wurde. Ohne diese Zeile fiele es bei mehreren Extrudern dem letzten zu
    # statt dem ersten -- die Stuetzstruktur waere dann richtig zugeordnet,
    # das Werkstueck aber nicht.
    befehl += [f"-e{anfangsextruder}"]
    for schluessel, wert in (lage or {}).items():
        befehl += ["-s", f"{schluessel}={wert}"]
    befehl += ["-l", modell, "-o", ausgabe]
    return befehl


def teile_werte(einstellungen: Einstellungen) -> Tuple[Dict[str, str], Any]:
    """Trennt die Werte in globale und extruderbezogene.

    Welche Parameter je Extruder uebergeben werden, entscheidet die
    Eigenschaft settable_per_extruder (plugins/CuraEngineBackend/
    StartSliceJob.py, _buildExtruderMessage). Die Werte dafuer stammen aus dem
    jeweiligen Extruderstapel, nicht aus dem globalen -- nur so wirken
    Material und Duese, die allein dort eingelegt sind.
    """
    global_werte = alle_werte(einstellungen)

    maschine = getattr(einstellungen, "maschine", None)
    stapel = list(getattr(maschine, "extruder", []) or []) if maschine else []
    if not stapel:
        stapel = [einstellungen]

    # Die Platzhalter im Start- und End-G-Code aufloesen. CuraEngine kennt
    # diese Schreibweise nicht; Cura ersetzt sie ebenfalls vorher.
    #
    # Massgeblich ist dabei nicht der globale Stapel, sondern der des zuerst
    # benutzten Extruders -- sonst stuende im Start-G-Code der CR-X die
    # Temperatur aus der Definitionsdatei statt der des eingelegten
    # Materials. Cura uebergibt dafuer initial_extruder_nr
    # (StartSliceJob._buildGlobalSettingsMessage).
    startcode.anwenden(global_werte, stapel[0])

    saetze: List[Dict[str, str]] = []
    for eigener in stapel:
        satz: Dict[str, str] = {}
        for schluessel, definition in einstellungen.definitionen.items():
            if not getattr(definition, "settable_per_extruder", False):
                continue
            wert = eigener.wert(schluessel)
            if wert is None:
                continue
            satz[schluessel] = als_text(wert)
        startcode.anwenden(satz, eigener)
        saetze.append(satz)
    return global_werte, saetze


def schneide(inst: CuraInstallation, drucker_datei: str, modell: str,
             ausgabe_pfad: str, einstellungen: Einstellungen,
             zeitgrenze: int = 600) -> Ergebnis:
    """Erzeugt aus einem Modell eine G-Code-Datei."""
    if not os.path.isfile(modell):
        raise SchnittFehler(f"Modelldatei nicht gefunden: {modell}")
    if not os.path.isfile(inst.engine):
        raise SchnittFehler(f"CuraEngine nicht gefunden: {inst.engine}")

    ordner = os.path.dirname(os.path.abspath(ausgabe_pfad))
    if ordner:
        os.makedirs(ordner, exist_ok=True)

    global_werte, extruder_werte = teile_werte(einstellungen)
    befehl = baue_befehl(inst, drucker_datei, modell, ausgabe_pfad,
                         global_werte, extruder_werte,
                         lage=mittig_setzen(modell))

    beginn = time.time()
    try:
        lauf = subprocess.run(befehl, env=umgebung(inst), timeout=zeitgrenze,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        raise SchnittFehler(f"Zeitgrenze von {zeitgrenze} s ueberschritten.")
    except OSError as fehler:
        raise SchnittFehler(f"CuraEngine liess sich nicht starten: {fehler}")
    dauer = time.time() - beginn

    text = lauf.stdout.decode("utf-8", errors="replace")
    if lauf.returncode != 0:
        raise SchnittFehler(
            f"CuraEngine endete mit Rueckgabewert {lauf.returncode}.", text)
    if not os.path.isfile(ausgabe_pfad) or os.path.getsize(ausgabe_pfad) == 0:
        raise SchnittFehler("CuraEngine hat keine G-Code-Datei erzeugt.", text)

    return Ergebnis(ausgabe_pfad, dauer, text, befehl)


# ------------------------------------------------------------ Platzierung

def mittig_setzen(modell: str) -> Dict[str, str]:
    """Legt das Modell mittig auf die Druckplatte.

    CuraEngine richtet ein Modell an dessen eigenem Nullpunkt aus, Cura
    dagegen an der Mitte seiner Ausdehnung. Bei einem Koerper, der im
    Konstruktionsprogramm nicht um den Nullpunkt herum liegt, entstuenden
    dadurch unterschiedliche Lagen -- und damit andere Verfahrwege, andere
    Einzuege und bei mehreren Extrudern ein anderer Abstand zum
    Reinigungsturm.

    Ausgeglichen wird das ueber mesh_position_x und mesh_position_y.
    Laesst sich die Ausdehnung nicht bestimmen, bleibt es bei der
    Ausrichtung der Engine.
    """
    masse = _stl_ausdehnung(modell)
    if masse is None:
        return {}
    (minx, maxx), (miny, maxy) = masse
    return {"mesh_position_x": als_text(-(minx + maxx) / 2.0),
            "mesh_position_y": als_text(-(miny + maxy) / 2.0)}


def _stl_ausdehnung(pfad: str) -> Optional[Tuple[Tuple[float, float],
                                                 Tuple[float, float]]]:
    """Die Ausdehnung einer STL-Datei in X und Y."""
    if not pfad.lower().endswith(".stl"):
        return None
    try:
        with open(pfad, "rb") as datei:
            kopf = datei.read(84)
            if len(kopf) < 84:
                return None
            anzahl = struct.unpack("<I", kopf[80:84])[0]
            rest = datei.read()
    except OSError:
        return None

    if len(rest) >= anzahl * 50 and anzahl > 0:
        return _ausdehnung_binaer(rest, anzahl)
    return _ausdehnung_text(pfad)


def _ausdehnung_binaer(daten: bytes, anzahl: int) -> Optional[Tuple[Tuple[float, float],
                                                                   Tuple[float, float]]]:
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for nummer in range(anzahl):
        stelle = nummer * 50 + 12          # 12 Byte Normalenvektor ueberspringen
        for ecke in range(3):
            x, y = struct.unpack("<ff", daten[stelle + ecke * 12:
                                              stelle + ecke * 12 + 8])
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
    if minx > maxx:
        return None
    return (minx, maxx), (miny, maxy)


def _ausdehnung_text(pfad: str) -> Optional[Tuple[Tuple[float, float],
                                                  Tuple[float, float]]]:
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    try:
        with open(pfad, "r", errors="replace") as datei:
            for zeile in datei:
                teile = zeile.split()
                if len(teile) != 4 or teile[0] != "vertex":
                    continue
                try:
                    x, y = float(teile[1]), float(teile[2])
                except ValueError:
                    continue
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
    except OSError:
        return None
    if minx > maxx:
        return None
    return (minx, maxx), (miny, maxy)


# ------------------------------------------------------------- Auswertung

def _kennzahlen(pfad: str) -> Dict[str, Any]:
    """Ermittelt die Eckdaten aus dem erzeugten G-Code.

    Die Kopfzeilen ;TIME: und ;Filament used: sind hier nicht brauchbar: beim
    Aufruf ueber die Befehlszeile laesst CuraEngine sie auf ihren Platzhaltern
    stehen (;Filament used: 0m, ;MINX:2.14748e+06, also dem groessten
    32-Bit-Wert). In Cura werden diese Angaben nachtraeglich von der
    Oberflaeche eingesetzt, die sie ueber die Prozessverbindung erhaelt.

    Deshalb werden Materialbedarf und Abmessungen hier aus den
    Bewegungsbefehlen selbst berechnet und die Druckzeit aus Wegstrecke und
    Vorschub geschaetzt.
    """
    daten: Dict[str, Any] = {}
    filament = 0.0
    strecke_druck = 0.0
    zeit = 0.0
    schichten = 0
    bewegungen = 0
    absolut_e = True
    letztes_e = 0.0
    vorschub = 1800.0          # mm/min, bis der erste F-Wert kommt
    x = y = z = None
    minx = miny = minz = float("inf")
    maxx = maxy = maxz = float("-inf")

    try:
        datei = open(pfad, "r", errors="replace")
    except OSError:
        return daten

    with datei:
        for zeile in datei:
            if zeile.startswith(";LAYER:"):
                schichten += 1
                continue
            if zeile.startswith(";"):
                continue
            code = zeile.split(";", 1)[0].strip()
            if not code:
                continue
            teile = code.split()
            befehl = teile[0]

            if befehl == "M82":
                absolut_e = True
                continue
            if befehl == "M83":
                absolut_e = False
                continue
            if befehl == "G92":
                for teil in teile[1:]:
                    if teil[:1] == "E":
                        try:
                            letztes_e = float(teil[1:])
                        except ValueError:
                            pass
                continue
            if befehl not in ("G0", "G1"):
                continue

            nx, ny, nz, e_wert = x, y, z, None
            for teil in teile[1:]:
                kennung, rest = teil[:1], teil[1:]
                try:
                    zahl = float(rest)
                except ValueError:
                    continue
                if kennung == "X":
                    nx = zahl
                elif kennung == "Y":
                    ny = zahl
                elif kennung == "Z":
                    nz = zahl
                elif kennung == "E":
                    e_wert = zahl
                elif kennung == "F":
                    vorschub = zahl

            zuwachs = 0.0
            if e_wert is not None:
                zuwachs = (e_wert - letztes_e) if absolut_e else e_wert
                if zuwachs > 0:
                    filament += zuwachs
                if absolut_e:
                    letztes_e = e_wert

            if None not in (x, y) and None not in (nx, ny):
                weg = math.hypot(nx - x, ny - y)
                if nz is not None and z is not None:
                    weg = math.hypot(weg, nz - z)
                if weg > 0:
                    if vorschub > 0:
                        zeit += weg / (vorschub / 60.0)
                    if zuwachs > 0:
                        strecke_druck += weg

            if nx is not None:
                minx, maxx = min(minx, nx), max(maxx, nx)
            if ny is not None:
                miny, maxy = min(miny, ny), max(maxy, ny)
            if nz is not None:
                minz, maxz = min(minz, nz), max(maxz, nz)
            x, y, z = nx, ny, nz
            bewegungen += 1

    daten["filament_mm"] = filament
    daten["zeit_s"] = int(zeit)
    daten["zeit_geschaetzt"] = True
    daten["schichten"] = schichten
    daten["bewegungen"] = bewegungen
    daten["druckstrecke_mm"] = strecke_druck
    if minx <= maxx:
        daten["abmessung"] = (minx, maxx, miny, maxy, minz, maxz)
    try:
        daten["groesse_b"] = os.path.getsize(pfad)
    except OSError:
        pass
    return daten


def material_gramm(filament_mm: float, durchmesser_mm: float,
                   dichte_g_cm3: float = 1.24) -> float:
    """Rechnet die Filamentlaenge in Masse um (Vorgabedichte: PLA)."""
    querschnitt_cm2 = math.pi * (durchmesser_mm / 20.0) ** 2
    return querschnitt_cm2 * (filament_mm / 10.0) * dichte_g_cm3


def befehl_als_text(befehl: List[str]) -> str:
    """Die Befehlszeile in einer Form, die sich im Terminal wiederholen laesst."""
    return " ".join(shlex.quote(teil) for teil in befehl)
