#!/usr/bin/env python3
"""Build the kotoba offline dictionary DB from jmdict-simplified releases.

Downloads the latest jmdict-eng (English JMdict) and kanjidic2-en (KANJIDIC2)
JSON zips into ~/.local/share/kotoba/src/ (skipped if already present), then
writes a SQLite DB to ~/.local/share/kotoba/jmdict.db with two tables:

    words(id INTEGER PRIMARY KEY, kanji TEXT, reading TEXT, glosses TEXT)
    kanji(char TEXT PRIMARY KEY, meanings TEXT, "on" TEXT, kun TEXT,
          strokes INTEGER, grade INTEGER)

JMdict and KANJIDIC2 are (c) EDRDG, CC BY-SA 4.0 — see LICENSE-EDRDG.
Stdlib only: json, sqlite3, subprocess, urllib, zipfile.
"""
import json
import os
import sqlite3
import subprocess
import sys
import urllib.parse
import zipfile

REPO = "scriptin/jmdict-simplified"
SHARE = os.path.expanduser("~/.local/share/kotoba")
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
        print(f"kotoba: gh failed ({exc}); falling back to curl", file=sys.stderr)
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
    sys.exit(f"kotoba: no {what} asset found in latest release")


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
        print(f"kotoba: {os.path.basename(dest)} already downloaded, skipping")
        return
    print(f"kotoba: downloading {url}")
    subprocess.run(["curl", "-fsSL", "-o", dest, url], check=True)


def load_json(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        return json.loads(z.read(z.namelist()[0]).decode("utf-8"))


def parse_jmdict(zip_path):
    rows = []
    for w in load_json(zip_path)["words"]:
        kanji = ";".join(k["text"] for k in w.get("kanji", []))
        reading = ";".join(k["text"] for k in w.get("kana", []))
        senses = []
        for s in w.get("sense", []):
            gloss = ", ".join(g["text"] for g in s.get("gloss", []))
            if gloss:
                senses.append(gloss)
        rows.append((int(w["id"]), kanji, reading, " | ".join(senses)[:400]))
    return rows


def parse_kanjidic2(zip_path):
    rows = []
    for c in load_json(zip_path)["characters"]:
        groups = (c.get("readingMeaning") or {}).get("groups", [])
        readings = [r for g in groups for r in g.get("readings", [])]
        on = ";".join(r["value"] for r in readings if r["type"] == "ja_on")
        kun = ";".join(r["value"] for r in readings if r["type"] == "ja_kun")
        meanings = ";".join(m["value"] for g in groups
                            for m in g.get("meanings", []) if m.get("lang") == "en")
        misc = c.get("misc", {})
        strokes = (misc.get("strokeCounts") or [None])[0]
        rows.append((c["literal"], meanings, on, kun, strokes, misc.get("grade")))
    return rows


def main():
    os.makedirs(SRC, exist_ok=True)
    urls = asset_urls()
    jmdict_url = pick(urls, is_jmdict, "JMdict (English)")
    kanjidic_url = pick(urls, is_kanjidic2, "kanjidic2 (English)")
    jmdict_zip = os.path.join(SRC, urllib.parse.unquote(jmdict_url.rsplit("/", 1)[-1]))
    kanjidic_zip = os.path.join(SRC, urllib.parse.unquote(kanjidic_url.rsplit("/", 1)[-1]))
    download(jmdict_url, jmdict_zip)
    download(kanjidic_url, kanjidic_zip)

    words = parse_jmdict(jmdict_zip)
    kanji = parse_kanjidic2(kanjidic_zip)

    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
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
    con.close()
    print(f"words: {wc} rows")
    print(f"kanji: {kc} rows")
    print(f"kotoba: wrote {DB}")


if __name__ == "__main__":
    main()
