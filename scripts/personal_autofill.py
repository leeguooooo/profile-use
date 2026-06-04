#!/usr/bin/env python3
"""Manage local personal-autofill JSON profiles."""

from __future__ import annotations

import argparse
import json
import os
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

# Legal-name fields. Medium sensitivity: usable for filling, but masked in
# redacted summaries so they do not leak when the agent reports back.
NAME_FIELDS = (
    "identity.full_name",
    "identity.family_name",
    "identity.given_name",
    "identity.middle_name",
    "identity.name_kana",
)


def matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    """Segment-aware prefix match, so ``tax`` does not match ``taxonomy``."""
    return any(path == prefix or path.startswith(prefix + ".") for prefix in prefixes)


def is_high_sensitivity(path: str) -> bool:
    return matches_prefix(path, HIGH_SENSITIVITY_PREFIXES)


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


def set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    if not parts or any(part == "" for part in parts):
        raise ValueError(f"Invalid field path: {dotted}")
    current: Any = data
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        if not isinstance(current[part], dict):
            raise ValueError(f"Cannot set nested field under non-object path: {part}")
        current = current[part]
    current[parts[-1]] = value


def unset_path(data: dict[str, Any], dotted: str) -> bool:
    parts = dotted.split(".")
    if not parts or any(part == "" for part in parts):
        raise ValueError(f"Invalid field path: {dotted}")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    del current[parts[-1]]
    return True


def parse_value(raw: str, as_json: bool) -> Any:
    if as_json:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON value: {exc}") from exc
    return raw


def iter_fields(data: Any, prefix: str = "") -> list[str]:
    if not isinstance(data, dict):
        return [prefix] if prefix else []
    result: list[str] = []
    for key in sorted(data):
        path = f"{prefix}.{key}" if prefix else key
        value = data[key]
        if isinstance(value, dict):
            result.extend(iter_fields(value, path))
        else:
            result.append(path)
    return result


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
    if is_high_sensitivity(path):
        return mask_tail(text, 4)
    if path in NAME_FIELDS:
        return redact_name(text)
    if "email" in path:
        return redact_email(text)
    if path.endswith("phone_country_code"):
        return text  # a dialing code such as +81 is not sensitive
    if "phone" in path or "postal_code" in path:
        return mask_tail(text, 2)
    if matches_prefix(path, ("address.line1", "address.line2")) or path == "notes":
        return mask_tail(text, 4)
    return text


def redact_name(value: str) -> str:
    tokens = value.split()
    if not tokens:
        return value
    return " ".join(token[:1] + "*" * (len(token) - 1) if len(token) > 1 else token for token in tokens)


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


def command_values(args: argparse.Namespace) -> None:
    """Return raw (unredacted) values for the agent to type into a form.

    With explicit fields, returns exactly those. With no fields, returns a flat
    {dotpath: value} map of every filled field, excluding high-sensitivity
    prefixes unless --include-sensitive is passed. High-sensitivity values are
    only ever returned when named explicitly or opted into.
    """
    data = load_profile(args.profile, args.directory)
    result: dict[str, Any] = {}
    if args.fields:
        for field in args.fields:
            try:
                result[field] = get_path(data, field)
            except KeyError:
                result[field] = None
    else:
        for field in iter_fields(data):
            if not args.include_sensitive and is_high_sensitivity(field):
                continue
            value = get_path(data, field)
            if value in ("", None, [], {}):
                continue
            result[field] = value
    print(json.dumps(result, indent=2, ensure_ascii=False))


def command_set(args: argparse.Namespace) -> None:
    data = load_profile(args.profile, args.directory)
    value = parse_value(args.value, args.json)
    try:
        set_path(data, args.field, value)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    path = profile_path(args.profile, args.directory)
    write_json(path, data)
    print(json.dumps({"ok": True, "profile": args.profile, "field": args.field, "path": str(path)}, indent=2))


def command_unset(args: argparse.Namespace) -> None:
    data = load_profile(args.profile, args.directory)
    try:
        removed = unset_path(data, args.field)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    path = profile_path(args.profile, args.directory)
    if removed:
        write_json(path, data)
    print(
        json.dumps(
            {"ok": removed, "profile": args.profile, "field": args.field, "path": str(path)},
            indent=2,
        )
    )


def command_list_fields(args: argparse.Namespace) -> None:
    data = load_profile(args.profile, args.directory)
    fields = iter_fields(data)
    if args.filled:
        fields = [field for field in fields if get_path(data, field) not in ("", None, [], {})]
    print("\n".join(fields))


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

    values = subparsers.add_parser(
        "values",
        help="Print raw (unredacted) values for filling a form. Excludes high-sensitivity fields unless named or --include-sensitive.",
    )
    values.add_argument("fields", nargs="*", help="Specific dot-paths; omit to dump all filled low/medium fields.")
    values.add_argument("--profile", default="personal")
    values.add_argument(
        "--include-sensitive",
        action="store_true",
        help="Include high-sensitivity fields (payment, bank, government_id, tax, birthdate, gender) in a no-field dump.",
    )
    values.set_defaults(func=command_values)

    set_cmd = subparsers.add_parser("set", help="Set a dot-path field, creating nested objects as needed.")
    set_cmd.add_argument("field")
    set_cmd.add_argument("value")
    set_cmd.add_argument("--profile", default="personal")
    set_cmd.add_argument("--json", action="store_true", help="Parse the value as JSON instead of a string.")
    set_cmd.set_defaults(func=command_set)

    unset = subparsers.add_parser("unset", help="Remove a dot-path field.")
    unset.add_argument("field")
    unset.add_argument("--profile", default="personal")
    unset.set_defaults(func=command_unset)

    list_fields = subparsers.add_parser("list-fields", help="List available dot-path fields.")
    list_fields.add_argument("--profile", default="personal")
    list_fields.add_argument("--filled", action="store_true", help="Only list fields with non-empty values.")
    list_fields.set_defaults(func=command_list_fields)

    check = subparsers.add_parser("check", help="Validate the profile shape lightly.")
    check.add_argument("--profile", default="personal")
    check.set_defaults(func=command_check)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
