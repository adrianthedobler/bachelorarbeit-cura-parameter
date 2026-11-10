# -*- coding: utf-8 -*-
"""Tastatur und Bildschirm.

Bewusst ohne zusaetzliche Bibliotheken. Die Standardbibliothek bietet mit
curses zwar eine fertige Loesung, diese fehlt unter Windows jedoch. Deshalb
wird hier auf beiden Systemen mit denselben Steuerzeichen (ANSI) gearbeitet;
lediglich das Einlesen einzelner Tastendruecke unterscheidet sich, weil macOS
dafuer termios und Windows msvcrt benutzt.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional, Tuple

IST_WINDOWS = os.name == "nt"

if IST_WINDOWS:
    import msvcrt
else:
    import termios
    import tty


# ------------------------------------------------------------- Steuerzeichen

VERSTECKEN = "\x1b[?25l"
ZEIGEN = "\x1b[?25h"
LEEREN = "\x1b[2J\x1b[H"
NACH_OBEN = "\x1b[H"
ZEILE_LOESCHEN = "\x1b[K"
ALTERNATIV_AN = "\x1b[?1049h"
ALTERNATIV_AUS = "\x1b[?1049l"

NORMAL = "\x1b[0m"
FETT = "\x1b[1m"
SCHWACH = "\x1b[2m"
UNTERSTRICHEN = "\x1b[4m"
INVERS = "\x1b[7m"

ROT = "\x1b[31m"
GRUEN = "\x1b[32m"
GELB = "\x1b[33m"
BLAU = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
GRAU = "\x1b[90m"

HELLGRUEN = "\x1b[92m"
HELLGELB = "\x1b[93m"
HELLBLAU = "\x1b[94m"
HELLCYAN = "\x1b[96m"


def farben_moeglich() -> bool:
    """Ob das Terminal Farben und Steuerzeichen darstellen kann."""
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if IST_WINDOWS:
        return _windows_ansi_einschalten()
    return os.environ.get("TERM", "") not in ("", "dumb")


def _windows_ansi_einschalten() -> bool:
    """Schaltet in der Windows-Eingabeaufforderung die Steuerzeichen frei.

    Seit Windows 10 versteht die Konsole ANSI-Folgen, muss dafuer aber
    ausdruecklich umgeschaltet werden.
    """
    try:
        import ctypes
        kernel = ctypes.windll.kernel32          # type: ignore[attr-defined]
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        griff = kernel.GetStdHandle(-11)
        modus = ctypes.c_uint32()
        if not kernel.GetConsoleMode(griff, ctypes.byref(modus)):
            return False
        kernel.SetConsoleMode(
            griff, modus.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        return True
    except Exception:
        return False


def groesse() -> Tuple[int, int]:
    """Breite und Hoehe des Terminals in Zeichen."""
    masse = shutil.get_terminal_size(fallback=(100, 30))
    return max(60, masse.columns), max(14, masse.lines)


# -------------------------------------------------------------- Tastendruck

#: Namen fuer Tasten, die mehr als ein Zeichen senden.
HOCH = "hoch"
RUNTER = "runter"
LINKS = "links"
RECHTS = "rechts"
BILD_HOCH = "bild_hoch"
BILD_RUNTER = "bild_runter"
ANFANG = "anfang"
ENDE = "ende"
ENTF = "entf"
RUECK = "rueck"
EINGABE = "eingabe"
ESC = "esc"
TAB = "tab"


def taste() -> str:
    """Wartet auf einen Tastendruck und liefert ihn als Text.

    Gewoehnliche Zeichen kommen unveraendert zurueck, Sondertasten unter den
    oben festgelegten Namen.
    """
    if IST_WINDOWS:
        return _taste_windows()
    return _taste_posix()


def _taste_windows() -> str:
    zeichen = msvcrt.getwch()
    if zeichen in ("\x00", "\xe0"):        # Vorzeichen fuer Sondertasten
        zweites = msvcrt.getwch()
        return {
            "H": HOCH, "P": RUNTER, "K": LINKS, "M": RECHTS,
            "I": BILD_HOCH, "Q": BILD_RUNTER, "G": ANFANG, "O": ENDE,
            "S": ENTF,
        }.get(zweites, "")
    if zeichen in ("\r", "\n"):
        return EINGABE
    if zeichen == "\x08":
        return RUECK
    if zeichen == "\x1b":
        return ESC
    if zeichen == "\t":
        return TAB
    return zeichen


def _taste_posix() -> str:
    """Liest einen Tastendruck unter macOS und Linux.

    Gelesen wird mit os.read unmittelbar von der Standardeingabe, nicht ueber
    sys.stdin. Der Unterschied ist wesentlich: sys.stdin puffert intern und
    holt sich beim Lesen eines einzelnen Zeichens gleich alles ab, was
    anliegt. Eine Pfeiltaste sendet drei Zeichen ("\x1b[A"). Die beiden
    letzten laegen dann in Pythons Puffer, waehrend die Pruefung auf weitere
    Zeichen die Datei selbst betrachtet und sie dort nicht mehr faende -- die
    Pfeiltaste wuerde als Escape gedeutet.
    """
    dateinummer = sys.stdin.fileno()
    alt = termios.tcgetattr(dateinummer)
    try:
        tty.setraw(dateinummer)
        roh = os.read(dateinummer, 1)
        if not roh:
            return ESC
        if roh == b"\x1b":
            folge = _lies_folge(dateinummer)
            if folge is None:
                return ESC
            return folge
        zeichen = _entschluessle(dateinummer, roh)
    finally:
        termios.tcsetattr(dateinummer, termios.TCSADRAIN, alt)

    if zeichen in ("\r", "\n"):
        return EINGABE
    if zeichen in ("\x7f", "\x08"):
        return RUECK
    if zeichen == "\t":
        return TAB
    if zeichen == "\x03":
        raise KeyboardInterrupt
    return zeichen


def _entschluessle(dateinummer: int, erstes: bytes) -> str:
    """Vervollstaendigt ein Zeichen, das aus mehreren Bytes besteht.

    Umlaute und aehnliche Zeichen belegen in UTF-8 mehrere Bytes. Wird nur das
    erste gelesen, laesst es sich nicht deuten; die fehlenden werden hier
    nachgeholt.
    """
    wert = erstes[0]
    if wert < 0x80:
        return chr(wert)
    if wert >= 0xF0:
        fehlend = 3
    elif wert >= 0xE0:
        fehlend = 2
    elif wert >= 0xC0:
        fehlend = 1
    else:
        return ""
    gesammelt = bytearray(erstes)
    for _ in range(fehlend):
        weiteres = os.read(dateinummer, 1)
        if not weiteres:
            break
        gesammelt += weiteres
    return gesammelt.decode("utf-8", errors="replace")


def _lies_folge(dateinummer: int) -> Optional[str]:
    """Liest den Rest einer Steuerfolge, sofort und ohne lange zu warten.

    Steht nach dem einleitenden Escape nichts an, war es die Escape-Taste
    selbst. Die kurze Wartezeit ueberbrueckt langsame Verbindungen, bei denen
    die drei Zeichen einer Pfeiltaste nicht gleichzeitig eintreffen.
    """
    import select

    def naechstes() -> Optional[str]:
        bereit, _, _ = select.select([dateinummer], [], [], 0.05)
        if not bereit:
            return None
        roh = os.read(dateinummer, 1)
        return roh.decode("latin-1") if roh else None

    zweites = naechstes()
    if zweites is None:
        return None
    if zweites not in ("[", "O"):
        return ""

    gesammelt = ""
    for _ in range(8):
        drittes = naechstes()
        if drittes is None:
            break
        gesammelt += drittes
        if drittes.isalpha() or drittes == "~":
            break

    return {
        "A": HOCH, "B": RUNTER, "C": RECHTS, "D": LINKS,
        "H": ANFANG, "F": ENDE,
        "5~": BILD_HOCH, "6~": BILD_RUNTER,
        "1~": ANFANG, "4~": ENDE, "3~": ENTF,
        "7~": ANFANG, "8~": ENDE,
    }.get(gesammelt, "")


# ------------------------------------------------------------- Textausgabe

def sichtbare_laenge(text: str) -> int:
    """Laenge eines Textes ohne die Steuerzeichen fuer Farbe und Stil."""
    laenge = 0
    in_folge = False
    for zeichen in text:
        if in_folge:
            if zeichen.isalpha():
                in_folge = False
            continue
        if zeichen == "\x1b":
            in_folge = True
            continue
        laenge += 1
    return laenge


def kuerzen(text: str, breite: int) -> str:
    """Kuerzt einen Text auf die angegebene Breite, Steuerzeichen ausgenommen."""
    if sichtbare_laenge(text) <= breite:
        return text
    ergebnis = ""
    laenge = 0
    in_folge = False
    for zeichen in text:
        if in_folge:
            ergebnis += zeichen
            if zeichen.isalpha():
                in_folge = False
            continue
        if zeichen == "\x1b":
            ergebnis += zeichen
            in_folge = True
            continue
        if laenge >= breite - 1:
            return ergebnis + "…" + NORMAL
        ergebnis += zeichen
        laenge += 1
    return ergebnis


def fuellen(text: str, breite: int) -> str:
    """Fuellt einen Text mit Leerzeichen auf die angegebene Breite auf."""
    fehlend = breite - sichtbare_laenge(text)
    return text + " " * max(0, fehlend)


class Bildschirm:
    """Sammelt die Zeilen einer Anzeige und gibt sie in einem Stueck aus.

    Das Zeichnen in einem Zug vermeidet das Flackern, das entstuende, wenn
    jede Zeile einzeln geschrieben wuerde.
    """

    def __init__(self, farbig: bool) -> None:
        self.farbig = farbig
        self._zeilen: List[str] = []

    def f(self, farbe: str, text: str) -> str:
        """Faerbt einen Text, sofern das Terminal Farben darstellt."""
        return f"{farbe}{text}{NORMAL}" if self.farbig else text

    def zeile(self, text: str = "") -> None:
        self._zeilen.append(text)

    def zeichnen(self) -> None:
        breite, hoehe = groesse()
        ausgabe = [NACH_OBEN]
        for nummer in range(hoehe - 1):
            inhalt = self._zeilen[nummer] if nummer < len(self._zeilen) else ""
            ausgabe.append(kuerzen(inhalt, breite) + ZEILE_LOESCHEN + "\r\n")
        letzte = self._zeilen[hoehe - 1] if len(self._zeilen) >= hoehe else ""
        ausgabe.append(kuerzen(letzte, breite) + ZEILE_LOESCHEN)
        sys.stdout.write("".join(ausgabe))
        sys.stdout.flush()
        self._zeilen = []


def _ausgabe_auf_utf8() -> None:
    """Stellt sicher, dass die Sonderzeichen der Oberflaeche ausgegeben werden.

    Die Oberflaeche benutzt Linien- und Pfeilzeichen. Unter Windows arbeitet
    die Ausgabe je nach Umgebung mit einer aelteren Zeichentabelle, in der
    diese Zeichen fehlen; ohne diese Umstellung braeche das Programm dort mit
    einem Kodierungsfehler ab.
    """
    for strom in (sys.stdout, sys.stderr):
        umstellen = getattr(strom, "reconfigure", None)
        if umstellen is not None:
            try:
                umstellen(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def start() -> None:
    """Schaltet auf einen eigenen Bildschirmbereich um."""
    _ausgabe_auf_utf8()
    sys.stdout.write(ALTERNATIV_AN + VERSTECKEN + LEEREN)
    sys.stdout.flush()


def ende() -> None:
    """Gibt den urspruenglichen Bildschirminhalt zurueck."""
    sys.stdout.write(ZEIGEN + ALTERNATIV_AUS + NORMAL)
    sys.stdout.flush()


def eingabezeile(aufforderung: str, vorgabe: str = "") -> Optional[str]:
    """Fragt eine Texteingabe ab.

    Rueckgabe ist None, wenn mit Escape abgebrochen wurde. Die Eingabe wird
    selbst verwaltet, damit Escape erkannt werden kann; input() koennte das
    nicht.
    """
    text = vorgabe
    breite, hoehe = groesse()
    while True:
        sys.stdout.write(f"\x1b[{hoehe};1H" + ZEILE_LOESCHEN + ZEIGEN)
        sichtbar = text
        platz = breite - sichtbare_laenge(aufforderung) - 3
        if len(sichtbar) > platz:
            sichtbar = sichtbar[-platz:]
        sys.stdout.write(f"{aufforderung}{sichtbar}█")
        sys.stdout.flush()

        gedrueckt = taste()
        if gedrueckt == EINGABE:
            sys.stdout.write(VERSTECKEN)
            return text
        if gedrueckt == ESC:
            sys.stdout.write(VERSTECKEN)
            return None
        if gedrueckt == RUECK:
            text = text[:-1]
            continue
        if gedrueckt in (HOCH, RUNTER, LINKS, RECHTS, BILD_HOCH, BILD_RUNTER,
                         ANFANG, ENDE, ENTF, TAB, ""):
            continue
        if gedrueckt == "\x15":            # Strg+U leert die Zeile
            text = ""
            continue
        text += gedrueckt
