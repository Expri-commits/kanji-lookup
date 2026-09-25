#!/usr/bin/env bash
# wl-paste --watch runs this once for the initial state and after every
# clipboard/primary-selection change. Never forward selection data to QML;
# consume it and emit one newline-framed state marker instead. wl-clipboard
# 2.3.0 does not set CLIPBOARD_TYPE, so do not infer the offered MIME here.
set -eu
cat >/dev/null

case ${CLIPBOARD_STATE:-nil} in
  data) printf 'data\n' ;;
  *) printf 'nil\n' ;;
esac
