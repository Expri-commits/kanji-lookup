"""Selection watcher framing and per-source freshness regressions."""

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATE_JS = ROOT / "scripts" / "selection-state.js"
WATCH_EVENT = ROOT / "scripts" / "selection-watch-event.sh"


class SelectionWatchEventTests(unittest.TestCase):
    def emit(self, state, payload):
        env = dict(os.environ, CLIPBOARD_STATE=state)
        env.pop("CLIPBOARD_TYPE", None)
        return subprocess.run(
            ["bash", str(WATCH_EVENT)], input=payload, text=True, capture_output=True,
            env=env, check=True,
        ).stdout

    def test_data_callback_is_one_newline_framed_marker_without_payload(self):
        payload = "一行目\n二行目"
        self.assertEqual(self.emit("data", payload), "data\n")

    def test_missing_mime_metadata_does_not_break_watcher(self):
        self.assertEqual(self.emit("data", "selected"), "data\n")

    def test_data_and_nil_callbacks_emit_framed_state_markers(self):
        self.assertEqual(self.emit("data", "binary-ish"), "data\n")
        self.assertEqual(self.emit("nil", ""), "nil\n")


class SelectionStateTests(unittest.TestCase):
    def api(self, expression):
        source = STATE_JS.read_text().replace(".pragma library", "", 1)
        code = source + "\nconsole.log(JSON.stringify(" + expression + "));"
        result = subprocess.run(
            ["node", "-e", code], text=True, capture_output=True, check=True,
        )
        return result.stdout.strip()

    def test_initial_data_and_nil_callbacks_remain_cold(self):
        for event in ("data", "nil"):
            with self.subTest(event=event):
                self.assertEqual(
                    self.api(f'applyWatchEvent({{at:0,valid:false,awaitingBaseline:true}}, "{event}", 1000)'),
                    '{"at":0,"valid":false,"awaitingBaseline":false}',
                )

    def test_data_events_refresh_even_when_content_is_repeated(self):
        self.assertEqual(
            self.api('applyWatchEvent({at:0,valid:false,awaitingBaseline:false}, "data", 1200)'),
            '{"at":1200,"valid":true,"awaitingBaseline":false}',
        )

    def test_nil_callback_invalidates_a_fresh_source(self):
        self.assertEqual(
            self.api('applyWatchEvent({at:1200,valid:true,awaitingBaseline:false}, "nil", 1300)'),
            '{"at":0,"valid":false,"awaitingBaseline":false}',
        )

    def test_watcher_restart_clears_state_and_replay_stays_cold(self):
        self.assertEqual(
            self.api('applyWatchEvent(awaitingBaseline({at:1200,valid:true}), "data", 5000)'),
            '{"at":0,"valid":false,"awaitingBaseline":false}',
        )

    def test_freshest_changed_source_wins_and_cold_or_stale_sources_are_rejected(self):
        scenarios = [
            'choose("primary", "copied", 7000, 8500, 9000, 5000)',
            'choose("primary", "copied", 8500, 7000, 9000, 5000)',
            'choose("stale", "fresh", 3000, 8500, 9000, 5000)',
            'choose("stale", "", 3000, 0, 9000, 5000)',
            'choose("older text", "", 9500, 10000, 10001, 5000)',
            'choose("", "", 8500, 8500, 9000, 5000)',
            'choose("", "", 10000, 10001, 10001, 5000)',
            'choose("boundary", "", 6000, 0, 11000, 5000)',
        ]
        expected = [
            '{"text":"copied","source":"clipboard"}',
            '{"text":"primary","source":"primary"}',
            '{"text":"fresh","source":"clipboard"}',
            "null",
            "null",
            "null",
            "null",
            "null",
        ]
        self.assertEqual(len(scenarios), len(expected))
        for scenario, want in zip(scenarios, expected):
            with self.subTest(scenario=scenario):
                self.assertEqual(self.api(scenario), want)


if __name__ == "__main__":
    unittest.main()
