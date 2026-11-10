#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vergleicht zwei G-Code-Dateien.

Gedacht fuer die Gegenprobe: derselbe Koerper, dieselben Einstellungen,
einmal mit diesem Programm geschnitten und einmal mit Cura selbst.

Verglichen wird nicht Zeile fuer Zeile, denn zwei Unterschiede sind zu
erwarten und sagen nichts ueber die Richtigkeit aus:

  * Cura setzt das Modell selbst auf die Druckplatte, waehrend beim Aufruf
    ueber die Befehlszeile die Koordinaten des Modells unveraendert bleiben.
    Die Bahnen koennen also als Ganzes verschoben sein.
  * Cura traegt Druckzeit, Materialbedarf und den eigenen Einstellungsblock
    (;SETTING_3) in die Datei ein; CuraEngine allein laesst diese Angaben leer.

Deshalb wird die Form verglichen: Schichtanzahl, Schichthoehen, Anzahl und
Laenge der Bahnen je Schicht, Materialbedarf und die um den eigenen Nullpunkt
bereinigten Bahnverlaeufe.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


class Schicht:
    def __init__(self, nummer: int) -> None:
        self.nummer = nummer
        self.z: Optional[float] = None
        self.punkte: List[Tuple[float, float, bool]] = []   # x, y, druckend
        self.filament = 0.0        # nur die foerdernden Bewegungen
        self.netto = 0.0           # einschliesslich der Einzuege
        self.einzuege = 0
        self.druckweg = 0.0
        self.leerweg = 0.0

    @property
    def bahnen(self) -> int:
        return len(self.punkte)


def einlesen(pfad: str) -> Tuple[List[Schicht], Dict[str, Any]]:
    """Zerlegt eine G-Code-Datei in Schichten."""
    schichten: List[Schicht] = []
    aktuell = Schicht(-1)
    schichten.append(aktuell)
    kopf: Dict[str, Any] = {"einstellungsblock": False, "zeilen": 0}

    # G90/G91 schalten alle Achsen einschliesslich E zwischen absoluter und
    # relativer Angabe um; M82/M83 danach nur E. Der End-G-Code vieler
    # Drucker benutzt G91 fuer Einzug und Anheben ("G1 E-2 Z0.2").
    absolut_xyz = True
    absolut_e = True
    letztes_e = 0.0
    x = y = z = None

    with open(pfad, "r", errors="replace") as datei:
        for zeile in datei:
            kopf["zeilen"] += 1
            if zeile.startswith(";SETTING_"):
                kopf["einstellungsblock"] = True
                continue
            if zeile.startswith(";LAYER:"):
                aktuell = Schicht(int(zeile.split(":")[1]))
                schichten.append(aktuell)
                continue
            if zeile.startswith(";Generated with"):
                kopf["erzeuger"] = zeile.strip().split("with", 1)[1].strip()
                continue
            if zeile.startswith(";"):
                continue

            code = zeile.split(";", 1)[0].strip()
            if not code:
                continue
            teile = code.split()
            befehl = teile[0]
            if befehl in ("G90", "G91"):
                absolut_xyz = absolut_e = befehl == "G90"
                continue
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
                kennung = teil[:1]
                try:
                    zahl = float(teil[1:])
                except ValueError:
                    continue
                if kennung == "X":
                    nx = zahl if absolut_xyz or x is None else x + zahl
                elif kennung == "Y":
                    ny = zahl if absolut_xyz or y is None else y + zahl
                elif kennung == "Z":
                    nz = zahl if absolut_xyz or z is None else z + zahl
                elif kennung == "E":
                    e_wert = zahl

            zuwachs = 0.0
            if e_wert is not None:
                zuwachs = (e_wert - letztes_e) if absolut_e else e_wert
                if absolut_e:
                    letztes_e = e_wert
            druckend = zuwachs > 1e-9
            if druckend:
                aktuell.filament += zuwachs
            elif zuwachs < -1e-9:
                aktuell.einzuege += 1
            if e_wert is not None:
                aktuell.netto += zuwachs

            if None not in (x, y) and None not in (nx, ny):
                weg = math.hypot(nx - x, ny - y)
                if druckend:
                    aktuell.druckweg += weg
                else:
                    aktuell.leerweg += weg

            if nz is not None and aktuell.z is None:
                aktuell.z = nz
            aktuell.punkte.append((nx if nx is not None else 0.0,
                                   ny if ny is not None else 0.0, druckend))
            x, y, z = nx, ny, nz

    schichten = [s for s in schichten if s.punkte]
    return schichten, kopf


def rahmen(schichten: List[Schicht]) -> Tuple[float, float]:
    """Kleinste X- und Y-Koordinate der eigentlichen Druckbahnen.

    Die Bahnen vor der ersten Schicht bleiben unberuecksichtigt: sie stammen
    aus dem Start-G-Code des Druckers (die Vorbereitungslinie am Plattenrand)
    und liegen an fester Stelle, verschieben sich mit dem Modell also nicht.
    Nur so laesst sich die Verschiebung des Koerpers sauber herausrechnen.
    """
    xs = [p[0] for s in schichten if s.nummer >= 0 for p in s.punkte if p[2]]
    ys = [p[1] for s in schichten if s.nummer >= 0 for p in s.punkte if p[2]]
    return (min(xs) if xs else 0.0, min(ys) if ys else 0.0)


def ausmass(schicht: Schicht) -> Tuple[float, float]:
    """Breite und Tiefe der Druckbahnen einer Schicht -- verschiebungsfrei."""
    xs = [p[0] for p in schicht.punkte if p[2]]
    ys = [p[1] for p in schicht.punkte if p[2]]
    if not xs:
        return (0.0, 0.0)
    return (max(xs) - min(xs), max(ys) - min(ys))


def vergleiche(pfad_a: str, pfad_b: str, name_a: str, name_b: str) -> int:
    a, kopf_a = einlesen(pfad_a)
    b, kopf_b = einlesen(pfad_b)

    def zeile(bezeichnung: str, wert_a: Any, wert_b: Any,
              gleich: Optional[bool] = None) -> None:
        if gleich is None:
            gleich = wert_a == wert_b
        marke = "gleich" if gleich else "ABWEICHUNG"
        print(f"  {bezeichnung:<28} {str(wert_a):>16} {str(wert_b):>16}   {marke}")

    print(f"\n{'':30} {name_a:>16} {name_b:>16}")
    print("  " + "-" * 78)
    zeile("Erzeuger", kopf_a.get("erzeuger", "?"), kopf_b.get("erzeuger", "?"))
    zeile("Einstellungsblock", "ja" if kopf_a["einstellungsblock"] else "nein",
          "ja" if kopf_b["einstellungsblock"] else "nein", True)
    zeile("Schichten", len(a), len(b))

    # Massgeblich ist der Nettoverbrauch. Wer nur die foerdernden Bewegungen
    # zusammenzaehlt, rechnet jede Rueckfoerderung nach einem Einzug als
    # verbrauchtes Material mit und erhaelt einen zu hohen Wert.
    fil_a = sum(s.netto for s in a)
    fil_b = sum(s.netto for s in b)
    abw_fil = abs(fil_a - fil_b) / max(abs(fil_a), 1e-9)
    zeile("Filament netto (mm)", f"{fil_a:.4f}", f"{fil_b:.4f}", abw_fil < 0.001)
    zeile("Einzuege", sum(s.einzuege for s in a), sum(s.einzuege for s in b))

    weg_a = sum(s.druckweg for s in a)
    weg_b = sum(s.druckweg for s in b)
    abw_weg = abs(weg_a - weg_b) / max(weg_a, 1e-9)
    zeile("Druckweg (mm)", f"{weg_a:.1f}", f"{weg_b:.1f}", abw_weg < 0.005)

    zeile("Bewegungen", sum(s.bahnen for s in a), sum(s.bahnen for s in b))

    ver_a, ver_b = rahmen(a), rahmen(b)
    zeile("Nullpunkt X/Y",
          f"{ver_a[0]:.1f}/{ver_a[1]:.1f}", f"{ver_b[0]:.1f}/{ver_b[1]:.1f}")
    versatz = (ver_b[0] - ver_a[0], ver_b[1] - ver_a[1])
    if abs(versatz[0]) > 1e-6 or abs(versatz[1]) > 1e-6:
        print(f"  {'Versatz des Koerpers':<28} "
              f"{'X %+.3f  Y %+.3f mm' % versatz:>36}   wird herausgerechnet")

    print("\n  Schichtweiser Vergleich (Bahnen, Filament, Druckweg):")
    print(f"  {'Schicht':>5} {'Z':>7} {'Bahnen A/B':>14} {'Filament A/B':>18} "
          f"{'Druckweg A/B':>18}  Form")
    fehler = 0
    for nummer in range(max(len(a), len(b))):
        sa = a[nummer] if nummer < len(a) else None
        sb = b[nummer] if nummer < len(b) else None
        if sa is None or sb is None:
            print(f"  {nummer:>5} {'—':>7} "
                  f"{(sa.bahnen if sa else '—'):>6}/{(sb.bahnen if sb else '—'):<7} "
                  f"{'':>18} {'':>18}  NUR IN EINER DATEI")
            fehler += 1
            continue
        # Bahnverlauf um den jeweiligen Nullpunkt bereinigt vergleichen
        form = _formabweichung(sa, sb, ver_a, ver_b)
        if form is not None:
            marke = ("deckungsgleich" if form < 0.01
                     else f"Abweichung {form:.3f} mm")
            if form >= 0.01:
                fehler += 1
        else:
            # Bei unterschiedlicher Bahnzahl bleibt der Vergleich der
            # verschiebungsfreien Ausmasse und der Weglaenge.
            ma, mb = ausmass(sa), ausmass(sb)
            passt = (abs(ma[0] - mb[0]) < 0.01 and abs(ma[1] - mb[1]) < 0.01
                     and abs(sa.druckweg - sb.druckweg)
                     / max(sa.druckweg, 1e-9) < 0.002)
            marke = (f"Ausmass {ma[0]:.2f}x{ma[1]:.2f} gleich, "
                     f"{abs(sa.bahnen - sb.bahnen)} Bahnen Unterschied"
                     if passt else
                     f"Ausmass {ma[0]:.2f}x{ma[1]:.2f} gegen {mb[0]:.2f}x{mb[1]:.2f}")
            if not passt:
                fehler += 1
        print(f"  {(str(sa.nummer) if sa.nummer >= 0 else 'Start'):>5} "
              f"{(sa.z if sa.z is not None else 0):>7.2f} "
              f"{sa.bahnen:>6}/{sb.bahnen:<7} "
              f"{sa.filament:>8.2f}/{sb.filament:<9.2f} "
              f"{sa.druckweg:>8.1f}/{sb.druckweg:<9.1f}  {marke}")

    print()
    if fehler == 0:
        print("  Ergebnis: Die Bahnen sind Schicht fuer Schicht deckungsgleich.")
    else:
        print(f"  Ergebnis: {fehler} Schichten weichen ab (siehe oben).")
    return 0 if fehler == 0 else 1


def _formabweichung(sa: Schicht, sb: Schicht,
                    ver_a: Tuple[float, float],
                    ver_b: Tuple[float, float]) -> Optional[float]:
    """Groesste Abweichung der Bahnpunkte nach Ausgleich der Verschiebung.

    Die Verschiebung wird nur bei den Schichten des Koerpers ausgeglichen.
    Die Bewegungen vor der ersten Schicht stammen aus dem Start-G-Code des
    Druckers und stehen an fester Stelle; sie wandern mit dem Modell nicht
    mit und duerfen deshalb auch nicht mitgerechnet werden.
    """
    if sa.bahnen != sb.bahnen:
        return None
    if sa.nummer < 0:
        ver_a = ver_b = (0.0, 0.0)
    groesste = 0.0
    for (xa, ya, _), (xb, yb, _) in zip(sa.punkte, sb.punkte):
        abstand = math.hypot((xa - ver_a[0]) - (xb - ver_b[0]),
                             (ya - ver_a[1]) - (yb - ver_b[1]))
        groesste = max(groesste, abstand)
    return groesste


def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Vergleicht zwei G-Code-Dateien der Form nach.")
    zerleger.add_argument("datei_a")
    zerleger.add_argument("datei_b")
    zerleger.add_argument("--name-a", default="A")
    zerleger.add_argument("--name-b", default="B")
    angaben = zerleger.parse_args()
    for pfad in (angaben.datei_a, angaben.datei_b):
        if not os.path.isfile(pfad):
            print(f"Datei nicht gefunden: {pfad}", file=sys.stderr)
            return 2
    return vergleiche(angaben.datei_a, angaben.datei_b,
                      angaben.name_a, angaben.name_b)


if __name__ == "__main__":
    sys.exit(main())
