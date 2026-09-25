"""Pure parsers of scripts/build-db.py: JMdict / KANJIDIC2 JSON -> DB rows,
fed from tiny one-file zips shaped like the jmdict-simplified releases."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


BUILD_DB = Path(__file__).resolve().parents[1] / "scripts" / "build-db.py"
_spec = importlib.util.spec_from_file_location("build_db", BUILD_DB)
build_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_db)


class ParseJmdictTests(unittest.TestCase):
    """parse_jmdict: one (id, kanji, reading, glosses) row per word entry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def zip_with(self, words):
        path = Path(self.tmp.name) / "jmdict.json.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("jmdict.json", json.dumps({"words": words}))
        return str(path)

    def test_normal_entry_joins_lists_and_senses(self):
        rows = build_db.parse_jmdict(self.zip_with([{
            "id": "1000010",
            "kanji": [{"text": "読む"}],
            "kana": [{"text": "よむ"}, {"text": "ヨム"}],
            "sense": [
                {"gloss": [{"text": "to read"}]},
                {"gloss": [{"text": "to peruse"}]},
                {"gloss": []},  # a sense without glosses contributes nothing
            ],
        }]))
        self.assertEqual(rows, [(1000010, "読む", "よむ;ヨム", "to read | to peruse")])

    def test_missing_optional_fields_become_empty_columns(self):
        # No kanji/kana arrays (reading-only entry); a numeric id works too.
        rows = build_db.parse_jmdict(self.zip_with([
            {"id": 2, "sense": [{"gloss": [{"text": "meaning"}]}]},
        ]))
        self.assertEqual(rows, [(2, "", "", "meaning")])

    def test_full_glosses_are_preserved_for_focused_word_details(self):
        rows = build_db.parse_jmdict(self.zip_with([
            {"id": 3, "sense": [{"gloss": [{"text": "x" * 500}]}]},
        ]))
        self.assertEqual(rows, [(3, "", "", "x" * 500)])

    def test_empty_dictionary_yields_no_rows(self):
        self.assertEqual(build_db.parse_jmdict(self.zip_with([])), [])


class ParseKanjidic2Tests(unittest.TestCase):
    """parse_kanjidic2: one (literal, meanings, on, kun, strokes, grade) row."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def zip_with(self, characters):
        path = Path(self.tmp.name) / "kanjidic2.json.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("kanjidic2.json", json.dumps({"characters": characters}))
        return str(path)

    def test_normal_character_keeps_japanese_readings_and_english_meanings(self):
        rows = build_db.parse_kanjidic2(self.zip_with([{
            "literal": "桜",
            "readingMeaning": {"groups": [{
                "readings": [
                    {"type": "ja_on", "value": "サク"},
                    {"type": "ja_kun", "value": "さくら"},
                    {"type": "pinyin", "value": "ying"},  # non-Japanese reading dropped
                ],
                "meanings": [
                    {"lang": "en", "value": "cherry"},
                    {"lang": "fr", "value": "cerisier"},  # non-English meaning dropped
                ],
            }]},
            "misc": {"strokeCounts": [10], "grade": 1},
        }]))
        self.assertEqual(rows, [("桜", "cherry", "サク", "さくら", 10, 1)])

    def test_character_without_optional_fields(self):
        # No readingMeaning / misc at all: empty strings, NULL strokes and grade.
        rows = build_db.parse_kanjidic2(self.zip_with([{"literal": "丂"}]))
        self.assertEqual(rows, [("丂", "", "", "", None, None)])

    def test_empty_kanjidic_yields_no_rows(self):
        self.assertEqual(build_db.parse_kanjidic2(self.zip_with([])), [])


if __name__ == "__main__":
    unittest.main()
