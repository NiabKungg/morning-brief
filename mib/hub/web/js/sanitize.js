// Sanitizer for Telegram's bot HTML parse-mode subset:
// b, i, u, s, a, code, pre, blockquote — `a` may only carry an http(s) href.
// Strategy: escape every character by default; only re-open a tag when it
// is unambiguously one of the allowed names (immediately following `<` or
// `</`, no stray characters). Unknown tags are dropped (their text content
// still streams through as escaped text). Safe to feed straight into v-html.
//
// The server already sends valid HTML entities for the 4 characters
// Telegram's HTML mode supports (&lt; &gt; &amp; &quot;) wherever it means a
// literal character rather than markup. Those must pass through unchanged
// (re-escaping the leading `&` would double-escape, e.g. "&amp;" -> "&amp;amp;").
// Any other `&` is a bare ampersand and gets escaped defensively.

const ALLOWED = new Set(['b', 'i', 'u', 's', 'a', 'code', 'pre', 'blockquote']);
const ENTITY_RE = /^&(?:lt|gt|amp|quot);/;

function escapeChar(c) {
  if (c === '&') return '&amp;';
  if (c === '<') return '&lt;';
  if (c === '>') return '&gt;';
  return c;
}

export function sanitizeTelegramHtml(raw) {
  const text = String(raw ?? '');
  let out = '';
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (c === '&') {
      const m = ENTITY_RE.exec(text.slice(i, i + 6));
      if (m) {
        out += m[0]; // already a valid entity - pass through, don't double-escape
        i += m[0].length;
      } else {
        out += '&amp;'; // bare ampersand
        i++;
      }
      continue;
    }
    if (c !== '<') {
      out += escapeChar(c);
      i++;
      continue;
    }
    const close = text.indexOf('>', i);
    const tagContent = close === -1 ? '' : text.slice(i + 1, close);
    const m = close === -1 ? null : /^(\/?)([a-zA-Z][a-zA-Z0-9]*)/.exec(tagContent);
    if (!m) {
      out += '&lt;';
      i++;
      continue;
    }
    const isClosing = m[1] === '/';
    const tagName = m[2].toLowerCase();
    if (ALLOWED.has(tagName)) {
      if (tagName === 'a' && !isClosing) {
        const hrefMatch = /href\s*=\s*"([^"]*)"/i.exec(tagContent) || /href\s*=\s*'([^']*)'/i.exec(tagContent);
        // The captured value is already HTML-attribute-escaped by the server
        // (that's why the regex could stop at the first literal quote); emit
        // it as-is rather than re-escaping, which would double-escape any
        // "&amp;" already inside a query string.
        const href = hrefMatch ? hrefMatch[1] : '';
        out += /^https?:\/\//i.test(href) ? `<a href="${href}" target="_blank" rel="noopener noreferrer">` : '<a>';
      } else {
        out += isClosing ? `</${tagName}>` : `<${tagName}>`;
      }
    }
    // Unknown tag: drop the wrapper, its text content still streams through.
    i = close + 1;
  }
  return out;
}
