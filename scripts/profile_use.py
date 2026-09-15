#!/usr/bin/env python3
"""Manage local profile-use JSON profiles."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unicodedata
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
    # Japan-specific street components (番地 / 建物名) are as precise as
    # address.line1/line2, so they get the same high-sensitivity treatment.
    "address.jp.banchi",
    "address.jp.building",
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
    # Romanised / kana / as-printed-on-ID name forms are the same legal name in
    # another script, so they get the same masking. Without these they would
    # sail through redacted output while identity.full_name was masked — the
    # residence-card romaji IS the full name (#3).
    "identity.romaji.family_name",
    "identity.romaji.given_name",
    "identity.kana.family_name",
    "identity.kana.given_name",
    "identity.name_on_id",
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


# ---------------------------------------------------------------------------
# Bitwarden / Vaultwarden vault adapter (read-through; secrets never stored)
# ---------------------------------------------------------------------------
#
# Login credentials belong in the password manager, not in the profile JSON
# (see references/sync-model.md). This adapter shells out to `rbw` on demand,
# returns one credential matched by domain, and treats every value it produces
# as high sensitivity: masked by default, raw only with --reveal, never written
# to disk or merged into the profile. The unlock lives in rbw-agent; we read it,
# we do not capture, store, or echo the master password.
#
# rbw is installed and configured separately (it is a global tool):
#   brew install rbw            # or: cargo install rbw
#   rbw config set base_url https://bit.leeguoo.com
#   rbw config set email <you@example.com>
#   rbw login                   # then rbw-agent caches the unlock


class VaultError(SystemExit):
    """rbw is missing, locked, or returned an error. The message carries the fix."""


def normalize_domain(raw: str) -> str:
    """Reduce a URL or host to a bare lowercase registrable host.

    ``https://www.Example.com:443/login?x=1`` -> ``example.com``. Used both to
    canonicalize the --domain argument and to compare against stored URIs.
    """
    text = (raw or "").strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0].split("?", 1)[0]
    if "@" in text:  # strip any userinfo
        text = text.rsplit("@", 1)[1]
    text = text.split(":", 1)[0]  # strip port
    if text.startswith("www."):
        text = text[4:]
    return text


# Multi-label public suffixes where the last two labels are NOT a registrable
# domain (rakuten.co.jp's base is rakuten.co.jp, not co.jp). Without this, every
# .co.jp entry collapses to the needle "co.jp" and matches all of them. Not the
# full Public Suffix List — just the common ones autofill actually meets.
_MULTI_LABEL_SUFFIXES = frozenset(
    {
        "co.jp", "ne.jp", "or.jp", "go.jp", "ac.jp", "ad.jp", "ed.jp", "gr.jp",
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk",
        "com.cn", "net.cn", "org.cn", "gov.cn",
        "com.au", "net.au", "org.au", "co.nz", "co.kr", "or.kr",
        "com.tw", "com.hk", "com.br", "com.sg", "com.mx",
    }
)


def domain_base(domain: str) -> str:
    """Loose registrable base: usually the last two labels (``a.b.example.com``
    -> ``example.com``), but the last *three* when the trailing two form a known
    multi-label public suffix (``rakuten.co.jp`` -> ``rakuten.co.jp``, not
    ``co.jp``). A heuristic matcher, not a full eTLD parser."""
    labels = [label for label in domain.split(".") if label]
    if len(labels) <= 2:
        return domain
    if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def rbw_binary() -> str | None:
    """rbw, or its fork bitwarden-use (same agent, database and subcommands)."""
    return shutil.which("rbw") or shutil.which("bitwarden-use")


def _run_rbw(*args: str) -> subprocess.CompletedProcess:
    rbw = rbw_binary()
    if not rbw:
        raise VaultError(
            "rbw not found. Install it and point it at your server:\n"
            "  brew install rbw            # or: cargo install rbw\n"
            "  rbw config set base_url https://bit.leeguoo.com\n"
            "  rbw config set email <you@example.com>\n"
            "  rbw login"
        )
    # No stdin: never feed a master password through this process. If the agent
    # is locked we detect it via `rbw unlocked` first, so rbw never blocks here
    # waiting on a pinentry prompt.
    if args and args[0] == "get" and Path(rbw).name == "bitwarden-use":
        # bitwarden-use prints "[redacted]" unless --reveal, which asks for Touch ID
        # outside its reveal folders. That prompt is intended; never bypass it.
        args = ("get", "--reveal", *args[1:])
    return subprocess.run([rbw, *args], capture_output=True, text=True)


def _vault_failure_hint(proc: subprocess.CompletedProcess) -> str:
    msg = (proc.stderr or proc.stdout or "").strip()
    low = msg.lower()
    if "locked" in low or "not logged in" in low or "unlock" in low or "log in" in low:
        return f"Vault not available: {msg}\nTry: rbw login && rbw unlock"
    return f"rbw error: {msg or 'unknown failure'}"


def vault_unlocked() -> bool:
    """True when rbw-agent holds an unlocked vault. Does not trigger a prompt."""
    return _run_rbw("unlocked").returncode == 0


def _install_rbw() -> bool:
    """Best-effort install of rbw via the host's package manager. Inherits stdio
    so the agent/user sees progress (cargo can take minutes). Returns True if rbw
    is on PATH afterwards."""
    if shutil.which("brew"):
        print("Installing rbw via Homebrew...", file=sys.stderr)
        if subprocess.run(["brew", "install", "rbw"]).returncode == 0 and shutil.which("rbw"):
            return True
    if shutil.which("cargo"):
        print("Installing rbw via cargo (compiles; may take a few minutes)...", file=sys.stderr)
        if subprocess.run(["cargo", "install", "rbw"]).returncode == 0 and shutil.which("rbw"):
            return True
    return False


def rbw_list_entries() -> list[dict[str, str]]:
    proc = _run_rbw("list", "--fields", "id,name,user")
    if proc.returncode != 0:
        raise VaultError(_vault_failure_hint(proc))
    entries: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 3:
            parts.append("")
        entries.append({"id": parts[0], "name": parts[1], "user": parts[2]})
    return entries


def match_entries(entries: list[dict[str, str]], domain: str) -> list[dict[str, str]]:
    """Entries whose name contains the domain or its registrable base.

    Pure so it can be unit-tested without rbw. The common Vaultwarden case is an
    item named after the site (``github.com`` / ``GitHub``); URI-only matches are
    handled by the opt-in deep scan.
    """
    norm = normalize_domain(domain)
    base = domain_base(norm)
    # The second-level label ("example" from example.com) is how items are most
    # often named — bare brand, no TLD. Guarded at >= 3 chars so a one-letter SLD
    # does not match everything; explicit --name covers the odd case.
    sld = base.split(".", 1)[0]
    needles = {n for n in (norm, base) if n}
    if len(sld) >= 3:
        needles.add(sld)
    out: list[dict[str, str]] = []
    for entry in entries:
        name = (entry.get("name") or "").lower()
        if any(needle in name for needle in needles):
            out.append(entry)
    return out


def parse_rbw_full(text: str) -> dict[str, Any]:
    """Parse ``rbw get --full`` output: password on line 1, then ``Key: value``."""
    lines = text.splitlines()
    cred: dict[str, Any] = {"password": lines[0] if lines else "", "username": "", "uris": [], "totp": ""}
    for line in lines[1:]:
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        key = key.strip().lower()
        if key == "username":
            cred["username"] = value
        elif key == "uri":
            cred["uris"].append(value)
        elif key in ("totp", "otp"):
            cred["totp"] = value
    return cred


def parse_bitwarden_use_raw(text: str) -> dict[str, Any]:
    """Parse ``bitwarden-use get --raw --reveal`` JSON. Its --full prints the same
    JSON rather than rbw's text, so the two binaries never share a parser."""
    item = json.loads(text)
    data = item.get("data") or {}
    return {
        "password": data.get("password") or "",
        "username": data.get("username") or "",
        "uris": [entry["uri"] for entry in data.get("uris") or [] if entry.get("uri")],
        "totp": data.get("totp") or "",
    }


def _is_bitwarden_use() -> bool:
    return Path(rbw_binary() or "").name == "bitwarden-use"


def get_credential(name: str, user: str | None = None) -> dict[str, Any]:
    bitwarden_use = _is_bitwarden_use()
    args = ["get", "--raw" if bitwarden_use else "--full", name]
    if user:
        args.append(user)
    proc = _run_rbw(*args)
    if proc.returncode != 0:
        raise VaultError(_vault_failure_hint(proc))
    return parse_bitwarden_use_raw(proc.stdout) if bitwarden_use else parse_rbw_full(proc.stdout)


def deep_uri_match(entries: list[dict[str, str]], domain: str) -> list[dict[str, str]]:
    """Slow opt-in fallback: pull each entry's URIs and match the host. Used only
    when no entry name matched and the user passed --deep."""
    if _is_bitwarden_use():
        # URIs are redacted without --reveal, and every --reveal asks for Touch ID:
        # scanning the whole vault would mean one prompt per entry.
        raise VaultError("--deep is not available with bitwarden-use. Name the entry with --name instead.")
    norm = normalize_domain(domain)
    hits: list[dict[str, str]] = []
    for entry in entries:
        cred = get_credential(entry["name"], entry.get("user") or None)
        for uri in cred.get("uris", []):
            host = normalize_domain(uri)
            if host and (host == norm or host.endswith("." + norm) or norm.endswith("." + host)):
                hits.append(entry)
                break
    return hits


def mask_user(user: str) -> str:
    if not user:
        return user
    return redact_email(user) if "@" in user else mask_tail(user, 2)


def redact_credential(cred: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": mask_user(cred.get("username") or ""),
        # Fixed-width: never leak the password's length.
        "password": "********" if cred.get("password") else "",
        "totp": "present" if cred.get("totp") else None,
        "uris": cred.get("uris", []),  # host names are not secret
    }


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


# Output formatting for `values` (#3). Agents were re-deriving these in shell
# with ad-hoc regexes at the moment of filling — a bank form that wants the
# domestic 11-digit number, or full-width digits in the address remainder.
# Both are pure: no profile access, no guessing.

_FULLWIDTH_TABLE = {
    **{ord(c): chr(ord(c) - 0x20 + 0xFF00) for c in "0123456789"},
    **{ord(c): chr(ord(c) - 0x20 + 0xFF00) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{ord(c): chr(ord(c) - 0x20 + 0xFF00) for c in "abcdefghijklmnopqrstuvwxyz"},
    ord("-"): "\uff0d",
}


def to_fullwidth(value: Any) -> Any:
    """ASCII digits, letters and hyphens to full-width, recursively.

    Japanese forms that auto-fill the address from the postal code want the
    remainder "as written on the ID" in full-width: 1番2-3号 becomes
    １番２－３号. Everything else (kana, kanji, spaces, punctuation)
    is left alone; non-strings pass through untouched.
    """
    if isinstance(value, str):
        return value.translate(_FULLWIDTH_TABLE)
    if isinstance(value, list):
        return [to_fullwidth(item) for item in value]
    if isinstance(value, dict):
        return {key: to_fullwidth(item) for key, item in value.items()}
    return value


def format_phone(value: Any, country_code: Any, mode: str) -> Any:
    """Render a phone number as `domestic` (trunk-prefixed national) or `e164`.

    Only acts when the number is a string AND a country code is known; with no
    country code there is no honest way to tell +81 70 from a national 070, so
    the value is returned unchanged rather than guessed. Accepts the usual
    input shapes: "070-1234-5678", "+81 70 1234 5678", "07012345678",
    "8170...". Country codes may be given as "81" or "+81".
    """
    if not isinstance(value, str) or mode not in ("domestic", "e164"):
        return value
    cc = "".join(ch for ch in str(country_code or "") if ch.isdigit())
    digits = "".join(ch for ch in value if ch.isdigit())
    if not cc or not digits:
        return value
    if value.lstrip().startswith("+") and digits.startswith(cc):
        national = digits[len(cc):]
    elif digits.startswith("0"):
        national = digits[1:]
    elif digits.startswith(cc) and len(digits) > len(cc) + 6:
        national = digits[len(cc):]
    else:
        national = digits
    if not national:
        return value
    if mode == "domestic":
        return "0" + national
    return "+" + cc + national


def _is_phone_field(path: str) -> bool:
    last = path.rsplit(".", 1)[-1]
    return last == "phone" or last.startswith("phone_") and not last.endswith("country_code")


def apply_value_formats(result: dict[str, Any], data: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    phone_mode = getattr(args, "phone_format", None)
    if phone_mode:
        try:
            cc = get_path(data, "contact.phone_country_code")
        except KeyError:
            cc = None
        for path, value in list(result.items()):
            if _is_phone_field(path):
                result[path] = format_phone(value, cc, phone_mode)
    if getattr(args, "format", None) == "jp-fullwidth":
        result = {path: to_fullwidth(value) for path, value in result.items()}
    return result


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
    result = apply_value_formats(result, data, args)
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


def command_login(args: argparse.Namespace) -> None:
    """Return one credential for a site, read live from the vault.

    Default output is redacted (for orienting / reporting back). Pass --reveal to
    get the raw username/password at the moment you fill the form. Nothing here is
    ever written to the profile JSON.
    """
    if args.name:
        cred = get_credential(args.name, args.user)
        payload: dict[str, Any] = {
            "ok": True,
            "domain": normalize_domain(args.domain) if args.domain else "",
            "item": args.name,
            "match": "name-arg",
        }
    else:
        if not args.domain:
            raise SystemExit("Provide --domain <host> or --name <item>.")
        if not vault_unlocked():
            raise VaultError("Vault is locked. Run: rbw unlock")
        entries = rbw_list_entries()
        matches = match_entries(entries, args.domain)
        if args.user:
            matches = [m for m in matches if (m.get("user") or "") == args.user]
        if not matches and args.deep:
            matches = deep_uri_match(entries, args.domain)
        if not matches:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "domain": normalize_domain(args.domain),
                        "reason": "no item whose name contains the domain",
                        "hint": "retry with --deep to scan stored URIs, or pass --name <item>",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            raise SystemExit(1)
        if len(matches) > 1:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "domain": normalize_domain(args.domain),
                        "reason": "multiple matches; disambiguate with --name and/or --user",
                        "candidates": [
                            {"name": m["name"], "user": mask_user(m.get("user") or "")} for m in matches
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            raise SystemExit(1)
        item = matches[0]
        cred = get_credential(item["name"], item.get("user") or None)
        payload = {
            "ok": True,
            "domain": normalize_domain(args.domain),
            "item": item["name"],
            "match": "deep-uri" if args.deep else "domain",
        }
    if args.reveal:
        payload.update(
            {
                "username": cred.get("username", ""),
                "password": cred.get("password", ""),
                "totp": cred.get("totp") or None,
                "uris": cred.get("uris", []),
            }
        )
    else:
        payload.update(redact_credential(cred))
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def command_vault_setup(args: argparse.Namespace) -> None:
    """Install (with --install) and configure rbw end to end, so the only step
    left for the human is the master-password unlock — which the agent must never
    perform. Designed to be driven by the skill, not typed by the user."""
    if not rbw_binary():
        if not args.install:
            raise VaultError("rbw not found. Re-run with --install (uses brew/cargo), or: brew install rbw")
        if not _install_rbw():
            raise VaultError(
                "Could not install rbw automatically. Install it manually:\n"
                "  brew install rbw            # or: cargo install rbw"
            )
    configured: list[str] = []
    if args.base_url:
        proc = _run_rbw("config", "set", "base_url", args.base_url)
        if proc.returncode != 0:
            raise VaultError(_vault_failure_hint(proc))
        configured.append("base_url")
    if args.email:
        proc = _run_rbw("config", "set", "email", args.email)
        if proc.returncode != 0:
            raise VaultError(_vault_failure_hint(proc))
        configured.append("email")
    info: dict[str, Any] = {"ok": True, "rbw_installed": True, "configured": configured}
    cfg = _run_rbw("config", "show")
    if cfg.returncode == 0:
        try:
            parsed = json.loads(cfg.stdout)
            info["base_url"] = parsed.get("base_url") or parsed.get("identity_url")
            email = parsed.get("email")
            info["email"] = mask_user(email) if email else None
        except json.JSONDecodeError:
            info["config_parse_error"] = True
    unlocked = vault_unlocked()
    info["unlocked"] = unlocked
    # The master password is the one thing the agent never handles: surface the
    # exact command for the human to run, do not run it here.
    info["next_step"] = None if unlocked else "rbw login   # you type the master password; the agent never sees it"
    print(json.dumps(info, indent=2, ensure_ascii=False))


def command_vault_status(args: argparse.Namespace) -> None:
    """Report rbw availability, server, and lock state — never any secret."""
    rbw = rbw_binary()
    info: dict[str, Any] = {"rbw_installed": bool(rbw), "rbw_path": rbw}
    if not rbw:
        info["hint"] = "brew install rbw   (or: cargo install rbw)"
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return
    cfg = _run_rbw("config", "show")
    if cfg.returncode == 0:
        try:
            parsed = json.loads(cfg.stdout)
            info["base_url"] = parsed.get("base_url") or parsed.get("identity_url")
            email = parsed.get("email")
            info["email"] = mask_user(email) if email else None
        except json.JSONDecodeError:
            info["config_parse_error"] = True
    info["unlocked"] = vault_unlocked()
    print(json.dumps(info, indent=2, ensure_ascii=False))


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
    values.add_argument(
        "--phone-format",
        choices=["domestic", "e164"],
        help="Render phone fields as the domestic trunk-prefixed number (070…) or E.164 (+8170…). Needs contact.phone_country_code; otherwise left unchanged.",
    )
    values.add_argument(
        "--format",
        choices=["jp-fullwidth"],
        help="jp-fullwidth: ASCII digits/letters/hyphens in returned strings as full-width (１－２－３), for Japanese forms.",
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
    attach.add_argument("--source", help="Where the file came from, e.g. 'lark chat 2026-01-01'.")
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

    login = subparsers.add_parser(
        "login",
        help="Read one site credential live from the Bitwarden/Vaultwarden vault via rbw (never stored).",
    )
    login.add_argument("--domain", help="Site host or URL, e.g. example.com — matched against item names.")
    login.add_argument("--name", help="Target a vault item by exact name instead of matching by domain.")
    login.add_argument("--user", help="Disambiguate when one item/domain has several accounts.")
    login.add_argument("--reveal", action="store_true", help="Return the raw username/password to fill a form.")
    login.add_argument(
        "--deep",
        action="store_true",
        help="If no item name matches, scan every item's stored URIs (slower).",
    )
    login.set_defaults(func=command_login)

    vault_status = subparsers.add_parser(
        "vault-status", help="Report rbw availability, server URL, and lock state (no secrets)."
    )
    vault_status.set_defaults(func=command_vault_status)

    vault_setup = subparsers.add_parser(
        "vault-setup",
        help="Install (with --install) and configure rbw for a Bitwarden/Vaultwarden server.",
    )
    vault_setup.add_argument("--base-url", dest="base_url", help="Server URL, e.g. https://bit.leeguoo.com.")
    vault_setup.add_argument("--email", help="Vault account email.")
    vault_setup.add_argument(
        "--install", action="store_true", help="Install rbw via brew/cargo if it is missing."
    )
    vault_setup.set_defaults(func=command_vault_setup)

    leak_scan = subparsers.add_parser(
        "leak-scan",
        help="Fail if any real profile value appears in files, stdin, staged changes, or history. Prints dot-paths, never values.",
    )
    leak_scan.add_argument("paths", nargs="*", type=Path, help="Files or directories to scan.")
    leak_scan.add_argument("--profile", default="personal")
    leak_scan.add_argument("--all-profiles", action="store_true", help="Check against every *.profile.json in the profile directory.")
    source = leak_scan.add_mutually_exclusive_group()
    source.add_argument("--stdin", action="store_true", help="Scan text piped on stdin.")
    source.add_argument("--staged", action="store_true", help="Scan lines added in `git diff --cached` (the pre-commit hook).")
    source.add_argument("--history", action="store_true", help="Scan lines added anywhere in `git log --all`.")
    leak_scan.add_argument("--label", default="<stdin>", help="Name to report for --stdin input, e.g. the staged file's path.")
    leak_scan.add_argument("--json", action="store_true", help="Accepted for callers that ask for JSON; output is always JSON.")
    leak_scan.set_defaults(func=command_leak_scan)

    add_backup_parsers(subparsers)

    return parser


# leak-scan: real profile values must never reach Git. Doc and test examples
# once carried the real postal code, city and street numbers in reshaped forms
# (full-width digits, 番/号 instead of hyphens), so matching runs on normalised
# text and on fragments of address/name values, not only on whole values.

LEAK_SKIP_FIELDS = (
    "profile_name",
    "preferences",
    "government_id.type",
    "contact.phone_country_code",
    "identity.preferred_name",
)
# Attachment bookkeeping uses conventional names and dates that docs repeat.
LEAK_SKIP_LEAVES = ("file", "added", "sha256", "label", "mime")
LEAK_FRAGMENT_SECTIONS = ("address", "identity", "family", "employment", "government_id")
LEAK_GENERIC = {"東京都", "大阪府", "神奈川県", "北海道", "株式会社", "在留カード"}
LEAK_ALLOW_MARKER = "profile-use: allow"
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"})
_DATE_RE = re.compile(r"^\d{4}-\d{1,2}(-\d{1,2})?$")


def _leak_normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).casefold()
    # 1丁目2番3号 / 2番3-101号 → 1-2-3 / 2-3-101
    text = re.sub(r"(丁目|番地|番|号室|号|の)(?=\d)", "-", text)
    return re.sub(r"(?<=\d)(丁目|番地|号室|番|号)", "", text)


def leak_needles(data: Any) -> dict[str, str]:
    """Distinctive normalised fragments of every filled value → the dot-path they came from."""
    needles: dict[str, str] = {}

    def add(needle: str, path: str, minimum: int = 5) -> None:
        if len(needle) >= minimum and needle not in LEAK_GENERIC:
            needles.setdefault(needle, path)

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key)
            return
        if isinstance(value, list):
            for item in value:
                walk(item, path)
            return
        if value is None or isinstance(value, bool) or value == "":
            return
        if matches_prefix(path, LEAK_SKIP_FIELDS) or path.rsplit(".", 1)[-1] in LEAK_SKIP_LEAVES:
            return
        norm = _leak_normalize(str(value)).strip()
        add(norm, path)
        if path.split(".")[0] not in LEAK_FRAGMENT_SECTIONS:
            return
        cjk_min = 2 if matches_prefix(path, NAME_FIELDS) else 3
        for run in re.findall(r"[぀-ヿ一-鿿]+", norm):
            add(run, path, cjk_min)
        for chain in re.findall(r"\d+(?:-\d+)+", norm):
            if _DATE_RE.match(chain):
                continue
            add(chain, path)
            parts = chain.split("-")
            for left, right in zip(parts, parts[1:]):
                if len(left) + len(right) >= 4:
                    add(f"{left}-{right}", path, 0)

    walk(data, "")
    return needles


def _leak_patterns(needles: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    patterns = []
    for needle, path in needles.items():
        body = re.escape(needle)
        if needle[:1].isascii() and needle[:1].isalnum():
            body = r"(?<![0-9a-z])" + body
        if needle[-1:].isascii() and needle[-1:].isalnum():
            body = body + r"(?![0-9a-z])"
        patterns.append((re.compile(body), path))
    return patterns


def _leak_lines_from_paths(paths: list[Path]):
    for root in paths:
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
        for file in files:
            raw = file.read_bytes()
            if b"\0" in raw[:8192]:
                continue
            for number, line in enumerate(raw.decode("utf-8", errors="ignore").splitlines(), 1):
                yield f"{file}:{number}", line


def _leak_lines_from_git(args: list[str]):
    """Added lines from a unified diff (`git diff`/`git log -p`), labelled commit/file:line."""
    out = subprocess.run(["git", *args], capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        raise SystemExit(out.stderr.strip() or "git failed")
    commit, file, number = "", "", 0
    for line in out.stdout.splitlines():
        if line.startswith("COMMIT "):
            commit = line[7:] + " "
        elif line.startswith("+++ "):
            file = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match else 0
        elif line.startswith("+"):
            yield f"{commit}{file}:{number}", line[1:]
            number += 1


def command_leak_scan(args: argparse.Namespace) -> None:
    directory = args.directory or default_dir()
    if args.all_profiles:
        files = sorted(directory.glob("*.profile.json"))
    else:
        files = [p for p in [profile_path(args.profile, directory)] if p.exists()]
    if not files:
        # No local profile (CI, another contributor): nothing to compare against.
        # Exit 2 lets callers tell "skipped" apart from clean (0) and leak (1).
        print(json.dumps({"clean": True, "skipped": "no profile found", "directory": str(directory)}))
        raise SystemExit(2)
    needles: dict[str, str] = {}
    for file in files:
        for needle, path in leak_needles(json.loads(file.read_text(encoding="utf-8"))).items():
            needles.setdefault(needle, f"{file.name.removesuffix('.profile.json')}:{path}")
    patterns = _leak_patterns(needles)

    if args.stdin:
        lines = ((f"{args.label}:{n}", line) for n, line in enumerate(sys.stdin.read().splitlines(), 1))
    elif args.staged:
        lines = _leak_lines_from_git(["diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR"])
    elif args.history:
        lines = _leak_lines_from_git(["log", "-p", "--all", "-U0", "--no-color", "--format=COMMIT %h"])
    elif args.paths:
        lines = _leak_lines_from_paths(args.paths)
    else:
        raise SystemExit("leak-scan: pass paths, --stdin, --staged, or --history.")

    hits: list[dict[str, str]] = []
    for where, line in lines:
        if LEAK_ALLOW_MARKER in line:
            continue
        norm = _leak_normalize(line)
        for pattern, path in patterns:
            if pattern.search(norm):
                hits.append({"where": where, "field": path})
    result: dict[str, Any] = {"clean": not hits, "profiles": [f.name for f in files], "needles": len(needles), "hits": hits}
    if hits:
        result["hint"] = (
            "Real profile values found. Replace them with placeholders (e.g. 100-0001, 1-2-3); "
            f"mark a genuine false positive with '{LEAK_ALLOW_MARKER}' on that line."
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if hits:
        raise SystemExit(1)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


# backup / restore: the profile directory, age-encrypted, in a private Git repo
# (default ~/github.com/profile-use-data). Only ciphertext and the recipient
# public key are committed. Blob names are random ids, so file names, which
# carry context, stay inside the encrypted manifest. A local state file next to
# the profiles lets unchanged files skip re-encryption: age output is
# randomised, so re-encrypting everything would churn every blob in Git.

BACKUP_REPO_DEFAULT = Path.home() / "github.com" / "profile-use-data"
BACKUP_IDENTITY_DEFAULT = Path.home() / ".config" / "profile-use-backup" / "identity.txt"
BACKUP_STATE = ".backup-state.json"


def backup_repo(args: argparse.Namespace) -> Path:
    return Path(args.repo or os.environ.get("PROFILE_USE_BACKUP_REPO") or BACKUP_REPO_DEFAULT).expanduser()


def _age(*argv: str, data: bytes | None = None) -> bytes:
    age = shutil.which("age")
    if not age:
        raise SystemExit(
            "age is not installed: brew install age  (Linux: apt install age · Windows: winget install FiloSottile.age)"
        )
    proc = subprocess.run([age, *argv], input=data, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"age failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def _git(repo: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(argv)} failed: {proc.stderr.strip()}")
    return proc


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _backup_sources(directory: Path) -> dict[str, Path]:
    """Every file under the profile directory except dotfiles (state, temp writes, .DS_Store)."""
    return {
        path.relative_to(directory).as_posix(): path
        for path in sorted(directory.rglob("*"))
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(directory).parts)
    }


def command_backup(args: argparse.Namespace) -> None:
    directory = args.directory or default_dir()
    repo = backup_repo(args)
    recipients = repo / "recipients.txt"
    if not recipients.exists():
        raise SystemExit(
            f"No {recipients}. Clone the data repo first (gh repo clone <owner>/profile-use-data {repo}) or pass --repo."
        )
    if not args.no_push:
        _git(repo, "pull", "--rebase", "--quiet", check=False)  # an empty remote has nothing to pull yet
    state_path = directory / BACKUP_STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    blobs = repo / "blobs"
    blobs.mkdir(exist_ok=True)

    manifest: dict[str, dict[str, Any]] = {}
    changed = 0
    for rel, path in _backup_sources(directory).items():
        digest = sha256_file(path)
        entry = state.get(rel)
        if not entry or entry.get("sha256") != digest or not (blobs / f"{entry['id']}.age").exists():
            entry = {"id": entry["id"] if entry else secrets.token_hex(12), "sha256": digest}
            _age("-R", str(recipients), "-o", str(blobs / f"{entry['id']}.age"), str(path))
            changed += 1
        manifest[rel] = {"id": entry["id"], "sha256": digest, "size": path.stat().st_size}

    live = {entry["id"] for entry in manifest.values()}
    stale = [blob for blob in blobs.glob("*.age") if blob.stem not in live]
    for blob in stale:
        blob.unlink()
    manifest_file = repo / "manifest.json.age"
    if changed or stale or set(manifest) != set(state) or not manifest_file.exists():
        payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        manifest_file.write_bytes(_age("-R", str(recipients), data=payload))
    write_json(state_path, {rel: {"id": e["id"], "sha256": e["sha256"]} for rel, e in manifest.items()})

    _git(repo, "add", "-A", "--", "blobs", "manifest.json.age", "recipients.txt")
    committed = _git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0
    if committed:
        _git(repo, "commit", "-q", "-m", f"backup: {len(manifest)} files, {changed} changed, {len(stale)} removed")
    pushed = False
    if not args.no_push and _git(repo, "rev-parse", "HEAD", check=False).returncode == 0:
        _git(repo, "push", "-q", "-u", "origin", "HEAD")
        pushed = True
    print(json.dumps({
        "repo": str(repo), "files": len(manifest), "changed": changed,
        "removed": len(stale), "committed": committed, "pushed": pushed,
    }, indent=2))


def _backup_identity(args: argparse.Namespace) -> bytes:
    if args.identity_rbw:
        try:
            # Check first so a locked vault never leaves rbw blocked on a pinentry prompt.
            if not vault_unlocked():
                raise SystemExit("Vault is locked. Ask the user to run `rbw unlock` themselves, then retry.")
            proc = _run_rbw("get", args.identity_rbw)
        except VaultError as exc:
            raise SystemExit(str(exc)) from exc
        if proc.returncode != 0:
            raise SystemExit(_vault_failure_hint(proc))
        text = proc.stdout
    else:
        path = Path(args.identity or os.environ.get("PROFILE_USE_BACKUP_IDENTITY") or BACKUP_IDENTITY_DEFAULT).expanduser()
        if not path.exists():
            raise SystemExit(
                f"No age identity at {path}. Pass --identity FILE, or --identity-rbw '<vault item>' after `rbw unlock`."
            )
        text = path.read_text(encoding="utf-8")
    keys = [line.strip() for line in text.splitlines() if line.strip().startswith("AGE-SECRET-KEY-")]
    if not keys:
        raise SystemExit("The identity holds no AGE-SECRET-KEY- line.")
    return ("\n".join(keys) + "\n").encode()


def command_restore(args: argparse.Namespace) -> None:
    repo = backup_repo(args)
    target = Path(args.to or args.directory or default_dir()).expanduser()
    if not args.no_pull:
        _git(repo, "pull", "--rebase", "--quiet")
    manifest_file = repo / "manifest.json.age"
    if not manifest_file.exists():
        raise SystemExit(f"No backup in {repo} (manifest.json.age is missing).")
    identity = _backup_identity(args)
    restored, unchanged, conflicts = 0, 0, []
    with tempfile.TemporaryDirectory() as tmp:
        # The key only ever touches a private temp file, never the target or the repo.
        ident = Path(tmp) / "identity"
        fd = os.open(ident, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(identity)
        manifest = json.loads(_age("-d", "-i", str(ident), str(manifest_file)))
        for rel, entry in manifest.items():
            if Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise SystemExit(f"Refusing unsafe manifest path: {rel!r}")
            dest = target / rel
            if dest.exists():
                if sha256_file(dest) == entry["sha256"]:
                    unchanged += 1
                    continue
                if not args.force:
                    conflicts.append(rel)
                    continue
            data = _age("-d", "-i", str(ident), str(repo / "blobs" / f"{entry['id']}.age"))
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise SystemExit(f"Checksum mismatch for {rel}: the backup is corrupt.")
            _write_private(dest, data)
            for parent in Path(rel).parents:
                try:
                    (target / parent).chmod(0o700)
                except OSError:
                    pass
            restored += 1
    result: dict[str, Any] = {
        "target": str(target), "files": len(manifest), "restored": restored,
        "unchanged": unchanged, "conflicts": conflicts,
    }
    if conflicts:
        result["hint"] = "These local files differ from the backup; re-run with --force to overwrite them."
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if conflicts:
        raise SystemExit(1)


def add_backup_parsers(subparsers: Any) -> None:
    backup = subparsers.add_parser(
        "backup", help="Encrypt the profile directory (profiles + attachments) with age into the private data repo; commit and push."
    )
    backup.add_argument("--repo", help=f"Data repo checkout. Default: $PROFILE_USE_BACKUP_REPO, else {BACKUP_REPO_DEFAULT}.")
    backup.add_argument("--no-push", action="store_true", help="Commit locally without pulling or pushing.")
    backup.set_defaults(func=command_backup)

    restore = subparsers.add_parser(
        "restore", help="Decrypt the backup into the profile directory (or --to DIR). Works on any OS with python3, git and age."
    )
    restore.add_argument("--repo", help="Data repo checkout (same default as backup).")
    restore.add_argument("--to", type=Path, help="Restore here instead of the profile directory.")
    identity = restore.add_mutually_exclusive_group()
    identity.add_argument(
        "--identity", help=f"age identity file. Default: $PROFILE_USE_BACKUP_IDENTITY, else {BACKUP_IDENTITY_DEFAULT}."
    )
    identity.add_argument("--identity-rbw", help="Read the identity from this Bitwarden/Vaultwarden item via rbw.")
    restore.add_argument("--force", action="store_true", help="Overwrite local files that differ from the backup.")
    restore.add_argument("--no-pull", action="store_true", help="Use the checkout as is.")
    restore.set_defaults(func=command_restore)


if __name__ == "__main__":
    main()
