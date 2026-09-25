#!/usr/bin/env python3
"""Return one offline dictionary lookup as JSON for the QML panel.

Usage: python3 lookup-json.py QUERY [--entry-id ID]
The database is the one built by build-db.py, or KANJI_LOOKUP_DB when set.
"""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import unicodedata
from urllib.parse import quote


RESULT_LIMIT = 25
CANDIDATE_LIMIT = 500


def alternatives(value):
    return [part for part in (value or "").split(";") if part]


def is_ideograph(char):
    return unicodedata.name(char, "").startswith((
        "CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"
    ))


def ideographs(text):
    """Distinct defined CJK ideographs, including supplementary extensions."""
    return list(dict.fromkeys(char for char in text if is_ideograph(char)))


def fix_one_vs_prolonged(query):
    """OCR swaps kanji 一 and the look-alike prolonged-sound mark ー (ー生懸命,
    ラ一メン). Context-blind — legitimate words keep them adjacent too (コーヒー豆,
    一ヶ月) — so only trust the variant when it matches the dictionary and the
    original does not."""
    out = []
    for i, char in enumerate(query):
        near = [query[j] for j in (i - 1, i + 1) if 0 <= j < len(query)]
        if char == "ー" and any(is_ideograph(c) for c in near):
            out.append("一")
        elif char == "一" and any(
                unicodedata.name(c, "").startswith("KATAKANA") for c in near):
            out.append("ー")
        else:
            out.append(char)
    return "".join(out)


def like_literal(text):
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def empty_result(query):
    return {"query": query, "matchKind": "none", "main": None,
            "kanji": [], "related": []}


def load_jlpt_levels():
    """Optional modern JLPT estimates, independent of KANJIDIC grade."""
    path = Path(__file__).resolve().parents[1] / "resources" / "jlpt-levels.json"
    try:
        with path.open(encoding="utf-8") as source:
            levels = json.load(source)
    except (OSError, ValueError):
        return {}
    if not isinstance(levels, dict):
        return {}
    return {char: level for char, level in levels.items()
            if isinstance(char, str) and len(char) == 1
            and type(level) is int and 1 <= level <= 5}


class KanjiResolver:
    def __init__(self, con):
        self.con = con
        self.cache = {}
        self.jlpt_levels = load_jlpt_levels()

    def one(self, char):
        if char not in self.cache:
            row = self.con.execute(
                'SELECT char, meanings, "on", kun, strokes, grade FROM kanji WHERE char = ?',
                (char,),
            ).fetchone()
            if row is None:
                self.cache[char] = {
                    "char": char, "meanings": "", "on": "", "kun": "",
                    "strokes": None, "grade": None, "jlpt": self.jlpt_levels.get(char),
                    "unavailable": True,
                }
            else:
                self.cache[char] = {
                    "char": row["char"], "meanings": row["meanings"] or "",
                    "on": row["on"] or "", "kun": row["kun"] or "",
                    "strokes": row["strokes"], "grade": row["grade"],
                    "jlpt": self.jlpt_levels.get(char),
                }
        return self.cache[char]

    def in_text(self, text):
        return [self.one(char) for char in ideographs(text)]


def word_object(row, query, resolver):
    spellings = alternatives(row["kanji"])
    readings = alternatives(row["reading"])
    term = query if query in spellings else (spellings[0] if spellings else
                                             (query if query in readings else
                                              (readings[0] if readings else "")))
    reading = query if query in readings else (readings[0] if readings else "")
    return {
        "id": str(row["id"]), "term": term, "reading": reading,
        "glosses": row["glosses"] or "", "spellings": spellings,
        "readings": readings, "kanji": resolver.in_text(term),
    }


def find_exact(con, query):
    rows = con.execute(
        """SELECT id, kanji, reading, glosses FROM words
           WHERE instr(';' || COALESCE(kanji, '') || ';', ';' || ? || ';') > 0
              OR instr(';' || COALESCE(reading, '') || ';', ';' || ? || ';') > 0
           ORDER BY CASE WHEN instr(';' || COALESCE(kanji, '') || ';',
                                    ';' || ? || ';') > 0 THEN 0 ELSE 1 END, id
           LIMIT ?""",
        (query, query, query, CANDIDATE_LIMIT),
    ).fetchall()
    # The WHERE clause guarantees every row is a whole-alternative match and the
    # ORDER BY puts kanji matches before reading matches, then id — rows[0]
    # is the best exact match.
    return rows[0] if rows else None


def direct_rank(row, query):
    spellings = alternatives(row["kanji"])
    readings = alternatives(row["reading"])
    if query in spellings:
        return (0, len(query), row["id"])
    if query in readings:
        return (1, len(query), row["id"])
    lengths = [len(part) for part in spellings + readings if query in part]
    return (2, min(lengths), row["id"]) if lengths else None


def find_direct(con, query, exclude_id=None):
    # SQL limits the scan result; Python verifies whole alternatives, so a
    # substring spanning a semicolon cannot appear as a dictionary match.
    pattern = like_literal(query)
    rows = con.execute(
        """SELECT id, kanji, reading, glosses FROM words
           WHERE kanji LIKE ? ESCAPE '\\' OR reading LIKE ? ESCAPE '\\'
           ORDER BY CASE
             WHEN instr(';' || COALESCE(kanji, '') || ';', ';' || ? || ';') > 0 THEN 0
             WHEN instr(';' || COALESCE(reading, '') || ';', ';' || ? || ';') > 0 THEN 1
             ELSE 2 END,
             length(COALESCE(kanji, '')) + length(COALESCE(reading, '')), id
           LIMIT ?""",
        (pattern, pattern, query, query, CANDIDATE_LIMIT),
    ).fetchall()
    ranked = [(direct_rank(row, query), row) for row in rows if row["id"] != exclude_id]
    ranked = [(rank, row) for rank, row in ranked if rank is not None]
    ranked.sort(key=lambda pair: pair[0])
    return [row for _, row in ranked[:RESULT_LIMIT]]


def find_embedded(con, query):
    """OCR sentence fallback: find dictionary forms literally inside query."""
    ranked = []
    for row in con.execute("SELECT id, kanji, reading, glosses FROM words WHERE kanji != ''"):
        spellings = alternatives(row["kanji"])
        # Ignore one-character entries, as the existing TSV lookup does.
        if not spellings or len(spellings[0]) < 2:
            continue
        spelling_matches = [part for part in spellings if len(part) >= 2 and part in query]
        reading_matches = [part for part in alternatives(row["reading"])
                           if len(part) >= 2 and part in query]
        if spelling_matches:
            ranked.append(((0, -max(map(len, spelling_matches)), row["id"]), row))
        elif reading_matches:
            ranked.append(((1, -max(map(len, reading_matches)), row["id"]), row))
    ranked.sort(key=lambda pair: pair[0])
    return [row for _, row in ranked[:RESULT_LIMIT]]


def append_unseen(target, candidates, seen):
    for row in candidates:
        if len(target) >= RESULT_LIMIT:
            break
        if row["id"] not in seen:
            target.append(row)
            seen.add(row["id"])


def fill_shared_kanji(con, term, seen, remaining):
    chars = ideographs(term)
    if not chars or remaining <= 0:
        return []
    # This runs only for a focused entry and keeps candidate materialization
    # bounded even for common characters with thousands of compounds.
    where = " OR ".join("kanji LIKE ? ESCAPE '\\'" for _ in chars)
    score = " + ".join("(CASE WHEN kanji LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END)"
                       for _ in chars)
    patterns = [like_literal(char) for char in chars]
    rows = con.execute(
        f"""SELECT id, kanji, reading, glosses FROM words WHERE {where}
            ORDER BY ({score}) DESC,
                     length(COALESCE(kanji, '')) + length(COALESCE(reading, '')), id
            LIMIT ?""",
        patterns + patterns + [CANDIDATE_LIMIT],
    ).fetchall()
    wanted = set(chars)
    ranked = []
    for row in rows:
        if row["id"] in seen:
            continue
        spellings = alternatives(row["kanji"])
        shared_lengths = [(len(set(ideographs(part)) & wanted), len(part))
                          for part in spellings]
        shares = max((count for count, _ in shared_lengths), default=0)
        if shares:
            shortest = min(length for count, length in shared_lengths if count == shares)
            ranked.append(((-shares, shortest, row["id"]), row))
    ranked.sort(key=lambda pair: pair[0])
    return [row for _, row in ranked[:remaining]]


def lookup(con, query, entry_id=None):
    result = empty_result(query)
    if not query:
        return result
    resolver = KanjiResolver(con)
    if entry_id is not None:
        main_row = con.execute(
            "SELECT id, kanji, reading, glosses FROM words WHERE id = ?", (entry_id,)
        ).fetchone()
        if main_row is None:
            result["kanji"] = resolver.in_text(query)
            return result
    else:
        main_row = find_exact(con, query)
        if main_row is None:
            variant = fix_one_vs_prolonged(query)
            if variant != query:
                candidate = find_exact(con, variant)
                if candidate is not None:
                    query = variant
                    main_row = candidate

    if main_row is not None:
        main = word_object(main_row, query, resolver)
        is_reading_match = (entry_id is None and query not in main["spellings"]
                            and query in main["readings"])
        result["matchKind"] = "reading" if is_reading_match else "exact"
        result["main"] = main
        result["kanji"] = main["kanji"]
        focus = main["term"]
        related = []
        seen = {main_row["id"]}
        if entry_id is None:
            # Reading homophones need not share any character with main.term.
            homophones = [row for row in find_direct(con, query, main_row["id"])
                          if query in alternatives(row["reading"])]
            append_unseen(related, homophones, seen)
        append_unseen(related, find_direct(con, focus, main_row["id"]), seen)
        if len(related) < RESULT_LIMIT:
            append_unseen(related, fill_shared_kanji(
                con, focus, seen, RESULT_LIMIT - len(related)), seen)
    else:
        result["kanji"] = resolver.in_text(query)
        related = find_direct(con, query)
        if related:
            result["matchKind"] = "partial"
        elif len(query) > 4:
            related = find_embedded(con, query)
            if related:
                result["matchKind"] = "embedded"

    result["related"] = []
    for row in related:
        original_rank = direct_rank(row, query)
        display_query = (query if original_rank is not None and original_rank[0] < 2
                         else (focus if main_row else query))
        result["related"].append(word_object(row, display_query, resolver))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", metavar="QUERY")
    parser.add_argument("--entry-id", metavar="ID")
    args = parser.parse_args()
    if not args.query:
        print(json.dumps(empty_result(args.query), ensure_ascii=False,
                         separators=(",", ":")))
        return 0
    db = os.environ.get("KANJI_LOOKUP_DB") or os.path.expanduser(
        "~/.local/share/kanji-lookup/jmdict.db")
    if not os.path.isfile(db):
        print("DB_MISSING", file=sys.stderr)
        return 2
    try:
        # Read-only mode prevents SQLite from making an empty DB for a typo.
        con = sqlite3.connect("file:" + quote(os.path.abspath(db)) + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            result = lookup(con, args.query, args.entry_id)
        finally:
            con.close()
    except sqlite3.Error as exc:
        print(f"kanji-lookup: database error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
