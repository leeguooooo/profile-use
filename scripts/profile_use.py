#!/usr/bin/env python3
"""Manage local profile-use JSON profiles."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
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
    "address.line1",
    "address.line2",
    # Attachment metadata can carry PII in free-form label/source text, and the
    # schema treats every original document as high sensitivity.
    "documents",
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


def icloud_root() -> Path:
    return Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"


def _prefer_new_name(new: Path, legacy: Path) -> Path:
    """Use the profile-use directory, falling back to a pre-rename
    personal-autofill directory that still holds data."""
    if not new.exists() and legacy.exists():
        return legacy
    return new


def icloud_dir() -> Path:
    base = icloud_root() / "Agent Profiles"
    return _prefer_new_name(base / "profile-use", base / "personal-autofill")


def local_fallback_dir() -> Path:
    config = Path.home() / ".config"
    return _prefer_new_name(config / "profile-use", config / "personal-autofill")


def default_dir() -> Path:
    override = os.environ.get("PROFILE_USE_DIR") or os.environ.get("PERSONAL_AUTOFILL_DIR")
    if override:
        return Path(override).expanduser()
    if icloud_root().exists():
        return icloud_dir()
    return local_fallback_dir()


# A profile name becomes a filename and an attachments subdirectory, so it must
# not contain path separators or traversal — otherwise it escapes the protected
# (gitignored, mode-600) profile directory.
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def validate_profile_name(profile: str) -> str:
    if not PROFILE_NAME_RE.match(profile):
        raise SystemExit(
            f"Invalid profile name: {profile!r}. Use letters, digits, '_' or '-' "
            "(e.g. personal, work, family, jp)."
        )
    return profile


def profile_path(profile: str, directory: Path | None = None) -> Path:
    validate_profile_name(profile)
    return (directory or default_dir()) / f"{profile}.profile.json"


# Original document images (residence card, My Number card, bank card, ...)
# live next to the profile so they sync the same way and never enter Git.
DOC_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def attachments_dir(profile: str, directory: Path | None = None) -> Path:
    validate_profile_name(profile)
    return (directory or default_dir()) / "attachments" / profile


def validate_doc_key(doc: str) -> str:
    if not DOC_KEY_RE.match(doc):
        raise SystemExit(
            f"Invalid doc key: {doc!r}. Use lowercase letters, digits, '_', '-', '.' "
            "(e.g. residence_card_front, my_number_card_back, bank_card)."
        )
    return doc


def safe_attachment_path(dest_dir: Path, filename: str) -> Path:
    """Resolve a stored attachment filename, rejecting anything that is not a
    bare name inside ``dest_dir`` (defends against a poisoned ``documents.*.file``
    value being used as an unlink/copy target)."""
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise SystemExit(f"Refusing unsafe attachment filename: {filename!r}")
    candidate = dest_dir / filename
    if candidate.parent != dest_dir:
        raise SystemExit(f"Refusing unsafe attachment filename: {filename!r}")
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    # The profile holds bank/government-ID data, so never expose it world-readable:
    # create the directory 0700 and write the file 0600 from the start (no
    # create-then-chmod window), via a temp file + atomic rename.
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    tmp = path.parent / f".{path.name}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


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


def command_doctor(args: argparse.Namespace) -> None:
    profile = args.profile
    data = {
        "profile": profile,
        "env_PROFILE_USE_DIR": os.environ.get("PROFILE_USE_DIR"),
        "env_PERSONAL_AUTOFILL_DIR_legacy": os.environ.get("PERSONAL_AUTOFILL_DIR"),
        "icloud_root": str(icloud_root()),
        "icloud_root_exists": icloud_root().exists(),
        "icloud_profile_path": str(profile_path(profile, icloud_dir())),
        "icloud_profile_exists": profile_path(profile, icloud_dir()).exists(),
        "local_fallback_path": str(profile_path(profile, local_fallback_dir())),
        "local_fallback_exists": profile_path(profile, local_fallback_dir()).exists(),
        "resolved_default_path": str(profile_path(profile, args.directory)),
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))


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


def command_attach(args: argparse.Namespace) -> None:
    doc = validate_doc_key(args.doc)
    source = Path(args.file).expanduser()
    if not source.is_file():
        raise SystemExit(f"Source file not found: {source}")
    data = load_profile(args.profile, args.directory)
    documents = data.setdefault("documents", {})
    if doc in documents and not args.force:
        raise SystemExit(f"Document already attached: {doc}\nUse --force to replace it.")
    dest_dir = attachments_dir(args.profile, args.directory)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        dest_dir.chmod(0o700)
    except OSError:
        pass
    dest = dest_dir / f"{doc}{source.suffix.lower()}"
    previous = documents.get(doc, {}).get("file")
    if previous and previous != dest.name:
        safe_attachment_path(dest_dir, previous).unlink(missing_ok=True)
    shutil.copy2(source, dest)
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    documents[doc] = {
        "file": dest.name,
        "label": args.label or "",
        "source": args.source or "",
        "added": datetime.date.today().isoformat(),
        "sha256": sha256_file(dest),
    }
    write_json(profile_path(args.profile, args.directory), data)
    if args.move:
        source.unlink()
    print(json.dumps({"ok": True, "profile": args.profile, "doc": doc, "path": str(dest)}, indent=2))


def command_attachments(args: argparse.Namespace) -> None:
    data = load_profile(args.profile, args.directory)
    documents = data.get("documents", {})
    dest_dir = attachments_dir(args.profile, args.directory)
    result: dict[str, Any] = {}
    for doc in sorted(documents):
        meta = dict(documents[doc])
        try:
            path = safe_attachment_path(dest_dir, meta.get("file", ""))
        except SystemExit:
            meta["path"] = None
            meta["exists"] = False
            meta["size_bytes"] = None
            meta["unsafe_filename"] = True
            result[doc] = meta
            continue
        meta["path"] = str(path)
        meta["exists"] = path.is_file()
        meta["size_bytes"] = path.stat().st_size if path.is_file() else None
        result[doc] = meta
    tracked = {meta.get("file") for meta in documents.values()}
    orphans = (
        sorted(str(p) for p in dest_dir.iterdir() if p.is_file() and p.name not in tracked)
        if dest_dir.is_dir()
        else []
    )
    print(json.dumps({"documents": result, "orphan_files": orphans}, indent=2, ensure_ascii=False))


def command_attachment_path(args: argparse.Namespace) -> None:
    doc = validate_doc_key(args.doc)
    data = load_profile(args.profile, args.directory)
    meta = data.get("documents", {}).get(doc)
    if not meta or not meta.get("file"):
        raise SystemExit(f"No attached document: {doc}")
    path = safe_attachment_path(attachments_dir(args.profile, args.directory), meta["file"])
    if not path.is_file():
        raise SystemExit(f"Attachment metadata exists but file is missing: {path}")
    print(path)


def command_detach(args: argparse.Namespace) -> None:
    doc = validate_doc_key(args.doc)
    data = load_profile(args.profile, args.directory)
    documents = data.get("documents", {})
    meta = documents.pop(doc, None)
    removed_file = False
    if meta and meta.get("file"):
        path = safe_attachment_path(attachments_dir(args.profile, args.directory), meta["file"])
        if path.is_file():
            path.unlink()
            removed_file = True
    if meta is not None:
        write_json(profile_path(args.profile, args.directory), data)
    print(
        json.dumps(
            {"ok": meta is not None, "profile": args.profile, "doc": doc, "removed_file": removed_file},
            indent=2,
        )
    )


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

    doctor = subparsers.add_parser("doctor", help="Show profile path resolution and iCloud availability.")
    doctor.add_argument("--profile", default="personal")
    doctor.set_defaults(func=command_doctor)

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

    attach = subparsers.add_parser(
        "attach",
        help="Store an original document image/file next to the profile and record it under documents.<doc>.",
    )
    attach.add_argument("file", help="Source file to copy into the attachments directory.")
    attach.add_argument("--doc", required=True, help="Document key, e.g. residence_card_front.")
    attach.add_argument("--profile", default="personal")
    attach.add_argument("--label", help="Human-readable label, e.g. '在留カード 表面'.")
    attach.add_argument("--source", help="Where the file came from, e.g. 'lark chat with ning 2026-06-12'.")
    attach.add_argument("--move", action="store_true", help="Delete the source file after copying.")
    attach.add_argument("--force", action="store_true", help="Replace an existing attachment with the same key.")
    attach.set_defaults(func=command_attach)

    attachments = subparsers.add_parser("attachments", help="List attached original documents.")
    attachments.add_argument("--profile", default="personal")
    attachments.set_defaults(func=command_attachments)

    attachment_path = subparsers.add_parser(
        "attachment-path", help="Print the absolute path of one attached document (for uploads)."
    )
    attachment_path.add_argument("--doc", required=True)
    attachment_path.add_argument("--profile", default="personal")
    attachment_path.set_defaults(func=command_attachment_path)

    detach = subparsers.add_parser("detach", help="Remove an attached document and its metadata.")
    detach.add_argument("--doc", required=True)
    detach.add_argument("--profile", default="personal")
    detach.set_defaults(func=command_detach)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
