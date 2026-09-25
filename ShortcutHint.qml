import QtQuick
import Quickshell.Io
import "scripts/shortcut-hint.js" as ShortcutHint

// Invisible helper for showing the current Hyprland keybind in the bar.
// Bind active to the panel's opened state; no polling is performed.
Item {
  id: root
  visible: false
  width: 0
  height: 0

  property bool active: false
  // Display-only escape hatch for shell/Lua bindings the parser cannot infer.
  // It never creates or changes a Hyprland binding.
  property string overrideLabel: ""
  readonly property string label: overrideLabel.trim() || detectedLabel
  property string detectedLabel: ""
  property bool retryAfterExit: false

  function refresh() {
    if (bindsProc.running) {
      retryAfterExit = true
      return
    }
    bindsProc.command = ["hyprctl", "-j", "binds"]
    bindsProc.running = true
  }

  Component.onCompleted: refresh()
  onActiveChanged: if (active) refresh()

  Process {
    id: bindsProc
    stdout: StdioCollector { id: bindsOutput; waitForEnd: true }
    stderr: StdioCollector { id: bindsError; waitForEnd: true }
    onExited: function(exitCode) {
      if (root.retryAfterExit) {
        root.retryAfterExit = false
        root.refresh()
        return
      }
      root.detectedLabel = exitCode === 0
        ? ShortcutHint.findShortcut(String(bindsOutput.text || ""))
        : ""
    }
  }
}
