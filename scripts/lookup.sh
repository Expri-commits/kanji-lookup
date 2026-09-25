#!/usr/bin/env bash
# Kanji Lookup offline dictionary — prints TSV for the QML panel.
# Usage: lookup.sh QUERY
#   word rows: kanji<TAB>reading<TAB>glosses              (max 25)
#   single CJK ideograph query adds:
#     ##KANJI
#     char<TAB>meanings<TAB>on<TAB>kun<TAB>strokes<TAB>grade
#     ##WORDS
# Empty result: no output, exit 0. Missing DB: "DB_MISSING", exit 2.
set -u

DB="${KANJI_LOOKUP_DB:-$HOME/.local/share/kanji-lookup/jmdict.db}"
[ -f "$DB" ] || { echo "DB_MISSING"; exit 2; }
[ $# -eq 1 ] || { echo "usage: lookup.sh QUERY" >&2; exit 1; }
[ -n "$1" ] || exit 0

# SQL string literal: escape single quotes (' -> '')
Q=${1//\'/\'\'}
# Same literal for LIKE patterns, with the LIKE wildcards \, % and _ escaped
# so they match literally; the matching LIKE clauses carry ESCAPE '\'.
L=${1//\\/\\\\}
L=${L//%/\\%}
L=${L//_/\\_}
L=${L//\'/\'\'}

# Single CJK ideograph detection (bash, not SQL). Needs a UTF-8 locale.
is_single_kanji=""
if [[ ${#1} -eq 1 ]]; then
  cp=$(printf '%x' "'$1" 2>/dev/null) || cp=""
  if [[ $cp =~ ^[0-9a-fA-F]+$ ]]; then
    cp=$((16#$cp))
    if (( (cp >= 0x3400 && cp <= 0x4dbf) || (cp >= 0x4e00 && cp <= 0x9fff) || \
          (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0x20000 && cp <= 0x3234f) )); then
      is_single_kanji=$1
    fi
  fi
fi

if [[ -n $is_single_kanji ]]; then
  echo "##KANJI"
  sqlite3 -batch -noheader -separator $'\t' "$DB" \
    "SELECT char, replace(replace(meanings, char(10), ' '), char(9), ' '), \"on\", kun, strokes, grade
     FROM kanji WHERE char = '${Q}';"
  echo "##WORDS"
fi

# Word-row column list, shared by both queries below.
COLS="COALESCE(NULLIF(kanji, ''), reading), reading,
replace(replace(glosses, char(10), ' '), char(9), ' ')"

words=$(sqlite3 -batch -noheader -separator $'\t' "$DB" \
  "SELECT $COLS
   FROM words
   WHERE kanji LIKE '%${L}%' ESCAPE '\\' OR reading LIKE '%${L}%' ESCAPE '\\'
   ORDER BY (';' || kanji || ';' LIKE '%;${L};%' ESCAPE '\\') DESC,
            (';' || reading || ';' LIKE '%;${L};%' ESCAPE '\\') DESC, length(kanji)
   LIMIT 25;")

# No exact match and the query is long: OCR'd sentence. Find dictionary words
# embedded anywhere in it (single chars excluded — the ##KANJI card covers those).
# ponytail: substring scan, not tokenization — misses conjugated/dictionary-form
# mismatches (食べて won't find 食べる); upgrade path is MeCab/sudachi if it annoys.
if [[ -z $words && ${#1} -gt 4 ]]; then
  words=$(sqlite3 -batch -noheader -separator $'\t' "$DB" \
    "SELECT $COLS
     FROM words
     WHERE length(substr(kanji, 1, instr(kanji || ';', ';') - 1)) >= 2
       AND (instr('${Q}', kanji) > 0
            OR instr('${Q}', substr(reading, 1, instr(reading || ';', ';') - 1)) > 0)
     ORDER BY length(substr(kanji, 1, instr(kanji || ';', ';') - 1)) DESC
     LIMIT 25;")
fi

[[ -n $words ]] && printf '%s\n' "$words"

exit 0
