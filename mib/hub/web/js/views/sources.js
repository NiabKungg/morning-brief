import { api } from '../api.js';
import { pushToast } from '../store.js';
import { deepDiff } from '../settings-diff.js';

const { reactive, ref, computed, onMounted } = Vue;

export const SourcesView = {
  name: 'SourcesView',
  setup() {
    const original = ref(null);
    const draft = reactive({ rss: null, github: null, reddit: null, markets: null, calendar: null });
    const icsStatus = ref({ set: false, hint: null });
    const icsEdit = ref(undefined); // undefined = untouched; array = staged replacement
    const loading = ref(true);
    const saving = ref(false);

    function hydrate(settings) {
      const s = structuredClone(settings.sources);
      draft.rss = s.rss;
      draft.github = s.github;
      draft.reddit = s.reddit;
      draft.markets = s.markets;
      draft.calendar = { enabled: s.calendar.enabled, days: s.calendar.days };
      icsStatus.value = s.calendar.ics_urls || { set: false, hint: null };
      icsEdit.value = undefined;
    }

    async function load() {
      loading.value = true;
      try {
        const settings = await api.getSettings();
        original.value = settings;
        hydrate(settings);
      } catch (e) {
        pushToast(e.message || 'Could not load settings.', 'error');
      } finally {
        loading.value = false;
      }
    }
    onMounted(load);

    const dirty = computed(() => {
      if (!original.value) return false;
      const o = original.value.sources;
      const current = { rss: draft.rss, github: draft.github, reddit: draft.reddit, markets: draft.markets, calendar: draft.calendar };
      const base = { rss: o.rss, github: o.github, reddit: o.reddit, markets: o.markets, calendar: { enabled: o.calendar.enabled, days: o.calendar.days } };
      const d = deepDiff(current, base);
      return (d && Object.keys(d).length > 0) || icsEdit.value !== undefined;
    });

    function addFeed() {
      draft.rss.feeds.push({ name: '', url: '', enabled: true });
    }
    function removeFeed(i) {
      draft.rss.feeds.splice(i, 1);
    }

    async function save() {
      if (!dirty.value) return;
      saving.value = true;
      if (draft.github.languages.length === 0) draft.github.languages = [''];
      try {
        const o = original.value.sources;
        const current = { rss: draft.rss, github: draft.github, reddit: draft.reddit, markets: draft.markets, calendar: draft.calendar };
        const base = { rss: o.rss, github: o.github, reddit: o.reddit, markets: o.markets, calendar: { enabled: o.calendar.enabled, days: o.calendar.days } };
        const patch = deepDiff(current, base) || {};
        if (icsEdit.value !== undefined) patch.calendar = { ...(patch.calendar || {}), ics_urls: icsEdit.value };
        const updated = await api.putSettings({ sources: patch });
        pushToast('Sources settings saved.', 'ok');
        original.value = updated;
        hydrate(updated);
      } catch (e) {
        pushToast(e.message || 'Could not save settings.', 'error');
      } finally {
        saving.value = false;
      }
    }
    function discard() {
      load();
    }

    return { draft, loading, saving, dirty, icsStatus, icsEdit, addFeed, removeFeed, save, discard };
  },
  template: `
  <div class="view">
    <div class="view-head"><div><h1>Sources</h1><p>Configure what the Worker collects on every run.</p></div></div>

    <div v-if="loading" class="panel"><div class="panel__body"><span class="muted">Loading&hellip;</span></div></div>
    <template v-else>
      <div class="panel">
        <div class="panel__head">
          <div class="panel__title"><icon name="rss" :size="15"/>RSS &amp; News</div>
          <label class="switch"><input type="checkbox" v-model="draft.rss.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
        </div>
        <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-4)">
          <div class="field" style="max-width:180px">
            <label class="field__label">Items per feed</label>
            <input class="input" type="number" min="1" v-model.number="draft.rss.per_feed"/>
          </div>
          <div class="field">
            <label class="field__label">Feeds</label>
            <div class="feed-list">
              <div v-for="(f,i) in draft.rss.feeds" :key="i" class="feed-row">
                <label class="checkbox-row" style="flex:0"><input type="checkbox" v-model="f.enabled"/></label>
                <input class="input input--name" v-model="f.name" placeholder="Name"/>
                <input class="input" v-model="f.url" placeholder="https://example.com/feed.xml"/>
                <button type="button" class="btn btn--icon btn--ghost" @click="removeFeed(i)" aria-label="Remove feed"><icon name="trash" :size="14"/></button>
              </div>
            </div>
            <button type="button" class="btn btn--sm btn--add" style="margin-top:8px" @click="addFeed"><icon name="plus" :size="13"/>Add feed</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <div class="panel__title"><icon name="github" :size="15"/>GitHub Trending</div>
          <label class="switch"><input type="checkbox" v-model="draft.github.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
        </div>
        <div class="panel__body field-grid">
          <div class="field">
            <label class="field__label">Since</label>
            <select class="select" v-model="draft.github.since"><option value="daily">Daily</option><option value="weekly">Weekly</option></select>
          </div>
          <div class="field">
            <label class="field__label">Limit</label>
            <input class="input" type="number" min="1" v-model.number="draft.github.limit"/>
          </div>
          <div class="field" style="grid-column:1/-1">
            <label class="field__label">Languages</label>
            <tag-input v-model="draft.github.languages" placeholder="e.g. rust, python — empty = all" empty-label="All languages"/>
            <span class="field__hint">Leave empty to track all languages.</span>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <div class="panel__title"><icon name="reddit" :size="15"/>Reddit</div>
          <label class="switch"><input type="checkbox" v-model="draft.reddit.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
        </div>
        <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-4)">
          <div class="field-grid">
            <div class="field">
              <label class="field__label">Period</label>
              <select class="select" v-model="draft.reddit.period"><option value="day">Day</option><option value="week">Week</option></select>
            </div>
            <div class="field">
              <label class="field__label">Posts per subreddit</label>
              <input class="input" type="number" min="1" v-model.number="draft.reddit.per_sub"/>
            </div>
          </div>
          <div class="field">
            <label class="field__label">Subreddits</label>
            <tag-input v-model="draft.reddit.subreddits" placeholder="e.g. programming, MachineLearning"/>
          </div>
          <div class="field">
            <label class="field__label">Specific threads</label>
            <tag-input v-model="draft.reddit.threads" placeholder="Paste a thread URL…"/>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <div class="panel__title"><icon name="markets" :size="15"/>Markets</div>
          <label class="switch"><input type="checkbox" v-model="draft.markets.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
        </div>
        <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-4)">
          <div class="field">
            <label class="field__label">Crypto (CoinGecko ids)</label>
            <tag-input v-model="draft.markets.crypto" placeholder="e.g. bitcoin, ethereum"/>
          </div>
          <div class="field">
            <label class="field__label">Symbols (Yahoo Finance)</label>
            <tag-input v-model="draft.markets.symbols" placeholder="e.g. ^GSPC, NVDA, ^SET.BK, THB=X"/>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <div class="panel__title"><icon name="calendar" :size="15"/>Calendar</div>
          <label class="switch"><input type="checkbox" v-model="draft.calendar.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
        </div>
        <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-4)">
          <div class="field" style="max-width:180px">
            <label class="field__label">Look-ahead (days)</label>
            <input class="input" type="number" min="1" v-model.number="draft.calendar.days"/>
          </div>
          <div class="field">
            <label class="field__label">ICS calendar URLs</label>
            <div class="secret-field">
              <span class="secret-field__status">
                <template v-if="icsEdit!==undefined">New list staged &mdash; will replace on save.</template>
                <template v-else-if="icsStatus.set">{{ icsStatus.hint || 'URLs set' }}</template>
                <template v-else>No calendars configured.</template>
              </span>
              <button v-if="icsEdit===undefined" type="button" class="btn btn--sm" @click="icsEdit=[]">{{ icsStatus.set ? 'Replace' : 'Add' }}</button>
              <button v-if="icsEdit===undefined && icsStatus.set" type="button" class="btn btn--sm btn--ghost" @click="icsEdit=[]">Clear</button>
              <button v-if="icsEdit!==undefined" type="button" class="btn btn--sm btn--ghost" @click="icsEdit=undefined">Cancel</button>
            </div>
            <tag-input v-if="icsEdit!==undefined" v-model="icsEdit" placeholder="Paste a webcal/ICS URL…" style="margin-top:8px"/>
          </div>
        </div>
      </div>
    </template>

    <div v-if="dirty" class="unsaved-bar">
      <span class="unsaved-bar__msg"><icon name="alert-triangle" :size="14"/>You have unsaved changes.</span>
      <div style="display:flex;gap:8px">
        <button type="button" class="btn btn--ghost btn--sm" :disabled="saving" @click="discard">Discard</button>
        <button type="button" class="btn btn--primary btn--sm" :disabled="saving" @click="save"><icon name="check" :size="13"/>Save changes</button>
      </div>
    </div>
  </div>`,
};
