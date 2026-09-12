@echo off
rem Doppelklick startet die Oberflaeche in der Eingabeaufforderung.
cd /d "%~dp0"

rem Python heisst unter Windows je nach Installation anders.
where py >nul 2>nul && (
    py -3 "cura-ui.py" %*
    goto ende
)
where python >nul 2>nul && (
    python "cura-ui.py" %*
    goto ende
)
echo Python 3 wurde nicht gefunden. Bitte von python.org installieren
echo und dabei "Add Python to PATH" auswaehlen.
pause

:ende
if errorlevel 1 pause
