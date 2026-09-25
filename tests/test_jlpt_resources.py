import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class JlptResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.levels = json.loads((ROOT / "resources" / "jlpt-levels.json").read_text(encoding="utf-8"))

    def test_resource_contains_only_single_kanji_and_modern_level_values(self):
        self.assertGreater(len(self.levels), 2000)
        for kanji, level in self.levels.items():
            with self.subTest(kanji=kanji):
                self.assertEqual(len(kanji), 1)
                self.assertIs(type(level), int)
                self.assertIn(level, range(1, 6))

    def test_representative_modern_levels_are_preserved(self):
        # These values follow the modern estimates and catch a regression to
        # copying KANJIDIC2's legacy 1-4 `jlptLevel` values.
        self.assertEqual(self.levels["敬"], 2)
        self.assertEqual(self.levels["語"], 5)
