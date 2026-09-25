"""scripts/lookup.sh TSV contract: queries run end-to-end against a tiny
fixture DB built with the real sqlite3 CLI, mirroring the schema build-db.py
writes and the TSV layout Panel.qml's parseResult consumes."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


LOOKUP_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lookup.sh"

# The CREATE TABLE statements are copied from scripts/build-db.py (lines 139-141,
# the only schema definition); the rows cover every lookup.sh branch.
FIXTURE_SQL = """\
CREATE TABLE words(id INTEGER PRIMARY KEY, kanji TEXT, reading TEXT, glosses TEXT);
CREATE TABLE kanji(char TEXT PRIMARY KEY, meanings TEXT, "on" TEXT, kun TEXT,
                   strokes INTEGER, grade INTEGER);
INSERT INTO words VALUES
  (1, '読む', 'よむ;ヨム', 'to read | to read (aloud)'),
  (2, '読書', 'どくしょ', 'reading'),
  (3, '桜', 'さくら;サクラ', 'cherry blossom | cherry tree'),
  (4, '桜並木', 'さくらなみき', 'road lined with cherry trees'),
  (5, '日本語', 'にほんご', 'Japanese language'),
  (6, '勉強', 'べんきょう', 'study'),
  (7, '話す', 'はなす', 'to speak'),
  (8, '寿司', 'すし', 'sushi' || char(10) || 'vinegar rice' || char(9) || 'with fish'),
  (9, '', 'なにか', 'something');
INSERT INTO kanji VALUES
  ('桜', 'cherry blossom', 'サク', 'さくら', 10, 1),
  ('読', 'read', 'ドク', 'よ.む', 14, NULL);
"""


def utf8_env(**overrides):
    # The single-kanji detection needs a UTF-8 locale (${#1} counts characters,
    # printf '%x' the codepoint); under C it sees bytes and never fires.
    env = dict(os.environ, **overrides)
    if "UTF-8" not in "".join(env.get(k, "") for k in ("LC_ALL", "LC_CTYPE", "LANG")):
        env["LC_ALL"] = "C.UTF-8"
    return env


class LookupQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("sqlite3"):
            raise unittest.SkipTest("uses the sqlite3 CLI; installs nothing")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "jmdict.db"
        subprocess.run(["sqlite3", str(self.db)], input=FIXTURE_SQL, text=True,
                       capture_output=True, check=True)

    def run_lookup(self, query, db=None):
        env = utf8_env(KANJI_LOOKUP_DB=str(db or self.db))
        try:
            return subprocess.run(["bash", str(LOOKUP_SCRIPT), query], env=env,
                                  capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            self.fail(f"lookup.sh hung on {query!r}")

    def test_exact_word_query_returns_three_column_tsv(self):
        # Exact stdout pins the column order term<TAB>reading<TAB>glosses and
        # the ';'-joined first tokens that Panel.qml's parseResult splits on.
        result = self.run_lookup("読む")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout, "読む\tよむ;ヨム\tto read | to read (aloud)\n")

    def test_reading_only_entry_shows_reading_as_term(self):
        # COALESCE(NULLIF(kanji, ''), reading): an empty kanji column falls
        # back to the reading in the first output column.
        result = self.run_lookup("なにか")
        self.assertEqual(result.stdout, "なにか\tなにか\tsomething\n")

    def test_single_kanji_query_returns_kanji_then_words_sections(self):
        result = self.run_lookup("桜")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout,
                         "##KANJI\n"
                         "桜\tcherry blossom\tサク\tさくら\t10\t1\n"
                         "##WORDS\n"
                         "桜\tさくら;サクラ\tcherry blossom | cherry tree\n"
                         "桜並木\tさくらなみき\troad lined with cherry trees\n")

    def test_kanji_row_with_null_grade_keeps_six_columns(self):
        # NULL renders as empty and the separator is still emitted, so the row
        # keeps a trailing tab — parseResult reads grade as "".
        result = self.run_lookup("読")
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "##KANJI")
        self.assertEqual(lines[1], "読\tread\tドク\tよ.む\t14\t")
        self.assertEqual(lines[2], "##WORDS")
        self.assertEqual(sorted(lines[3:]),
                         ["読む\tよむ;ヨム\tto read | to read (aloud)",
                          "読書\tどくしょ\treading"])

    def test_kanji_absent_from_kanji_table_emits_bare_header(self):
        # A single CJK char missing from the kanji table still gets ##KANJI,
        # with no row between the markers (parseResult mints no card for it).
        result = self.run_lookup("勉")
        self.assertEqual(result.stdout, "##KANJI\n##WORDS\n勉強\tべんきょう\tstudy\n")

    def test_like_wildcards_match_nothing(self):
        # % and _ are escaped with ESCAPE '\': a query containing them must
        # match literally, not everything.
        for query in ("%", "_", "読_"):
            with self.subTest(query=query):
                result = self.run_lookup(query)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, "", ""))

    def test_glosses_newlines_and_tabs_are_flattened(self):
        # Gloss text is flattened onto one line so the row stays single-line TSV.
        result = self.run_lookup("寿司")
        self.assertEqual(result.stdout, "寿司\tすし\tsushi vinegar rice with fish\n")

    def test_long_sentence_falls_back_to_embedded_words_longest_first(self):
        # No direct match and >4 chars: words embedded in the sentence come
        # back ordered by their first kanji token's length, longest first.
        result = self.run_lookup("日本語を勉強しています")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout,
                         "日本語\tにほんご\tJapanese language\n"
                         "勉強\tべんきょう\tstudy\n")

    def test_long_query_falls_back_on_reading_match(self):
        result = self.run_lookup("きれいにはなす")
        self.assertEqual(result.stdout, "話す\tはなす\tto speak\n")

    def test_no_match_returns_nothing_and_exits_zero(self):
        result = self.run_lookup("存在しない言葉")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        # A single kanji with no hits keeps the empty section markers.
        result = self.run_lookup("鰐")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, "##KANJI\n##WORDS\n", ""))


class LookupErrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # lookup.sh checks DB_MISSING before usage and empty-query handling,
        # so these tests need an existing (empty) DB file to reach their paths.
        self.db = Path(self.tmp.name) / "empty.db"
        self.db.touch()

    def run_lookup(self, *args, db):
        try:
            return subprocess.run(["bash", str(LOOKUP_SCRIPT), *args],
                                  env=utf8_env(KANJI_LOOKUP_DB=db),
                                  capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            self.fail(f"lookup.sh hung with db {db!r}")

    def test_missing_db_reports_db_missing_with_exit_two(self):
        result = self.run_lookup("桜", db=str(self.tmp.name) + "/absent.db")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, "DB_MISSING\n", ""))

    def test_wrong_argument_count_prints_usage_and_exits_one(self):
        result = self.run_lookup(db=str(self.db))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, "", "usage: lookup.sh QUERY\n"))

    def test_empty_query_exits_zero_without_output(self):
        result = self.run_lookup("", db=str(self.db))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
