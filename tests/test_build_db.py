"""Pure parsers of scripts/build-db.py: JMdict / KANJIDIC2 JSON -> DB rows,
fed from tiny one-file zips shaped like the jmdict-simplified releases."""

import importlib.util
import json
from pathlib import Path
import os
import random
import sqlite3
import tempfile
import time
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
        rows = list(build_db.parse_jmdict(self.zip_with([{
            "id": "1000010",
            "kanji": [{"text": "読む"}],
            "kana": [{"text": "よむ"}, {"text": "ヨム"}],
            "sense": [
                {"gloss": [{"text": "to read"}]},
                {"gloss": [{"text": "to peruse"}]},
                {"gloss": []},  # a sense without glosses contributes nothing
            ],
        }])))
        self.assertEqual(rows, [(1000010, "読む", "よむ;ヨム", "to read | to peruse")])

    def test_missing_optional_fields_become_empty_columns(self):
        # No kanji/kana arrays (reading-only entry); a numeric id works too.
        rows = list(build_db.parse_jmdict(self.zip_with([
            {"id": 2, "sense": [{"gloss": [{"text": "meaning"}]}]},
        ])))
        self.assertEqual(rows, [(2, "", "", "meaning")])

    def test_full_glosses_are_preserved_for_focused_word_details(self):
        rows = list(build_db.parse_jmdict(self.zip_with([
            {"id": 3, "sense": [{"gloss": [{"text": "x" * 500}]}]},
        ])))
        self.assertEqual(rows, [(3, "", "", "x" * 500)])

    def test_empty_dictionary_yields_no_rows(self):
        self.assertEqual(list(build_db.parse_jmdict(self.zip_with([]))), [])


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
        rows = list(build_db.parse_kanjidic2(self.zip_with([{
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
        }])))
        self.assertEqual(rows, [("桜", "cherry", "サク", "さくら", 10, 1)])

    def test_character_without_optional_fields(self):
        # No readingMeaning / misc at all: empty strings, NULL strokes and grade.
        rows = list(build_db.parse_kanjidic2(self.zip_with([{"literal": "丂"}])))
        self.assertEqual(rows, [("丂", "", "", "", None, None)])

    def test_empty_kanjidic_yields_no_rows(self):
        self.assertEqual(list(build_db.parse_kanjidic2(self.zip_with([]))), [])


class IterEntriesTests(unittest.TestCase):
    """iter_entries: streams the target top-level array element by element
    off the zip, aborting past the size cap instead of decompressing a bomb
    wholly into memory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._saved_chunk = build_db.READ_CHUNK
        self.addCleanup(lambda: setattr(build_db, "READ_CHUNK", self._saved_chunk))
        self._saved_cap = build_db.MAX_JSON_BYTES
        self.addCleanup(lambda: setattr(build_db, "MAX_JSON_BYTES", self._saved_cap))
        self._saved_entry_cap = build_db.MAX_ENTRY_BYTES
        self.addCleanup(
            lambda: setattr(build_db, "MAX_ENTRY_BYTES", self._saved_entry_cap))

    def zip_with(self, text):
        path = Path(self.tmp.name) / "dict.json.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("dict.json", text)
        return str(path)

    def test_target_array_is_not_the_first_key(self):
        doc = {"version": "1", "languages": ["eng"], "words": [{"id": 1}, {"id": 2}]}
        got = list(build_db.iter_entries(self.zip_with(json.dumps(doc)), "words"))
        self.assertEqual(got, doc["words"])

    def test_entry_strings_with_json_punctuation_and_escapes(self):
        entry = {"t": 'braces {} [ ] , : "quoted" back\\slash',
                 "nested": [1, {"x": ","}, "new\nline\ttab"]}
        got = list(build_db.iter_entries(
            self.zip_with(json.dumps({"words": [entry]})), "words"))
        self.assertEqual(got, [entry])

    def test_multibyte_characters_straddling_tiny_chunk_boundaries(self):
        build_db.READ_CHUNK = 7  # force every 3-byte kana / 4-byte 𠮷 to split
        entries = [{"j": "読む日本語、漢字とかな。"}, {"k": ["桜", "𠮷野"], "n": 12345}]
        got = list(build_db.iter_entries(
            self.zip_with(json.dumps({"version": "1", "words": entries})), "words"))
        self.assertEqual(got, entries)

    def test_entry_unpacking_past_cap_aborts(self):
        build_db.MAX_JSON_BYTES = 10
        with self.assertRaises(SystemExit):
            list(build_db.iter_entries(
                self.zip_with(json.dumps({"words": ["x" * 100]})), "words"))

    def test_single_entry_past_cap_aborts(self):
        # Chunk kept well under the cap so only the oversized element can
        # push the buffer past it, and the abort lands mid-accumulation.
        build_db.MAX_ENTRY_BYTES, build_db.READ_CHUNK = 64, 8
        with self.assertRaises(SystemExit):
            list(build_db.iter_entries(
                self.zip_with(json.dumps({"words": ["x" * 100]})), "words"))

    def test_many_small_entries_just_under_cap_parse(self):
        build_db.MAX_ENTRY_BYTES, build_db.READ_CHUNK = 64, 16
        entries = [{"id": n} for n in range(50)]  # ~10 bytes each
        got = list(build_db.iter_entries(
            self.zip_with(json.dumps({"words": entries})), "words"))
        self.assertEqual(got, entries)

    def test_missing_target_key_aborts(self):
        with self.assertRaises(SystemExit):
            list(build_db.iter_entries(
                self.zip_with(json.dumps({"version": "1"})), "words"))

    def test_empty_array_yields_nothing(self):
        got = list(build_db.iter_entries(self.zip_with('{"words": []}'), "words"))
        self.assertEqual(got, [])


class IterEntriesFuzzTests(unittest.TestCase):
    """Differential fuzz: iter_entries must equal json.loads on random docs,
    read through tiny chunks full of JSON punctuation and CJK."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._saved_chunk = build_db.READ_CHUNK
        self.addCleanup(lambda: setattr(build_db, "READ_CHUNK", self._saved_chunk))

    def test_random_entries_match_json_loads(self):
        rng = random.Random(20260927)
        alphabet = ['"', "\\", "{", "}", "[", "]", ",", ":", " ", "\n", "\t",
                    "読", "む", "日", "本", "語", "桜", "a", "b", "0"]

        def payload():
            return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 30)))

        def node(depth):
            pick = rng.randrange(8 if depth < 3 else 6)
            if pick == 0:
                return payload()
            if pick == 1:
                return rng.randrange(-10**6, 10**6)
            if pick == 2:
                return rng.random() * 10 ** rng.randrange(-3, 4)
            if pick == 3:
                return rng.choice([True, False])
            if pick == 4:
                return None
            if pick == 5:
                return [node(depth + 1) for _ in range(rng.randrange(0, 4))]
            return {payload(): node(depth + 1) for _ in range(rng.randrange(0, 4))}

        for _ in range(100):
            doc = {"version": "x",
                   "words": [node(0) for _ in range(rng.randrange(1, 6))]}
            path = Path(self.tmp.name) / "fuzz.json.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("fuzz.json", json.dumps(doc))
            build_db.READ_CHUNK = rng.choice([1, 2, 3, 7, 13])
            self.assertEqual(
                list(build_db.iter_entries(str(path), "words")), doc["words"],
                f"mismatch on doc: {json.dumps(doc)[:200]}")


class MainAtomicRebuildTests(unittest.TestCase):
    """main(): a zip that dies mid-insert (parsers stream lazily) must abort
    before the working DB is swapped out, leaving the old rows in place."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = Path(tmp.name) / "src"
        self.db = Path(tmp.name) / "jmdict.db"
        self.src.mkdir()
        saved = build_db.SRC, build_db.DB, build_db.asset_urls
        self.addCleanup(
            lambda: (setattr(build_db, "SRC", saved[0]),
                     setattr(build_db, "DB", saved[1]),
                     setattr(build_db, "asset_urls", saved[2])))
        build_db.SRC, build_db.DB = str(self.src), str(self.db)
        # No network: main() only needs urls whose basenames match the zips
        # written below, and download() skips existing files.
        build_db.asset_urls = lambda: [
            "https://example.invalid/jmdict-eng-test.json.zip",
            "https://example.invalid/kanjidic2-en-test.json.zip",
        ]
        self.jmdict = self.src / "jmdict-eng-test.json.zip"
        self.kanjidic = self.src / "kanjidic2-en-test.json.zip"

    def write_zip(self, path, text):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(path.name.replace(".zip", ""), text)

    def word_rows(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT id, glosses FROM words").fetchall()
        finally:
            con.close()

    def test_corrupt_zip_aborts_without_losing_previous_db(self):
        self.write_zip(self.jmdict, json.dumps(
            {"words": [{"id": "1", "sense": [{"gloss": [{"text": "ok"}]}]}]}))
        self.write_zip(self.kanjidic, json.dumps({"characters": [{"literal": "読"}]}))
        build_db.main()
        self.assertEqual(self.word_rows(), [(1, "ok")])
        self.assertFalse(Path(str(self.db) + ".tmp").exists())

        # "Corrupt" the jmdict zip: valid container, truncated JSON, so the
        # streaming parser dies mid-insert with the house SystemExit.
        self.write_zip(self.jmdict, '{"words": [{"id": "2"}, ')
        newer = time.time() + 10  # force rebuild: zips newer than the DB
        os.utime(self.jmdict, (newer, newer))
        os.utime(self.kanjidic, (newer, newer))
        with self.assertRaises(SystemExit):
            build_db.main()
        self.assertFalse(Path(str(self.db) + ".tmp").exists())
        self.assertEqual(self.word_rows(), [(1, "ok")])  # old DB untouched


if __name__ == "__main__":
    unittest.main()
