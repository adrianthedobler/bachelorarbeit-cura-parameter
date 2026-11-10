#!/bin/bash
# Doppelklick startet die Oberflaeche im Terminal.
cd "$(dirname "$0")" || exit 1
exec python3 "cura-ui.py" "$@"
