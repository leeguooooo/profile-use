#!/usr/bin/env python3
"""Smoke + redaction tests. Run: python3 tests/test_personal_autofill.py"""

import importlib.util
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
