import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import contextlib
import io

spec = importlib.util.spec_from_file_location("profile_sync", Path(__file__).parents[1] / "scripts/profile_vault_sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class ProfileSyncTests(unittest.TestCase):
    def test_lossless_chunks_and_native_fields(self):
        data = {"identity": {"given_name": "Taro", "family_name": "Yamada"},
                "contact": {"email": "taro@example.com"},
                "notes": '"\\日本語🙂' * 4000,
                "payment": {"card": {"number": "4111111111111111", "expiry": "12/29", "holder": "Taro", "cvv": "123", "label": "Example card"}}}
        items, files, manifest = sync.plan(data, "fixture", Path("/nonexistent/fixture.profile.json"))
        self.assertFalse(files)
        stored = sync.json.loads(manifest["notes"])["data"]
        rebuilt = {}
        for section, count in stored["sections"].items():
            chunks = [sync.json.loads(i["notes"])["data"] for i in items if f" / data / {section} / " in i["name"]]
            self.assertEqual(len(chunks), count)
            rebuilt[section] = sync.json.loads("".join(chunks))
        self.assertEqual(rebuilt, data)
        self.assertTrue(all(len(i["notes"].encode()) <= 7000 for i in items))
        native = next(i for i in items if i["type"] == 4)
        self.assertEqual(native["identity"]["firstName"], "Taro")
        card = next(i for i in items if i["type"] == 3)
        self.assertEqual(card["card"]["expYear"], "2029")
        self.assertEqual(sync.json.loads(card["notes"])["data"], {"label":"Example card"})
        self.assertNotIn("4111111111111111", card["notes"])
        self.assertNotIn('"cvv"', card["notes"])

    def test_vault_linked_cards_are_not_overwritten_from_local_metadata(self):
        reference = {"$vault":{"provider":"bitwarden","item":"11111111-1111-4111-8111-111111111111","field":"number"}}
        data = {"payment":{"card":{"number":reference,"brand":"Visa"}, "other":{"number":"4111111111111111","brand":"Visa"}}}
        items,_,manifest = sync.plan(data,"fixture",Path("/nonexistent/fixture.profile.json"))
        cards = [item for item in items if item["type"]==3]
        self.assertEqual(len(cards),1)
        self.assertTrue(cards[0]["name"].endswith("payment.other"))
        payment = next(item for item in items if " / data / payment / " in item["name"])
        self.assertEqual(sync.json.loads(sync.json.loads(payment["notes"])["data"]),data["payment"])

    def test_attachment_hash_and_path_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            attachments = root / "attachments/fixture"
            attachments.mkdir(parents=True)
            file = attachments / "passport.bin"
            file.write_bytes(b"synthetic binary\0\xff")
            metadata = {"file": file.name, "sha256": sync.sha(file.read_bytes())}
            data = {"documents": {"passport": metadata}}
            items, files, _ = sync.plan(data, "fixture", root / "fixture.profile.json")
            self.assertEqual(len(files), 1)
            self.assertIn(metadata["sha256"], files[0]["filename"])
            metadata["file"] = "attachments/fixture/passport.bin"
            self.assertEqual(len(sync.plan(data, "fixture", root / "fixture.profile.json")[1]), 1)
            metadata["sha256"] = "wrong"
            with self.assertRaises(ValueError): sync.plan(data, "fixture", root / "fixture.profile.json")
            metadata["file"] = "../passport.bin"
            with self.assertRaises(ValueError): sync.plan(data, "fixture", root / "fixture.profile.json")
            metadata["file"] = "alias.bin"
            (attachments / "alias.bin").symlink_to(file)
            with self.assertRaises(ValueError): sync.plan(data, "fixture", root / "fixture.profile.json")

    def test_ownership_and_native_drift(self):
        item = {"type": 3, "notes": sync.note("fixture", "card", {}), "card": {"number": "1234"}}
        existing = {"notes": item["notes"], "data": {"number": "1234"}}
        sync.check_owned(existing, item)
        self.assertTrue(sync.equivalent(existing, item))
        existing["data"]["number"] = "9999"
        self.assertFalse(sync.equivalent(existing, item))
        with self.assertRaises(ValueError): sync.check_owned({"notes": "unrelated private note"}, item)

    def test_sync_repeatedly_without_duplicate_writes_or_uploads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "attachments/fixture"
            docs.mkdir(parents=True)
            content = b"synthetic document\0\xff"
            (docs / "document.bin").write_bytes(content)
            profile = root / "fixture.profile.json"
            profile.write_text(sync.encode({"identity": {"given_name": "Taro"},
                                           "documents": {"document": {"file": "document.bin", "sha256": sync.sha(content)}}}))
            entries, attachments = {}, {}
            writes, uploads = [], []
            def fake_run(*args, data=None, binary=False):
                if args[0] == "sync": return ""
                if args[0] == "ls": return "\n".join(f"{key}\t{value['name']}\tprofile-use\t{value['kind']}" for key, value in entries.items())
                if args[0] == "get": return sync.encode(entries[args[1]])
                if args[:2] == ("item", "put"):
                    item = sync.json.loads(data)
                    key = args[args.index("--id") + 1] if "--id" in args else "fixture-" + str(len(entries))
                    native = item.get("card", item.get("identity", {}))
                    entries[key] = {"name": item["name"], "notes": item["notes"], "kind": {2:"Note",3:"Card",4:"Identity"}[item["type"]],
                                    "data": {sync.re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): v for k,v in native.items()}}
                    writes.append(key)
                    return key
                if args[:2] == ("attachment", "list"): return sync.encode(attachments.get(args[2], []))
                if args[:2] == ("attachment", "upload"):
                    uploads.append(args[2])
                    attachments[args[2]] = [{"id": "synthetic-attachment", "fileName": args[args.index("--filename") + 1]}]
                    return "synthetic-attachment"
                if args[:2] == ("attachment", "download"): return content
                raise AssertionError(args)
            args = SimpleNamespace(file=profile, profile="fixture", folder="profile-use", skip_attachments=False, yes=True, dry_run=True)
            with patch.object(sync, "run", fake_run), contextlib.redirect_stdout(io.StringIO()):
                sync.synchronize(args)
                self.assertFalse(writes)
                args.dry_run = False
                sync.synchronize(args)
                first_writes = len(writes)
                sync.synchronize(args)
                self.assertEqual(len(writes), first_writes)
                self.assertEqual(len(uploads), 1)
                self.assertEqual(profile.read_text(), sync.encode(sync.json.loads(profile.read_text())))


if __name__ == "__main__":
    unittest.main()
