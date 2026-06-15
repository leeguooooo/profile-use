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
        self.assertEqual(pa.redact_value("address.jp.banchi", "1-25-57"), pa.mask_tail("1-25-57", 4))
        # 都道府県 / 市区町村 stay low sensitivity (like region/city), shown raw for filling.
        self.assertFalse(pa.is_high_sensitivity("address.jp.prefecture"))
        self.assertFalse(pa.is_high_sensitivity("address.jp.city"))
        self.assertEqual(pa.redact_value("address.jp.city", "狛江市西野川"), "狛江市西野川")

    def test_document_metadata_is_high_sensitivity(self):
        # Regression: documents.<doc>.label/source carried PII through redacted show.
        self.assertTrue(pa.is_high_sensitivity("documents.residence_card_front.label"))
        self.assertEqual(
            pa.redact_value("documents.x.source", "lark chat with ning 2026-06-12"),
            pa.mask_tail("lark chat with ning 2026-06-12", 4),
        )


class PathTests(unittest.TestCase):
    def test_set_get_roundtrip(self):
        data = {}
        pa.set_path(data, "address.jp.prefecture", "Tokyo")
        self.assertEqual(pa.get_path(data, "address.jp.prefecture"), "Tokyo")

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
