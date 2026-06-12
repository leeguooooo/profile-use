#!/usr/bin/env python3
"""Smoke + redaction tests. Run: python3 tests/test_personal_autofill.py"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "pa", Path(__file__).resolve().parents[1] / "scripts" / "personal_autofill.py"
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
                    icloud_root / "Agent Profiles" / "personal-autofill",
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


if __name__ == "__main__":
    unittest.main()
