// Central reactive state: SSE connection, global hub/worker/llm snapshot,
// toast notifications, a shared ticking clock, and the `createTimeline()`
// factory used by both the Live view (current run) and the Run detail view
// (replay of a persisted run's events).

import { api, connectEvents } from './api.js';
import { makePartialJsonParser } from './partial-json.js';

const { reactive, ref } = Vue;

// ---------------------------------------------------------------- toasts --
export const toasts = reactive([]);
let toastSeq = 1;
export function pushToast(message, type = 'info', timeout = 4500) {
  const id = toastSeq++;
  toasts.push({ id, message, type });
  if (timeout) setTimeout(() => dismissToast(id), timeout);
  return id;
}
export function dismissToast(id) {
  const i = toasts.findIndex((t) => t.id === id);
  if (i !== -1) toasts.splice(i, 1);
}

// ------------------------------------------------------------------ clock --
export const clock = ref(Date.now());
setInterval(() => {
  clock.value = Date.now();
}, 1000);

// ------------------------------------------------------------ global state --
export const state = reactive({
  ready: false,
  connected: 'connecting', // connecting | open | closed
  now: null,
  tz: 'UTC',
  hub: { host: '', model: '', sys: null },
  workers: [],
  llm: { online: false, model: '', ctx: 0, busy: false, last: null },
  delivery: { telegram: false, discord: false },
  schedule: { enabled: false, collect_times: [], brief_time: null, next: [] },
  active_run: null,
  latest_brief: null,
  stats: { items_24h: 0, items_total: 0, briefs: 0 },
  telegram: { enabled: false, token_set: false, bot_username: null, polling: false, chat_id: null, chat_title: null, error: null, link_url: null },
});

// Most recently touched run regardless of status, so the Live view keeps
// showing a finished run's final state instead of going blank.
export const lastRun = ref(null);

export const runsCache = reactive({});

const HISTORY_CAP = 60;
export const cpuHistory = reactive({ hub: [], workers: {} });
function pushHistory(arr, v) {
  arr.push(typeof v === 'number' && !Number.isNaN(v) ? v : 0);
  if (arr.length > HISTORY_CAP) arr.splice(0, arr.length - HISTORY_CAP);
}

const listeners = new Set();
/** Subscribe to every raw SSE event (after global state has been updated). */
export function onEvent(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function applySnapshot(s) {
  state.now = s.now;
  state.tz = s.tz;
  state.hub = s.hub;
  state.workers = s.workers || [];
  state.llm = s.llm;
  state.delivery = s.delivery;
  state.schedule = s.schedule;
  state.active_run = s.active_run;
  state.latest_brief = s.latest_brief;
  state.stats = s.stats;
  if (s.telegram) state.telegram = s.telegram;
  state.ready = true;
  if (s.active_run) {
    runsCache[s.active_run.id] = s.active_run;
    lastRun.value = s.active_run;
  }
}

function handleGlobal(evt) {
  switch (evt.type) {
    case 'snapshot':
      applySnapshot(evt.state);
      break;
    case 'worker': {
      const idx = state.workers.findIndex((w) => w.id === evt.worker.id);
      if (idx === -1) state.workers.push(evt.worker);
      else state.workers[idx] = evt.worker;
      const arr = cpuHistory.workers[evt.worker.id] || (cpuHistory.workers[evt.worker.id] = []);
      pushHistory(arr, evt.worker.sys && evt.worker.sys.cpu_pct);
      break;
    }
    case 'hub':
      state.hub = { ...state.hub, sys: evt.sys };
      state.llm = evt.llm;
      pushHistory(cpuHistory.hub, evt.sys && evt.sys.cpu_pct);
      break;
    case 'run':
      runsCache[evt.run.id] = evt.run;
      lastRun.value = evt.run;
      if (evt.run.status === 'running' || evt.run.status === 'queued') {
        state.active_run = evt.run;
      } else if (state.active_run && state.active_run.id === evt.run.id) {
        state.active_run = null;
      }
      break;
    case 'brief':
      state.latest_brief = evt.brief;
      break;
    case 'telegram':
      state.telegram = evt.telegram;
      break;
    default:
      break;
  }
}

let started = false;
export function initConnection() {
  if (started) return;
  started = true;
  connectEvents(
    (evt) => {
      handleGlobal(evt);
      listeners.forEach((fn) => fn(evt));
    },
    (status) => {
      state.connected = status;
    },
  );
}

// ------------------------------------------------------------- run timeline --
const SOURCE_GROUP_ORDER = ['rss', 'github', 'reddit', 'markets', 'calendar'];

function mergeDelivery(existing, results) {
  const out = { ...(existing || {}) };
  const at = new Date().toISOString();
  for (const r of results) out[r.channel] = { ok: r.ok, error: r.error, at };
  return out;
}

/**
 * Creates a self-contained, mutable "timeline" of one run's live feeds:
 * sources, items (triage merged in place), crawl pages, log lines, LLM
 * phase blocks (console text + stats) and the progressively-parsed brief
 * preview. Used both for the Live view's active run and for replaying a
 * finished/active run's persisted events on the Run detail page.
 */
export function createTimeline() {
  const run = ref(null);
  const sources = ref([]);
  const items = ref([]);
  const pages = ref([]);
  const logs = ref([]);
  const llmPhases = ref([]);
  const brief = reactive({ partialText: '', partialDoc: null, summary: null, full: null });

  let itemIndex = new Map();
  let parsePartial = makePartialJsonParser();
  let lastParseAt = 0;
  let loadingId = null;
  let buffer = null;
  let loadGen = 0;

  function reset(r) {
    run.value = r || null;
    sources.value = [];
    items.value = [];
    pages.value = [];
    logs.value = [];
    llmPhases.value = [];
    brief.partialText = '';
    brief.partialDoc = null;
    brief.summary = null;
    brief.full = null;
    itemIndex = new Map();
    parsePartial = makePartialJsonParser();
    lastParseAt = 0;
  }

  function currentOpenPhase(phase) {
    for (let i = llmPhases.value.length - 1; i >= 0; i--) {
      if (llmPhases.value[i].phase === phase && !llmPhases.value[i].endedAt) return llmPhases.value[i];
    }
    return null;
  }

  function addItem(raw) {
    const existing = itemIndex.get(raw.id);
    if (existing) {
      Object.assign(existing, raw);
      return;
    }
    const rec = reactive({ triage: null, summary: '', metrics: {}, ...raw });
    itemIndex.set(raw.id, rec);
    items.value.unshift(rec);
    if (items.value.length > 300) {
      for (const removed of items.value.splice(300)) itemIndex.delete(removed.id);
    }
  }

  function apply(evt, opts) {
    if (opts && opts.live && loadingId !== null) {
      buffer.push(evt);
      return;
    }
    switch (evt.type) {
      case 'run':
        run.value = evt.run;
        break;
      case 'log': {
        const last = logs.value[logs.value.length - 1];
        if (last && last.ts === evt.ts && last.msg === evt.msg && last.origin === evt.origin) break;
        logs.value.push(evt);
        if (logs.value.length > 500) logs.value.splice(0, logs.value.length - 500);
        break;
      }
      case 'source': {
        const idx = sources.value.findIndex((s) => s.key === evt.key);
        const rec = {
          key: evt.key,
          group: evt.group,
          name: evt.name,
          status: evt.status,
          count: evt.count,
          new: evt.new,
          ms: evt.ms,
          error: evt.error,
        };
        if (idx === -1) sources.value.push(rec);
        else sources.value[idx] = rec;
        break;
      }
      case 'item':
        addItem(evt.item);
        break;
      case 'page':
        pages.value.unshift(evt);
        if (pages.value.length > 200) pages.value.splice(200);
        break;
      case 'triage':
        for (const r of evt.results) {
          const it = itemIndex.get(r.item_id);
          if (it) it.triage = { score: r.score, keep: r.keep, category: r.category, reason: r.reason };
        }
        break;
      case 'llm': {
        if (evt.event === 'start') {
          const blk = reactive({
            phase: evt.phase,
            label: evt.label,
            text: '',
            startedAt: Date.now(),
            endedAt: null,
            stats: null,
            approxTokens: 0,
          });
          llmPhases.value.push(blk);
          if (llmPhases.value.length > 40) llmPhases.value.splice(0, llmPhases.value.length - 40);
        } else if (evt.event === 'token') {
          let blk = currentOpenPhase(evt.phase);
          if (!blk) {
            blk = reactive({ phase: evt.phase, label: evt.phase, text: '', startedAt: Date.now(), endedAt: null, stats: null, approxTokens: 0 });
            llmPhases.value.push(blk);
          }
          blk.text += evt.text;
          blk.approxTokens += Math.max(1, Math.round(evt.text.length / 4));
          if (evt.phase === 'synth' || evt.phase === 'web') {
            brief.partialText += evt.text;
            const now = performance.now();
            if (now - lastParseAt > 95) {
              lastParseAt = now;
              const parsed = parsePartial(brief.partialText);
              if (parsed) brief.partialDoc = parsed;
            }
          }
        } else if (evt.event === 'end') {
          let blk = currentOpenPhase(evt.phase);
          if (!blk) {
            // Replay: only "end" events are persisted (no start/token), so
            // each one becomes its own standalone console line.
            blk = reactive({
              phase: evt.phase,
              label: evt.phase,
              text: '',
              startedAt: Date.now(),
              endedAt: null,
              stats: null,
              approxTokens: 0,
            });
            llmPhases.value.push(blk);
          }
          blk.endedAt = Date.now();
          blk.stats = evt.stats;
          if (evt.phase === 'synth' || evt.phase === 'web') {
            const parsed = parsePartial(brief.partialText);
            if (parsed) brief.partialDoc = parsed;
          }
        }
        break;
      }
      case 'brief':
        brief.summary = evt.brief;
        api
          .getBrief(evt.brief.id)
          .then((res) => {
            brief.full = res.brief;
          })
          .catch(() => {});
        break;
      case 'delivery':
        if (brief.full && brief.full.id === evt.brief_id) brief.full = { ...brief.full, delivery: mergeDelivery(brief.full.delivery, evt.results) };
        if (brief.summary && brief.summary.id === evt.brief_id) brief.summary = { ...brief.summary, delivery: mergeDelivery(brief.summary.delivery, evt.results) };
        break;
      default:
        break;
    }
  }

  /** Fetch a run's persisted events + items and replay them, buffering any
   *  concurrent live events (passed via apply(evt, {live:true})) until the
   *  backfill finishes so nothing is lost or clobbered mid-fetch. */
  async function load(id) {
    const gen = ++loadGen;
    loadingId = id;
    buffer = [];
    reset(null);
    try {
      const { run: r, events } = await api.getRun(id);
      if (gen !== loadGen) return; // superseded by a newer load() call
      reset(r);
      for (const e of events) apply(e);
      if (r.brief_id) {
        try {
          const { brief: fullBrief } = await api.getBrief(r.brief_id);
          if (gen !== loadGen) return;
          brief.full = fullBrief;
        } catch {
          // best-effort - brief event isn't persisted on the run's event log
        }
      }
      try {
        const { items: backfill } = await api.getItems({ run_id: id, limit: 300 });
        if (gen !== loadGen) return;
        for (const it of backfill) apply({ type: 'item', item: it });
      } catch {
        // items backfill is best-effort
      }
    } finally {
      if (gen === loadGen) {
        const buffered = buffer || [];
        buffer = null;
        loadingId = null;
        for (const e of buffered) apply(e);
      }
    }
  }

  return reactive({ run, sources, items, pages, logs, llmPhases, brief, reset, apply, load });
}

export const SOURCE_GROUPS = {
  rss: { label: 'RSS & News', icon: 'rss' },
  github: { label: 'GitHub Trending', icon: 'github' },
  reddit: { label: 'Reddit', icon: 'reddit' },
  markets: { label: 'Markets', icon: 'markets' },
  calendar: { label: 'Calendar', icon: 'calendar' },
};
export { SOURCE_GROUP_ORDER };
