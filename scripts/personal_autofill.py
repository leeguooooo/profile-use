#!/usr/bin/env python3
"""Manage local personal-autofill JSON profiles."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "references" / "profile-template.json"

HIGH_SENSITIVITY_PREFIXES = (
    "payment",
    "bank",
    "government_id",
    "tax",
    "identity.birthdate",
    "identity.gender",
)


def default_dir() -> Path:
    override = os.environ.get("PERSONAL_AUTOFILL_DIR")
    if override:
        return Path(override).expanduser()
    icloud = (
        Path.home()
        / "Library"
        / "Mobile Documents"
        / "com~apple~CloudDocs"
        / "Agent Profiles"
        / "personal-autofill"
    )
    if icloud.parent.exists():
        return icloud
    return Path.home() / ".config" / "personal-autofill"


def profile_path(profile: str, directory: Path | None = None) -> Path:
    return (directory or default_dir()) / f"{profile}.profile.json"


def load_profile(profile: str, directory: Path | None = None) -> dict[str, Any]:
    path = profile_path(profile, directory)
    if not path.exists():
        raise SystemExit(
            f"Profile not found: {path}\n"
            f"Create it with: {Path(sys.argv[0]).name} init --profile {profile}"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def get_path(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted)
        current = current[part]
    return current


def redact_value(path: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_value(f"{path}.{key}" if path else key, val) for key, val in value.items()}
    if isinstance(value, list):
        return [redact_value(path, item) for item in value]
    if value in ("", None):
        return value
    if isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    if path.startswith(HIGH_SENSITIVITY_PREFIXES):
        return mask_tail(text, 4)
    if "email" in path:
        return redact_email(text)
    if "phone" in path or "postal_code" in path:
        return mask_tail(text, 2)
    if path.startswith("address.line"):
        return mask_tail(text, 4)
    return text


def redact_email(value: str) -> str:
    if "@" not in value:
        return mask_tail(value, 2)
    name, domain = value.split("@", 1)
    if not name:
        return f"***@{domain}"
    return f"{name[:1]}***@{domain}"


def mask_tail(value: str, keep: int) -> str:
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def command_init(args: argparse.Namespace) -> None:
    path = profile_path(args.profile, args.directory)
    if path.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing profile: {path}\nUse --force to replace it.")
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    template["profile_name"] = args.profile
    write_json(path, template)
    print(path)


def command_path(args: argparse.Namespace) -> None:
    print(profile_path(args.profile, args.directory))


def command_show(args: argparse.Namespace) -> None:
    data = load_profile(args.profile, args.directory)
    if not args.reveal:
        data = redact_value("", data)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def command_get(args: argparse.Namespace) -> None:
    data = load_profile(args.profile, args.directory)
    result: dict[str, Any] = {}
    for field in args.fields:
        try:
            value = get_path(data, field)
        except KeyError:
            result[field] = None
            continue
        result[field] = value if args.reveal else redact_value(field, value)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def command_check(args: argparse.Namespace) -> None:
    data = load_profile(args.profile, args.directory)
    problems: list[str] = []
    for section in ("identity", "contact", "address"):
        if section not in data or not isinstance(data[section], dict):
            problems.append(f"missing object: {section}")
    if problems:
        print(json.dumps({"ok": False, "problems": problems}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"ok": True, "path": str(profile_path(args.profile, args.directory))}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", dest="directory", type=Path, help="Profile directory override.")
    subparsers = parser.add_subparsers(required=True)

    init = subparsers.add_parser("init", help="Create a placeholder profile.")
    init.add_argument("--profile", default="personal")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    path = subparsers.add_parser("path", help="Print the profile path.")
    path.add_argument("--profile", default="personal")
    path.set_defaults(func=command_path)

    show = subparsers.add_parser("show", help="Print the profile as JSON.")
    show.add_argument("--profile", default="personal")
    show.add_argument("--reveal", action="store_true", help="Show full values instead of redacted values.")
    show.set_defaults(func=command_show)

    get = subparsers.add_parser("get", help="Print selected dot-path fields as JSON.")
    get.add_argument("fields", nargs="+")
    get.add_argument("--profile", default="personal")
    get.add_argument("--reveal", action="store_true", help="Show full values instead of redacted values.")
    get.set_defaults(func=command_get)

    check = subparsers.add_parser("check", help="Validate the profile shape lightly.")
    check.add_argument("--profile", default="personal")
    check.set_defaults(func=command_check)

    return parser


def main() -> None:
    if not shutil.which("python3") and sys.version_info.major < 3:
        raise SystemExit("python3 is required")
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
