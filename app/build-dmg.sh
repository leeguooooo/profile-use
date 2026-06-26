#!/usr/bin/env bash
# Build ProfileUse.app (Release) and package a .dmg. Ad-hoc signed (not notarized),
# same model as ChooseBrowser: distribute via GitHub Releases + curl install.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${SCRIPT_DIR}/ProfileUse.xcodeproj"
SCHEME="ProfileUse"
APP_NAME="ProfileUse"
DERIVED="${SCRIPT_DIR}/.build/release"
OUT="${SCRIPT_DIR}/build"
APP="${OUT}/${APP_NAME}.app"
DMG="${OUT}/${APP_NAME}.dmg"

command -v xcodegen >/dev/null && xcodegen generate --project "${SCRIPT_DIR}" >/dev/null 2>&1 || true
mkdir -p "${OUT}"
rm -rf "${APP}" "${DMG}"

xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -configuration Release \
	-destination 'platform=macOS' -derivedDataPath "${DERIVED}" build >/dev/null

ditto "${DERIVED}/Build/Products/Release/${APP_NAME}.app" "${APP}"

TMP="${OUT}/.dmg-root"
rm -rf "${TMP}"; mkdir -p "${TMP}"
ditto "${APP}" "${TMP}/${APP_NAME}.app"
ln -s /Applications "${TMP}/Applications"
hdiutil create -volname "${APP_NAME}" -srcfolder "${TMP}" -ov -format UDZO "${DMG}" >/dev/null
rm -rf "${TMP}"

echo "app: ${APP}"
echo "dmg: ${DMG}"
