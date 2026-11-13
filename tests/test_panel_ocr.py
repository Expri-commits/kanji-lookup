"""Exercise the panel's actual OCR handlers with Qt text-change signals.

External process output and request dispatch are stubbed. TextField, Timer,
lookup(), searchFor(), and the completion/text-change handlers are real.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PANEL = Path(__file__).resolve().parents[1] / "Panel.qml"
QML_RUNNER = next((str(path) for path in [
    Path("/usr/lib/qt6/bin/qmltestrunner"),
    Path(shutil.which("qmltestrunner") or "/nonexistent"),
] if path.is_file()), None)


def block_after(source, marker, start=0):
    """Extract the balanced bodies used here (no braces inside their strings)."""
    opening = source.index("{", source.index(marker, start) + len(marker))
    depth, end = 1, opening + 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[opening + 1:end - 1]


@unittest.skipUnless(QML_RUNNER, "Qt QML test runner not installed")
class PanelOcrTests(unittest.TestCase):
    def test_ocr_completion_with_real_textfield_signals(self):
        source = PANEL.read_text()
        functions = "\n".join(
            f"function {name}({argument}) {{" + block_after(source, f"function {name}(") + "}"
            for name, argument in [("capture", ""), ("searchFor", "q"), ("lookup", "rawQuery"),
                                   ("clearResults", ""), ("applyResult", "data, request"),
                                   ("finishLookup", "exitCode, request"), ("showDictionarySetup", "outdated"),
                                   ("queryTooLong", "query")]
        )
        completion = block_after(source, "onExited: function(exitCode)", source.index("id: ocrProc"))
        text_changed = block_after(source, "onTextChanged:")
        probe_completion = block_after(source, "onExited: function(exitCode)", source.index("id: dbProbe"))
        bar_source = (PANEL.parent / "BarWidget.qml").read_text()
        bar_probe_completion = block_after(bar_source, "onExited: function(exitCode)", bar_source.index("id: dbProbe"))
        qml = '''import QtQuick 2.15
import QtQuick.Controls 2.15
import QtTest 1.3
import "@NAVIGATION@" as WordNavigation
Item {
  id: root
  width: 400; height: 100
  property string lastQuery: ""
  property string statusText: ""
  property bool capturing: false
  property int lookupCalls: 0
  property string requestedQuery: ""
  property int maxQueryLength: 4096
  property int maxKanjiEntries: 32
  property int lookupSeq: 1
  property bool dbMissing: false
  property string resultQuery: ""
  property string matchKind: "none"
  property var mainWord: null
  property var kanjiEntries: []
  property var relatedWords: []
  function scriptPath(name) { return name }
  function cancelLookup() {}
  function queueLookup(query, entryId, previous) {
    lookupCalls++
    requestedQuery = query
    statusText = "Looking up " + query + "…"
  }
  @FUNCTIONS@
  function finishOcr(exitCode) { @COMPLETION@ }
  function finishProbe(exitCode) { @PROBE_COMPLETION@ }
  function finishBarProbe(exitCode) { @BAR_PROBE_COMPLETION@ }
  QtObject { id: setupNotify; property bool running: false }
  QtObject { id: outCollector; property string text: "" }
  QtObject { id: errCollector; property string text: "" }
  QtObject { id: dbProbeError; property string text: "" }
  QtObject { id: resultScroll; property int contentY: 0 }
  QtObject { id: kanjiStrip; property int contentX: 0 }
  Repeater { id: kanjiRepeater; model: root.kanjiEntries; delegate: Item {} }
  QtObject { id: ocrProc; property bool running: false; property var command: [] }
  QtObject { id: ocrOut; property string text: "" }
  QtObject { id: ocrErr; property string text: "" }
  Timer { id: debounce; interval: 350; onTriggered: root.lookup(searchField.text) }
  TextField { id: searchField; maximumLength: root.maxQueryLength * 2; onTextChanged: { @TEXT_CHANGED@ } }
  TestCase {
    name: "PanelOcrCompletion"
    function init() {
      root.lastQuery = "日本語"
      searchField.text = root.lastQuery
      debounce.stop()
      root.lookupCalls = 0
      root.requestedQuery = ""
      root.statusText = ""
      root.dbMissing = false
      root.clearResults()
      outCollector.text = ""
      errCollector.text = ""
      dbProbeError.text = ""
      setupNotify.running = false
      root.capturing = false
      ocrProc.running = false
      ocrErr.text = ""
    }
    function finishCapture(text, code) {
      root.capture()
      compare(root.statusText, "Capturing screen…")
      ocrOut.text = text
      ocrProc.running = false
      root.finishOcr(code)
    }
    function test_same_text_runs_lookup_again() {
      finishCapture("日本語\\n", 0)
      compare(root.capturing, false)
      compare(root.lookupCalls, 1)
      compare(root.requestedQuery, "日本語")
      verify(root.statusText !== "Capturing screen…")
      compare(debounce.running, false)
    }
    function test_different_text_runs_exactly_one_lookup() {
      finishCapture(" 敬語\\n", 0)
      compare(root.capturing, false)
      compare(root.lookupCalls, 1)
      compare(root.requestedQuery, "敬語")
      compare(searchField.text, "敬語")
      compare(debounce.running, false)
    }
    function test_cancel_does_not_lookup_or_change_text() {
      finishCapture("", 0)
      compare(root.capturing, false)
      compare(root.lookupCalls, 0)
      compare(searchField.text, "日本語")
      compare(root.statusText, "")
    }
    function test_oversized_ocr_does_not_lookup_or_truncate_text() {
      finishCapture("日".repeat(root.maxQueryLength + 1), 0)
      compare(root.lookupCalls, 0)
      compare(searchField.text, "日本語")
      verify(root.statusText.indexOf("too long") !== -1)
    }
    function test_oversized_ipc_does_not_lookup_or_replace_text() {
      root.searchFor("日".repeat(root.maxQueryLength + 1))
      compare(root.lookupCalls, 0)
      compare(searchField.text, "日本語")
      verify(root.statusText.indexOf("too long") !== -1)
    }
    function test_supplementary_query_boundary_matches_cli() {
      var query = "𠀀".repeat(root.maxQueryLength)
      root.searchFor(query)
      compare(root.lookupCalls, 1)
      compare(root.requestedQuery, query)
      compare(searchField.text, query)
      root.searchFor(query + "𠀀")
      compare(root.lookupCalls, 1)
      compare(searchField.text, query)
      verify(root.statusText.indexOf("too long") !== -1)
    }
    function test_bar_probe_timeout_does_not_request_setup() {
      dbProbeError.text = "kanji-lookup: process timed out\\n"
      root.finishBarProbe(124)
      compare(setupNotify.running, false)
    }
    function test_bar_missing_database_still_offers_setup() {
      dbProbeError.text = "DB_MISSING\\n"
      root.finishBarProbe(2)
      compare(setupNotify.running, true)
    }
    function test_large_response_caps_real_kanji_delegates() {
      var entries = []
      for (var i = 0; i < 100; i++) entries.push({ char: "日" })
      root.applyResult({ query: "日本語", main: null, kanji: entries, related: [] },
        { query: "日本語", entryId: "", previous: null })
      compare(root.kanjiEntries.length, root.maxKanjiEntries)
      tryCompare(kanjiRepeater, "count", root.maxKanjiEntries)
      compare(entries.length, 100)
    }
    function test_lookup_deadline_is_reported_as_error() {
      errCollector.text = "kanji-lookup: process timed out\\n"
      root.finishLookup(124, { seq: root.lookupSeq, query: "日本語", fieldText: searchField.text,
        entryId: "", previous: null })
      compare(root.dbMissing, false)
      verify(root.statusText.indexOf("timed out") !== -1)
    }
    function test_probe_deadline_does_not_claim_database_is_missing() {
      dbProbeError.text = "kanji-lookup: process timed out\\n"
      root.finishProbe(124)
      compare(root.dbMissing, false)
      verify(root.statusText.indexOf("timed out") !== -1)
    }
    function test_outdated_probe_still_offers_setup() {
      dbProbeError.text = "DB_OUTDATED\\n"
      root.finishProbe(2)
      compare(root.dbMissing, true)
      verify(root.statusText.indexOf("need updating") !== -1)
    }
    function test_failure_keeps_query_and_reports_error() {
      ocrErr.text = "no text recognized\\n"
      finishCapture("", 1)
      compare(root.capturing, false)
      compare(root.lookupCalls, 0)
      compare(searchField.text, "日本語")
      compare(root.statusText, "no text recognized")
    }
  }
}
'''.replace("@FUNCTIONS@", functions).replace("@COMPLETION@", completion).replace("@TEXT_CHANGED@", text_changed)
        qml = qml.replace("@PROBE_COMPLETION@", probe_completion).replace("@BAR_PROBE_COMPLETION@", bar_probe_completion).replace(
            "@NAVIGATION@", (PANEL.parent / "scripts" / "word-navigation.js").as_uri())
        with tempfile.TemporaryDirectory(prefix="kanji-panel-test-") as directory:
            path = Path(directory) / "tst_ocr.qml"
            path.write_text(qml)
            result = subprocess.run(
                [QML_RUNNER, "-input", str(path)], capture_output=True, text=True,
                env=dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software"),
                timeout=20,
            )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("PanelOcrCompletion::test_same_text_runs_lookup_again", output)


if __name__ == "__main__":
    unittest.main()
