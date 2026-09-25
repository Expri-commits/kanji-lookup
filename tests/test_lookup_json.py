"""End-to-end JSON lookup tests against the build-db.py SQLite schema."""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lookup-json.py"

WORDS = [
    (1, "読む;讀む", "よむ;ヨム", "to read"),
    (2, "読書", "どくしょ", "reading"),
    (3, "桜", "さくら;サクラ", "cherry blossom"),
    (4, "桜並木", "さくらなみき", "cherry-lined road"),
    (5, "日本語", "にほんご", "Japanese language"),
    (6, "勉強", "べんきょう", "study"),
    (7, "話す", "はなす", "to speak"),
    (8, "", "なにか;ナニカ", "something"),
    (9, "漢字;汉字", "かんじ;カンジ", "kanji"),
    (10, "漢語", "かんご", "Sino-Japanese word"),
    (11, "漢字", "かんじ", "Chinese character"),
    (12, "日本", "にほん", "Japan"),
    (13, "語学", "ごがく", "language study"),
    (14, "学校学", "がっこうがく", "school study"),
    (15, "𠀀野;𠀀原", "あらの", "field"),
    (16, "はなす", "ハナス", "phonetic spelling"),
    (17, "100%完成", "ひゃくぱーせんとかんせい", "complete"),
    (18, "読_本", "よみほん", "literal underscore"),
    (19, "詠む", "ヨム;よむ", "to recite"),
    (20, "使丁", "してい", "reading-only sentence distractor"),
]
KANJI = [
    ("読", "read;reading", "ドク", "よ.む", 14, None),
    ("桜", "cherry blossom", "オウ", "さくら", 10, 1),
    ("日", "day", "ニチ", "ひ", 4, 1),
    ("本", "book", "ホン", "もと", 5, 1),
    ("語", "language", "ゴ", "かた.る", 14, 2),
    ("漢", "Chinese", "カン", "", 13, 3),
    ("字", "character", "ジ", "あざ", 6, 1),
    ("学", "study", "ガク", "まな.ぶ", 8, 1),
    ("𠀀", "first CJK extension B", "", "", 1, None),
]


class JsonLookupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "jmdict.db"
        con = sqlite3.connect(self.db)
        con.executescript(
            'CREATE TABLE words(id INTEGER PRIMARY KEY, kanji TEXT, reading TEXT, glosses TEXT);'
            'CREATE TABLE kanji(char TEXT PRIMARY KEY, meanings TEXT, "on" TEXT, kun TEXT,'
            ' strokes INTEGER, grade INTEGER);'
        )
        con.executemany("INSERT INTO words VALUES (?,?,?,?)", WORDS)
        con.executemany("INSERT INTO kanji VALUES (?,?,?,?,?,?)", KANJI)
        con.commit()
        con.close()

    def run_lookup(self, query, *args, db=None, script=SCRIPT):
        env = dict(os.environ, KANJI_LOOKUP_DB=str(db if db is not None else self.db))
        return subprocess.run([sys.executable, str(script), query, *args],
                              env=env, text=True, capture_output=True, timeout=10)

    def result(self, query, *args):
        proc = self.run_lookup(query, *args)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""), proc.stdout)
        return json.loads(proc.stdout)

    def test_exact_multi_kanji_word_keeps_metadata_and_alternatives(self):
        data = self.result("日本語")
        self.assertEqual((data["query"], data["matchKind"]), ("日本語", "exact"))
        self.assertEqual(data["main"]["id"], "5")
        self.assertEqual(data["main"]["term"], "日本語")
        self.assertEqual(data["main"]["reading"], "にほんご")
        self.assertEqual(data["main"]["spellings"], ["日本語"])
        self.assertEqual(data["main"]["readings"], ["にほんご"])
        self.assertEqual([k["char"] for k in data["kanji"]], ["日", "本", "語"])
        self.assertEqual(data["kanji"], data["main"]["kanji"])
        self.assertEqual((data["kanji"][0]["strokes"], data["kanji"][0]["grade"]),
                         (4, 1))
        self.assertIn("jlpt", data["kanji"][0])
        self.assertEqual(data["kanji"][0]["jlpt"], 5)
        self.assertEqual([w["id"] for w in data["related"][:2]], ["12", "10"])
        self.assertEqual([k["char"] for k in data["related"][0]["kanji"]], ["日", "本"])

    def test_alternate_spelling_and_reading_are_exact(self):
        spelling = self.result("讀む")
        self.assertEqual(spelling["main"]["term"], "讀む")
        self.assertEqual(spelling["main"]["spellings"], ["読む", "讀む"])
        self.assertTrue(spelling["kanji"][0]["unavailable"])
        reading = self.result("ヨム")
        self.assertEqual(reading["matchKind"], "reading")
        self.assertEqual(reading["main"]["term"], "読む")
        self.assertEqual(reading["main"]["reading"], "ヨム")
        self.assertEqual(reading["main"]["readings"], ["よむ", "ヨム"])
        homophones = self.result("よむ")
        self.assertEqual(homophones["matchKind"], "reading")
        self.assertEqual(homophones["related"][0]["id"], "19")
        self.assertEqual(homophones["related"][0]["reading"], "よむ")

    def test_exact_spelling_precedes_reading_and_homonym_id_is_stable(self):
        spelling = self.result("はなす")
        self.assertEqual(spelling["main"]["id"], "16")
        homonyms = self.result("漢字")
        self.assertEqual(homonyms["main"]["id"], "9")
        self.assertEqual(homonyms["related"][0]["id"], "11")

    def test_selected_entry_id_is_authoritative_and_uses_its_term(self):
        selected = self.result("かんじ", "--entry-id", "11")
        self.assertEqual((selected["matchKind"], selected["main"]["id"]),
                         ("exact", "11"))
        self.assertEqual(selected["main"]["term"], "漢字")
        self.assertEqual(selected["related"][0]["id"], "9")
        selected_alternate = self.result("汉字", "--entry-id", "9")
        self.assertEqual(selected_alternate["main"]["term"], "汉字")
        self.assertEqual([k["char"] for k in selected_alternate["kanji"]], ["汉", "字"])
        invalid = self.result("漢字", "--entry-id", "999999")
        self.assertEqual((invalid["matchKind"], invalid["main"], invalid["related"]),
                         ("none", None, []))

    def test_partial_query_has_no_main_and_word_kanji_is_ready(self):
        data = self.result("桜並")
        self.assertEqual((data["matchKind"], data["main"]), ("partial", None))
        self.assertEqual([k["char"] for k in data["kanji"]], ["桜", "並"])
        self.assertTrue(data["kanji"][1]["unavailable"])
        self.assertEqual(data["related"][0]["term"], "桜並木")
        self.assertEqual([k["char"] for k in data["related"][0]["kanji"]],
                         ["桜", "並", "木"])

    def test_kana_only_and_reading_only_entry(self):
        kana = self.result("なにか")
        self.assertEqual(kana["matchKind"], "reading")
        self.assertEqual(kana["main"]["term"], "なにか")
        self.assertEqual(kana["main"]["reading"], "なにか")
        self.assertEqual(kana["main"]["spellings"], [])
        self.assertEqual(kana["kanji"], [])
        self.assertEqual(self.result("ナニカ")["main"]["term"], "ナニカ")

    def test_distinct_kanji_and_supplementary_plane(self):
        duplicate = self.result("学校学")
        self.assertEqual([k["char"] for k in duplicate["kanji"]], ["学", "校"])
        supplementary = self.result("𠀀原")
        self.assertEqual([k["char"] for k in supplementary["kanji"]], ["𠀀", "原"])
        self.assertEqual(supplementary["kanji"][0]["meanings"],
                         "first CJK extension B")
        self.assertTrue(supplementary["kanji"][1]["unavailable"])

    def test_embedded_sentence_fallback_uses_longest_words_first(self):
        data = self.result("日本語を勉強しています")
        self.assertEqual((data["matchKind"], data["main"]), ("embedded", None))
        self.assertEqual([w["id"] for w in data["related"][:2]], ["5", "6"])
        kana_sentence = self.result("きれいにはなす")
        self.assertEqual(kana_sentence["related"][0]["id"], "16")
        self.assertIn("7", [word["id"] for word in kana_sentence["related"]])

    def test_wildcards_and_quotes_are_literal(self):
        for query in ("桜%", "' OR 1=1 --", "\\"):
            with self.subTest(query=query):
                data = self.result(query)
                self.assertEqual((data["matchKind"], data["main"], data["related"]),
                                 ("none", None, []))
        self.assertEqual(self.result("100%")["related"][0]["id"], "17")
        self.assertEqual(self.result("読_")["related"][0]["id"], "18")

    def test_jlpt_resource_is_optional_and_values_are_validated(self):
        sandbox = self.db.parent / "standalone"
        scripts = sandbox / "scripts"
        resources = sandbox / "resources"
        scripts.mkdir(parents=True)
        script = scripts / "lookup-json.py"
        shutil.copy2(SCRIPT, script)

        missing = self.run_lookup("日本語", script=script)
        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertIsNone(json.loads(missing.stdout)["kanji"][2]["jlpt"])

        resources.mkdir()
        levels = resources / "jlpt-levels.json"
        levels.write_text('{"語":5,"敬":2,"日":"N5","本":true,"読":6}',
                          encoding="utf-8")
        mapped = self.run_lookup("日本語", script=script)
        self.assertEqual(mapped.returncode, 0, mapped.stderr)
        self.assertEqual([k["jlpt"] for k in json.loads(mapped.stdout)["kanji"]],
                         [None, None, 5])

        levels.write_text("{broken", encoding="utf-8")
        malformed = self.run_lookup("日本語", script=script)
        self.assertEqual(malformed.returncode, 0, malformed.stderr)
        self.assertEqual([k["jlpt"] for k in json.loads(malformed.stdout)["kanji"]],
                         [None, None, None])

    def test_empty_query_has_complete_empty_json(self):
        expected = {
            "query": "", "matchKind": "none", "main": None, "kanji": [], "related": []
        }
        self.assertEqual(self.result(""), expected)
        missing = self.run_lookup("", db=self.db.parent / "missing.db")
        self.assertEqual((missing.returncode, missing.stderr), (0, ""))
        self.assertEqual(json.loads(missing.stdout), expected)

    def test_query_starting_with_dash_works_after_option_separator(self):
        proc = self.run_lookup("--", "-unexpected")
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(json.loads(proc.stdout)["query"], "-unexpected")

    def test_missing_and_invalid_database_are_clean_errors(self):
        missing = self.run_lookup("桜", db=self.db.parent / "missing.db")
        self.assertEqual((missing.returncode, missing.stdout, missing.stderr),
                         (2, "", "DB_MISSING\n"))
        invalid_path = self.db.parent / "invalid.db"
        invalid_path.write_text("not sqlite", encoding="utf-8")
        invalid = self.run_lookup("桜", db=invalid_path)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(invalid.stdout, "")
        self.assertIn("database error", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
