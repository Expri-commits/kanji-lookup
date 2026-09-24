import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Kotoba's popup: a search field over the local JMdict/KANJIDIC2 database,
// plus a 撮 button that OCRs kanji off the screen into the field. Lookups
// and capture shell out to the plugin's own scripts/ with the query as a
// single argv element; a new lookup kills the running one and stale replies
// are dropped by sequence number.
Panel {
  id: root
  moduleName: "io.github.expri-commits.kotoba"
  ipcTarget: "io.github.expri-commits.kotoba"
  manageIpc: false // IPC lives on the bar widget, mirroring the clock

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // scripts/ ships next to this file; resolved the way third-party plugins
  // (acrogenesis.theme-scheduler) resolve their shipped scripts.
  function scriptPath(name) {
    return String(Qt.resolvedUrl("scripts/" + name)).replace(/^file:\/\//, "")
  }

  property int lookupSeq: 0
  property string lastQuery: ""
  property string statusText: ""
  property var kanji: null
  property var words: []
  property bool capturing: false

  Timer {
    id: debounce
    interval: 350
    onTriggered: root.lookup(searchField.text)
  }

  function clearResults() {
    root.kanji = null
    root.words = []
  }

  function lookup(rawQuery) {
    var query = String(rawQuery || "").trim()
    debounce.stop()
    root.lastQuery = query
    if (query === "") { root.clearResults(); root.statusText = ""; return }
    if (lookupProc.running) { lookupProc.killed = true; lookupProc.running = false } // kill the stale run
    root.lookupSeq++
    lookupProc.seq = root.lookupSeq
    lookupProc.command = ["bash", root.scriptPath("lookup.sh"), query]
    lookupProc.running = true
    root.statusText = "Looking up " + query + "…"
  }

  // IPC entry: pre-fill the field and run the lookup immediately. lastQuery
  // is set first so onTextChanged sees no change and leaves the debounce alone.
  function searchFor(q) {
    var query = String(q || "").trim()
    root.lastQuery = query
    searchField.text = query
    root.lookup(query)
  }

  function finishLookup(exitCode) {
    var out = String(outCollector.text || "")
    var err = String(errCollector.text || "").trim()
    if (out.trim() === "DB_MISSING" || err.indexOf("DB_MISSING") !== -1) {
      root.clearResults()
      root.statusText = "Run scripts/build-db.py to download JMdict (see README)"
      return
    }
    if (exitCode !== 0) {
      root.statusText = err.split("\n")[0].trim() || ("lookup failed (" + exitCode + ")")
      return
    }
    root.parseResult(out)
  }

  // lookup.sh contract: an optional "##KANJI" header followed by ONE
  // tab-separated row char<TAB>meanings<TAB>on<TAB>kun<TAB>strokes<TAB>grade
  // (columns may be empty), then "##WORDS" and up to 25 tab-separated
  // term / reading / glosses rows where term and reading are ';'-joined
  // lists — only their first token is displayed. Non-kanji queries emit
  // headerless word rows, so the section defaults to "WORDS".
  function parseResult(out) {
    var foundKanji = null
    var foundWords = []
    var section = "WORDS"
    var lines = out.split("\n")
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].replace(/\r$/, "").trim()
      if (line === "") continue
      var head = line.match(/^##\s*(\S+)/)
        if (head) {
          section = head[1].toUpperCase()
          continue
        }
        if (section === "KANJI") {
          // The object is minted by the row, not the header: lookup.sh emits
          // a bare ##KANJI when the char is absent from the kanji table, and
          // an eagerly created object would render an all-empty card.
          if (!foundKanji)
            foundKanji = { "char": "", meanings: "", on: "", kun: "", strokes: "", grade: "" }
          var cols = line.split("\t")
        var keys = ["char", "meanings", "on", "kun", "strokes", "grade"]
        for (var k = 0; k < keys.length && k < cols.length; k++)
          foundKanji[keys[k]] = cols[k].trim()
      } else if (section === "WORDS") {
        var f = line.split("\t")
        var word = { term: f[0].split(";")[0].trim(), reading: "", glosses: "" }
        if (f.length >= 3) { word.reading = f[1].split(";")[0].trim(); word.glosses = f.slice(2).join("; ").trim() }
        else if (f.length === 2) word.glosses = f[1].trim()
        foundWords.push(word)
      }
    }
    root.kanji = foundKanji
    root.words = foundWords.slice(0, 25)
    root.statusText = (foundKanji || root.words.length) ? "" : "No results"
  }

  function capture() {
    if (root.capturing || ocrProc.running) return
    root.capturing = true
    root.statusText = "Capturing screen…"
    ocrProc.command = ["bash", root.scriptPath("ocr.sh")]
    ocrProc.running = true
  }

  Process {
    id: lookupProc
    property int seq: 0
    // A superseded lookup is killed, but its own exited event still fires —
    // after seq has been reassigned to the newer run, so the seq guard alone
    // would pass it and flash empty results for ~one frame. Consume exactly
    // one exit per kill: the killed process dies before its replacement can.
    property bool killed: false
    stdout: StdioCollector { id: outCollector; waitForEnd: true }
    stderr: StdioCollector { id: errCollector; waitForEnd: true }
    onExited: function(exitCode) {
      if (killed) { killed = false; return }
      if (seq === root.lookupSeq) root.finishLookup(exitCode)
    }
  }

  Process {
    id: ocrProc
    stdout: StdioCollector { id: ocrOut; waitForEnd: true }
    stderr: StdioCollector { id: ocrErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.capturing = false
      if (exitCode !== 0) {
        root.statusText = String(ocrErr.text || "").split("\n")[0].trim()
          || ("capture failed (" + exitCode + ")")
        return
      }
      var text = String(ocrOut.text || "").replace(/\r?\n/g, " ").trim()
      // ocr.sh's contract: exit 0 with empty stdout happens only when the
      // user cancelled the region selection — a real miss is exit 1 with
      // stderr. Treat it as a silent cancel, not an OCR failure.
      if (text === "") { root.statusText = ""; return }
      // Assignment routes through onTextChanged into the debounce → lookup.
      searchField.text = text
    }
  }

  // Panel sized to its content, the way the stock clock/weather panels size
  // themselves (fittedContentHeight of the measured stack): with LIMIT 25 the
  // natural height always fits under the bar, so every returned row renders
  // whole and nothing is ever cut at the panel's bottom edge. The fitted cap
  // keeps it bounded on short screens, where the ListView scrolls instead.
  readonly property real naturalContentHeight: Style.space(14 * 2) // inner Item margins
    + searchRow.height
    + (statusLine.visible ? Style.space(8) + statusLine.height : 0)
    + Style.space(8) + (kanjiCard.visible ? kanjiCard.height + Style.space(8) : 0)
    + resultsList.rowH * resultsList.count

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    // Off: the clock/weather center-cluster widgets center on the bar, but
    // kotoba sits in the right cluster, so the card must center under the
    // 辞 button (cardOrigin's per-anchor branch) instead of mid-screen.
    centerOnBar: false
    focusTarget: searchField
    contentWidth: panel.fittedContentWidth(Style.space(520))
    contentHeight: panel.fittedContentHeight(Math.max(Style.space(120), root.naturalContentHeight))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: searchField.activeFocus
      onCloseRequested: root.close()

      Item {
        anchors.fill: parent
        anchors.margins: Style.space(14)

        Row {
          id: searchRow
          anchors { top: parent.top; left: parent.left; right: parent.right }
          spacing: Style.space(10)

          TextField {
            id: searchField
            width: parent.width - captureButton.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            placeholderText: "Search JMdict / KANJIDIC2"
            foreground: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.body

            onTextChanged: {
              if (text.trim() === "") { debounce.stop(); root.lastQuery = ""; root.clearResults(); root.statusText = "" }
              else if (text !== root.lastQuery) debounce.restart()
            }
            onAccepted: root.lookup(text)
            // Escape closes outright, even while the field holds focus.
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) { root.close(); event.accepted = true }
            }
          }

          Button {
            id: captureButton
            anchors.verticalCenter: parent.verticalCenter
            text: "撮"
            tooltipText: "Capture kanji from the screen (OCR)"
            onClicked: root.capture()
          }
        }

        Text {
          id: statusLine
          anchors { top: searchRow.bottom; topMargin: Style.space(8); left: parent.left; right: parent.right }
          visible: root.statusText !== ""
          text: root.statusText
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: Qt.darker(root.fg, 1.4)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        // ---- Kanji card (KANJIDIC2 hit), collapsed away when absent.
        Row {
          id: kanjiCard
          anchors { top: statusLine.visible ? statusLine.bottom : searchRow.bottom
                   topMargin: Style.space(8); left: parent.left; right: parent.right }
          visible: root.kanji !== null
          height: visible ? implicitHeight : 0
          spacing: Style.space(14)

          Text {
            id: kanjiGlyph
            anchors.verticalCenter: parent.verticalCenter
            text: root.kanji ? root.kanji.char : ""
            textFormat: Text.PlainText
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.space(44)
          }

          Column {
            width: parent.width - kanjiGlyph.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              width: parent.width
              visible: root.kanji && root.kanji.meanings !== ""
              text: root.kanji ? root.kanji.meanings : ""
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: root.fg
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              font.bold: true
            }

            Text {
              width: parent.width
              visible: text !== ""
              text: root.kanji
                ? [root.kanji.on ? "ON " + root.kanji.on : "", root.kanji.kun ? "KUN " + root.kanji.kun : "",
                   root.kanji.strokes ? root.kanji.strokes + " strokes" : "",
                   root.kanji.grade ? "grade " + root.kanji.grade : ""].filter(Boolean).join("  ·  ")
                : ""
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: Qt.darker(root.fg, 1.4)
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }
        }

        ListView {
          id: resultsList
          // Uniform whole-pixel row height, measured so naturalContentHeight
          // can size the panel to fit every row without a partial one.
          readonly property real rowH: count > 0 && itemAtIndex(0) ? itemAtIndex(0).height : 0
          anchors { top: kanjiCard.bottom
                    topMargin: kanjiCard.visible ? Style.space(8) : 0
                    bottom: parent.bottom; left: parent.left; right: parent.right }
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          model: root.words

          delegate: Text {
            required property var modelData
            width: resultsList.width
            height: Math.ceil(implicitHeight) + Style.space(6)
            verticalAlignment: Text.AlignVCenter
            text: modelData.term
              + (modelData.reading !== "" ? " 【" + modelData.reading + "】" : "")
              + (modelData.glosses !== "" ? "  " + modelData.glosses : "")
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }
        }
      }
    }
  }
}
