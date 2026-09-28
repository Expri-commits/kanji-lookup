"""setup.sh wizard regressions: prompts, idempotence, keybind writing."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup.sh"
PLUGIN_ID = "io.github.expri-commits.kanji-lookup"

OMARCHY_STUB = """#!/bin/bash
if [[ $1 == plugin && $2 == list ]]; then printf '%s\\n' "${PLUGIN_LIST_JSON:-[]}"; exit 0; fi
if [[ $1 == menu && $2 == keybindings && $3 == --print ]]; then printf '%s\\n' "${KEYBINDINGS:-}"; exit 0; fi
printf '%s\\n' "$*" >> "$CALLS_LOG"
"""

TESSERACT_STUB = """#!/bin/bash
if [[ $1 == --list-langs ]]; then printf 'jpn\\njpn_vert\\n'; exit 0; fi
exit 1
"""

PYTHON_STUB = """#!/bin/bash
printf '%s\\n' "python3 $*" >> "$CALLS_LOG"
"""


class SetupWizardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".config/hypr").mkdir(parents=True)
        self.data = self.home / ".local/share/kanji-lookup"
        self.data.mkdir(parents=True)
        (self.data / "jmdict.db").write_bytes(b"")  # dictionaries prebuilt
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.log = Path(self.tmp.name) / "calls.log"
        self.write_stub("omarchy", OMARCHY_STUB)
        self.write_stub("tesseract", TESSERACT_STUB)
        self.write_stub("python3", PYTHON_STUB)  # never a real dictionary build
        self.write_stub("hyprctl", "exit 0\n")
        self.plugin_list_json = f'[{{"id":"{PLUGIN_ID}","enabled":true}}]'

    def write_stub(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def run_setup(self, answers, keybindings=""):
        env = dict(
            os.environ,
            HOME=str(self.home),
            PATH=f"{self.bin}:{os.environ['PATH']}",
            KANJI_LOOKUP_SETUP_FORCE="1",
            CALLS_LOG=str(self.log),
            PLUGIN_LIST_JSON=self.plugin_list_json,
            KEYBINDINGS=keybindings,
        )
        return subprocess.run(
            ["bash", str(SETUP)], input=answers, text=True,
            capture_output=True, env=env, timeout=30)

    def bindings(self):
        path = self.home / ".config/hypr/bindings.lua"
        return path.read_text() if path.exists() else ""

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def kanji_bind_lines(self):
        return [line for line in self.bindings().splitlines()
                if '"Kanji lookup"' in line and "o.bind" in line]

    def test_syntax(self):
        result = subprocess.run(["bash", "-n", str(SETUP)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_defaults_widget_to_right(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["barWidget"]["defaultSection"], "right")

    def test_fresh_install_binds_default_key(self):
        result = self.run_setup("\n\n")  # rebuild? no; shortcut: Enter = default
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.kanji_bind_lines()
        self.assertEqual(len(lines), 1)
        # Pin the exact command bytes: a wrong wl-paste flag here breaks the
        # clipboard half of every lookup the bind performs.
        self.assertIn('o.bind("SUPER+SHIFT+J", "Kanji lookup"', lines[0])
        self.assertIn("added by setup.sh", self.bindings())
        self.assertIn("wl-paste --type text --primary 2>/dev/null", lines[0])
        self.assertIn("wl-paste --type text 2>/dev/null", lines[0])
        self.assertIn('omarchy-shell io.github.expri-commits.kanji-lookup smartTrigger "$P" "$C"', lines[0])
        self.assertEqual(self.calls(), "")  # nothing installed or enabled

    def test_custom_key(self):
        result = self.run_setup("\nSUPER+ALT+K\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('o.bind("SUPER+ALT+K", "Kanji lookup"', self.bindings())

    def test_custom_key_normalizes_spaces_and_case(self):
        result = self.run_setup("\nsuper + alt + k\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('o.bind("SUPER+ALT+K", "Kanji lookup"', self.bindings())

    def test_invalid_key_rejected_then_accepted(self):
        result = self.run_setup("\n???\nSUPER+F2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("does not look like a Hyprland combo", result.stdout)
        self.assertIn('o.bind("SUPER+F2", "Kanji lookup"', self.bindings())

    def test_conflicting_key_refused_writes_nothing(self):
        result = self.run_setup(
            "\nSUPER+ALT+K\nn\n",
            keybindings="SUPER ALT + K → Music player\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        # read -p only shows prompts on a TTY; the refuse branch is the marker.
        self.assertIn("Shortcut left as is.", result.stdout)
        self.assertNotIn("o.bind", self.bindings())

    def test_conflicting_key_takeover_confirmed(self):
        result = self.run_setup(
            "\nSUPER+ALT+K\ny\n",
            keybindings="SUPER ALT + K → Music player\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('o.bind("SUPER+ALT+K", "Kanji lookup"', self.bindings())

    def test_existing_bind_replaced(self):
        (self.home / ".config/hypr/bindings.lua").write_text(
            'o.bind("SUPER + SHIFT + L", "Kanji lookup", \'old\')\n')
        result = self.run_setup("\ny\nSUPER+SHIFT+J\n")  # rebuild? no; change? yes
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.kanji_bind_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn('o.bind("SUPER+SHIFT+J", "Kanji lookup"', lines[0])

    def test_existing_bind_kept(self):
        original = 'o.bind("SUPER + SHIFT + L", "Kanji lookup", \'old\')\n'
        (self.home / ".config/hypr/bindings.lua").write_text(original)
        result = self.run_setup("\n\n")  # rebuild? no; change? no
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.bindings(), original)

    def test_existing_bind_removed_by_none(self):
        (self.home / ".config/hypr/bindings.lua").write_text(
            'o.bind("SUPER + SHIFT + L", "Kanji lookup", \'old\')\n')
        result = self.run_setup("\ny\nnone\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.kanji_bind_lines(), [])

    def test_none_on_fresh_install_skips_bind(self):
        result = self.run_setup("\nnone\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("o.bind", self.bindings())

    def test_dictionaries_declined(self):
        (self.data / "jmdict.db").unlink()
        result = self.run_setup("n\n\n")  # download? no; shortcut: Enter
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipped", result.stdout)
        self.assertNotIn("build-db.py", self.calls())

    def test_dictionaries_accepted_runs_build(self):
        (self.data / "jmdict.db").unlink()
        self.write_stub("python3", PYTHON_STUB)
        result = self.run_setup("y\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build-db.py", self.calls())

    def test_offers_enable_when_not_enabled(self):
        self.plugin_list_json = "[]"
        result = self.run_setup("y\n\n\n")  # enable? yes; rebuild? no; shortcut: Enter
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"plugin enable {PLUGIN_ID}", self.calls())

    def test_offers_pkg_add_when_tesseract_missing(self):
        self.write_stub("tesseract", "exit 1\n")  # --list-langs finds no jpn
        result = self.run_setup("n\ny\n\n")  # rebuild? no; install OCR? yes; shortcut: Enter
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pkg add tesseract-data-jpn tesseract-data-jpn_vert", self.calls())

    def test_double_run_writes_one_bind(self):
        self.run_setup("\n\n")
        result = self.run_setup("\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.kanji_bind_lines()), 1)

    def test_eof_with_invalid_existing_keeps_bind(self):
        # A hand-edited key ("code:18") fails validation; EOF during the
        # re-prompt loop must terminate, not loop forever, leaving the file.
        original = 'o.bind("code:18", "Kanji lookup", \'old\')\n'
        (self.home / ".config/hypr/bindings.lua").write_text(original)
        result = self.run_setup("\ny\n???\n")  # rebuild? no; change? yes; bad key; EOF in loop
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.bindings(), original)

    def test_removes_multiline_readme_style_bind(self):
        self.write_stub("hyprctl", "exit 0\n")
        (self.home / ".config/hypr/bindings.lua").write_text(
            'o.bind("SUPER + SHIFT + J", "Kanji lookup", [[\n'
            '  P="$(timeout 0.5s wl-paste --type text --primary 2>/dev/null)"; \\\n'
            '  omarchy-shell io.github.expri-commits.kanji-lookup smartTrigger "$P" "$C"\n'
            ']])\n')
        result = self.run_setup("\ny\nnone\n")  # rebuild? no; change? yes; none
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("o.bind", self.bindings())
        self.assertNotIn("]])", self.bindings())
        self.assertNotIn("omarchy-shell", self.bindings())  # body must go too
        self.assertNotIn("wl-paste", self.bindings())

    def test_remove_after_setup_cleans_comment_too(self):
        self.run_setup("\n\n")  # writes bind + marker comment
        result = self.run_setup("\ny\nnone\n")  # rebuild? no; change? yes; none
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("o.bind", self.bindings())
        self.assertNotIn("Kanji Lookup", self.bindings())

    def test_no_space_hand_edited_bind_replaced(self):
        (self.home / ".config/hypr/bindings.lua").write_text(
            "o.bind(\"K\",\"Kanji lookup\",'old')\n")
        result = self.run_setup("\ny\nSUPER+SHIFT+J\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.kanji_bind_lines()
        self.assertEqual(len(lines), 1)
        # The replace only rewrites the key; the user's original spacing and
        # their own command body stay untouched.
        self.assertIn('o.bind("SUPER+SHIFT+J"', lines[0])
        self.assertIn('"Kanji lookup"', lines[0])


if __name__ == "__main__":
    unittest.main()
