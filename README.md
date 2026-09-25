# Kanji Lookup

An offline Japanese dictionary for the Omarchy bar, built from JMdict (English)
and KANJIDIC2. Look up selected text, type a word, or capture it from the screen.

The panel shows the word's constituent kanji in a compact horizontal strip,
then emphasizes the focused word, its reading, and its full definition. Smaller
related entries underneath are clickable: selecting one makes it the focused
word and puts the previous word first in the related list. New searches reset
this browsing context. Partial searches and captured sentences show matching
entries to choose from rather than presenting a partial match as an exact word.
Kanji cards are clickable too. Use Tab to move through cards and entries,
Enter or Space to open one, and Escape to close the panel. Down from the search
field focuses the first related entry; Up and Down move through that list.

Kanji cards include meanings, on/kun readings, and estimated JLPT levels when
available. Hover for full details when a card's text is shortened. Levels come
from community study lists, not an official modern JLPT syllabus; see
[data sources and attribution](resources/README.md). Missing levels are omitted.

## Build the DB

    ./scripts/build-db.py

Fetches the latest `scriptin/jmdict-simplified` release (jmdict-eng +
kanjidic2-en JSON zips) into `~/.local/share/kanji-lookup/src/` (re-runnable:
already-downloaded zips are skipped) and writes
`~/.local/share/kanji-lookup/jmdict.db`.
Definitions are stored in full. Run the builder again after upgrading an older
database to replace definitions that were previously limited to 400 characters.

## Look up

The CLI and the panel share one JSON interface (Python 3 standard library only):

    python3 scripts/lookup-json.py 敬語
    python3 scripts/lookup-json.py 敬語 --entry-id ENTRY_ID

It returns the focused entry, constituent kanji, and related entries with stable
JMdict IDs. The optional entry ID selects a particular dictionary entry even
when several entries have the same spelling. Related words are found by literal
text matches and shared kanji; sentence fallback finds embedded dictionary
words, without morphological analysis. Lookups and the bundled JLPT estimates
work entirely offline once the dictionary has been built.

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

A keybind can call `smartTrigger PRIMARY CLIPBOARD` instead: it looks up the
freshest text source when that source changed within the last 5 seconds;
otherwise the panel opens and a region-OCR capture starts immediately (Capture
always forces OCR). Wayland keeps old selection content forever, so recency —
not emptiness — distinguishes a fresh pick. Apps that do not publish a primary
selection may still work after Ctrl+C, through the regular clipboard. The
keybind should read both values as text:

    P="$(timeout 0.5s wl-paste --type text --primary 2>/dev/null)"
    C="$(timeout 0.5s wl-paste --type text 2>/dev/null)"
    omarchy-shell io.github.expri-commits.kanji-lookup smartTrigger "$P" "$C"

The plugin does not assign a keybind. The panel's shortcut hint reads
the current Hyprland bindings when the panel starts or opens, so it follows
custom keybinds automatically. For example, add this in
`~/.config/hypr/bindings.lua` to bind Super+Shift+K:

    o.bind("SUPER + SHIFT + K", "Kanji lookup", [[
      P="$(timeout 0.5s wl-paste --type text --primary 2>/dev/null)"; \
      C="$(timeout 0.5s wl-paste --type text 2>/dev/null)"; \
      omarchy-shell io.github.expri-commits.kanji-lookup smartTrigger "$P" "$C"
    ]])

The hint recognizes the plugin's `smartTrigger`, `lookup`, `open`, `show`, or
`toggle` binding, preferring `smartTrigger`. It skips mouse bindings, numeric
keycodes, non-empty submaps, and modifier bits it cannot display; named keys
such as F8 and Return are shown as readable labels. Lua callbacks are
recognized by the exact description `Kanji lookup`; arbitrary shell wrappers
may need a display-only `shortcutHint` override on their existing bar entry in
`~/.config/omarchy/shell.json`:

```json
{ "id": "io.github.expri-commits.kanji-lookup", "shortcutHint": "Super+Shift+K" }
```

This changes only the displayed hint; it does not create or change a binding.
If detection fails and no override is set, the footer says "No shortcut detected".

The Capture button in the panel OCRs kanji off the screen into the search field;
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
