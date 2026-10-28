// Tolerant partial-JSON parser for progressively rendering a streaming LLM
// JSON payload. Tracks string/escape state and the open-bracket stack so it
// can close whatever is currently open, then falls back to trimming trailing
// punctuation / characters until `JSON.parse` succeeds. Always non-throwing.

function scanState(s) {
  const stack = [];
  let inString = false;
  let escape = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inString) {
      if (escape) escape = false;
      else if (c === '\\') escape = true;
      else if (c === '"') inString = false;
    } else if (c === '"') inString = true;
    else if (c === '{' || c === '[') stack.push(c);
    else if (c === '}' || c === ']') stack.pop();
  }
  return { stack, inString };
}

function closeBuffer(s) {
  const { stack, inString } = scanState(s);
  let out = s;
  if (inString) out += '"';
  for (let i = stack.length - 1; i >= 0; i--) out += stack[i] === '{' ? '}' : ']';
  return out;
}

// Drops a single trailing ",' or ':' (outside strings, ignoring trailing
// whitespace) that would otherwise leave a dangling key/value when closed.
function trimTrailingPunct(s) {
  let i = s.length - 1;
  while (i >= 0 && /\s/.test(s[i])) i--;
  if (i >= 0 && (s[i] === ',' || s[i] === ':')) return s.slice(0, i);
  return null;
}

/**
 * Creates a stateful parser: each call feeds the *full* buffer accumulated
 * so far (not just the delta) and returns the best-effort parsed value, or
 * the previous successfully parsed value if nothing new parses yet.
 */
export function makePartialJsonParser() {
  let lastGood = null;
  return function parsePartial(buffer) {
    let s = buffer;
    for (let attempts = 0; attempts < 60; attempts++) {
      if (s.length === 0) break;
      try {
        lastGood = JSON.parse(closeBuffer(s));
        return lastGood;
      } catch {
        const trimmed = trimTrailingPunct(s);
        s = trimmed !== null ? trimmed : s.slice(0, -1);
      }
    }
    return lastGood;
  };
}
