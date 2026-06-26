#!/bin/sh
# ProfileUse.app installer (the macOS GUI).
#   curl -fsSL https://raw.githubusercontent.com/leeguooooo/profile-use/main/install-app.sh | sh
# curl downloads aren't quarantined, so macOS won't show the Gatekeeper "Move to Trash" prompt.
set -eu
REPO="leeguooooo/profile-use"; APP="ProfileUse"
[ "$(uname -s)" = "Darwin" ] || { echo "error: macOS only." >&2; exit 1; }
TMP="$(mktemp -d)"; MNT=""
cleanup() { [ -n "$MNT" ] && hdiutil detach "$MNT" -quiet 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT
echo "Downloading the latest ${APP}…"
curl -fsSL -o "$TMP/${APP}.dmg" "https://github.com/${REPO}/releases/latest/download/${APP}.dmg"
pkill -x "$APP" 2>/dev/null || true
MNT="$(hdiutil attach -nobrowse -noautoopen -quiet "$TMP/${APP}.dmg" | grep -o '/Volumes/.*' | head -1)"
echo "Installing to /Applications (you may be asked for your password)…"
sudo rm -rf "/Applications/${APP}.app"
sudo cp -R "$MNT/${APP}.app" "/Applications/${APP}.app"
sudo xattr -cr "/Applications/${APP}.app" 2>/dev/null || true
echo ""
echo "✅ ${APP} installed to /Applications. Launch it from Spotlight."
