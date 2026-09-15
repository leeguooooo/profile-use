#!/bin/sh
# Install the profile-use skill from this checkout and enable the leak-scan pre-commit hook.
# Re-run any time; `git pull` then keeps the skill up to date (it is a symlink into this repo).
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)

link() {  # link <target> <link-path>; never replaces a real directory
  if [ -e "$2" ] && [ ! -L "$2" ]; then
    echo "skip: $2 exists and is not a symlink (move it aside, then re-run)"
  else
    ln -sfn "$1" "$2" && echo "linked: $2 -> $1"
  fi
}

mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
link "$ROOT" "$HOME/.agents/skills/profile-use"
link "../../.agents/skills/profile-use" "$HOME/.claude/skills/profile-use"
[ -d "$HOME/.codex/skills" ] && link "$ROOT" "$HOME/.codex/skills/profile-use"

chmod +x "$ROOT/.githooks/pre-commit" "$ROOT/scripts/profile_use.py"
git -C "$ROOT" config core.hooksPath .githooks && echo "hook: core.hooksPath=.githooks"

echo "profile: $(python3 "$ROOT/scripts/profile_use.py" path)"
