#!/bin/sh
# Runs install.sh the three ways people run it — piped from curl, as a downloaded copy outside
# any checkout, and from a checkout — with a fake git (clone = copy of this repo) and an
# isolated HOME. Checks the skill is always linked to a real checkout, never to where the
# script happened to sit. Nothing outside a temp dir is touched.
#   sh tests/install.test.sh
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat > "$TMP/bin/git" <<GIT
#!/bin/sh
for dest; do :; done
case "\$*" in
  *clone*) mkdir -p "\$dest" && cp -R "$REPO/." "\$dest/" ;;
  *config*|*pull*) ;;
esac
GIT
chmod +x "$TMP/bin/git"
export PATH="$TMP/bin:$PATH"

fail() { echo "FAIL: $1"; exit 1; }
fresh() { rm -rf "$TMP/home"; mkdir -p "$TMP/home"; export HOME="$TMP/home"; }
linked() { readlink "$HOME/.agents/skills/profile-use"; }

fresh; sh < "$REPO/install.sh" >/dev/null
[ "$(linked)" = "$HOME/.agents/use-family/profile-use" ] || fail "piped: linked to $(linked)"
[ -f "$(linked)/SKILL.md" ] || fail "piped: no SKILL.md behind the link"

fresh; mkdir -p "$TMP/dl"; cp "$REPO/install.sh" "$TMP/dl/install.sh"; sh "$TMP/dl/install.sh" >/dev/null
[ "$(linked)" = "$HOME/.agents/use-family/profile-use" ] || fail "downloaded copy: linked to $(linked)"

fresh; sh "$REPO/install.sh" >/dev/null
[ "$(linked)" = "$REPO" ] || fail "checkout: linked to $(linked), not the checkout"

echo "ok install.sh"
