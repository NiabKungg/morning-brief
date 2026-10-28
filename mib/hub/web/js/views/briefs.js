import { api } from '../api.js';
import { pushToast } from '../store.js';
import { fmtDate, fmtRelative } from '../format.js';

const { ref, onMounted, watch } = Vue;

export const BriefsListView = {
  name: 'BriefsListView',
  setup() {
    const briefs = ref([]);
    const kind = ref('');
    const loading = ref(false);

    async function load() {
      loading.value = true;
      try {
        const res = await api.getBriefs({ limit: 30, kind: kind.value });
        briefs.value = res.briefs;
      } catch (e) {
        pushToast(e.message || 'Could not load briefs.', 'error');
      } finally {
        loading.value = false;
      }
    }
    watch(kind, load);
    onMounted(load);

    function go(id) {
      location.hash = `#/briefs/${id}`;
    }

    return { briefs, kind, loading, go };
  },
  methods: { fmtDate, fmtRelative },
  template: `
  <div class="view">
    <div class="view-head">
      <div><h1>Briefs</h1><p>Daily Executive Summaries and ad-hoc web crawl briefs.</p></div>
      <div class="tabs">
        <button type="button" class="tab" :class="{active: kind===''}" @click="kind=''">All</button>
        <button type="button" class="tab" :class="{active: kind==='daily'}" @click="kind='daily'">Daily</button>
        <button type="button" class="tab" :class="{active: kind==='web'}" @click="kind='web'">Web</button>
      </div>
    </div>
    <empty-state v-if="!loading && !briefs.length" icon="briefs" title="No briefs yet"
      hint="Run the full pipeline or generate a brief from the Live view."/>
    <div v-else class="panel">
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Date</th><th>Kind</th><th>Headline</th><th>Delivery</th><th>Stats</th></tr></thead>
          <tbody>
            <tr v-for="b in briefs" :key="b.id" class="is-clickable" @click="go(b.id)">
              <td class="tabular" style="white-space:nowrap" data-label="Date">{{ fmtDate(b.date) }}</td>
              <td data-label="Kind"><span class="badge">{{ b.kind }}</span></td>
              <td class="table-cell--title" data-label="Headline"><a :href="'#/briefs/'+b.id" @click.stop class="truncate brief-row-link">{{ b.headline }}</a></td>
              <td data-label="Delivery">
                <span v-if="b.delivered_at" class="pill pill--ok"><icon name="check" :size="11"/>{{ fmtRelative(b.delivered_at) }}</span>
                <span v-else class="pill pill--muted">not sent</span>
              </td>
              <td class="muted tabular" data-label="Stats">
                <template v-if="b.stats">{{ b.stats.items_kept }}/{{ b.stats.items_considered }} kept &middot; {{ b.stats.gen_tps ? b.stats.gen_tps.toFixed(1)+' tok/s' : '—' }}</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>`,
};

export const BriefView = {
  name: 'BriefView',
  props: { id: { type: String, required: true } },
  setup(props) {
    const brief = ref(null);
    const loading = ref(true);
    const error = ref(null);

    async function load(id) {
      loading.value = true;
      error.value = null;
      try {
        const res = await api.getBrief(id);
        brief.value = res.brief;
      } catch (e) {
        error.value = e.message || 'Could not load brief.';
      } finally {
        loading.value = false;
      }
    }
    onMounted(() => load(props.id));
    watch(() => props.id, load);

    return { brief, loading, error };
  },
  template: `
  <div class="view">
    <a href="#/briefs" class="btn btn--ghost btn--sm view-back" style="align-self:flex-start"><icon name="chevron-right" :size="13" style="transform:rotate(180deg)"/>All briefs</a>
    <div v-if="loading" class="panel"><div class="panel__body"><span class="muted">Loading&hellip;</span></div></div>
    <div v-else-if="error" class="panel"><div class="panel__body"><empty-state icon="x-circle" title="Could not load brief" :hint="error"/></div></div>
    <div v-else class="panel"><div class="panel__body"><brief-reader :brief="brief"/></div></div>
  </div>`,
};
