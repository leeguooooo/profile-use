#!/bin/sh
# Install (or update) the ProfileUse menu bar app from the latest GitHub release.
#   curl -fsSL https://raw.githubusercontent.com/leeguooooo/profile-use/main/install-app.sh | sh
# Verifies the dmg's sha256 and that the app is notarized before installing, and
# installs it owned by you (no sudo), so the app can update itself in place.
set -eu
REPO="leeguooooo/profile-use"; APP="ProfileUse"
BASE="https://github.com/${REPO}/releases/latest/download"
DEST="${PROFILE_USE_APP_DIR:-/Applications}"
[ "$(uname -s)" = "Darwin" ] || { echo "error: macOS only." >&2; exit 1; }
TMP="$(mktemp -d)"; MNT=""
cleanup() { [ -n "$MNT" ] && hdiutil detach "$MNT" -quiet 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

echo "Downloading the latest ${APP}…"
curl -fsSL -o "$TMP/${APP}.dmg" "${BASE}/${APP}.dmg"
curl -fsSL -o "$TMP/${APP}.dmg.sha256" "${BASE}/${APP}.dmg.sha256" \
  || { echo "error: this release has no checksum — refusing to install an unverified download" >&2; exit 1; }
want="$(awk '{print $1}' "$TMP/${APP}.dmg.sha256")"
got="$(shasum -a 256 "$TMP/${APP}.dmg" | awk '{print $1}')"
[ -n "$want" ] && [ "$want" = "$got" ] || { echo "error: checksum mismatch for ${APP}.dmg" >&2; exit 1; }

MNT="$(hdiutil attach -nobrowse -noautoopen "$TMP/${APP}.dmg" | grep -o '/Volumes/.*' | head -1)"
spctl --assess --type execute "$MNT/${APP}.app" 2>/dev/null \
  || { echo "error: ${APP}.app is not notarized — refusing to install" >&2; exit 1; }

mkdir -p "$DEST"
[ -w "$DEST" ] || { echo "error: can't write to $DEST (set PROFILE_USE_APP_DIR=\$HOME/Applications)" >&2; exit 1; }
TARGET="$DEST/${APP}.app"
pkill -x "$APP" 2>/dev/null || true
if [ -e "$TARGET" ]; then
  if [ "$(stat -f %u "$TARGET")" != "$(id -u)" ]; then
    # Older install-app.sh copied with sudo; a root-owned app can't update itself.
    echo "Removing an old root-owned ${APP}.app (one-time; asks for your password)…"
    sudo rm -rf "$TARGET"
  else
    rm -rf "$TARGET"
  fi
fi
ditto "$MNT/${APP}.app" "$TARGET"
ver="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$TARGET/Contents/Info.plist" 2>/dev/null || echo '?')"
echo ""
echo "✅ ${APP} ${ver} installed to ${DEST}. It updates itself from now on."
open "$TARGET" 2>/dev/null || true
