"""Promoted entries retain a stable, bounded path back by dictionary ID."""

import json
from pathlib import Path
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "word-navigation.js"


def related(previous, main, candidates, limit=25):
    expression = (
        f"relatedAfterFocus({json.dumps(previous)}, {json.dumps(main)}, "
        f"{json.dumps(candidates)}, {limit})"
    )
    script = SOURCE.read_text() + "\nconsole.log(JSON.stringify(" + expression + "));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


class WordNavigationTests(unittest.TestCase):
    def test_previous_focus_is_first_and_duplicates_use_id(self):
        old = {"id": "1", "term": "敬語"}
        new = {"id": "2", "term": "尊敬語"}
        homonym = {"id": "3", "term": "敬語"}
        self.assertEqual(
            related(old, new, [new, homonym, old]),
            [old, homonym],
        )

    def test_back_and_forth_promotion_keeps_latest_previous_first(self):
        first = {"id": "1", "term": "敬語"}
        second = {"id": "2", "term": "尊敬語"}
        third = {"id": "3", "term": "謙譲語"}
        forward = related(first, second, [third, first])
        self.assertEqual(forward[0], first)
        backward = related(second, first, [third, second])
        self.assertEqual(backward[0], second)

    def test_previous_is_kept_when_limit_is_full(self):
        previous = {"id": "old", "term": "old"}
        candidates = [{"id": str(i), "term": str(i)} for i in range(30)]
        result = related(previous, None, candidates)
        self.assertEqual(len(result), 25)
        self.assertEqual(result[0], previous)
        self.assertEqual(result[-1], candidates[23])


if __name__ == "__main__":
    unittest.main()
