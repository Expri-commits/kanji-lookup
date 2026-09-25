import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "scripts/selection-state.js" as SelectionState
import "scripts/word-navigation.js" as WordNavigation

// Offline word and kanji lookup. OCR, IPC, and direct typing start a new search;
// choosing a related entry keeps the previous focus available for backtracking.
Panel {
  id: root
  moduleName: "io.github.expri-commits.kanji-lookup"
  ipcTarget: "io.github.expri-commits.kanji-lookup"
  manageIpc: false // IPC lives on the bar widget, mirroring the clock

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property color fg: Color.popups.text
  readonly property color secondary: Qt.rgba(fg.r, fg.g, fg.b, 0.82)
  readonly property color subtle: Qt.rgba(fg.r, fg.g, fg.b, 0.62)
  readonly property string shortcutLabel: shortcutHint.label
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  ShortcutHint {
    id: shortcutHint
    active: root.opened
    overrideLabel: String(root.setting("shortcutHint", ""))
  }

  // scripts/ ships next to this file; resolved the way third-party plugins
  // (acrogenesis.theme-scheduler) resolve their shipped scripts.
  function scriptPath(name) {
    return String(Qt.resolvedUrl("scripts/" + name)).replace(/^file:\/\//, "")
  }

  property int lookupSeq: 0
  property string lastQuery: ""
  property string statusText: ""
  property string resultQuery: ""
  property string matchKind: "none"
  property var mainWord: null
  property var relatedWords: []
  property var kanjiEntries: []
  property var pendingRequest: null
  property var activeRequest: null
  property bool capturing: false
  readonly property bool lookupBusy: debounce.running || lookupProc.running || pendingRequest !== null

  Timer {
    id: debounce
    interval: 350
    onTriggered: root.lookup(searchField.text)
  }

  function clearResults() {
    root.mainWord = null
    root.relatedWords = []
    root.kanjiEntries = []
    root.matchKind = "none"
    root.resultQuery = ""
  }

  function cancelLookup() {
    root.lookupSeq++
    root.pendingRequest = null
    if (lookupProc.running) {
      lookupProc.cancelled = true
      lookupProc.running = false
    }
  }

  function startPendingRequest() {
    if (lookupProc.cancelled || lookupProc.running || !root.pendingRequest) return
    var request = root.pendingRequest
    root.pendingRequest = null
    root.activeRequest = request
    lookupProc.command = ["python3", root.scriptPath("lookup-json.py")]
      .concat(request.entryId !== "" ? ["--entry-id", request.entryId] : [])
      .concat(["--", request.query])
    lookupProc.running = true
  }

  function queueLookup(query, entryId, previous) {
    root.lookupSeq++
    root.pendingRequest = {
      seq: root.lookupSeq,
      query: query,
      entryId: entryId || "",
      previous: previous || null,
      fieldText: searchField.text
    }
    root.statusText = "Looking up " + query + "…"
    if (lookupProc.running) {
      lookupProc.cancelled = true
      lookupProc.running = false
    } else root.startPendingRequest()
  }

  function lookup(rawQuery) {
    var query = String(rawQuery || "").trim()
    debounce.stop()
    root.lastQuery = query
    if (query === "") {
      root.cancelLookup()
      root.clearResults()
      root.statusText = ""
      return
    }
    root.queueLookup(query, "", null)
  }

  function focusWord(word) {
    if (root.lookupBusy || !word || !word.id) return
    debounce.stop()
    var term = String(word.term || "").trim()
    root.lastQuery = term
    searchField.text = term
    root.queueLookup(term, String(word.id), root.mainWord)
  }

  function focusKanji(character) {
    if (root.lookupBusy || !character) return
    debounce.stop()
    var query = String(character)
    root.lastQuery = query
    searchField.text = query
    root.queueLookup(query, "", root.mainWord)
  }

  // IPC entry: pre-fill the field and run the lookup immediately. lastQuery
  // is set first so onTextChanged sees no change and leaves the debounce alone.
  function searchFor(q) {
    var query = String(q || "").trim()
    root.lastQuery = query
    searchField.text = query
    root.lookup(query)
  }

  // Keybind routing: each candidate is trusted only when its own Wayland
  // source changed recently. The keybind passes both values, read as text.
  readonly property real selectionFreshMs: 5000
  property var primarySelectionState: ({ at: 0, valid: false, awaitingBaseline: true })
  property var clipboardSelectionState: ({ at: 0, valid: false, awaitingBaseline: true })

  function recordSelectionEvent(source, event) {
    if (source === "primary") {
      primarySelectionState = SelectionState.applyWatchEvent(
        primarySelectionState, event, Date.now())
    } else {
      clipboardSelectionState = SelectionState.applyWatchEvent(
        clipboardSelectionState, event, Date.now())
    }
  }

  function smartTrigger(primaryQuery, clipboardQuery) {
    var selection = SelectionState.choose(
      primaryQuery, clipboardQuery,
      primarySelectionState.valid ? primarySelectionState.at : 0,
      clipboardSelectionState.valid ? clipboardSelectionState.at : 0,
      Date.now(), selectionFreshMs)
    if (selection) searchFor(selection.text)
    else capture()
  }

  function finishLookup(exitCode, request) {
    if (request.seq !== root.lookupSeq || searchField.text !== request.fieldText) return
    var out = String(outCollector.text || "")
    var err = String(errCollector.text || "").trim()
    if (out.trim() === "DB_MISSING" || err.indexOf("DB_MISSING") !== -1) {
      if (!request.entryId && !request.previous) root.clearResults()
      root.statusText = "Run scripts/build-db.py to download JMdict (see README)"
      return
    }
    if (exitCode !== 0) {
      if (!request.entryId && !request.previous) root.clearResults()
      root.statusText = err.split("\n")[0].trim() || ("lookup failed (" + exitCode + ")")
      return
    }
    try {
      root.applyResult(JSON.parse(out), request)
    } catch (error) {
      if (!request.entryId && !request.previous) root.clearResults()
      root.statusText = "Invalid dictionary response"
    }
  }

  function applyResult(data, request) {
    if (!data || !Array.isArray(data.related) || !Array.isArray(data.kanji))
      throw new Error("Malformed lookup")
    root.resultQuery = String(data.query || request.query)
    root.matchKind = String(data.matchKind || "none")
    root.mainWord = data.main || null
    root.kanjiEntries = data.kanji
    root.relatedWords = WordNavigation.relatedAfterFocus(request.previous, root.mainWord, data.related, 25)
    resultScroll.contentY = 0
    kanjiStrip.contentX = 0
    // Replacing the delegates destroys keyboard focus on the activated row.
    // Return it to the field so Escape, typing, and Down work immediately.
    if (request.entryId || request.previous) searchField.forceActiveFocus()
    if (root.mainWord) root.statusText = ""
    else if (root.relatedWords.length > 0)
      root.statusText = root.matchKind === "embedded"
        ? "Words found in the captured text"
        : "No exact entry for “" + root.resultQuery + "”. Related words:"
    else if (root.kanjiEntries.length > 0) root.statusText = "Kanji found in “" + root.resultQuery + "”"
    else root.statusText = "No matches. Try a shorter word or another reading."
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
    property bool cancelled: false
    stdout: StdioCollector { id: outCollector; waitForEnd: true }
    stderr: StdioCollector { id: errCollector; waitForEnd: true }
    onExited: function(exitCode) {
      var request = root.activeRequest
      root.activeRequest = null
      if (cancelled) {
        cancelled = false
        Qt.callLater(root.startPendingRequest)
        return
      }
      if (request) root.finishLookup(exitCode, request)
      Qt.callLater(root.startPendingRequest)
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

  // Emit framed state markers rather than raw selection bytes. wl-paste --watch
  // replays the current offer at startup; the first marker establishes a cold
  // baseline. Later changes refresh only their own source, while clear and
  // nil offers invalidate it. The keybind reads both candidates as text.
  Process {
    id: primaryWatch
    running: true
    command: ["wl-paste", "--primary", "--watch", "bash", root.scriptPath("selection-watch-event.sh")]
    stdout: SplitParser { onRead: function(data) { root.recordSelectionEvent("primary", data) } }
    onExited: {
      root.primarySelectionState = SelectionState.awaitingBaseline(root.primarySelectionState)
      primaryWatchRetry.start()
    }
  }

  Process {
    id: clipboardWatch
    running: true
    command: ["wl-paste", "--watch", "bash", root.scriptPath("selection-watch-event.sh")]
    stdout: SplitParser { onRead: function(data) { root.recordSelectionEvent("clipboard", data) } }
    onExited: {
      root.clipboardSelectionState = SelectionState.awaitingBaseline(root.clipboardSelectionState)
      clipboardWatchRetry.start()
    }
  }

  // A restarted watcher first replays current state. Re-arm baseline handling
  // so that replay does not refresh an old selection's timestamp.
  Timer {
    id: primaryWatchRetry
    interval: 5000
    onTriggered: {
      root.primarySelectionState = SelectionState.awaitingBaseline(root.primarySelectionState)
      primaryWatch.running = true
    }
  }
  Timer {
    id: clipboardWatchRetry
    interval: 5000
    onTriggered: {
      root.clipboardSelectionState = SelectionState.awaitingBaseline(root.clipboardSelectionState)
      clipboardWatch.running = true
    }
  }

  readonly property real searchToResultsGap: Style.space(12) + 4
  readonly property real naturalContentHeight: headerRow.height + Style.space(12)
    + searchRow.height + searchToResultsGap + resultColumn.implicitHeight
    + Style.space(16) + footer.height

  function revealResult(item) {
    if (!item) return
    var y = item.mapToItem(resultColumn, 0, 0).y
    if (y < resultScroll.contentY) resultScroll.contentY = y
    else if (y + item.height > resultScroll.contentY + resultScroll.height)
      resultScroll.contentY = Math.min(resultScroll.contentHeight - resultScroll.height,
        y + item.height - resultScroll.height)
  }

  function revealKanji(item) {
    if (!item) return
    var x = item.mapToItem(kanjiRow, 0, 0).x
    if (x < kanjiStrip.contentX) kanjiStrip.contentX = x
    else if (x + item.width > kanjiStrip.contentX + kanjiStrip.width)
      kanjiStrip.contentX = Math.min(kanjiStrip.contentWidth - kanjiStrip.width,
        x + item.width - kanjiStrip.width)
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: false
    focusTarget: searchField
    // Keep the gutter inside the interactive surface. Content owns its padding
    // so the scrollbar can sit beside it without falling outside a hit area.
    padding: 0
    contentWidth: panel.fittedContentWidth(Style.space(576))
    contentHeight: panel.fittedContentHeight(Math.max(Style.space(210),
      Math.min(root.naturalContentHeight, Style.space(680))) + 2 * Style.spacing.popupPadding)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      anchors.margins: Style.spacing.popupPadding
      blocked: true
      onCloseRequested: root.close()
      Keys.onEscapePressed: root.close()

      Item {
        anchors.fill: parent

        Row {
          id: headerRow
          anchors { top: parent.top; left: parent.left; right: parent.right }
          spacing: Style.space(8)

          Text {
            id: headerTitle
            text: "Kanji Lookup"
            textFormat: Text.PlainText
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.body + Style.space(2)
            font.bold: true
          }
          Text {
            anchors.baseline: headerTitle.baseline
            text: root.lookupBusy ? "Searching…" : "Offline dictionary"
            textFormat: Text.PlainText
            color: root.subtle
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Row {
          id: searchRow
          objectName: "lookupSearchRow"
          anchors { top: headerRow.bottom; topMargin: Style.space(12); left: parent.left; right: parent.right }
          spacing: Style.space(8)
          height: Math.max(Style.space(36), searchField.implicitHeight, captureButton.implicitHeight)

          TextField {
            id: searchField
            objectName: "lookupSearch"
            width: parent.width - captureButton.width - parent.spacing
            height: parent.height
            placeholderText: "Search a word or kanji…"
            foreground: root.fg
            accent: Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.body

            onTextChanged: {
              if (text.trim() === "") root.lookup("")
              else if (text !== root.lastQuery) {
                root.cancelLookup()
                root.statusText = "Searching…"
                debounce.restart()
              }
            }
            onAccepted: root.lookup(text)
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) { root.close(); event.accepted = true }
              else if (event.key === Qt.Key_Down && relatedRepeater.count > 0) {
                var first = relatedRepeater.itemAt(0)
                if (first) { first.forceActiveFocus(); root.revealResult(first) }
                event.accepted = true
              } else if (event.key === Qt.Key_PageDown || event.key === Qt.Key_PageUp) {
                resultScroll.contentY = Math.max(0, Math.min(
                  resultScroll.contentHeight - resultScroll.height,
                  resultScroll.contentY + (event.key === Qt.Key_PageDown ? 1 : -1) * resultScroll.height))
                event.accepted = true
              }
            }
          }

          Button {
            id: captureButton
            objectName: "lookupCapture"
            height: parent.height
            text: root.capturing ? "Capturing…" : "Capture"
            tooltipText: "Select text on your screen to capture with OCR"
            foreground: root.fg
            accent: Color.accent
            bordered: true
            focusable: true
            enabled: !root.capturing
            onClicked: root.capture()
            Keys.onEscapePressed: root.close()
          }
        }

        Item {
          id: body
          anchors { top: searchRow.bottom; topMargin: root.searchToResultsGap
                    bottom: footer.top; bottomMargin: Style.space(16)
                    left: parent.left; right: parent.right }

          Flickable {
            id: resultScroll
            objectName: "lookupBody"
            anchors.fill: parent
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            contentWidth: width
            contentHeight: resultColumn.implicitHeight
            ScrollBar.vertical: ScrollBar {
              id: verticalBar
              objectName: "lookupVerticalScroll"
              parent: keyCatcher.parent
              x: keyCatcher.x + body.x + body.width + Style.space(6)
              y: keyCatcher.y + body.y
              height: body.height
              policy: resultScroll.contentHeight > resultScroll.height + 1 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
              width: Style.space(4)
              padding: 0
              contentItem: Rectangle {
                radius: width / 2
                color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.35)
              }
            }

            Column {
              id: resultColumn
              objectName: "lookupResults"
              width: resultScroll.width
              spacing: Style.space(16)

              Text {
                id: statusLine
                width: parent.width
                visible: root.statusText !== ""
                text: root.statusText
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: root.secondary
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }

              Column {
                id: emptyState
                visible: searchField.text.trim() === "" && root.statusText === ""
                width: parent.width
                spacing: Style.space(5)
                Text {
                  text: "Japanese words & kanji"
                  textFormat: Text.PlainText
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
                Text {
                  width: parent.width
                  text: "Type a word or capture text from your screen."
                  textFormat: Text.PlainText
                  wrapMode: Text.Wrap
                  color: root.secondary
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
              }

              Column {
                id: kanjiSection
                objectName: "kanjiSection"
                width: parent.width
                visible: root.kanjiEntries.length > 0
                spacing: Style.space(8)
                opacity: root.lookupBusy ? 0.58 : 1

                Text {
                  text: "KANJI" + (root.kanjiEntries.length > 1 ? "  ·  " + root.kanjiEntries.length : "")
                  textFormat: Text.PlainText
                  color: root.subtle
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
                Flickable {
                  id: kanjiStrip
                  objectName: "kanjiStrip"
                  width: parent.width
                  height: Style.space(106) + (contentWidth > width + 1 ? Style.space(16) : 0)
                  clip: true
                  contentWidth: kanjiRow.implicitWidth
                  contentHeight: height
                  boundsBehavior: Flickable.StopAtBounds
                  flickableDirection: Flickable.HorizontalFlick
                  ScrollBar.horizontal: ScrollBar {
                    id: horizontalBar
                    objectName: "kanjiHorizontalScroll"
                    policy: kanjiStrip.contentWidth > kanjiStrip.width + 1 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                    // Use the full gutter for pointer input, with the thin
                    // thumb centered inside it instead of at the clip edge.
                    height: Style.space(16)
                    padding: 0
                    topPadding: (height - Style.space(6)) / 2
                    bottomPadding: topPadding
                    contentItem: Rectangle {
                      radius: height / 2
                      color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.35)
                    }
                  }
                  Row {
                    id: kanjiRow
                    spacing: Style.space(8)
                    Repeater {
                      id: kanjiRepeater
                      model: root.kanjiEntries
                      delegate: Rectangle {
                        required property var modelData
                        required property int index
                        objectName: "kanjiTile-" + index
                        width: root.kanjiEntries.length === 1 ? kanjiStrip.width
                          : root.kanjiEntries.length === 2
                            ? (index === 0 ? Math.floor((kanjiStrip.width - kanjiRow.spacing) / 2)
                              : kanjiStrip.width - kanjiRow.spacing - Math.floor((kanjiStrip.width - kanjiRow.spacing) / 2))
                            : Style.space(246)
                        height: Style.space(106)
                        radius: Style.cornerRadius
                        color: kanjiHover.hovered || activeFocus
                          ? Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.10)
                          : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.055)
                        border.width: activeFocus ? 1 : 0
                        border.color: Color.accent
                        activeFocusOnTab: true
                        onActiveFocusChanged: if (activeFocus) {
                          root.revealResult(kanjiSection)
                          root.revealKanji(this)
                        }

                        Text {
                          id: kanjiGlyph
                          anchors { left: parent.left; top: parent.top
                                    leftMargin: Style.space(12); topMargin: Style.space(10) }
                          text: modelData.char || ""
                          textFormat: Text.PlainText
                          color: root.fg
                          font.family: root.fontFamily
                          font.pixelSize: Style.space(34)
                        }
                        Column {
                          objectName: "kanjiDetails-" + index
                          anchors { left: kanjiGlyph.right; leftMargin: Style.space(8)
                                    right: parent.right; rightMargin: Style.space(12)
                                    top: parent.top; topMargin: Style.space(12) }
                          spacing: Style.space(2)
                          Text {
                            width: parent.width
                            text: modelData.unavailable ? "Details unavailable" :
                              String(modelData.meanings || "").replace(/;/g, ", ")
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                            color: root.fg
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.bodySmall
                            font.bold: true
                          }
                          Text {
                            width: parent.width
                            visible: text !== ""
                            text: modelData.on ? "ON " + String(modelData.on).replace(/;/g, "、") : ""
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.secondary
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                          }
                          Text {
                            width: parent.width
                            visible: text !== ""
                            text: modelData.kun ? "KUN " + String(modelData.kun).replace(/;/g, "、") : ""
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.secondary
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                          }
                        }
                        Text {
                          objectName: "kanjiMeta-" + index
                          anchors { left: parent.left; leftMargin: Style.space(12)
                                    right: parent.right; rightMargin: Style.space(12)
                                    bottom: parent.bottom; bottomMargin: Style.space(12) }
                          text: [modelData.strokes != null ? modelData.strokes + " strokes" : "",
                            modelData.grade != null ? "Grade " + modelData.grade : "",
                            modelData.jlpt != null ? "N" + modelData.jlpt : ""].filter(Boolean).join("  ·  ")
                          textFormat: Text.PlainText
                          elide: Text.ElideRight
                          color: root.subtle
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                        }
                        HoverHandler { id: kanjiHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { enabled: !root.lookupBusy; onTapped: root.focusKanji(modelData.char) }
                        Keys.onReturnPressed: root.focusKanji(modelData.char)
                        Keys.onEnterPressed: root.focusKanji(modelData.char)
                        Keys.onSpacePressed: root.focusKanji(modelData.char)
                        Keys.onEscapePressed: root.close()
                        PanelToolTip {
                          id: kanjiTip
                          visible: kanjiHover.hovered
                          text: [modelData.char || "", modelData.meanings ? String(modelData.meanings).replace(/;/g, ", ") : "Details unavailable",
                            modelData.on ? "ON: " + String(modelData.on).replace(/;/g, "、") : "",
                            modelData.kun ? "KUN: " + String(modelData.kun).replace(/;/g, "、") : "",
                            modelData.jlpt != null ? "Estimated JLPT N" + modelData.jlpt + " · community study list" : ""].filter(Boolean).join("\n")
                          fontFamily: root.fontFamily
                          contentItem: Text {
                            text: kanjiTip.text
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            width: Math.min(Style.space(360), panel.contentWidth - Style.space(20))
                            color: Color.tooltip.text
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.bodySmall
                            padding: Style.spacing.controlPaddingX
                          }
                        }
                      }
                    }
                  }
                }
              }

              Rectangle {
                id: focusedCard
                objectName: "focusedCard"
                visible: root.mainWord !== null
                width: parent.width
                height: visible ? focusedContent.implicitHeight + Style.space(24) : 0
                radius: Style.cornerRadius
                color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.065)
                opacity: root.lookupBusy ? 0.65 : 1

                Column {
                  id: focusedContent
                  objectName: "focusedContent"
                  anchors { left: parent.left; right: parent.right; top: parent.top; margins: Style.space(12) }
                  spacing: Style.space(8)
                  Column {
                    width: parent.width
                    spacing: Style.space(1)
                    Text {
                      text: root.mainWord ? root.mainWord.term : ""
                      width: parent.width
                      textFormat: Text.PlainText
                      wrapMode: Text.Wrap
                      color: root.fg
                      font.family: root.fontFamily
                      font.pixelSize: Style.space(30)
                      font.bold: true
                    }
                    Text {
                      visible: text !== ""
                      text: root.mainWord && root.mainWord.reading !== root.mainWord.term ? root.mainWord.reading : ""
                      width: parent.width
                      textFormat: Text.PlainText
                      wrapMode: Text.Wrap
                      color: root.secondary
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body + Style.space(1)
                    }
                  }
                  Text {
                    text: root.mainWord ? root.mainWord.glosses.split(" | ").map(function(sense, index, senses) {
                      return senses.length > 1 ? (index + 1) + ". " + sense : sense
                    }).join("\n") : ""
                    width: parent.width
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    lineHeight: 1.15
                  }
                }
              }

              Column {
                id: relatedSection
                objectName: "relatedSection"
                visible: root.relatedWords.length > 0
                width: parent.width
                spacing: Style.space(8)
                opacity: root.lookupBusy ? 0.6 : 1
                Text {
                  text: root.mainWord ? "RELATED WORDS" : "MATCHING WORDS"
                  textFormat: Text.PlainText
                  color: root.subtle
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
                Column {
                  width: parent.width
                  spacing: 0
                  Repeater {
                    id: relatedRepeater
                    model: root.relatedWords
                    delegate: Rectangle {
                      required property var modelData
                      required property int index
                      objectName: "relatedWord-" + index
                      width: relatedSection.width
                      height: Math.max(Style.space(52), relatedContent.implicitHeight + Style.space(16))
                      radius: Style.cornerRadius
                      color: relatedHover.hovered || activeFocus
                        ? Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.085) : "transparent"
                      border.width: activeFocus ? 1 : 0
                      border.color: Color.accent
                      activeFocusOnTab: true
                      onActiveFocusChanged: if (activeFocus) root.revealResult(this)

                      Column {
                        id: relatedContent
                        anchors { left: parent.left; right: parent.right
                                  leftMargin: Style.space(12); rightMargin: Style.space(12)
                                  verticalCenter: parent.verticalCenter }
                        spacing: Style.space(3)
                        Row {
                          id: relatedHeading
                          objectName: "relatedHeading-" + index
                          width: parent.width
                          spacing: Style.space(8)
                          Text {
                            id: relatedTerm
                            width: Math.min(implicitWidth, relatedHeading.width * 0.58)
                            text: modelData.term || ""
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.fg
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.bodySmall + Style.space(1)
                            font.bold: true
                          }
                          Text {
                            anchors.baseline: relatedTerm.baseline
                            width: Math.max(0, relatedHeading.width - relatedTerm.width - relatedHeading.spacing)
                            text: modelData.reading === modelData.term ? "" : (modelData.reading || "")
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.secondary
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.bodySmall
                          }
                        }
                        Text {
                          id: relatedGloss
                          objectName: "relatedGloss-" + index
                          width: parent.width
                          text: modelData.glosses || ""
                          textFormat: Text.PlainText
                          elide: Text.ElideRight
                          color: root.secondary
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.bodySmall
                        }
                      }
                      HoverHandler { id: relatedHover; cursorShape: Qt.PointingHandCursor }
                      TapHandler { enabled: !root.lookupBusy; onTapped: root.focusWord(modelData) }
                      Keys.onReturnPressed: root.focusWord(modelData)
                      Keys.onEnterPressed: root.focusWord(modelData)
                      Keys.onSpacePressed: root.focusWord(modelData)
                      Keys.onEscapePressed: root.close()
                      Keys.onDownPressed: {
                        var next = relatedRepeater.itemAt(Math.min(index + 1, relatedRepeater.count - 1))
                        if (next) { next.forceActiveFocus(); root.revealResult(next) }
                      }
                      Keys.onUpPressed: {
                        if (index === 0) searchField.forceActiveFocus()
                        else {
                          var previous = relatedRepeater.itemAt(index - 1)
                          if (previous) { previous.forceActiveFocus(); root.revealResult(previous) }
                        }
                      }
                      PanelToolTip {
                        id: relatedTip
                        visible: relatedHover.hovered && relatedGloss.truncated
                        text: modelData.glosses || ""
                        fontFamily: root.fontFamily
                        contentItem: Text {
                          text: relatedTip.text
                          textFormat: Text.PlainText
                          wrapMode: Text.Wrap
                          width: Math.min(Style.space(430), panel.contentWidth - Style.space(20))
                          color: Color.tooltip.text
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.bodySmall
                          padding: Style.spacing.controlPaddingX
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }

        Item {
          id: footer
          objectName: "lookupFooter"
          anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
          height: Math.max(Style.space(38), closeHint.implicitHeight + Style.space(24))

          Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 1
            color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.16)
          }
          Text {
            anchors { left: parent.left; top: parent.top; topMargin: Style.space(12) }
            width: Math.max(0, footer.width - closeHint.width - Style.space(12))
            text: root.shortcutLabel !== "" ? "Shortcut  " + root.shortcutLabel : "No shortcut detected"
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.shortcutLabel !== "" ? root.secondary : root.subtle
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            id: closeHint
            anchors { right: parent.right; top: parent.top; topMargin: Style.space(12) }
            text: "Esc  Close"
            textFormat: Text.PlainText
            color: root.subtle
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }
      }
    }
  }
}
