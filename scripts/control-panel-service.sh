#!/bin/bash
# Run the Tracery control panel as a macOS background service (a per-user LaunchAgent).
#
# Once installed the panel starts at login, restarts by itself if it ever stops and needs
# no Terminal window. It still listens only on 127.0.0.1 (this computer).
#
# Usage: scripts/control-panel-service.sh install | uninstall | status
set -euo pipefail

LABEL="io.github.edoardodaprato.tracery"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="http://127.0.0.1:8765/"
DOMAIN="gui/$(id -u)"

wait_until_up() {
  for _ in $(seq 1 40); do
    if curl -fs -o /dev/null "$URL"; then return 0; fi
    sleep 0.5
  done
  return 1
}

case "${1:-status}" in
  install)
    if [ ! -x "$ROOT/.venv/bin/btc-aml" ]; then
      echo "btc-aml-monitor is not installed yet. See docs/GUIDE.md, section 1 (Installation)." >&2
      exit 1
    fi
    mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/output"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/.venv/bin/btc-aml</string>
    <string>ui</string>
    <string>--no-browser</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$ROOT/output/control-panel.log</string>
  <key>StandardErrorPath</key><string>$ROOT/output/control-panel.log</string>
</dict>
</plist>
PLIST
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    if wait_until_up; then
      echo "Tracery control panel is running at $URL and will stay on (also after a restart)."
    else
      echo "The service is installed but the panel does not answer yet." >&2
      echo "Is another copy already using port 8765? Details: output/control-panel.log" >&2
      exit 1
    fi
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Tracery control panel stopped; it will no longer start automatically."
    ;;
  status)
    if [ -f "$PLIST" ]; then echo "Service installed."; else echo "Service not installed."; fi
    if curl -fs -o /dev/null "$URL"; then echo "Panel answering at $URL"; else echo "Panel not answering."; fi
    ;;
  *)
    echo "Usage: $0 install | uninstall | status" >&2
    exit 2
    ;;
esac
