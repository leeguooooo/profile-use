#!/bin/sh
# Release profile-use: bump the ProfileUse.app version, test, build ProfileUse.dmg, push main, publish the GitHub
# Release with the dmg attached (install-app.sh downloads it from releases/latest), then sync the plugin marketplace
# so Claude Code plugin installs pick the new version up right away (no token: uses your `gh` login).
#   scripts/release.sh [--dry-run] 0.2.0 [release-notes.md]
set -eu
run_ok() {  # run_ok <run-id> [-R owner/repo]: wait until the run completes (gh run watch can drop on a network error), then require success
  _r=$1; shift
  until [ "$(gh run view "$_r" "$@" --json status -q .status 2>/dev/null)" = completed ]; do gh run watch "$_r" "$@" >/dev/null 2>&1 || sleep 15; done
  [ "$(gh run view "$_r" "$@" --json conclusion -q .conclusion)" = success ]
}
DRY=; [ "${1:-}" = --dry-run ] && { DRY=1; shift; }
V=${1:?usage: scripts/release.sh [--dry-run] <version> [release-notes.md]}
V=${V#v}
NOTES=${2:-}
MARKETPLACE=leeguooooo/plugins
FILES="app/project.yml app/ProfileUse/App/Info.plist"
cd "$(dirname "$0")/.."
die() { echo "error: $*" >&2; exit 1; }

echo "$V" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "version must look like 0.2.0"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "not on main"
[ -z "$(git status --porcelain)" ] || die "working tree not clean"
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "main is not in sync with origin/main"
[ -z "$(git ls-remote --tags origin "refs/tags/v$V")" ] || die "v$V already exists"
[ -z "$NOTES" ] || [ -f "$NOTES" ] || die "no such notes file: $NOTES"
# Releases must be Developer ID signed + notarized: install-app.sh refuses anything
# else, and the app's in-place updater only accepts this team's notarized builds.
[ -n "$DRY" ] || { [ -n "${SIGN_ID:-}" ] && [ -n "${NOTARY_PROFILE:-}" ]; } \
  || die "set SIGN_ID (Developer ID Application identity) and NOTARY_PROFILE (notarytool profile); see app/build-dmg.sh"

# Marketing version + build number live in project.yml (xcodegen) and the generated Info.plist.
trap 'git checkout -q -- $FILES' EXIT
B=$(( $(sed -n 's/.*CFBundleVersion: "\([0-9]*\)".*/\1/p' app/project.yml) + 1 ))
sed -i.bak -e "s/CFBundleShortVersionString: \".*\"/CFBundleShortVersionString: \"$V\"/" \
  -e "s/CFBundleVersion: \".*\"/CFBundleVersion: \"$B\"/" app/project.yml
sed -i.bak -e "/<key>CFBundleShortVersionString<\/key>/{n;s|<string>.*</string>|<string>$V</string>|;}" \
  -e "/<key>CFBundleVersion<\/key>/{n;s|<string>.*</string>|<string>$B</string>|;}" app/ProfileUse/App/Info.plist
rm app/project.yml.bak app/ProfileUse/App/Info.plist.bak
python3 -m unittest discover -s tests -q
sh -n install.sh install-app.sh && bash -n app/build-dmg.sh

if [ -n "$DRY" ]; then
  git --no-pager diff
  echo "dry run: reverted; nothing built, committed, pushed or published"
  exit 0
fi
app/build-dmg.sh
trap - EXIT
git add -A app
git commit -qm "chore(release): v$V"
git push -q origin main

# gh creates the tag on the pushed commit together with the release, so the dmg is there as soon as the tag is.
set -- "v$V" app/build/ProfileUse.dmg app/build/ProfileUse.dmg.sha256 \
  app/build/ProfileUse-macos.tar.gz app/build/ProfileUse-macos.tar.gz.sha256 \
  --target "$(git rev-parse HEAD)" --title "ProfileUse v$V"
if [ -n "$NOTES" ]; then gh release create "$@" --notes-file "$NOTES"; else gh release create "$@" --generate-notes; fi
git fetch -q --tags origin

# The marketplace reads profile-use's version from its latest release; run its sync now instead of the hourly cron.
gh workflow run auto-sync-versions.yml -R "$MARKETPLACE"
sleep 5
RUN=$(gh run list -R "$MARKETPLACE" -w auto-sync-versions.yml -e workflow_dispatch -L 1 --json databaseId -q '.[0].databaseId')
run_ok "$RUN" -R "$MARKETPLACE" && echo "marketplace synced" || echo "warn: marketplace sync run $RUN failed; the hourly run will retry"
gh api "repos/$MARKETPLACE/contents/.claude-plugin/marketplace.json" -q .content | base64 -d \
  | python3 -c "import json,sys; print('marketplace profile-use:', next(p['version'] for p in json.load(sys.stdin)['plugins'] if p['name']=='profile-use'))"
