# kotoba

Offline Japanese dictionary data layer for an Omarchy plugin: a SQLite DB
built from JMdict (English) and KANJIDIC2, plus a tiny lookup CLI that a QML
panel parses as TSV.

## Build the DB

    ./scripts/build-db.py

Fetches the latest `scriptin/jmdict-simplified` release (jmdict-eng +
kanjidic2-en JSON zips) into `~/.local/share/kotoba/src/` (re-runnable:
already-downloaded zips are skipped) and writes
`~/.local/share/kotoba/jmdict.db`.

## Look up

    ./scripts/lookup.sh QUERY        # e.g. QUERY = 大学

Word results print as `kanji<TAB>reading<TAB>glosses` (max 25 rows). If QUERY
is a single kanji, output starts with `##KANJI`, one
`char<TAB>meanings<TAB>on<TAB>kun<TAB>strokes<TAB>grade` row, then `##WORDS`
before the word rows. Exit 0 with no output when nothing matches; prints
`DB_MISSING` and exits 2 when the database has not been built yet.

## Plugin

Bar widget + popup panel for the Omarchy shell. Install and enable:

    rsync -a --exclude .git --exclude '*.db' ~/Documents/Projects/kotoba/ \
      ~/.config/omarchy/plugins/io.github.expri-commits.kotoba/
    omarchy plugin validate ~/.config/omarchy/plugins/io.github.expri-commits.kotoba
    omarchy-shell shell rescanPlugins
    omarchy plugin enable io.github.expri-commits.kotoba
    omarchy bar move io.github.expri-commits.kotoba --section right

(or `omarchy plugin add <repo-url>` once published.) Lookups work from the
bar button or over IPC — bar widgets are reached directly, not via
`shell call`:

    omarchy-shell io.github.expri-commits.kotoba lookup "$(wl-paste)"

The 撮 button in the panel OCRs kanji off the screen into the search field;
it needs the Japanese tesseract data:

    omarchy pkg add tesseract-data-jpn tesseract-data-jpn_vert

## License

JMdict and KANJIDIC2 are © EDRDG, licensed CC BY-SA 4.0 — see LICENSE-EDRDG
(https://www.edrdg.org/edrdg/licence.html).
