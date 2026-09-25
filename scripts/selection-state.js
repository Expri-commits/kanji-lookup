.pragma library

// wl-paste --watch replays the current offer when a watcher starts. Consume
// that first callback as a baseline so it cannot make an old selection fresh.
function applyWatchEvent(state, event, now) {
  var waiting = !!(state && state.awaitingBaseline)
  if (waiting) {
    return {
      at: Number(state.at) || 0,
      valid: !!state.valid,
      awaitingBaseline: false
    }
  }

  var hasData = String(event || "").trim() === "data"
  return {
    at: hasData ? now : 0,
    valid: hasData,
    awaitingBaseline: false
  }
}

function awaitingBaseline(state) {
  return { at: 0, valid: false, awaitingBaseline: true }
}

function fresh(at, now, maxAge) {
  var age = now - at
  return at > 0 && age >= 0 && age < maxAge
}

// Values are read by the keybind at trigger time. Their matching timestamps
// are tracked independently so a fresh clipboard copy can never bless stale
// primary-selection text (or vice versa).
function choose(primaryText, clipboardText, primaryAt, clipboardAt, now, maxAge) {
  var primary = String(primaryText || "").trim()
  var clipboard = String(clipboardText || "").trim()
  var primaryFresh = fresh(primaryAt, now, maxAge)
  var clipboardFresh = fresh(clipboardAt, now, maxAge)

  // The newest changed source wins even if its text-mode read is empty (for
  // example, the user copied an image). Falling back would use older text.
  if (primaryFresh && clipboardFresh && clipboardAt > primaryAt)
    return clipboard ? { text: clipboard, source: "clipboard" } : null
  if (primaryFresh) return primary ? { text: primary, source: "primary" } : null
  if (clipboardFresh) return clipboard ? { text: clipboard, source: "clipboard" } : null
  return null
}
