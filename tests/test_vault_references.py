import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("profile", Path(__file__).parents[1] / "scripts/profile_use.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)
ITEM = "11111111-1111-4111-8111-111111111111"


def ref(field="number", encoding="string"):
    return {"$vault": {"provider":"bitwarden", "item":ITEM, "field":field, "encoding":encoding}}


class VaultReferenceTests(unittest.TestCase):
    def setUp(self):
        self.refresh = patch.object(profile, "refresh_vault_cache")
        self.refresh.start()
        self.addCleanup(self.refresh.stop)

    def invoke(self, directory, *args):
        parsed = profile.build_parser().parse_args(["--dir", str(directory), *args])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            parsed.func(parsed)
        return json.loads(output.getvalue()) if output.getvalue() else None

    def test_redacted_reads_never_open_vault_and_refs_are_atomic(self):
        data = {"payment":{"card":{"number":ref()}}, "contact":{"email":ref("username")}}
        self.assertEqual(profile.iter_fields(data), ["contact.email", "payment.card.number"])
        with tempfile.TemporaryDirectory() as temp, patch.object(profile, "read_vault_reference", side_effect=AssertionError("unexpected reveal")):
            profile.write_json(Path(temp)/"personal.profile.json", data)
            self.assertEqual(self.invoke(temp, "get", "payment.card.number"), {"payment.card.number":"[vault]"})
            self.assertEqual(self.invoke(temp, "show")["contact"]["email"], "[vault]")
            self.assertEqual(self.invoke(temp, "values"), {})

    def test_explicit_values_resolve_arrays_and_apply_existing_formatting(self):
        data = {"bank":{"accounts":[{"account_number":ref("custom:account")} ]},
                "address":{"jp":{"banchi":ref("custom:address")}}}
        with tempfile.TemporaryDirectory() as temp, patch.object(profile, "read_vault_reference", side_effect=lambda v: "001234" if v["$vault"]["field"]=="custom:account" else "1-2-3"):
            profile.write_json(Path(temp)/"personal.profile.json", data)
            self.assertEqual(self.invoke(temp, "values", "bank.accounts[0].account_number"), {"bank.accounts[0].account_number":"001234"})
            self.assertEqual(self.invoke(temp, "values", "address.jp.banchi", "--format", "jp-fullwidth"), {"address.jp.banchi":"１－２－３"})
            self.assertEqual(profile.get_path(data, "bank.accounts.0.account_number"), ref("custom:account"))

    def test_exact_selection_and_json_encoding_preserve_type(self):
        response = subprocess.CompletedProcess([],0,'["00123",2]\n','')
        with patch.object(profile, "ensure_vault_unlocked"), patch.object(profile, "_is_bitwarden_use", return_value=True), patch.object(profile, "_run_rbw_quiet", return_value=response) as cli:
            self.assertEqual(profile.read_vault_reference(ref("custom:accounts", "json")), ["00123",2])
            self.assertEqual(cli.call_args.args, ("get",ITEM,"--field","custom:accounts","--reveal"))

    def test_normal_edits_cannot_replace_or_edit_reference_metadata(self):
        data = {"payment":{"card":{"number":ref(),"label":"fixture"}}}
        for field in ["payment.card.number", "payment.card", "payment.card.number.$vault.item"]:
            with self.assertRaises(ValueError): profile.set_path(data,field,"replacement")
        profile.set_path(data,"payment.card.label","new label")
        self.assertEqual(data["payment"]["card"]["number"],ref())

    def test_leak_scan_checks_private_ids_without_fetching_or_flagging_protocol_words(self):
        with patch.object(profile,"read_vault_reference",side_effect=AssertionError("unexpected reveal")):
            needles=profile.leak_needles({"payment":{"card":{"number":ref()}}})
        self.assertEqual(needles,{ITEM:"payment.card.number.$vault.item"})

    def test_typed_parent_references_keep_descendant_field_reads_working(self):
        data={"bank":{"credentials":ref("custom:credentials","json"),"accounts":ref("custom:accounts","json")}}
        with patch.object(profile,"read_vault_reference",side_effect=AssertionError("unexpected reveal")):
            self.assertEqual(profile.redact_value("bank.credentials.username",profile.get_read_path(data,"bank.credentials.username")),"[vault]")
        with patch.object(profile,"read_vault_reference",side_effect=lambda value: {"username":"fixture-user"} if value["$vault"]["field"]=="custom:credentials" else [{"account_number":"001234"}]):
            self.assertEqual(profile.get_read_path(data,"bank.credentials.username",True),"fixture-user")
            self.assertEqual(profile.get_read_path(data,"bank.accounts[0].account_number",True),"001234")

    def test_failures_and_invalid_references_do_not_echo_values(self):
        for invalid in [{"$vault":{"item":"some name","field":"password"}}, {"$vault":{"item":ITEM,"field":"--password"}}, {**ref(), "cache":"synthetic secret"}]:
            with self.assertRaises(profile.VaultError): profile.vault_ref_spec(invalid)
        for response in [subprocess.CompletedProcess([],1,'','synthetic secret'), subprocess.CompletedProcess([],0,'[redacted]\n','')]:
            with patch.object(profile, "ensure_vault_unlocked"), patch.object(profile, "_is_bitwarden_use", return_value=True), patch.object(profile, "_run_rbw_quiet", return_value=response):
                with self.assertRaises(profile.VaultError) as error: profile.read_vault_reference(ref())
                self.assertNotIn("synthetic secret",str(error.exception))

    def test_link_checks_equality_before_replacing_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"personal.profile.json"
            profile.write_json(path,{"bank":{"accounts":[{"account_number":"001234"}]}})
            with patch.object(profile,"read_vault_reference",return_value="wrong"):
                with self.assertRaises(profile.VaultError): self.invoke(temp,"link-vault","bank.accounts[0].account_number","--item",ITEM,"--vault-field","custom:account","--yes")
                self.assertEqual(profile.get_path(json.loads(path.read_text()),"bank.accounts.0.account_number"),"001234")
            with patch.object(profile,"read_vault_reference",return_value="001234"):
                self.invoke(temp,"link-vault","bank.accounts[0].account_number","--item",ITEM,"--vault-field","custom:account","--dry-run")
                self.assertIn("001234",path.read_text())
                self.assertTrue(self.invoke(temp,"link-vault","bank.accounts[0].account_number","--item",ITEM,"--vault-field","custom:account","--yes")["changed"])
                self.assertNotIn("001234",path.read_text())
                self.assertFalse(self.invoke(temp,"link-vault","bank.accounts[0].account_number","--item",ITEM,"--vault-field","custom:account","--yes")["changed"])


if __name__ == "__main__":
    unittest.main()
