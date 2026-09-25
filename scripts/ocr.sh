#!/bin/bash
# Kanji Lookup OCR: recognize Japanese text for the dictionary search box.
#   scripts/ocr.sh            Interactive: select a region (slurp), capture it
#                             (grim), OCR with tesseract jpn, and print the
#                             cleaned text (newlines stripped, ASCII spaces
#                             collapsed) on one line to stdout.
#   scripts/ocr.sh --file P   Headless test mode: OCR image file P with the same
#                             recognition and cleaning rules.
# Exit codes: 0 ok (or user cancelled region); 1 no text recognized; 2 Japanese data missing.
# ponytail: no screen-freeze layer (hyprpicker/wayfreeze) on purpose — an
# interactive freeze layer under slurp has undefined stacking/input routing on
# Hyprland (ate Escape, ate the drag click). Pause videos instead; if a freeze
# is ever wanted, wayfreeze --enable-keyboard is the safe tool for it.

set -euo pipefail

usage() { echo "usage: ocr.sh [--file <image>]" >&2; }

LANGS=${KANJI_LOOKUP_OCR_LANGS:-jpn+jpn_vert}

# Gate both modes before any capture: jpn is required, jpn_vert warns only.
preflight() {
  if ! tesseract --list-langs 2>/dev/null | grep -qx jpn; then
    echo "kanji-lookup ocr: tesseract Japanese data not found; install it with: omarchy pkg add tesseract-data-jpn tesseract-data-jpn_vert" >&2
    exit 2
  fi
  if [[ -z ${KANJI_LOOKUP_OCR_LANGS:-} ]] && ! tesseract --list-langs 2>/dev/null | grep -qx jpn_vert; then
    echo "kanji-lookup ocr: warning: jpn_vert data missing, falling back to jpn only (vertical text may suffer)" >&2
    LANGS=jpn
  fi
}

# Japanese needs no spaces: drop newlines/CR/FF, squeeze ASCII space runs, trim ends.
clean_text() {
  printf '%s' "$1" | tr -d '\r\f\n' | tr -s ' ' | sed -e 's/^ *//' -e 's/ *$//'
}

# Keep Tesseract's plain text spacing; use its TSV only to compare confidence.
# workdir/best_text/best_score are local to main (Bash dynamic scope).
try_ocr() {
  local candidate score
  if ! tesseract "$1" "$workdir/result" --oem 1 --psm "$2" -l "$LANGS" \
      --dpi 300 -c preserve_interword_spaces=1 txt tsv </dev/null 2>/dev/null; then
    return 0
  fi
  candidate=$(clean_text "$(cat "$workdir/result.txt")")
  score=$(LC_ALL=C awk -F '\t' '
    $1 == 5 && $11 >= 0 && $12 != "" {
      weight = length($12); total += $11 * weight; count += weight
    }
    END { print count ? int(100 * total / count) : 0 }
  ' "$workdir/result.tsv")
  if [[ -n $candidate ]] && (( score > 0 && score > best_score )); then
    best_text=$candidate
    best_score=$score
  fi
}

main() (
  local mode=region file=
  if [[ ${1:-} == --file ]]; then
    if [[ $# -lt 2 || -z $2 ]]; then
      usage
      exit 1
    fi
    mode=file
    file=$2
  elif [[ $# -gt 0 ]]; then
    usage
    exit 1
  fi

  preflight

  if [[ $mode == region ]]; then
    local selection
    # GUI launchers keep stdin open. slurp reads non-TTY stdin for suggested
    # rectangles before showing its overlay, so give it EOF immediately.
    selection=$(slurp </dev/null 2>/dev/null) || true
    if [[ -z $selection ]]; then
      exit 0 # user cancelled the region (Escape or a degenerate click)
    fi
  fi

  local workdir best_text= best_score=0
  workdir=$(mktemp -d "${TMPDIR:-/tmp}/kanji-lookup-ocr.XXXXXXXX")
  trap 'rm -rf -- "$workdir"' EXIT
  if [[ $mode == region ]]; then
    file=$workdir/capture.png
    grim -g "$selection" "$file" || exit 1
  fi

  # Preserve the fast path for ordinary text, including dark backgrounds.
  try_ocr "$file" 6
  if (( best_score < 9000 )) && command -v magick >/dev/null 2>&1; then
    # Omarchy already ships ImageMagick. Isolate bright subtitle fills from
    # their dark outlines and the scene behind them. Threshold BEFORE scaling
    # so interpolation cannot mix the outline/background into the strokes.
    # Grow the enlarged strokes slightly to reconnect small antialiased gaps.
    # A subtitle mask has sparse ink. Reject empty masks and bright scenery
    # turned into a solid ink block, which word mode can hallucinate as kanji.
    local prepared=$workdir/subtitle.png usable geometry width height
    if usable=$(magick "$file" -alpha off -colorspace Gray -threshold 90% -negate \
        -format '%[fx:mean>0.5 && mean<1]' -write info: \
        -filter Point -resize 200% -morphology Erode Disk:1 \
        -bordercolor white -border 10 "$prepared" 2>/dev/null) && [[ $usable == 1 ]]; then
      try_ocr "$prepared" 6
      # A compact crop can be one kanji whose radicals were split into lines.
      # Word segmentation keeps them together; don't force it on text blocks.
      geometry=$(magick identify -format '%w %h' "$file" 2>/dev/null) || geometry=
      read -r width height <<< "$geometry"
      if (( best_score < 9000 )) && [[ $width =~ ^[0-9]+$ && $height =~ ^[0-9]+$ ]] \
          && (( width * 2 >= height && height * 2 >= width )); then
        try_ocr "$prepared" 8
      fi
    fi
  fi

  if [[ -z $best_text ]]; then
    echo "no text recognized" >&2
    exit 1
  fi
  printf '%s\n' "$best_text"
)

main "$@"
