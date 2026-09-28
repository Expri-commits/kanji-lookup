#!/usr/bin/env python3
"""Build the Kanji Lookup offline dictionary DB from jmdict-simplified releases.

Downloads the latest jmdict-eng (English JMdict) and kanjidic2-en (KANJIDIC2)
JSON zips into ~/.local/share/kanji-lookup/src/ (skipped if already present), then
writes a SQLite DB to ~/.local/share/kanji-lookup/jmdict.db with two tables:

    words(id INTEGER PRIMARY KEY, kanji TEXT, reading TEXT, glosses TEXT)
    kanji(char TEXT PRIMARY KEY, meanings TEXT, "on" TEXT, kun TEXT,
          strokes INTEGER, grade INTEGER)

Both zips are parsed streaming (iter_entries): the JSON is read in chunks and
decoded one dictionary entry at a time, so peak memory is one chunk plus one
entry regardless of how big a release grows.

JMdict and KANJIDIC2 are (c) EDRDG, CC BY-SA 4.0 — see LICENSE-EDRDG.
Stdlib only: codecs, json, sqlite3, subprocess, urllib, zipfile.
"""
import codecs
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import zipfile

REPO = "scriptin/jmdict-simplified"
# Largest legit asset today is ~12 MB zipped / ~60 MB of JSON; caps exist so a
# huge or zip-bomb release asset cannot exhaust disk or RAM. Generous headroom.
MAX_ZIP_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024 * 1024
# Real entries are a few KB; bounds one buffered element so a single huge
# value cannot balloon memory even under the JSON cap.
MAX_ENTRY_BYTES = 16 * 1024 * 1024
READ_CHUNK = 1 << 16
SHARE = os.path.expanduser("~/.local/share/kanji-lookup")
SRC = os.path.join(SHARE, "src")
DB = os.path.join(SHARE, "jmdict.db")


def asset_urls():
    """Latest release asset URLs: gh first, curl+json fallback."""
    try:
        out = subprocess.run(
            ["/usr/bin/gh", "api", f"repos/{REPO}/releases/latest",
             "--jq", ".assets[].browser_download_url"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        urls = out.split()
        if urls:
            return urls
        raise RuntimeError("gh returned no assets")
    except Exception as exc:
        print(f"kanji-lookup: gh failed ({exc}); falling back to curl", file=sys.stderr)
        out = subprocess.run(
            ["curl", "-fsSL", f"https://api.github.com/repos/{REPO}/releases/latest"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        return [a["browser_download_url"] for a in json.loads(out)["assets"]]


def pick(urls, pred, what):
    for url in urls:
        name = url.rsplit("/", 1)[-1].lower()
        if pred(name):
            return url
    sys.exit(f"kanji-lookup: no {what} asset found in latest release")


def is_jmdict(name):
    # JMdict_e-<ver>.json.zip (old) or jmdict-eng-<ver>.json.zip (current);
    # not jmdict-eng-common / jmdict-examples-eng.
    return (name.endswith(".json.zip")
            and (name.startswith("jmdict_e-") or name.startswith("jmdict-eng-"))
            and "common" not in name and "examples" not in name)


def is_kanjidic2(name):
    return name.startswith("kanjidic2-en-") and name.endswith(".json.zip")


def download(url, dest):
    if os.path.exists(dest):
        print(f"kanji-lookup: {os.path.basename(dest)} already downloaded, skipping")
        return
    print(f"kanji-lookup: downloading {url}")
    # On a terminal curl's own meter shows percent, speed, and time left; -s
    # would hide it. Silence it everywhere else (pipes, cron, tests). A
    # .part name keeps an interrupted download from looking complete.
    quiet = [] if sys.stderr.isatty() else ["-s"]
    part = dest + ".part"
    subprocess.run(["curl", "-fSL", *quiet, "--max-filesize", str(MAX_ZIP_BYTES),
                    "-o", part, url], check=True)
    # --max-filesize is a no-op when the server sends no Content-Length.
    size = os.path.getsize(part)
    if size > MAX_ZIP_BYTES:
        os.remove(part)
        sys.exit(f"kanji-lookup: {os.path.basename(dest)} is {size} bytes"
                 f" (> {MAX_ZIP_BYTES}); refusing to continue")
    os.replace(part, dest)


def iter_entries(zip_path, array_key):
    """Yield decoded elements of the top-level `array_key` JSON array,
    streaming: chunked reads, incremental UTF-8 decode, one element at a
    time, so peak memory stays bounded regardless of entry size."""
    dec = codecs.getincrementaldecoder("utf-8")()
    tok = json.JSONDecoder()
    malformed = (f"kanji-lookup: {os.path.basename(zip_path)} is not valid"
                 f" JSON; refusing to continue")

    with zipfile.ZipFile(zip_path) as z, z.open(z.namelist()[0]) as f:
        buf, eof, total = "", False, 0

        def feed():
            nonlocal buf, eof, total
            if eof:
                return False
            chunk = f.read(READ_CHUNK)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                sys.exit(f"kanji-lookup: {os.path.basename(zip_path)} entry"
                         f" unpacks past {MAX_JSON_BYTES} bytes;"
                         f" refusing to continue")
            # final=True flushes a multibyte char split across the last chunks
            buf += dec.decode(chunk) if chunk else dec.decode(b"", final=True)
            # buf holds only the current value plus at most one chunk tail
            # (consumed prefixes are sliced off), so this aborts an oversized
            # element while it accumulates, never after parsing it.
            if len(buf) > MAX_ENTRY_BYTES:
                sys.exit(f"kanji-lookup: {os.path.basename(zip_path)} has a"
                         f" single entry past {MAX_ENTRY_BYTES} bytes;"
                         f" refusing to continue")
            eof = not chunk
            return bool(chunk)

        def skip_ws(i):
            # raw_decode does not skip leading whitespace; only these four
            # characters count as JSON whitespace.
            while True:
                while i < len(buf) and buf[i] in " \t\n\r":
                    i += 1
                if i < len(buf) or not feed():
                    return i

        def decode(i):
            # raw_decode at i, feeding more chunks while the value is
            # truncated: a value ending at the buffer edge is retried ("123"
            # cut mid-number), and so is one followed by a non-structural
            # char ("0." cut mid-float parses as the shorter number 0).
            nonlocal buf
            while True:
                try:
                    value, end = tok.raw_decode(buf, i)
                except json.JSONDecodeError:
                    if not feed():
                        sys.exit(malformed)
                    continue
                if (end == len(buf) or buf[end] not in " \t\n\r,]}:") and feed():
                    continue
                return value, end

        i = skip_ws(0)
        if i >= len(buf) or buf[i] != "{":
            sys.exit(malformed)
        i = skip_ws(i + 1)
        while True:
            if i >= len(buf):
                sys.exit(malformed)
            if buf[i] == "}":
                sys.exit(f"kanji-lookup: {os.path.basename(zip_path)} has no"
                         f" {array_key!r} array")
            key, end = decode(i)
            if not isinstance(key, str):
                sys.exit(malformed)
            buf, i = buf[end:], 0
            i = skip_ws(i)
            if i >= len(buf) or buf[i] != ":":
                sys.exit(malformed)
            i = skip_ws(i + 1)
            if i >= len(buf):
                sys.exit(malformed)
            if key == array_key:
                if buf[i] != "[":
                    sys.exit(malformed)
                i = skip_ws(i + 1)
                while True:
                    if i >= len(buf):
                        sys.exit(malformed)
                    if buf[i] == "]":
                        return
                    elem, end = decode(i)
                    buf, i = buf[end:], 0
                    yield elem
                    i = skip_ws(i)
                    if i >= len(buf) or buf[i] not in ",]":
                        sys.exit(malformed)
                    if buf[i] == ",":
                        i = skip_ws(i + 1)
            _, end = decode(i)  # version/languages: tiny, discard
            buf, i = buf[end:], 0
            i = skip_ws(i)
            if i >= len(buf) or buf[i] not in ",}":
                sys.exit(malformed)
            if buf[i] == ",":
                i = skip_ws(i + 1)


def parse_jmdict(zip_path):
    for w in iter_entries(zip_path, "words"):
        kanji = ";".join(k["text"] for k in w.get("kanji", []))
        reading = ";".join(k["text"] for k in w.get("kana", []))
        senses = []
        for s in w.get("sense", []):
            gloss = ", ".join(g["text"] for g in s.get("gloss", []))
            if gloss:
                senses.append(gloss)
        yield (int(w["id"]), kanji, reading, " | ".join(senses))


def parse_kanjidic2(zip_path):
    for c in iter_entries(zip_path, "characters"):
        groups = (c.get("readingMeaning") or {}).get("groups", [])
        readings = [r for g in groups for r in g.get("readings", [])]
        on = ";".join(r["value"] for r in readings if r["type"] == "ja_on")
        kun = ";".join(r["value"] for r in readings if r["type"] == "ja_kun")
        meanings = ";".join(m["value"] for g in groups
                            for m in g.get("meanings", []) if m.get("lang") == "en")
        misc = c.get("misc", {})
        strokes = (misc.get("strokeCounts") or [None])[0]
        yield (c["literal"], meanings, on, kun, strokes, misc.get("grade"))


def main():
    os.makedirs(SRC, exist_ok=True)
    urls = asset_urls()
    jmdict_url = pick(urls, is_jmdict, "JMdict (English)")
    kanjidic_url = pick(urls, is_kanjidic2, "kanjidic2 (English)")
    jmdict_zip = os.path.join(SRC, urllib.parse.unquote(jmdict_url.rsplit("/", 1)[-1]))
    kanjidic_zip = os.path.join(SRC, urllib.parse.unquote(kanjidic_url.rsplit("/", 1)[-1]))
    download(jmdict_url, jmdict_zip)
    download(kanjidic_url, kanjidic_zip)

    # Re-parsing the zips and rebuilding takes minutes: skip when the DB
    # already reflects both cached zips and this builder version.
    if (os.path.exists(DB) and os.path.getmtime(DB) >= os.path.getmtime(__file__)
            and os.path.getmtime(DB) >= os.path.getmtime(jmdict_zip)
            and os.path.getmtime(DB) >= os.path.getmtime(kanjidic_zip)):
        print(f"DB up to date ({time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(DB)))});"
              " delete it or touch a zip to force rebuild")
        return

    words = parse_jmdict(jmdict_zip)
    kanji = parse_kanjidic2(kanjidic_zip)

    # Build into a temp path and swap in on success only: the parsers stream
    # rows lazily, so a parse error would otherwise surface mid-insert, after
    # the working DB was gone.
    tmp = DB + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(
            """
            CREATE TABLE words(id INTEGER PRIMARY KEY, kanji TEXT, reading TEXT, glosses TEXT);
            CREATE TABLE kanji(char TEXT PRIMARY KEY, meanings TEXT, "on" TEXT, kun TEXT,
                               strokes INTEGER, grade INTEGER);
            """
        )
        con.executemany("INSERT INTO words VALUES (?,?,?,?)", words)
        con.executemany('INSERT INTO kanji VALUES (?,?,?,?,?,?)', kanji)
        con.commit()
        wc = con.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        kc = con.execute("SELECT COUNT(*) FROM kanji").fetchone()[0]
    except BaseException:
        con.close()
        os.remove(tmp)
        raise
    con.close()
    os.replace(tmp, DB)
    print(f"words: {wc} rows")
    print(f"kanji: {kc} rows")
    print(f"kanji-lookup: wrote {DB}")


if __name__ == "__main__":
    main()
