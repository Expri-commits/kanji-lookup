// Keep the word just left at the front so each promotion can be reversed.
// IDs, rather than displayed spellings, distinguish homonyms.
function relatedAfterFocus(previous, main, candidates, limit) {
  var result = []
  var seen = {}
  var max = Math.max(0, limit || 25)
  if (main && main.id) seen[String(main.id)] = true

  function append(word) {
    if (!word || !word.id || result.length >= max) return
    var id = String(word.id)
    if (seen[id]) return
    seen[id] = true
    result.push(word)
  }

  append(previous)
  for (var i = 0; i < (candidates || []).length; i++) append(candidates[i])
  return result
}
