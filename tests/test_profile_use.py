#!/usr/bin/env python3
"""Smoke + redaction tests. Run: python3 tests/test_profile_use.py"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "pa", Path(__file__).resolve().parents[1] / "scripts" / "profile_use.py"
)
pa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pa)


class RedactionTests(unittest.TestCase):
    def test_legal_names_are_masked(self):
        # Regression: names used to leak in full under the default redacted mode.
        self.assertEqual(pa.redact_value("identity.full_name", "Yamada Taro"), "Y***** T***")
        self.assertEqual(pa.redact_value("identity.given_name", "Taro"), "T***")

    def test_notes_are_masked(self):
        self.assertEqual(pa.redact_value("notes", "allergic to penicillin"), "******************llin")

    def test_email_masked_but_domain_kept(self):
        self.assertEqual(pa.redact_value("contact.email", "taro@example.com"), "t***@example.com")

    def test_dialing_code_is_not_over_redacted(self):
        self.assertEqual(pa.redact_value("contact.phone_country_code", "+81"), "+81")

    def test_phone_and_card_masked(self):
        self.assertEqual(pa.redact_value("contact.phone", "09012345678"), "*********78")
        self.assertEqual(pa.redact_value("payment.card.number", "4111111111111111"), "************1111")

    def test_address_line_masked(self):
        self.assertEqual(pa.redact_value("address.line1", "1-2-3 Shibuya"), "*********buya")


class LeakScanTests(unittest.TestCase):
    # Placeholder data only — the scanner compares against whatever profile is on disk.
    PROFILE = {
        "identity": {"full_name": "Yamada Taro"},
        "address": {
            "postal_code": "150-0002",
            "city": "渋谷区",
            "line1": "渋谷1丁目23番45号",
            "jp": {"postal_code_hyphenated": "150-0002"},
        },
        "contact": {"email": "taro@example.com", "phone_country_code": "+81"},
        "documents": {"bank_card": {"file": "bank_card.jpg", "label": "キャッシュカード"}},
    }

    def scan(self, text, profile=True):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            if profile:
                pa.write_json(tmp / "personal.profile.json", self.PROFILE)
            doc = tmp / "doc.md"
            doc.write_text(text, encoding="utf-8")
            args = pa.build_parser().parse_args(["--dir", str(tmp), "leak-scan", str(doc)])
            out, code = io.StringIO(), 0
            with contextlib.redirect_stdout(out):
                try:
                    args.func(args)
                except SystemExit as exc:
                    code = exc.code
            return code, out.getvalue()

    def test_reshaped_street_numbers_are_caught(self):
        # Regression: a full-width, hyphenated fragment of the real 番地 shipped in help text.
        code, out = self.scan("full-width (２３－４５), for Japanese forms")
        self.assertEqual(code, 1)
        self.assertIn("personal:address.line1", out)

    def test_postal_code_city_and_name_are_caught_without_echoing_values(self):
        code, out = self.scan("type #postal 150-0002\nwriting 渋谷区 failed\nby yamada taro\n")
        self.assertEqual(code, 1)
        self.assertEqual(out.count('"where"'), 3)
        for value in ("150-0002", "渋谷", "Yamada", "yamada"):
            self.assertNotIn(value, out)

    def test_conventional_names_and_dialing_codes_do_not_fire(self):
        code, _ = self.scan("attach bank_card.jpg (キャッシュカード), dial +81 then 1-2-3\n")
        self.assertEqual(code, 0)

    def test_allow_marker_and_missing_profile(self):
        self.assertEqual(self.scan("150-0002  <!-- profile-use: allow -->")[0], 0)
        # Exit 2 = nothing to compare against; callers (memory-use, the hook) treat it as a skip.
        code, out = self.scan("150-0002", profile=False)
        self.assertEqual(code, 2)
        self.assertIn("no profile found", out)


@unittest.skipUnless(__import__("shutil").which("age") and __import__("shutil").which("age-keygen"), "age not installed")
class BackupTests(unittest.TestCase):
    def cli(self, directory, *argv):
        import contextlib
        import io
        import json

        args = pa.build_parser().parse_args(["--dir", str(directory), *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            args.func(args)
        return json.loads(out.getvalue())

    def test_backup_restore_roundtrip_hides_names_and_skips_unchanged(self):
        import json
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src, repo, out = tmp / "profiles", tmp / "data", tmp / "restored"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["age-keygen", "-o", str(tmp / "id.txt")], check=True, capture_output=True)
            pub = subprocess.run(["age-keygen", "-y", str(tmp / "id.txt")], check=True, capture_output=True, text=True)
            (repo / "recipients.txt").write_text(pub.stdout)
            pa.write_json(src / "personal.profile.json", {"identity": {"full_name": "Yamada Taro"}})
            card = src / "attachments" / "personal" / "residence_card_front.jpg"
            card.parent.mkdir(parents=True)
            card.write_bytes(b"\xff\xd8 fake image")

            first = self.cli(src, "backup", "--repo", str(repo), "--no-push")
            self.assertEqual((first["files"], first["changed"], first["committed"]), (2, 2, True))
            committed = b"".join(p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts)
            for plain in (b"Yamada", b"residence_card", b"personal.profile", b"fake image"):
                self.assertNotIn(plain, committed)

            second = self.cli(src, "backup", "--repo", str(repo), "--no-push")
            self.assertEqual((second["changed"], second["committed"]), (0, False))

            result = self.cli(src, "restore", "--repo", str(repo), "--to", str(out), "--identity", str(tmp / "id.txt"), "--no-pull")
            self.assertEqual(result["restored"], 2)
            self.assertEqual((out / "attachments" / "personal" / "residence_card_front.jpg").read_bytes(), b"\xff\xd8 fake image")
            restored = out / "personal.profile.json"
            self.assertEqual(json.loads(restored.read_text())["identity"]["full_name"], "Yamada Taro")
            self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
            self.assertEqual((out / "attachments").stat().st_mode & 0o777, 0o700)


class SensitivityMatchTests(unittest.TestCase):
    def test_segment_aware_prefix(self):
        self.assertTrue(pa.is_high_sensitivity("payment.card.number"))
        self.assertTrue(pa.is_high_sensitivity("tax"))
        self.assertFalse(pa.is_high_sensitivity("taxonomy"))  # must not over-match
        self.assertFalse(pa.is_high_sensitivity("address.city"))

    def test_street_address_is_high_sensitivity(self):
        # Regression: values no-field dump used to leak the full street address
        # because address.line1/line2 were absent from HIGH_SENSITIVITY_PREFIXES.
        self.assertTrue(pa.is_high_sensitivity("address.line1"))
        self.assertTrue(pa.is_high_sensitivity("address.line2"))

    def test_jp_street_components_are_high_sensitivity(self):
        # 番地 / 建物名 are as precise as line1/line2 and must not leak through
        # the no-field values dump or redacted show.
        self.assertTrue(pa.is_high_sensitivity("address.jp.banchi"))
        self.assertTrue(pa.is_high_sensitivity("address.jp.building"))
        self.assertEqual(pa.redact_value("address.jp.banchi", "1-2-3"), pa.mask_tail("1-2-3", 4))
        # 都道府県 / 市区町村 stay low sensitivity (like region/city), shown raw for filling.
        self.assertFalse(pa.is_high_sensitivity("address.jp.prefecture"))
        self.assertFalse(pa.is_high_sensitivity("address.jp.city"))
        self.assertEqual(pa.redact_value("address.jp.city", "千代田区千代田"), "千代田区千代田")

    def test_document_metadata_is_high_sensitivity(self):
        # Regression: documents.<doc>.label/source carried PII through redacted show.
        self.assertTrue(pa.is_high_sensitivity("documents.residence_card_front.label"))
        self.assertEqual(
            pa.redact_value("documents.x.source", "lark chat 2026-01-01"),
            pa.mask_tail("lark chat 2026-01-01", 4),
        )


class PathTests(unittest.TestCase):
    def test_set_get_roundtrip(self):
        data = {}
        pa.set_path(data, "address.jp.prefecture", "Hokkaido")
        self.assertEqual(pa.get_path(data, "address.jp.prefecture"), "Hokkaido")

    def test_set_under_non_object_raises(self):
        data = {"payment": {"card": {"number": "x"}}}
        with self.assertRaises(ValueError):
            pa.set_path(data, "payment.card.number.foo", "y")

    def test_empty_path_rejected(self):
        with self.assertRaises(ValueError):
            pa.set_path({}, "address..city", "x")

    def test_default_dir_uses_icloud_root_even_before_agent_folder_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            icloud_root = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
            icloud_root.mkdir(parents=True)
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(pa.Path, "home", return_value=home):
                self.assertEqual(
                    pa.default_dir(),
                    icloud_root / "Agent Profiles" / "profile-use",
                )


class AttachmentTests(unittest.TestCase):
    def run_cli(self, tmp, *argv):
        import contextlib
        import io

        parser = pa.build_parser()
        args = parser.parse_args(["--dir", str(tmp), *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            args.func(args)
        return out.getvalue()

    def test_attach_list_path_detach_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_cli(tmp, "init", "--profile", "personal")
            source = tmp / "card.JPG"
            source.write_bytes(b"fake image bytes")

            self.run_cli(tmp, "attach", str(source), "--doc", "residence_card_front", "--label", "front")
            dest = tmp / "attachments" / "personal" / "residence_card_front.jpg"
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            self.assertTrue(source.exists())  # copy by default, not move

            import json as _json

            listing = _json.loads(self.run_cli(tmp, "attachments"))
            self.assertIn("residence_card_front", listing["documents"])
            self.assertTrue(listing["documents"]["residence_card_front"]["exists"])

            path_out = self.run_cli(tmp, "attachment-path", "--doc", "residence_card_front").strip()
            self.assertEqual(path_out, str(dest))

            self.run_cli(tmp, "detach", "--doc", "residence_card_front")
            self.assertFalse(dest.exists())
            listing = _json.loads(self.run_cli(tmp, "attachments"))
            self.assertEqual(listing["documents"], {})

    def test_attach_move_deletes_source_and_force_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_cli(tmp, "init", "--profile", "personal")
            source = tmp / "a.png"
            source.write_bytes(b"v1")
            self.run_cli(tmp, "attach", str(source), "--doc", "bank_card", "--move")
            self.assertFalse(source.exists())

            other = tmp / "b.jpg"
            other.write_bytes(b"v2")
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "attach", str(other), "--doc", "bank_card")
            self.run_cli(tmp, "attach", str(other), "--doc", "bank_card", "--force")
            # extension changed: old .png file is cleaned up, new .jpg tracked
            self.assertFalse((tmp / "attachments" / "personal" / "bank_card.png").exists())
            self.assertTrue((tmp / "attachments" / "personal" / "bank_card.jpg").is_file())

    def test_invalid_doc_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_cli(tmp, "init", "--profile", "personal")
            source = tmp / "a.png"
            source.write_bytes(b"x")
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "attach", str(source), "--doc", "../escape")


class SecurityTests(unittest.TestCase):
    def run_cli(self, tmp, *argv):
        import contextlib
        import io

        parser = pa.build_parser()
        args = parser.parse_args(["--dir", str(tmp), *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            args.func(args)
        return out.getvalue()

    def test_profile_name_traversal_rejected(self):
        # Regression: --profile was interpolated into a path with no validation,
        # so ../.. escaped the protected profile directory.
        with self.assertRaises(SystemExit):
            pa.profile_path("../../etc/passwd")
        with self.assertRaises(SystemExit):
            pa.attachments_dir("../../tmp/x")
        with self.assertRaises(SystemExit):
            pa.profile_path("a/b")
        # ordinary names still work
        self.assertTrue(str(pa.profile_path("personal", Path("/x"))).endswith("personal.profile.json"))

    def test_init_with_traversal_name_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "init", "--profile", "../escape")

    def test_poisoned_document_file_cannot_delete_outside_dir(self):
        # Regression: detach trusted documents.<doc>.file verbatim, giving an
        # arbitrary-file-delete primitive when the value was poisoned via set.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_cli(tmp, "init", "--profile", "personal")
            victim = tmp / "victim.txt"
            victim.write_text("do not delete")
            self.run_cli(tmp, "set", "documents.evil.file", "../../victim.txt")
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "detach", "--doc", "evil")
            self.assertTrue(victim.exists())  # untouched

    def test_profile_written_0600_and_dir_0700(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_cli(tmp, "init", "--profile", "personal")
            prof = tmp / "personal.profile.json"
            self.assertEqual(prof.stat().st_mode & 0o777, 0o600)
            self.assertEqual(tmp.stat().st_mode & 0o777, 0o700)
            # no leftover temp file
            self.assertEqual(list(tmp.glob(".*.tmp")), [])


class VaultTests(unittest.TestCase):
    """rbw adapter. The subprocess boundary is mocked; live tests run against a
    real Vaultwarden separately."""

    def setUp(self):
        # These tests speak rbw's text format, so resolve the CLI as rbw whatever
        # this machine has installed (bitwarden-use has its own test). Tests that
        # mock shutil.which to simulate "not installed" still go through the mock.
        real_which = pa.shutil.which

        def binary():
            return "/usr/local/bin/rbw" if pa.shutil.which is real_which else pa.shutil.which("rbw")

        patcher = mock.patch.object(pa, "rbw_binary", side_effect=binary)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _completed(self, returncode=0, stdout="", stderr=""):
        import subprocess

        return subprocess.CompletedProcess(args=["rbw"], returncode=returncode, stdout=stdout, stderr=stderr)

    def run_cli(self, *argv):
        import contextlib
        import io

        parser = pa.build_parser()
        args = parser.parse_args(list(argv))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            args.func(args)
        return out.getvalue()

    def test_normalize_domain_strips_scheme_port_path_www(self):
        self.assertEqual(pa.normalize_domain("https://www.Example.com:443/login?x=1"), "example.com")
        self.assertEqual(pa.normalize_domain("user@mail.example.co/path"), "mail.example.co")

    def test_domain_base_takes_last_two_labels(self):
        self.assertEqual(pa.domain_base("a.b.example.com"), "example.com")
        self.assertEqual(pa.domain_base("example.com"), "example.com")

    def test_domain_base_handles_multi_label_public_suffix(self):
        # Regression: rakuten.co.jp collapsed to "co.jp", matching every .co.jp item.
        self.assertEqual(pa.domain_base("rakuten.co.jp"), "rakuten.co.jp")
        self.assertEqual(pa.domain_base("shop.rakuten.co.jp"), "rakuten.co.jp")
        self.assertEqual(pa.domain_base("example.co.uk"), "example.co.uk")

    def test_match_entries_does_not_match_on_shared_public_suffix(self):
        # rakuten.co.jp must not pull in unrelated .co.jp items via "co.jp".
        entries = [
            {"id": "1", "name": "amazon.co.jp", "user": "a"},
            {"id": "2", "name": "paypay-sec.co.jp", "user": "b"},
            {"id": "3", "name": "Rakuten", "user": "c"},
        ]
        names = {m["name"] for m in pa.match_entries(entries, "rakuten.co.jp")}
        self.assertEqual(names, {"Rakuten"})  # the bare-brand item, and nothing else

    def test_match_entries_by_name_and_base(self):
        entries = [
            {"id": "1", "name": "GitHub", "user": "a"},
            {"id": "2", "name": "login.example.com", "user": "b"},
            {"id": "3", "name": "unrelated", "user": "c"},
        ]
        names = {m["name"] for m in pa.match_entries(entries, "https://example.com/")}
        self.assertEqual(names, {"login.example.com"})

    def test_bitwarden_use_reads_raw_json_with_reveal(self):
        import json

        raw = json.dumps({
            "data": {"password": "s3cr3t", "totp": None, "username": "taro@example.com",
                     "uris": [{"match_type": None, "uri": "https://example.com"}]},
            "fields": [], "id": "x", "name": "Example", "notes": "",
        })
        binary = "/home/u/.local/bin/bitwarden-use"
        with mock.patch.object(pa, "rbw_binary", return_value=binary), \
                mock.patch.object(pa.subprocess, "run", return_value=self._completed(stdout=raw)) as run:
            cred = pa.get_credential("Example")
            with self.assertRaises(pa.VaultError):
                pa.deep_uri_match([{"id": "x", "name": "Example", "user": ""}], "example.com")
        self.assertEqual(run.call_args[0][0], [binary, "get", "--reveal", "--raw", "Example"])
        self.assertEqual(cred, {"password": "s3cr3t", "username": "taro@example.com",
                                "uris": ["https://example.com"], "totp": ""})

    def test_parse_rbw_full(self):
        cred = pa.parse_rbw_full("s3cr3t\nUsername: taro@example.com\nURI: https://example.com\nTOTP: 123456")
        self.assertEqual(cred["password"], "s3cr3t")
        self.assertEqual(cred["username"], "taro@example.com")
        self.assertEqual(cred["uris"], ["https://example.com"])
        self.assertEqual(cred["totp"], "123456")

    def test_redact_credential_hides_password_and_user(self):
        red = pa.redact_credential({"password": "s3cr3t", "username": "taro@example.com", "totp": "123456"})
        self.assertEqual(red["password"], "********")  # fixed width, no length leak
        self.assertEqual(red["username"], "t***@example.com")
        self.assertEqual(red["totp"], "present")  # presence only, never the code

    def test_login_redacted_by_default(self):
        list_out = "1\tExample\ttaro@example.com\n2\tOther\tx\n"
        full_out = "s3cr3t\nUsername: taro@example.com\nURI: https://example.com"

        def fake_run(*args):
            if args[0] == "unlocked":
                return self._completed(0)
            if args[0] == "list":
                return self._completed(0, list_out)
            if args[0] == "get":
                return self._completed(0, full_out)
            return self._completed(1, stderr="unexpected")

        with mock.patch.object(pa, "_run_rbw", side_effect=fake_run):
            import json as _json

            payload = _json.loads(self.run_cli("login", "--domain", "example.com"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["item"], "Example")
            self.assertEqual(payload["password"], "********")
            self.assertNotIn("s3cr3t", _json.dumps(payload))

            revealed = _json.loads(self.run_cli("login", "--domain", "example.com", "--reveal"))
            self.assertEqual(revealed["password"], "s3cr3t")

    def test_login_reports_multiple_matches_without_fetching_secrets(self):
        list_out = "1\texample.com\ta\n2\tlogin.example.com\tb\n"

        def fake_run(*args):
            if args[0] == "unlocked":
                return self._completed(0)
            if args[0] == "list":
                return self._completed(0, list_out)
            if args[0] == "get":
                raise AssertionError("must not fetch a password while ambiguous")
            return self._completed(1)

        with mock.patch.object(pa, "_run_rbw", side_effect=fake_run):
            import json as _json

            with self.assertRaises(SystemExit):
                out = self.run_cli("login", "--domain", "example.com")
                self.assertFalse(_json.loads(out)["ok"])

    def test_login_errors_when_locked(self):
        with mock.patch.object(pa, "_run_rbw", return_value=self._completed(1)):
            with self.assertRaises(SystemExit):
                self.run_cli("login", "--domain", "example.com")

    def test_missing_rbw_raises_with_install_hint(self):
        with mock.patch.object(pa.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                pa._run_rbw("list")
            self.assertIn("rbw not found", str(ctx.exception))

    def test_vault_setup_configures_and_surfaces_unlock_step(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            if args[:2] == ("config", "set"):
                return self._completed(0)
            if args == ("config", "show"):
                return self._completed(0, '{"base_url": "https://bit.leeguoo.com", "email": "me@x.com"}')
            if args == ("unlocked",):
                return self._completed(1)  # locked
            return self._completed(1)

        with mock.patch.object(pa.shutil, "which", return_value="/usr/local/bin/rbw"):
            with mock.patch.object(pa, "_run_rbw", side_effect=fake_run):
                import json as _json

                out = _json.loads(
                    self.run_cli("vault-setup", "--base-url", "https://bit.leeguoo.com", "--email", "me@x.com")
                )
        self.assertTrue(out["ok"])
        self.assertEqual(out["configured"], ["base_url", "email"])
        self.assertEqual(out["email"], "m***@x.com")  # masked, never raw
        self.assertFalse(out["unlocked"])
        self.assertIn("rbw login", out["next_step"])  # the one human step

    def test_vault_setup_without_install_flag_refuses_when_missing(self):
        with mock.patch.object(pa.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit):
                self.run_cli("vault-setup", "--base-url", "https://x")


if __name__ == "__main__":
    unittest.main()


class ValueFormatTests(unittest.TestCase):
    """#3: agents were converting phone numbers and full-width digits in shell
    with ad-hoc regexes at fill time. `values` now does it, and only when it
    can do so honestly."""

    def run_cli(self, tmp, *argv):
        import contextlib
        import io

        parser = pa.build_parser()
        args = parser.parse_args(["--dir", str(tmp), *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            args.func(args)
        return out.getvalue()

    def test_format_phone_domestic_and_e164(self):
        self.assertEqual(pa.format_phone("070-1234-5678", "81", "domestic"), "07012345678")
        self.assertEqual(pa.format_phone("070-1234-5678", "+81", "e164"), "+817012345678")
        self.assertEqual(pa.format_phone("+81 70 1234 5678", "81", "domestic"), "07012345678")
        self.assertEqual(pa.format_phone("+81 70 1234 5678", "81", "e164"), "+817012345678")

    def test_format_phone_never_guesses_without_a_country_code(self):
        # +81 70 vs a national 070 cannot be told apart without the code, so
        # the value must come back untouched rather than mangled.
        self.assertEqual(pa.format_phone("070-1234-5678", None, "domestic"), "070-1234-5678")
        self.assertEqual(pa.format_phone("070-1234-5678", "", "e164"), "070-1234-5678")
        self.assertEqual(pa.format_phone(12345, "81", "e164"), 12345)

    def test_to_fullwidth_matches_the_bank_form(self):
        self.assertEqual(pa.to_fullwidth("1番2-3号"), "１番２－３号")
        self.assertEqual(pa.to_fullwidth("100-0001"), "１００－０００１")
        # Kana/kanji/spaces untouched; nested containers handled; non-strings pass.
        self.assertEqual(pa.to_fullwidth({"r": ["Room 101", 7]}), {"r": ["Ｒｏｏｍ １０１", 7]})

    def test_values_applies_formats_only_where_they_belong(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_cli(tmp, "init", "--profile", "personal")
            self.run_cli(tmp, "set", "contact.phone", "070-1234-5678")
            self.run_cli(tmp, "set", "contact.phone_country_code", "81")
            self.run_cli(tmp, "set", "address.jp.postal_code_hyphenated", "100-0001")

            import json

            out = json.loads(self.run_cli(tmp, "values", "contact.phone", "address.jp.postal_code_hyphenated", "--phone-format", "domestic"))
            self.assertEqual(out["contact.phone"], "07012345678")
            # --phone-format must not touch non-phone fields.
            self.assertEqual(out["address.jp.postal_code_hyphenated"], "100-0001")

            out = json.loads(self.run_cli(tmp, "values", "contact.phone", "--phone-format", "e164"))
            self.assertEqual(out["contact.phone"], "+817012345678")

            out = json.loads(self.run_cli(tmp, "values", "address.jp.postal_code_hyphenated", "--format", "jp-fullwidth"))
            self.assertEqual(out["address.jp.postal_code_hyphenated"], "１００－０００１")

            # No country code on file → phone comes back exactly as stored.
            self.run_cli(tmp, "unset", "contact.phone_country_code")
            out = json.loads(self.run_cli(tmp, "values", "contact.phone", "--phone-format", "domestic"))
            self.assertEqual(out["contact.phone"], "070-1234-5678")
