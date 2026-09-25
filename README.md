# Kanji Lookup

Offline Japanese dictionary data layer for an Omarchy plugin: a SQLite DB
built from JMdict (English) and KANJIDIC2, plus a tiny lookup CLI that a QML
panel parses as TSV.

## Build the DB

    ./scripts/build-db.py

Fetches the latest `scriptin/jmdict-simplified` release (jmdict-eng +
kanjidic2-en JSON zips) into `~/.local/share/kanji-lookup/src/` (re-runnable:
already-downloaded zips are skipped) and writes
`~/.local/share/kanji-lookup/jmdict.db`.

## Look up

    ./scripts/lookup.sh QUERY        # e.g. QUERY = 大学

Word results print as `kanji<TAB>reading<TAB>glosses` (max 25 rows). If QUERY
is a single kanji, output starts with `##KANJI`, one
`char<TAB>meanings<TAB>on<TAB>kun<TAB>strokes<TAB>grade` row, then `##WORDS`
before the word rows. Exit 0 with no output when nothing matches; prints
`DB_MISSING` and exits 2 when the database has not been built yet.

## Plugin

Bar widget + popup panel for the Omarchy shell. Install and enable:

    rsync -a --exclude .git --exclude '*.db' ~/Documents/Projects/kanji-lookup/ \
      ~/.config/omarchy/plugins/io.github.expri-commits.kanji-lookup/
    omarchy plugin validate ~/.config/omarchy/plugins/io.github.expri-commits.kanji-lookup
    omarchy-shell shell rescanPlugins
    omarchy plugin enable io.github.expri-commits.kanji-lookup
    omarchy bar move io.github.expri-commits.kanji-lookup --section right

(or `omarchy plugin add <repo-url>` once published.) Lookups work from the
bar button or over IPC — bar widgets are reached directly, not via
`shell call`:

    omarchy-shell io.github.expri-commits.kanji-lookup lookup "$(wl-paste)"

A keybind can call `smartTrigger QUERY` instead: when the primary selection
or clipboard changed within the last 5 seconds, QUERY is looked up directly;
otherwise the panel opens and a region-OCR capture starts immediately (撮
always forces OCR). Wayland keeps old selection content forever, so recency —
not emptiness — is what distinguishes a fresh pick. Apps that never publish a
primary selection (many Electron ones): Ctrl+C first; the clipboard watcher
timestamps that change too.

    omarchy-shell io.github.expri-commits.kanji-lookup smartTrigger "$(wl-paste --primary)"

The 撮 button in the panel OCRs kanji off the screen into the search field;
it needs the Japanese tesseract data:

    omarchy pkg add tesseract-data-jpn tesseract-data-jpn_vert

ocr.sh passes `KANJI_LOOKUP_OCR_LANGS` to tesseract `-l` (default
`jpn+jpn_vert`; if the variable is unset and `jpn_vert` data is missing, it
warns and falls back to `jpn`).

OCR keeps confident readings from the original capture. For uncertain readings,
it uses ImageMagick (already included in Omarchy) to separate bright subtitle
strokes from their outlines/background, enlarge them, and retry Tesseract.
Compact selections also get a word-segmentation retry to keep kanji radicals
together. The result with the highest recognition confidence is used; no extra
models or packages are downloaded. Without ImageMagick, original-image OCR still
works. Select the complete character with a little space around it, and pause
videos before selecting.

The preprocessing follows Tesseract's
[image-quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).
Recognition is still imperfect on stylized text or when a selection clips strokes.

Run the launcher and screenshot regression tests with:

    python3 -m unittest discover -s tests -v

The image tests use the existing local Tesseract Japanese data and ImageMagick;
they skip if these are unavailable and never install dependencies.

## License

JMdict and KANJIDIC2 are © EDRDG, licensed CC BY-SA 4.0 — see LICENSE-EDRDG
(https://www.edrdg.org/edrdg/licence.html).
