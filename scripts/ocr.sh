#!/bin/bash
# kotoba OCR: recognize Japanese text for the dictionary search box.
#   scripts/ocr.sh            Interactive: select a region (slurp), capture it
#                             (grim), OCR with tesseract jpn, and print the
#                             cleaned text (newlines stripped, ASCII spaces
#                             collapsed) on one line to stdout.
#   scripts/ocr.sh --file P   Headless test mode: OCR image file P with the same
#                             tesseract flags and cleaning rules.
# Exit codes: 0 ok (or user cancelled region); 1 no text recognized; 2 Japanese data missing.
# ponytail: no screen-freeze layer (hyprpicker/wayfreeze) on purpose — an
# interactive freeze layer under slurp has undefined stacking/input routing on
# Hyprland (ate Escape, ate the drag click). Pause videos instead; if a freeze
# is ever wanted, wayfreeze --enable-keyboard is the safe tool for it.

set -euo pipefail

usage() { echo "usage: ocr.sh [--file <image>]" >&2; }

LANGS=${KOTOBA_OCR_LANGS:-jpn+jpn_vert}

# Gate both modes before any capture: jpn is required, jpn_vert warns only.
preflight() {
  if ! tesseract --list-langs 2>/dev/null | grep -qx jpn; then
    echo "kotoba ocr: tesseract Japanese data not found; install it with: omarchy pkg add tesseract-data-jpn tesseract-data-jpn_vert" >&2
    exit 2
  fi
  if [[ -z ${KOTOBA_OCR_LANGS:-} ]] && ! tesseract --list-langs 2>/dev/null | grep -qx jpn_vert; then
    echo "kotoba ocr: warning: jpn_vert data missing, falling back to jpn only (vertical text may suffer)" >&2
    LANGS=jpn
  fi
}

# Japanese needs no spaces: drop newlines/CR/FF, squeeze ASCII space runs, trim ends.
clean_text() {
  printf '%s' "$1" | tr -d '\r\f\n' | tr -s ' ' | sed -e 's/^ *//' -e 's/ *$//'
}

main() {
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

  local raw text
  if [[ $mode == file ]]; then
    raw=$(tesseract "$file" stdout --oem 1 --psm 6 -l "$LANGS" --dpi 300 -c preserve_interword_spaces=1 2>/dev/null) || exit 1
  else
    local selection
    selection=$(slurp 2>/dev/null) || true
    if [[ -z $selection ]]; then
      exit 0 # user cancelled the region (Escape or a degenerate click)
    fi
    raw=$(grim -g "$selection" - | tesseract stdin stdout --oem 1 --psm 6 -l "$LANGS" --dpi 300 -c preserve_interword_spaces=1 2>/dev/null) || exit 1
  fi

  text=$(clean_text "$raw")
  if [[ -z $text ]]; then
    echo "no text recognized" >&2
    exit 1
  fi
  printf '%s\n' "$text"
}

main "$@"
