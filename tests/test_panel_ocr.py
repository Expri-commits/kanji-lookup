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
            for name, argument in [("capture", ""), ("searchFor", "q"), ("lookup", "rawQuery")]
        )
        completion = block_after(source, "onExited: function(exitCode)", source.index("id: ocrProc"))
        text_changed = block_after(source, "onTextChanged:")
        qml = '''import QtQuick 2.15
import QtQuick.Controls 2.15
import QtTest 1.3
Item {
  id: root
  width: 400; height: 100
  property string lastQuery: ""
  property string statusText: ""
  property bool capturing: false
  property int lookupCalls: 0
  property string requestedQuery: ""
  function scriptPath(name) { return name }
  function cancelLookup() {}
  function clearResults() {}
  function queueLookup(query, entryId, previous) {
    lookupCalls++
    requestedQuery = query
    statusText = "Looking up " + query + "…"
  }
  @FUNCTIONS@
  function finishOcr(exitCode) { @COMPLETION@ }
  QtObject { id: ocrProc; property bool running: false; property var command: [] }
  QtObject { id: ocrOut; property string text: "" }
  QtObject { id: ocrErr; property string text: "" }
  Timer { id: debounce; interval: 350; onTriggered: root.lookup(searchField.text) }
  TextField { id: searchField; onTextChanged: { @TEXT_CHANGED@ } }
  TestCase {
    name: "PanelOcrCompletion"
    function init() {
      root.lastQuery = "日本語"
      searchField.text = root.lastQuery
      debounce.stop()
      root.lookupCalls = 0
      root.requestedQuery = ""
      root.statusText = ""
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
