#!/bin/bash
# Double-click this file (macOS) to open the Tracery control panel in the browser.
#
# The first time, it installs the panel as a background service: from then on the panel
# is always on (it starts at login and restarts by itself), and this window can be closed.
# To switch it off, double-click stop-control-panel.command.
# Requires the installation described in docs/GUIDE.md (section 1).
cd "$(dirname "$0")" || exit 1
URL="http://127.0.0.1:8765/"
if ! curl -fs -o /dev/null "$URL"; then
  if ! scripts/control-panel-service.sh install; then
    read -r -p "Press Enter to close."
    exit 1
  fi
fi
open "$URL"
echo "Tracery is running at $URL. You can close this window."
