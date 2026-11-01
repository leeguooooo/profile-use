import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prepare-release.py"
PROJECT = 'CFBundleShortVersionString: "0.4.0"\nCFBundleVersion: "5"\n'
PLIST = (
    "<key>CFBundleShortVersionString</key>\n\t<string>0.4.0</string>\n"
    "<key>CFBundleVersion</key>\n\t<string>5</string>\n"
)


class PrepareReleaseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.plist = self.root / "app/ProfileUse/App/Info.plist"
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text(PLIST)
        (self.root / "app/project.yml").write_text(PROJECT)
        self.git("init", "-q")
        self.git("add", ".")
        self.commit("chore: init")
        self.git("tag", "v0.4.0")

    def git(self, *args):
        subprocess.run(
            ("git", "-c", "user.name=t", "-c", "user.email=t@example.com") + args,
            cwd=self.root, check=True, capture_output=True,
        )

    def commit(self, subject):
        self.git("commit", "-q", "--allow-empty", "-m", subject)

    def run_script(self):
        done = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=self.root, check=True, capture_output=True, text=True
        )
        return done.stdout.strip()

    def test_ignored_types_do_not_release(self):
        for subject in ("docs: a", "chore: b", "ci: c", "build(deps): d", "chore(release): v0.4.0"):
            self.commit(subject)
        self.assertEqual(self.run_script(), "")
        self.assertEqual((self.root / "app/project.yml").read_text(), PROJECT)

    def test_fix_bumps_patch_and_build_number_everywhere(self):
        self.commit("fix(profile): a")
        self.assertEqual(self.run_script(), "v0.4.1")
        self.assertEqual(
            (self.root / "app/project.yml").read_text(),
            'CFBundleShortVersionString: "0.4.1"\nCFBundleVersion: "6"\n',
        )
        self.assertEqual(self.plist.read_text(), PLIST.replace("0.4.0", "0.4.1").replace(">5<", ">6<"))

    def test_feat_and_breaking_bump_minor(self):
        for subject in ("feat: a", "fix!: a", "feat!: a"):
            with self.subTest(subject):
                self.commit(subject)
                self.assertEqual(self.run_script(), "v0.5.0")
                self.git("checkout", "-q", ".")
                self.git("reset", "-q", "--hard", "v0.4.0")

    def test_refuses_mismatched_version_files(self):
        self.plist.write_text(PLIST.replace("0.4.0", "0.3.9"))
        self.commit("fix: a")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_script()


if __name__ == "__main__":
    unittest.main()
