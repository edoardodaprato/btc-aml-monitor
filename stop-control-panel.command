#!/bin/bash
# Double-click this file (macOS) to switch off the Tracery control panel service.
# start-control-panel.command switches it on again.
cd "$(dirname "$0")" || exit 1
scripts/control-panel-service.sh uninstall
read -r -p "Press Enter to close."
