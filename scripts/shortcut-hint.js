.pragma library

// Keep the supported Hyprland modifier mask deliberately small. Bindings with
// additional modifier bits cannot be represented faithfully, so skip them.
var KNOWN_MODIFIER_MASK = 1 | 4 | 8 | 64
var MODIFIERS = [
  { bit: 64, label: "Super" },
  { bit: 4, label: "Ctrl" },
  { bit: 8, label: "Alt" },
  { bit: 1, label: "Shift" }
]
var PLUGIN_ID = "io.github.expri-commits.kanji-lookup"
var ALLOWED_ACTIONS = ["smarttrigger", "lookup", "open", "show", "toggle"]
var NAMED_KEYS = {
  return: "Return", enter: "Enter", space: "Space", tab: "Tab",
  escape: "Escape", backspace: "Backspace", delete: "Delete",
  insert: "Insert", home: "Home", end: "End", page_up: "Page Up",
  page_down: "Page Down", left: "Left", right: "Right", up: "Up",
  down: "Down", print: "Print", pause: "Pause", menu: "Menu"
}

function readableKey(rawKey) {
  if (typeof rawKey !== "string") return ""
  var key = rawKey.trim()
  if (Array.from(key).length === 1) return key.toUpperCase()
  var lower = key.toLowerCase()
  if (Object.prototype.hasOwnProperty.call(NAMED_KEYS, lower)) return NAMED_KEYS[lower]
  if (/^f(?:[1-9]|[12][0-9]|3[0-5])$/i.test(key)) return key.toUpperCase()
  return ""
}

function shortcutForBinding(binding) {
  if (!binding || typeof binding !== "object" || binding.mouse === true
      || binding.submap) return null

  // Hyprland reports key names for key bindings. Do not turn keycodes or
  // mouse bindings into a misleading printable shortcut.
  var key = readableKey(binding.key)
  if (!key) return null

  var mask = Number(binding.modmask)
  if (!isFinite(mask) || mask < 0 || Math.floor(mask) !== mask
      || (mask & ~KNOWN_MODIFIER_MASK) !== 0) return null

  var parts = []
  for (var i = 0; i < MODIFIERS.length; i++)
    if ((mask & MODIFIERS[i].bit) !== 0) parts.push(MODIFIERS[i].label)
  parts.push(key)
  return parts.join("+")
}

function actionForBinding(binding) {
  if (!binding || typeof binding !== "object") return ""
  var dispatcher = String(binding.dispatcher || "").trim().toLowerCase()
  var description = String(binding.description || "").trim().toLowerCase()
  if (dispatcher === "__lua" && description === "kanji lookup")
    return "smarttrigger"
  if (dispatcher !== "exec" && dispatcher !== "execr") return ""

  // Require the shell call, plugin id, and action to appear as one command
  // sequence. This avoids unrelated output/path text that happens to mention
  // the plugin name plus a word such as "lookup".
  var arg = String(binding.arg || "")
  var pluginId = PLUGIN_ID.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  var actions = ALLOWED_ACTIONS.join("|")
  var commandPattern = new RegExp(
    "(?:^|[;&|\\s])(?:[^\\s;&|]*/)?omarchy-shell(?:\\s+-q)?\\s+[\\\"']?"
      + pluginId + "[\\\"']?\\s+[\\\"']?(" + actions + ")(?:[\\\"']?(?:\\s|$))",
    "i")
  var match = commandPattern.exec(arg)
  if (match) return match[1].toLowerCase()
  return ""
}

function priority(action) {
  if (action === "smarttrigger") return 0
  if (action === "lookup") return 1
  if (action === "toggle") return 2
  return 3 // open/show
}

// Return a single stable, useful shortcut. A Lua-backed binding is recognized
// through its exact human description because Hyprland hides its Lua callback.
function findShortcut(jsonText) {
  var binds
  try {
    var parsed = JSON.parse(String(jsonText || ""))
    if (!Array.isArray(parsed)) return ""
    binds = parsed
  } catch (error) {
    return ""
  }

  var candidates = []
  for (var i = 0; i < binds.length; i++) {
    var action = actionForBinding(binds[i])
    if (!action) continue
    var shortcut = shortcutForBinding(binds[i])
    if (shortcut) candidates.push({ action: action, shortcut: shortcut })
  }
  candidates.sort(function(a, b) {
    var rank = priority(a.action) - priority(b.action)
    if (rank !== 0) return rank
    return a.shortcut < b.shortcut ? -1 : (a.shortcut > b.shortcut ? 1 : 0)
  })
  return candidates.length ? candidates[0].shortcut : ""
}
