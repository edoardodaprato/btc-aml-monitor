#!/bin/bash
# Double-click this file (macOS) to open the Tracery control panel in the browser.
# Requires the installation described in docs/GUIDE.md (section 1).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/btc-aml ]; then
  echo "btc-aml-monitor is not installed yet. See docs/GUIDE.md, section 1 (Installation)."
  read -r -p "Press Enter to close."
  exit 1
fi
.venv/bin/btc-aml ui
