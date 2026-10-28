// Minimal hash router: #/, #/briefs, #/briefs/:id, #/items, #/runs,
// #/runs/:id, #/sources, #/settings. No history API usage (same-origin
// static server with client-side routing only).

const { reactive } = Vue;

function parseHash() {
  let h = location.hash || '#/';
  h = h.slice(1);
  if (!h.startsWith('/')) h = `/${h}`;
  const [pathPart, queryPart] = h.split('?');
  const segments = pathPart.split('/').filter(Boolean);
  const query = Object.fromEntries(new URLSearchParams(queryPart || ''));
  return { segments, query };
}

function matchRoute(segments) {
  if (segments.length === 0) return { name: 'live', params: {} };
  const [first, second] = segments;
  switch (first) {
    case 'briefs':
      return second ? { name: 'brief', params: { id: second } } : { name: 'briefs', params: {} };
    case 'items':
      return { name: 'items', params: {} };
    case 'runs':
      return second ? { name: 'run', params: { id: second } } : { name: 'runs', params: {} };
    case 'sources':
      return { name: 'sources', params: {} };
    case 'settings':
      return { name: 'settings', params: {} };
    default:
      return { name: 'notfound', params: {} };
  }
}

function resolve() {
  const { segments, query } = parseHash();
  return { ...matchRoute(segments), query };
}

export const route = reactive(resolve());

window.addEventListener('hashchange', () => {
  Object.assign(route, resolve());
});

export function navigate(path) {
  location.hash = path.startsWith('#') ? path : `#${path}`;
}
