#!/usr/bin/env bash
# Build ProfileUse.app (Release) and package it for GitHub Releases.
#
# With SIGN_ID and NOTARY_PROFILE set (what scripts/release.sh requires) the app is
# Developer ID signed with the hardened runtime, notarized and stapled, and the
# outputs are:
#   build/ProfileUse.dmg (+ .sha256)              install-app.sh / manual install
#   build/ProfileUse-macos.tar.gz (+ .sha256)     the app's in-place updater
# Without them it is a local, ad-hoc signed development build (dmg only).
#
#   SIGN_ID="Developer ID Application: LI GUO (6ZPXG4KVVS)"
#   NOTARY_PROFILE=<xcrun notarytool store-credentials profile> [NOTARY_KEYCHAIN=<keychain path>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${SCRIPT_DIR}/ProfileUse.xcodeproj"
SCHEME="ProfileUse"
APP_NAME="ProfileUse"
DERIVED="${SCRIPT_DIR}/.build/release"
OUT="${SCRIPT_DIR}/build"
APP="${OUT}/${APP_NAME}.app"
DMG="${OUT}/${APP_NAME}.dmg"
TARBALL="${OUT}/${APP_NAME}-macos.tar.gz"
TEAM_ID="6ZPXG4KVVS"
SIGN_ID="${SIGN_ID:-}"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"
NOTARY_KEYCHAIN="${NOTARY_KEYCHAIN:-}"

if command -v xcodegen >/dev/null; then ( cd "${SCRIPT_DIR}" && xcodegen generate >/dev/null ); fi
mkdir -p "${OUT}"
rm -rf "${APP}" "${DMG}" "${DMG}.sha256" "${TARBALL}" "${TARBALL}.sha256"

notarize() {
	local args=(--keychain-profile "${NOTARY_PROFILE}" --wait)
	[[ -n "${NOTARY_KEYCHAIN}" ]] && args+=(--keychain "${NOTARY_KEYCHAIN}")
	xcrun notarytool submit "$1" "${args[@]}"
}

if [[ -n "${SIGN_ID}" ]]; then
	[[ -n "${NOTARY_PROFILE}" ]] || { echo "error: SIGN_ID needs NOTARY_PROFILE (xcrun notarytool store-credentials)" >&2; exit 1; }
	xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -configuration Release \
		-destination 'platform=macOS' -derivedDataPath "${DERIVED}" CODE_SIGNING_ALLOWED=NO build >/dev/null
	ditto "${DERIVED}/Build/Products/Release/${APP_NAME}.app" "${APP}"
	codesign --force --options runtime --timestamp --sign "${SIGN_ID}" "${APP}"
	codesign --verify --deep --strict "${APP}"
	info="$(codesign --display --verbose=4 "${APP}" 2>&1)"
	[[ "${info}" == *"TeamIdentifier=${TEAM_ID}"* && "${info}" == *"Runtime Version="* ]] \
		|| { echo "error: app is not Developer ID signed for ${TEAM_ID} with the hardened runtime" >&2; exit 1; }
	ZIP="${OUT}/${APP_NAME}-notarize.zip"
	ditto -c -k --keepParent "${APP}" "${ZIP}"
	notarize "${ZIP}"
	rm -f "${ZIP}"
	xcrun stapler staple "${APP}"
	spctl --assess --type execute "${APP}"
else
	echo "note: SIGN_ID not set — ad-hoc development build (not for release)" >&2
	xcodebuild -project "${PROJECT}" -scheme "${SCHEME}" -configuration Release \
		-destination 'platform=macOS' -derivedDataPath "${DERIVED}" build >/dev/null
	ditto "${DERIVED}/Build/Products/Release/${APP_NAME}.app" "${APP}"
fi

TMP="${OUT}/.dmg-root"
rm -rf "${TMP}"; mkdir -p "${TMP}"
ditto "${APP}" "${TMP}/${APP_NAME}.app"
ln -s /Applications "${TMP}/Applications"
hdiutil create -volname "${APP_NAME}" -srcfolder "${TMP}" -ov -format UDZO "${DMG}" >/dev/null
rm -rf "${TMP}"

if [[ -n "${SIGN_ID}" ]]; then
	codesign --force --timestamp --sign "${SIGN_ID}" "${DMG}"
	notarize "${DMG}"
	xcrun stapler staple "${DMG}"
	tar -czf "${TARBALL}" -C "${OUT}" "${APP_NAME}.app"
	( cd "${OUT}" && shasum -a 256 "${APP_NAME}.dmg" > "${APP_NAME}.dmg.sha256" \
		&& shasum -a 256 "${APP_NAME}-macos.tar.gz" > "${APP_NAME}-macos.tar.gz.sha256" )
	echo "tarball: ${TARBALL}"
fi

echo "app: ${APP}"
echo "dmg: ${DMG}"
