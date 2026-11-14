#!/bin/bash
# Install or update telegram-digest.   Run from the repo:  bash setup.sh
# Everything else (API keys, Telegram login, choosing groups) happens in the web app.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
LABEL="local.telegram-digest"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT=8765

echo "→ Python environment…"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip telethon
[ -f .env ] && chmod 600 .env

echo "→ Starting the app in the background (it also starts when you log in)…"
mkdir -p logs "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/.venv/bin/python</string>
    <string>$DIR/app.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$(printf '%s' "$PATH" | sed 's/&/\&amp;/g; s/</\&lt;/g')</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/app.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/app.log</string>
</dict>
</plist>
EOF
# remove the first version's service name, if present
launchctl bootout "gui/$(id -u)/com.michal.telegram-digest" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.michal.telegram-digest.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$PLIST"

for _ in $(seq 1 30); do
  curl -s -o /dev/null "http://localhost:$PORT/api/status" && break
  sleep 0.5
done
echo "✓ Running at http://localhost:$PORT  (log: logs/app.log)"
open "http://localhost:$PORT"
