// Thin REST client + SSE connector for the MIB hub API. No framework deps.

const BASE = '/api';

function cleanParams(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj || {})) {
    if (v !== undefined && v !== null && v !== '') out[k] = v;
  }
  return out;
}

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json', ...(options.headers || {}) } : options.headers,
  });
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const detail = (data && (data.detail || data.error)) || res.statusText || `HTTP ${res.status}`;
    const err = new Error(detail);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  getState: () => request('/state'),
  getRuns: (limit = 20) => request(`/runs?${new URLSearchParams(cleanParams({ limit }))}`),
  getRun: (id) => request(`/runs/${id}`),
  createRun: (kind, params = {}) => request('/runs', { method: 'POST', body: JSON.stringify({ kind, params }) }),
  cancelRun: (id) => request(`/runs/${id}/cancel`, { method: 'POST' }),
  getItems: (params = {}) => request(`/items?${new URLSearchParams(cleanParams(params))}`),
  getBriefs: (params = {}) => request(`/briefs?${new URLSearchParams(cleanParams(params))}`),
  getBrief: (id) => request(`/briefs/${id}`),
  deliverBrief: (id) => request(`/briefs/${id}/deliver`, { method: 'POST' }),
  getSettings: () => request('/settings'),
  putSettings: (patch) => request('/settings', { method: 'PUT', body: JSON.stringify(patch) }),
  testDelivery: () => request('/delivery/test', { method: 'POST' }),
};

/**
 * Opens the hub's SSE stream. `onEvent` receives each parsed message
 * (`{type, ...}`); `onStatus` receives 'connecting' | 'open' | 'closed'.
 * EventSource auto-reconnects on its own; every reconnect yields a fresh
 * 'snapshot' message per the contract, so no manual retry logic is needed.
 */
export function connectEvents(onEvent, onStatus) {
  const es = new EventSource(`${BASE}/events`);
  es.onopen = () => onStatus('open');
  es.onerror = () => onStatus(es.readyState === EventSource.CLOSED ? 'closed' : 'connecting');
  es.onmessage = (ev) => {
    try {
      onEvent(JSON.parse(ev.data));
    } catch {
      // ignore malformed/comment-only messages
    }
  };
  return () => es.close();
}
