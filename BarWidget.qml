import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Kanji Lookup's bar button: the 辞 glyph opens the dictionary popup. Panel
// lifecycle, summon routing, and IPC follow the clock's shape.
BarWidget {
  id: root
  moduleName: "io.github.expri-commits.kanji-lookup"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  // Shape contract for shell.summon/hide/toggle routing: Bar.findPanelWidget
  // requires open/close/opened on the bar-widget root.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  function togglePanel() {
    if (panelLoader.item) panelLoader.item.toggle()
  }

  // Forwarded so this widget can stand in for the panel as the bar's popout
  // identity: Bar.requestPopout prefers closeForPopoutSwitch over close, and
  // KeyboardPanel reads popoutSwitchClosing back off its owner.
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "io.github.expri-commits.kanji-lookup"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.togglePanel() }

    // Open the panel pre-filled and looking up `query` right away.
    function lookup(query: string): void {
      root.open()
      if (panelLoader.item) panelLoader.item.searchFor(query)
    }

    // Keybind entry: look up `query` only when a selection/clipboard change
    // happened within the recency window (the user just selected or copied
    // it); otherwise open the panel and start the screen-OCR capture.
    function smartTrigger(query: string): void {
      root.open()
      if (panelLoader.item) panelLoader.item.smartTrigger(query)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "辞"
    tooltipText: "Kanji Lookup — Japanese dictionary"

    onPressed: function(b) {
      if (b === Qt.LeftButton) root.togglePanel()
    }
  }
}
