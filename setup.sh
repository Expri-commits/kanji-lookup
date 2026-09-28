#!/bin/bash
# Kanji Lookup setup: the post-install wizard. `omarchy plugin add` never runs
# plugin code, so run this right after installing:
#   ~/.config/omarchy/plugins/io.github.expri-commits.kanji-lookup/setup.sh
# It asks about the dictionaries, the OCR data, and the panel shortcut. Safe to
# re-run: every step detects what is already done. Everything it changes lives
# in ~/.local/share/kanji-lookup/, the tesseract packages, and one bind line in
# ~/.config/hypr/bindings.lua.

set -euo pipefail

PLUGIN_ID="io.github.expri-commits.kanji-lookup"
DEFAULT_KEY="SUPER+SHIFT+J"
PLUGIN_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BINDINGS="$HOME/.config/hypr/bindings.lua"
DATA_DIR="$HOME/.local/share/kanji-lookup"

say() { printf '%s\n' "$*"; }
die() { say "kanji-lookup setup: $*" >&2; exit 1; }

# Interactive wizard; KANJI_LOOKUP_SETUP_FORCE lets the test suite drive a pipe.
[[ -t 0 || ${KANJI_LOOKUP_SETUP_FORCE:-} ]] || die "run me from a terminal"

# ask "question" Y  -> true on Enter/y/yes;  ask "question" N -> only y/yes.
ask() {
  local reply
  read -rp "$1 [$2] " reply || true
  reply="${reply:-$2}"
  [[ ${reply,,} == y* ]]
}

# "super + alt + k" and "super shift k" both become SUPER+ALT+K / SUPER+SHIFT+K.
normalize_key() {
  printf '%s' "$1" | sed -E -e 's/[[:space:]]+/+/g' -e 's/\++/+/g' | tr 'a-z' 'A-Z'
}

is_valid_key() {
  [[ $1 =~ ^[A-Z0-9+_().-]+$ && $1 != +* && $1 != *+ && $1 != *++* ]]
}

# SUPER+SHIFT+J -> "SUPER SHIFT + J", the shape omarchy menu keybindings prints.
menu_key() {
  local words=()
  read -r -a words <<<"${1//+/ }" || true
  if ((${#words[@]} > 1)); then
    say "${words[*]:0:${#words[@]}-1} + ${words[-1]}"
  elif ((${#words[@]})); then
    say "${words[-1]}"
  fi
}

# Delete every existing "Kanji lookup" bind line: our one-line marker comment,
# the bind itself, and — for a hand-copied README-style bind — its multi-line
# [[ ... ]] body (an orphaned body would be a Lua syntax error).
remove_kanji_bind() {
  local tmp="$BINDINGS.tmp.$$"
  awk '
    /^-- Kanji Lookup: bind added by setup\.sh/ { next }
    /o\.bind\("[^"]*", *"Kanji lookup"/ {
      if ($0 ~ /\[\[/) skipping = 1
      next
    }
    skipping && /^[[:space:]]*\]\]\)/ { skipping = 0; next }
    skipping && /^$/ { next }
    skipping && /^[[:space:]]/ { next }
    # Unterminated body (mangled file): stop at the next unindented line so a
    # bad [[ cannot eat the rest of the config.
    skipping { skipping = 0 }
    { print }
  ' "$BINDINGS" > "$tmp" && chmod --reference="$BINDINGS" "$tmp" && mv "$tmp" "$BINDINGS"
}

say "Kanji Lookup setup"
say "=================="

if ! omarchy plugin list --json 2>/dev/null | jq -e --arg id "$PLUGIN_ID" \
    'any(.[]; .id == $id and .enabled == true)' >/dev/null; then
  if ask "Enable the bar widget now?" Y; then
    omarchy plugin enable "$PLUGIN_ID" \
      || say "Enable failed; try later with: omarchy plugin enable $PLUGIN_ID"
  else
    say "Enable later with: omarchy plugin enable $PLUGIN_ID"
  fi
fi

if [[ -f $DATA_DIR/jmdict.db ]]; then
  say "Dictionaries: already built ($DATA_DIR/jmdict.db)"
  if ask "Rebuild from the latest JMdict/KANJIDIC2 release?" N; then
    python3 "$PLUGIN_DIR/scripts/build-db.py" \
      || say "Rebuild failed; retry with: python3 $PLUGIN_DIR/scripts/build-db.py"
  fi
elif ask "Download and build the offline dictionaries now? (~30 MB, a few minutes)" Y; then
  command -v python3 >/dev/null || die "python3 is required by scripts/build-db.py"
  python3 "$PLUGIN_DIR/scripts/build-db.py" \
    || die "dictionary build failed; retry with: python3 $PLUGIN_DIR/scripts/build-db.py"
  say "Dictionaries: built $DATA_DIR/jmdict.db"
else
  say "Skipped. Until then the panel only shows a build hint. Later: python3 $PLUGIN_DIR/scripts/build-db.py"
fi

if tesseract --list-langs 2>/dev/null | grep -qx jpn; then
  say "OCR: Tesseract Japanese data already installed"
elif ask "Install Tesseract Japanese data for the capture (撮) button? (asks for your password)" Y; then
  omarchy pkg add tesseract-data-jpn tesseract-data-jpn_vert \
    || say "Install cancelled or failed; later: omarchy pkg add tesseract-data-jpn tesseract-data-jpn_vert"
else
  say "Skipped. Later: omarchy pkg add tesseract-data-jpn tesseract-data-jpn_vert"
fi

say ""
say "Shortcut: opens the panel with the freshest selected text, or starts an"
say "OCR capture when nothing is fresh."

BIND_CMD='P="$(timeout 0.5s wl-paste --type text --primary 2>/dev/null)"; C="$(timeout 0.5s wl-paste --type text 2>/dev/null)"; omarchy-shell io.github.expri-commits.kanji-lookup smartTrigger "$P" "$C"'

existing=""
if [[ -f $BINDINGS ]]; then
  existing=$(awk 'match($0, /^ *o\.bind\("([^"]*)", *"Kanji lookup"/, m) { gsub(/[ \t]/, "", m[1]); print m[1]; exit }' "$BINDINGS")
fi

key=""
if [[ -n $existing ]]; then
  say "Current shortcut: $existing"
  if ask "Change it?" N; then
    read -rp "New shortcut (Hyprland syntax, e.g. SUPER+ALT+K; 'none' removes it): " key || true
    key="$(normalize_key "$key")"
  fi
else
  read -rp "Shortcut for the panel [Enter = $DEFAULT_KEY, or type your own; 'none' to skip]: " key || true
  key="$(normalize_key "${key:-$DEFAULT_KEY}")"
fi

while [[ -n $key && $key != NONE ]] && ! is_valid_key "$key"; do
  say "That does not look like a Hyprland combo (e.g. SUPER+SHIFT+J, ALT+F2)."
  if ! read -rp "Shortcut [Enter = ${existing:-$DEFAULT_KEY}; 'none' to skip]: " key; then
    key="" # EOF (piped input, closed terminal): stop, leave the file untouched
    break
  fi
  key="$(normalize_key "${key:-${existing:-$DEFAULT_KEY}}")"
done

if [[ -n $key && $key != NONE ]]; then
  conflict=$(omarchy menu keybindings --print 2>/dev/null | awk -F'→' -v k="$(menu_key "$key")" '
    { gsub(/^ +| +$/, "", $1); gsub(/^ +/, "", $2) }
    $1 == k && $2 != "Kanji lookup" { print $2; exit }') || true
  if [[ -n $conflict ]] && ! ask "'$key' is already bound to: $conflict. Take it over?" N; then
    key=""
    say "Shortcut left as is."
  fi
fi

if [[ $key == NONE ]]; then
  if [[ -n $existing ]]; then
    remove_kanji_bind
    hyprctl reload >/dev/null 2>&1 || true
    say "Shortcut: removed."
  else
    say "Shortcut: none. Add one any time in $BINDINGS (README has the block)."
  fi
elif [[ -n $key ]]; then
  mkdir -p "${BINDINGS%/*}"
  touch "$BINDINGS"
  if [[ -n $existing ]]; then
    sed -i -E 's/^( *o\.bind\(")[^"]+(", *"Kanji lookup",)/\1'"$key"'\2/' "$BINDINGS"
    say "Shortcut: now $key."
  else
    cat >>"$BINDINGS" <<BLOCK

-- Kanji Lookup: bind added by setup.sh; edit the key or delete this line any time.
o.bind("$key", "Kanji lookup", '$BIND_CMD')
BLOCK
    say "Shortcut: bound $key in $BINDINGS"
  fi
  hyprctl reload >/dev/null 2>&1 || true
fi

say ""
say "Done. Click the 辞 widget in the bar, or press the shortcut."
[[ -f $DATA_DIR/jmdict.db ]] || say "Dictionaries still missing: python3 $PLUGIN_DIR/scripts/build-db.py"
[[ -n $key || -n $existing ]] || say "No shortcut set; see the Use section of the README."
