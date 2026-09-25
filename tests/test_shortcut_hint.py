"""Hyprland shortcut discovery for the optional bar hint."""

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
HINT_JS = ROOT / "scripts" / "shortcut-hint.js"
PLUGIN = "io.github.expri-commits.kanji-lookup"


class ShortcutHintTests(unittest.TestCase):
    def parse(self, binds):
        source = HINT_JS.read_text().replace(".pragma library", "", 1)
        payload = json.dumps(binds)
        code = source + "\nconsole.log(JSON.stringify(findShortcut(" + json.dumps(payload) + ")));"
        result = subprocess.run(
            ["node", "-e", code], text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def test_lua_description_recovers_current_omarchy_shortcut(self):
        self.assertEqual(self.parse([{
            "dispatcher": "__lua", "arg": "140", "description": "Kanji lookup",
            "modmask": 65, "key": "J", "submap": "", "mouse": False,
        }]), "Super+Shift+J")

    def test_custom_exec_action_and_modifier_names_are_detected(self):
        self.assertEqual(self.parse([{
            "dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} smartTrigger '$P' '$C'",
            "description": "Personal lookup", "modmask": 12, "key": "k",
            "submap": "", "mouse": False,
        }]), "Ctrl+Alt+K")

    def test_absent_or_malformed_json_fails_closed(self):
        source = HINT_JS.read_text().replace(".pragma library", "", 1)
        for payload in ("", "not json", "{}"):
            with self.subTest(payload=payload):
                code = source + "\nconsole.log(JSON.stringify(findShortcut(" + json.dumps(payload) + ")));"
                result = subprocess.run(
                    ["node", "-e", code], text=True, capture_output=True, check=True,
                )
                self.assertEqual(json.loads(result.stdout), "")

    def test_unrelated_mentions_and_close_hide_routes_are_ignored(self):
        self.assertEqual(self.parse([
            {"dispatcher": "exec", "arg": f"echo {PLUGIN} in docs", "modmask": 64, "key": "D"},
            {"dispatcher": "exec", "arg": f"echo {PLUGIN} lookup", "modmask": 64, "key": "E"},
            {"dispatcher": "exec", "arg": f"xdg-open /repo/{PLUGIN}/lookup", "modmask": 64, "key": "R"},
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} close", "modmask": 64, "key": "C"},
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} hide", "modmask": 64, "key": "H"},
        ]), "")

    def test_smart_trigger_wins_and_submaps_are_not_misrepresented(self):
        self.assertEqual(self.parse([
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} open", "modmask": 64, "key": "O"},
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} smartTrigger", "modmask": 65, "key": "J"},
            {"dispatcher": "exec", "arg": f"/usr/bin/omarchy-shell -q {PLUGIN} lookup foo", "modmask": 64, "key": "F8"},
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} smartTrigger", "modmask": 64, "key": "X", "submap": "resize"},
        ]), "Super+Shift+J")

    def test_named_keysyms_are_readable_and_malformed_entries_are_ignored(self):
        self.assertEqual(self.parse([
            None,
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} lookup", "modmask": 64, "key": "Return"},
        ]), "Super+Return")

    def test_mouse_keycode_and_unknown_modifier_bindings_are_skipped(self):
        self.assertEqual(self.parse([
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} lookup", "modmask": 64, "key": "", "keycode": 44},
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} lookup", "modmask": 64, "key": "M", "mouse": True},
            {"dispatcher": "exec", "arg": f"omarchy-shell {PLUGIN} lookup", "modmask": 65 | 2, "key": "U"},
        ]), "")


if __name__ == "__main__":
    unittest.main()
