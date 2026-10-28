import { api } from '../api.js';
import { pushToast, onEvent, createTimeline, clock } from '../store.js';
import { fmtDuration, elapsedSeconds, triggerLabel } from '../format.js';

const { ref, onMounted, onUnmounted, watch } = Vue;

const STATUS_VARIANT = { queued: 'warn', running: 'accent', done: 'ok', failed: 'error', cancelled: 'muted' };

export const RunsListView = {
  name: 'RunsListView',
  setup() {
    const runs = ref([]);
    const loading = ref(false);

    async function load() {
      loading.value = true;
      try {
        const res = await api.getRuns(50);
        runs.value = res.runs;
      } catch (e) {
        pushToast(e.message || 'Could not load runs.', 'error');
      } finally {
        loading.value = false;
      }
    }
    onMounted(load);

    const unsub = onEvent((evt) => {
      if (evt.type !== 'run') return;
      const idx = runs.value.findIndex((r) => r.id === evt.run.id);
      if (idx !== -1) runs.value[idx] = evt.run;
      else runs.value = [evt.run, ...runs.value];
    });
    onUnmounted(unsub);

    function go(id) {
      location.hash = `#/runs/${id}`;
    }

    return { runs, loading, clock, go };
  },
  methods: {
    fmtDuration,
    triggerLabel,
    statusVariant(s) {
      return STATUS_VARIANT[s] || 'muted';
    },
    duration(r) {
      const secs = elapsedSeconds(r.started_at || r.created_at, r.finished_at, this.clock);
      return secs === null ? '—' : fmtDuration(secs);
    },
    itemsStat(r) {
      const s = r.stats || {};
      return s.items_kept ?? s.items_used ?? s.items ?? '—';
    },
  },
  template: `
  <div class="view">
    <div class="view-head"><div><h1>Runs</h1><p>History of pipeline, collect, brief and web-crawl runs.</p></div></div>
    <empty-state v-if="!loading && !runs.length" icon="runs" title="No runs yet" hint="Trigger a run from the Live view to see it appear here."/>
    <div v-else class="panel">
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Run</th><th>Kind</th><th>Trigger</th><th>Status</th><th>Duration</th><th>Items</th><th>Brief</th></tr></thead>
          <tbody>
            <tr v-for="r in runs" :key="r.id" class="is-clickable" @click="go(r.id)">
              <td class="tabular muted" data-label="Run">#{{ r.id }}</td>
              <td style="text-transform:capitalize" data-label="Kind">{{ r.kind }}</td>
              <td data-label="Trigger">
                <span v-if="r.trigger==='telegram'" class="badge badge--telegram"><icon name="send" :size="9"/>via Telegram /now</span>
                <span v-else class="muted">{{ triggerLabel(r.trigger) }}</span>
              </td>
              <td data-label="Status"><span class="pill" :class="'pill--'+statusVariant(r.status)">{{ r.status }}</span></td>
              <td class="tabular" data-label="Duration">{{ duration(r) }}</td>
              <td class="tabular" data-label="Items">{{ itemsStat(r) }}</td>
              <td data-label="Brief">
                <a v-if="r.brief_id" :href="'#/briefs/'+r.brief_id" @click.stop class="btn btn--sm btn--ghost"><icon name="briefs" :size="12"/></a>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>`,
};

export const RunView = {
  name: 'RunView',
  props: { id: { type: String, required: true } },
  setup(props) {
    const timeline = createTimeline();
    const loading = ref(true);
    const notFound = ref(false);
    let unsub = null;
    let bootGen = 0;

    async function boot(id) {
      const myGen = ++bootGen;
      loading.value = true;
      notFound.value = false;
      if (unsub) {
        unsub();
        unsub = null;
      }
      let failed = false;
      try {
        await timeline.load(id);
      } catch {
        failed = true;
      }
      if (myGen !== bootGen) return; // superseded by a newer navigation
      loading.value = false;
      if (failed) {
        notFound.value = true;
        return;
      }
      if (timeline.run && (timeline.run.status === 'running' || timeline.run.status === 'queued')) {
        const numId = Number(id);
        unsub = onEvent((evt) => {
          if (evt.type === 'run' && evt.run.id === numId) timeline.apply(evt, { live: true });
          else if ('run_id' in evt && evt.run_id === numId) timeline.apply(evt, { live: true });
        });
      }
    }
    onMounted(() => boot(props.id));
    watch(() => props.id, boot);
    onUnmounted(() => {
      if (unsub) unsub();
    });

    return { timeline, loading, notFound };
  },
  template: `
  <div class="view">
    <a href="#/runs" class="btn btn--ghost btn--sm view-back" style="align-self:flex-start"><icon name="chevron-right" :size="13" style="transform:rotate(180deg)"/>All runs</a>
    <div v-if="loading" class="panel"><div class="panel__body"><span class="muted">Loading&hellip;</span></div></div>
    <empty-state v-else-if="notFound" icon="x-circle" title="Run not found"/>
    <template v-else>
      <run-stepper :run="timeline.run"/>
      <div class="live-grid">
        <div class="stack live-side">
          <div class="panel"><div class="panel__head"><div class="panel__title"><icon name="brain" :size="15"/>LLM console</div></div><div class="panel__body"><llm-console :phases="timeline.llmPhases"/></div></div>
          <div class="panel"><div class="panel__head"><div class="panel__title"><icon name="briefs" :size="15"/>Brief</div></div><div class="panel__body preview-pane"><brief-preview :brief="timeline.brief"/></div></div>
        </div>
        <div class="stack live-main">
          <div class="panel"><div class="panel__head"><div class="panel__title"><icon name="sources" :size="15"/>Sources</div></div><div class="panel__body"><source-grid :sources="timeline.sources"/></div></div>
          <div class="panel"><div class="panel__head"><div class="panel__title"><icon name="items" :size="15"/>Items</div></div><div class="panel__body"><item-feed :items="timeline.items"/></div></div>
          <div class="panel"><div class="panel__head"><div class="panel__title"><icon name="globe" :size="15"/>Crawl pages</div></div><div class="panel__body"><crawl-feed :pages="timeline.pages"/></div></div>
        </div>
      </div>
      <div class="panel"><div class="panel__head"><div class="panel__title"><icon name="live" :size="15"/>Run log</div></div><run-log :logs="timeline.logs"/></div>
    </template>
  </div>`,
};
