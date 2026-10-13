"""Private profile -> native vault items and encrypted attachments. No plaintext exports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FORMAT = "profile-use-sync-v1"
MAX_FILE = 128 * 1024 * 1024


def is_reference(value):
    return isinstance(value, dict) and "$vault" in value


def contains_references(value):
    if is_reference(value): return True
    if isinstance(value, dict): return any(contains_references(v) for v in value.values())
    if isinstance(value, list): return any(contains_references(v) for v in value)
    return False


class SyncError(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(*args, data=None, binary=False):
    proc = subprocess.run([os.environ.get("PROFILE_SYNC_BWU", "bwu"), *map(str, args)],
                          input=data, capture_output=True, text=not binary)
    if proc.returncode:
        # CLI/server errors may contain values or signed URLs. Keep them out of logs.
        raise SyncError("vault command failed: " + " ".join(map(str, args[:2])) +
                           "; sync and inspect saved state before retrying")
    return proc.stdout if binary else proc.stdout.strip()


def note(profile, role, data):
    return encode({"format": FORMAT, "profile": profile, "role": role, "data": data})


def identity(data):
    mappings = {
        "identity": {"firstName": "given_name", "lastName": "family_name"},
        "address": {"address1": "line1", "address2": "line2", "city": "city",
                    "state": "region", "postalCode": "postal_code", "country": "country"},
        "contact": {"phone": "phone", "email": "email"},
    }
    result = {}
    for section, fields in mappings.items():
        for target, source in fields.items():
            value = data.get(section, {}).get(source)
            if isinstance(value, str) and value:
                result[target] = value
    return result


def cards(value, path="payment"):
    if isinstance(value, dict):
        if value.get("number") and any(k in value for k in ("brand", "expiry", "holder")):
            if contains_references(value): return
            card = {}
            for source, target in [("number", "number"), ("holder", "cardholderName"),
                                   ("brand", "brand"), ("cvv", "code")]:
                if isinstance(value.get(source), str) and value[source]:
                    card[target] = value[source]
            expiry = re.fullmatch(r"(\d{1,2})\s*[/\-]\s*(\d{2}|\d{4})", str(value.get("expiry", "")))
            if expiry and 1 <= int(expiry[1]) <= 12:
                card["expMonth"] = str(int(expiry[1]))
                card["expYear"] = "20" + expiry[2] if len(expiry[2]) == 2 else expiry[2]
            yield path, card, value
        else:
            for key, child in value.items():
                yield from cards(child, path + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from cards(child, path + "." + str(index))


def plan(data, profile, profile_file, skip_attachments=False):
    prefix = "profile-use " + profile
    items, files, sections = [], [], {}
    # Store every JSON value losslessly, including fields with no native equivalent.
    for section, value in data.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", section):
            raise SyncError("invalid profile section key")
        serialized = encode(value)
        chunks = []
        while serialized:
            length = min(6000, len(serialized))
            while len(note(profile, "section:" + section, serialized[:length]).encode()) > 7000:
                length //= 2
            chunks.append(serialized[:length])
            serialized = serialized[length:]
        sections[section] = len(chunks)
        for index, chunk in enumerate(chunks, 1):
            items.append({"name": f"{prefix} / data / {section} / {index:02}", "type": 2,
                          "notes": note(profile, "section:" + section, chunk)})
    native = identity(data)
    if native:
        items.append({"name": prefix + " / identity", "type": 4, "identity": native,
                      "notes": note(profile, "identity", data.get("identity", {}))})
    for path, card, original in cards(data.get("payment", {})):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", path):
            raise SyncError("invalid payment field path")
        items.append({"name": prefix + " / card / " + path, "type": 3, "card": card,
                      "notes": note(profile, "card:" + path, {k: original[k] for k in ("label", "billing_address_same_as_profile") if k in original})})
    root = (profile_file.parent / "attachments" / profile).resolve()
    for doc, metadata in data.get("documents", {}).items():
        if not isinstance(metadata, dict) or not metadata.get("file") or skip_attachments:
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", doc):
            raise SyncError("invalid document key")
        filename = metadata["file"]
        if not isinstance(filename, str) or filename in (".", "..") or any(c in filename for c in ("\\", "\0")):
            raise SyncError("unsafe document filename")
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise SyncError("unsafe document filename")
        if len(relative.parts) == 1:
            path = root / filename
        elif relative.parts[:2] == ("attachments", profile) and len(relative.parts) == 3:
            # Earlier profiles stored a path relative to the profile directory.
            path = profile_file.parent / relative
        else:
            raise SyncError("unsafe document filename")
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root or path.stat().st_size > MAX_FILE:
            raise SyncError("missing, unsafe or oversized document file")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else sha(stream.read())
        if metadata.get("sha256") and metadata["sha256"] != digest:
            raise SyncError("document differs from recorded hash; fix profile before syncing")
        name = prefix + " / document / " + doc
        # Content-addressed names prevent duplicate uploads and retain earlier versions.
        vault_name = doc + "-" + digest + path.suffix
        items.append({"name": name, "type": 2, "notes": note(profile, "document:" + doc, metadata)})
        files.append({"item": name, "path": path, "filename": vault_name, "sha256": digest})
    manifest = {"sections": sections, "sha256": sha(encode(data).encode()),
                "attachments": [{"doc": f["item"].split(" / document / ", 1)[1], "sha256": f["sha256"], "extension": f["path"].suffix} for f in files],
                "attachments_skipped": skip_attachments}
    manifest_item = {"name": prefix + " / manifest", "type": 2,
                     "notes": note(profile, "manifest", manifest)}
    for item in [*items, manifest_item]:
        padded = (len(item["notes"].encode()) // 16 + 1) * 16
        if 72 + ((padded + 2) // 3) * 4 > 10000:  # profile-use: allow (public API notes size limit)
            raise SyncError("native metadata or manifest exceeds encrypted notes limit; split metadata before syncing")
    return items, files, manifest_item


def inventory(folder):
    result = {}
    for line in run("ls", "--fields", "id,name,folder,type").splitlines():
        values = line.split("\t")
        if len(values) == 4 and values[2] == folder:
            result.setdefault(values[1], []).append((values[0], values[3]))
    return result


def read_item(item_id):
    return json.loads(run("get", item_id, "--json", "--reveal"))


def check_owned(existing, expected):
    try:
        actual, target = json.loads(existing["notes"]), json.loads(expected["notes"])
    except (ValueError, TypeError, KeyError):
        raise SyncError("same-name vault item is not managed by profile sync") from None
    if any(actual.get(key) != target.get(key) for key in ("format", "profile", "role")):
        raise SyncError("same-name vault item belongs to another source")


def equivalent(existing, expected):
    if existing.get("notes") != expected["notes"]:
        return False
    native = expected.get("card", expected.get("identity", {}))
    for key, value in native.items():
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        if existing.get("data", {}).get(snake) != value:
            return False
    return True


def synchronize(args):
    profile_file = Path(args.file).expanduser().resolve()
    data = json.loads(profile_file.read_text())
    if not isinstance(data, dict):
        raise SyncError("profile must be a JSON object")
    profile = args.profile or profile_file.name.removesuffix(".profile.json")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        raise SyncError("invalid profile name")
    items, files, manifest = plan(data, profile, profile_file, args.skip_attachments)
    run("sync")
    known = inventory(args.folder)
    pending, ids = [], {}
    # Complete the ownership/file validation before the first write.
    for item in [*items, manifest]:
        matches = known.get(item["name"], [])
        if len(matches) > 1:
            raise SyncError("duplicate managed item name; resolve before syncing")
        if matches:
            item_id, kind = matches[0]
            existing = read_item(item_id)
            check_owned(existing, item)
            ids[item["name"]] = item_id
            expected_kind = {2: "Note", 3: "Card", 4: "Identity"}[item["type"]]
            if kind == expected_kind and equivalent(existing, item):
                continue
        pending.append(item)
    print(encode({"sections": len(data), "items": len(items) + 1, "item_writes": len(pending),
                  "attachments": len(files), "dry_run": args.dry_run}), flush=True)
    if args.dry_run:
        return
    if not args.yes:
        if not sys.stdin.isatty() or input("Sync these private fields and document files to your vault? [y/N] ").lower() not in ("y", "yes"):
            raise SyncError("confirmation required; preview with --dry-run, then pass --yes")
    def put(item):
        flags = ["--id", ids[item["name"]]] if item["name"] in ids else ["--folder", args.folder]
        ids[item["name"]] = run("item", "put", "-", *flags, "--yes", data=encode(item))
    # Save manifest last: it is the completion marker, never a promise of pending work.
    for index, item in enumerate(items, 1):
        if item in pending:
            put(item)
        existing = read_item(ids[item["name"]])
        if not equivalent(existing, item):
            raise SyncError("native item readback mismatch")
        print(encode({"items_verified": index, "total": len(items)}), flush=True)
    for index, file in enumerate(files, 1):
        item_id = ids[file["item"]]
        attachments = json.loads(run("attachment", "list", item_id, "--reveal"))
        matches = [a for a in attachments if a["fileName"] == file["filename"]]
        if len(matches) > 1:
            raise SyncError("duplicate content-addressed attachment; inspect before retrying")
        attachment_id = matches[0]["id"] if matches else run("attachment", "upload", item_id, file["path"], "--filename", file["filename"], "--yes")
        downloaded = run("attachment", "download", item_id, attachment_id, "--output", "-", binary=True)
        if sha(downloaded) != file["sha256"]:
            raise SyncError("attachment download checksum mismatch")
        print(encode({"attachments_verified": index, "total": len(files)}), flush=True)
    # Reassemble the text profile from the stored chunks, not from the source file.
    stored_manifest = json.loads(manifest["notes"])["data"]
    rebuilt = {}
    for section, count in stored_manifest["sections"].items():
        chunks = []
        for index in range(1, count + 1):
            name = f"profile-use {profile} / data / {section} / {index:02}"
            chunks.append(json.loads(read_item(ids[name])["notes"])["data"])
        rebuilt[section] = json.loads("".join(chunks))
    if sha(encode(rebuilt).encode()) != stored_manifest["sha256"]:
        raise SyncError("full profile readback checksum mismatch")
    if sha(encode(json.loads(profile_file.read_text())).encode()) != stored_manifest["sha256"]:
        raise SyncError("profile changed during sync; completion marker was not saved")
    if manifest in pending:
        put(manifest)
    if not equivalent(read_item(ids[manifest["name"]]), manifest):
        raise SyncError("manifest readback mismatch")
    print(encode({"ok": True, "profile_matches": True, "attachments_verified": len(files),
                  "item_writes": len(pending), "automatic_schedule": False}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--profile")
    parser.add_argument("--folder", default="profile-use")
    parser.add_argument("--skip-attachments", action="store_true")
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--yes", action="store_true")
    flags.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        synchronize(args)
    except SyncError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError, KeyError, TypeError):
        # Do not echo exception text: JSON/parser/filesystem errors can contain private values.
        print("Profile sync stopped; inspect vault state and validate source files before retrying. No personal values logged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
