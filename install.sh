#!/bin/bash
# Telegram Digest — installer / updater for macOS. Paste into Terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.sh | bash
#
# Installs into ~/TelegramDigest, keeps your settings and exports when updating,
# starts the app in the background and opens http://localhost:8765.
set -euo pipefail
ZIP_URL="https://github.com/m3h0w/telegram-digest/archive/refs/heads/main.zip"
DEST="$HOME/TelegramDigest"
FILES="app.py export.py update.py release.json ui.html setup.sh service.pyw install.ps1 README.md AI-SETUP.md HOW-TO-DIGEST.md .env.example"

if [ "$(uname)" != "Darwin" ]; then
  echo "This installer is for a Mac. On Windows, paste this into PowerShell instead:"; echo "  irm https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.ps1 | iex"; exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
  echo
  echo "macOS needs to install Apple's free developer tools first (they include Python)."
  echo "A window will pop up: click Install, wait for it to finish, then run this same command again."
  xcode-select --install 2>/dev/null || true
  exit 1
fi

echo "→ Downloading Telegram Digest…"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$ZIP_URL" -o "$TMP/app.zip"
unzip -q "$TMP/app.zip" -d "$TMP"
SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -1)"

mkdir -p "$DEST"
for f in $FILES; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DEST/$f"
done
echo "→ Installed to $DEST"

bash "$DEST/setup.sh"
echo
echo "Next: in the page that just opened, go to Setup. Bookmark http://localhost:8765"
