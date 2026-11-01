#!/usr/bin/env python3
"""Prepare an automatic release from conventional commits since the last tag.

Prints the new tag after bumping every version file, or nothing when no commit
is releasable. feat -> minor, fix -> patch, a breaking ! -> minor; everything
else is ignored, which also skips the bot's own chore(release) commits. CI
commits, tags and pushes. Pre-1.0, so breaking changes do not bump major.
"""
import re
import subprocess
from pathlib import Path

TAG_PREFIX = "v"
PROJECT = "app/project.yml"
PLIST = "app/ProfileUse/App/Info.plist"
# (file, regex with the value as group 2)
MARKETING = [
    (PROJECT, r'(CFBundleShortVersionString: ")([^"]+)'),
    (PLIST, r"(<key>CFBundleShortVersionString</key>\s*<string>)([^<]+)"),
]
BUILD = [
    (PROJECT, r'(CFBundleVersion: ")([^"]+)'),
    (PLIST, r"(<key>CFBundleVersion</key>\s*<string>)([^<]+)"),
]
RELEASABLE = re.compile(r"^(feat|fix)(\([^)]*\))?(!)?: ")
STABLE = re.compile(re.escape(TAG_PREFIX) + r"(\d+)\.(\d+)\.(\d+)$")


def git(*args):
    return subprocess.check_output(("git",) + args, text=True)


def replace(fields, expected, new):
    """Replace each field, refusing to touch a file that disagrees with `expected`."""
    for name, pattern in fields:
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        found = re.findall(pattern, text)
        if len(found) != 1 or found[0][1] != expected:
            raise SystemExit("%s: expected %s once, found %r" % (name, expected, found))
        path.write_text(re.sub(pattern, lambda m: m.group(1) + new, text), encoding="utf-8")


def main():
    tags = git("tag", "--list", TAG_PREFIX + "*", "--sort=-version:refname").split()
    latest = next(tag for tag in tags if STABLE.match(tag))
    subjects = git("log", "--no-merges", "--format=%s", latest + "..HEAD").splitlines()
    matches = [m for m in map(RELEASABLE.match, subjects) if m]
    if not matches:
        return
    major, minor, patch = map(int, STABLE.match(latest).groups())
    if any(m.group(1) == "feat" or m.group(3) for m in matches):
        minor, patch = minor + 1, 0
    else:
        patch += 1
    version = "%d.%d.%d" % (major, minor, patch)
    if TAG_PREFIX + version in tags:
        raise SystemExit("tag for %s already exists" % version)
    build = re.search(BUILD[0][1], Path(PROJECT).read_text(encoding="utf-8")).group(2)
    replace(MARKETING, latest[len(TAG_PREFIX):], version)
    replace(BUILD, build, str(int(build) + 1))
    print(TAG_PREFIX + version)


if __name__ == "__main__":
    main()
