#!/bin/sh
# Install the profile-use skill and enable the leak-scan pre-commit hook.
#   curl -fsSL https://raw.githubusercontent.com/leeguooooo/profile-use/main/install.sh | sh
# Run from a checkout, it links that checkout. Otherwise (piped from curl, or a downloaded copy)
# it keeps a checkout under ~/.agents/use-family like the rest of the family.
# Re-run any time; `git pull` then keeps the skill up to date (it is a symlink into the checkout).
set -e
command -v git >/dev/null 2>&1 || { echo "error: git is required" >&2; exit 1; }

SELF_DIR=""
case "$0" in */install.sh) SELF_DIR=$(cd "$(dirname "$0")" && pwd) ;; esac
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/SKILL.md" ] && [ -f "$SELF_DIR/scripts/profile_use.py" ]; then
  ROOT=$SELF_DIR
else
  ROOT="${PROFILE_USE_HOME:-${USE_FAMILY_DIR:-$HOME/.agents/use-family}/profile-use}"
  if [ -d "$ROOT/.git" ]; then
    git -C "$ROOT" pull -q --ff-only || echo "warn: $ROOT not updated (local changes?)"
  else
    mkdir -p "$(dirname "$ROOT")"
    git clone -q --depth 1 https://github.com/leeguooooo/profile-use.git "$ROOT"
  fi
fi

link() {  # link <target> <link-path>; never replaces a real directory
  if [ -e "$2" ] && [ ! -L "$2" ]; then
    echo "skip: $2 exists and is not a symlink (move it aside, then re-run)"
  else
    ln -sfn "$1" "$2" && echo "linked: $2 -> $1"
  fi
}

mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
link "$ROOT" "$HOME/.agents/skills/profile-use"
# Claude Code gets the skill from the profile-use plugin when it is installed; a second
# copy here would list the skill twice.
if grep -q '"profile-use@' "$HOME/.claude/plugins/installed_plugins.json" 2>/dev/null; then
  echo "skip: $HOME/.claude/skills/profile-use (Claude Code already has the profile-use plugin)"
else
  link "../../.agents/skills/profile-use" "$HOME/.claude/skills/profile-use"
fi
[ -d "$HOME/.codex/skills" ] && link "$ROOT" "$HOME/.codex/skills/profile-use"

chmod +x "$ROOT/.githooks/pre-commit" "$ROOT/scripts/profile_use.py"
git -C "$ROOT" config core.hooksPath .githooks && echo "hook: core.hooksPath=.githooks"

echo "profile: $(python3 "$ROOT/scripts/profile_use.py" path)"
