import { api } from '../api.js';
import { state, clock, pushToast, SOURCE_GROUPS, SOURCE_GROUP_ORDER } from '../store.js';
import { fmtDuration, elapsedSeconds, fmtClock, triggerLabel } from '../format.js';

// ------------------------------------------------------------- RunStepper --
export const RunStepper = {
  name: 'RunStepper',
  props: { run: { type: Object, default: null } },
  setup() {
    return { clock };
  },
  computed: {
    steps() {
      return this.run ? this.run.steps || [] : [];
    },
    kindLabel() {
      if (!this.run) return 'No run yet';
      const k = this.run.kind;
      return k ? k.charAt(0).toUpperCase() + k.slice(1) : k;
    },
    statusMeta() {
      const map = {
        queued: { v: 'warn', label: 'Queued' },
        running: { v: 'accent', label: 'Running' },
        done: { v: 'ok', label: 'Done' },
        failed: { v: 'error', label: 'Failed' },
        cancelled: { v: 'muted', label: 'Cancelled' },
      };
      return this.run ? map[this.run.status] || { v: 'muted', label: this.run.status } : null;
    },
    overallElapsed() {
      if (!this.run) return null;
      return elapsedSeconds(this.run.started_at || this.run.created_at, this.run.finished_at, this.clock);
    },
  },
  methods: {
    fmtDuration,
    triggerLabel,
    stepClass(s) {
      return {
        'is-active': s.status === 'active',
        'is-done': s.status === 'done',
        'is-error': s.status === 'error',
        'is-pending': s.status === 'pending',
        'is-skipped': s.status === 'skipped',
      };
    },
    stepIcon(s) {
      if (s.status === 'done') return 'check';
      if (s.status === 'error') return 'x';
      if (s.status === 'active') return 'loader';
      if (s.status === 'skipped') return 'minus';
      return 'clock';
    },
    stepElapsed(s) {
      if (!s.started_at) return '';
      const secs = elapsedSeconds(s.started_at, s.finished_at, this.clock);
      return secs === null ? '' : fmtDuration(secs);
    },
    progressPct(s) {
      if (!s.progress) return null;
      const [done, total] = s.progress;
      return total ? Math.min(100, (done / total) * 100) : 0;
    },
  },
  template: `
  <div class="panel run-panel">
    <div class="run-panel__head">
      <div class="run-panel__title">
        <span class="run-panel__kind">{{ kindLabel }}</span>
        <span v-if="run" class="pill" :class="'pill--'+statusMeta.v">
          <icon v-if="run.status==='running'" name="loader" :size="11" class="spin"/>
          <span v-else class="status-dot" :class="'status-dot--'+statusMeta.v"></span>
          {{ statusMeta.label }}
        </span>
        <span v-if="run" class="badge" :class="{'badge--telegram': run.trigger==='telegram'}">
          <icon v-if="run.trigger==='telegram'" name="send" :size="9"/>{{ triggerLabel(run.trigger) }}
        </span>
      </div>
      <div v-if="run" class="run-panel__meta">
        <span class="tabular">Elapsed {{ fmtDuration(overallElapsed) }}</span>
        <span v-if="run.error" style="color:var(--error)">{{ run.error }}</span>
        <a v-if="run.brief_id" :href="'#/briefs/'+run.brief_id" class="btn btn--sm"><icon name="briefs" :size="12"/>Brief</a>
        <a :href="'#/runs/'+run.id" class="btn btn--sm btn--ghost"><icon name="external-link" :size="12"/>Details</a>
      </div>
    </div>
    <empty-state v-if="!run" icon="runs" title="No run yet"
      hint="Trigger a pipeline, collection, brief or crawl above to see it unfold here in real time."/>
    <div v-else class="stepper">
      <div v-for="(s,i) in steps" :key="s.key" class="step" :class="stepClass(s)">
        <div class="step__col">
          <div class="step__icon-wrap">
            <icon :name="stepIcon(s)" :size="16" :class="{spin: s.status==='active'}"/>
          </div>
          <div class="step__body">
            <div class="step__label">{{ s.label }}</div>
            <div v-if="s.detail" class="step__detail truncate">{{ s.detail }}</div>
            <div v-if="progressPct(s)!==null" class="step__bar"><div class="step__bar-fill" :style="{width: progressPct(s)+'%'}"></div></div>
            <div v-if="stepElapsed(s)" class="step__timer tabular">{{ stepElapsed(s) }}</div>
          </div>
        </div>
        <div v-if="i < steps.length-1" class="step__connector"></div>
      </div>
    </div>
  </div>`,
};

// ------------------------------------------------------------- CommandBar --
export const CommandBar = {
  name: 'CommandBar',
  setup() {
    return { state };
  },
  data() {
    return {
      deliver: true,
      showCrawl: false,
      submitting: null,
      crawl: { urls: '', depth: 1, max_pages: 8, render: 'auto' },
    };
  },
  computed: {
    busy() {
      return !!this.state.active_run;
    },
  },
  methods: {
    async run(kind) {
      if (this.busy || this.submitting) return;
      this.submitting = kind;
      try {
        const params = kind === 'collect' ? {} : { deliver: this.deliver };
        await api.createRun(kind, params);
      } catch (e) {
        pushToast(e.status === 409 ? 'A run is already active.' : e.message || 'Could not start run.', 'error');
      } finally {
        this.submitting = null;
      }
    },
    async submitCrawl() {
      const urls = this.crawl.urls
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (!urls.length) {
        pushToast('Add at least one URL to crawl.', 'warn');
        return;
      }
      this.submitting = 'web';
      try {
        await api.createRun('web', {
          urls,
          depth: Number(this.crawl.depth),
          max_pages: Number(this.crawl.max_pages),
          render: this.crawl.render,
        });
        this.showCrawl = false;
      } catch (e) {
        pushToast(e.status === 409 ? 'A run is already active.' : e.message || 'Could not start crawl.', 'error');
      } finally {
        this.submitting = null;
      }
    },
    async cancel() {
      if (!this.state.active_run) return;
      try {
        await api.cancelRun(this.state.active_run.id);
      } catch (e) {
        pushToast(e.message || 'Could not cancel run.', 'error');
      }
    },
  },
  template: `
  <div class="panel command-bar">
    <div class="command-bar__row">
      <button class="btn btn--primary" :disabled="busy || !!submitting" @click="run('pipeline')">
        <icon name="play" :size="15"/>Run full pipeline
      </button>
      <button class="btn" :disabled="busy || !!submitting" @click="run('collect')">
        <icon name="refresh" :size="15"/>Collect now
      </button>
      <button class="btn" :disabled="busy || !!submitting" @click="run('brief')">
        <icon name="briefs" :size="15"/>Generate brief
      </button>
      <button class="btn" :class="{'btn--primary': showCrawl}" :disabled="busy" @click="showCrawl = !showCrawl">
        <icon name="globe" :size="15"/>Crawl the web
      </button>
      <label class="checkbox-row command-bar__deliver">
        <input type="checkbox" v-model="deliver"/>Deliver when done
      </label>
      <button v-if="busy" class="btn btn--danger" @click="cancel">
        <icon name="square" :size="14"/>Cancel run
      </button>
    </div>
    <div v-if="state.telegram.chat_id" class="command-bar__hint">
      <icon name="send" :size="12"/>Tip: send <code>/now</code> to @{{ state.telegram.bot_username }} for an instant brief.
    </div>
    <transition name="disclosure">
      <div v-if="showCrawl" class="crawl-form">
        <div class="field">
          <label class="field__label">URLs to crawl</label>
          <textarea class="textarea" v-model="crawl.urls" rows="3"
            placeholder="https://example.com/article&#10;https://news.site/post, https://other.site/page"></textarea>
          <span class="field__hint">One per line, or comma-separated.</span>
        </div>
        <div class="crawl-form__grid">
          <div class="field">
            <label class="field__label">Depth</label>
            <select class="select" v-model.number="crawl.depth">
              <option :value="0">0 &middot; just these pages</option>
              <option :value="1">1 &middot; follow one hop</option>
              <option :value="2">2 &middot; follow two hops</option>
            </select>
          </div>
          <div class="field">
            <label class="field__label">Max pages</label>
            <input class="input" type="number" min="1" max="20" v-model.number="crawl.max_pages"/>
          </div>
          <div class="field">
            <label class="field__label">Render mode</label>
            <select class="select" v-model="crawl.render">
              <option value="auto">Auto</option>
              <option value="always">Always render</option>
              <option value="never">Never render</option>
            </select>
          </div>
        </div>
        <div class="crawl-form__actions">
          <button class="btn btn--ghost" @click="showCrawl=false">Cancel</button>
          <button class="btn btn--primary" :disabled="!!submitting" @click="submitCrawl">
            <icon name="play" :size="14"/>Start crawl
          </button>
        </div>
      </div>
    </transition>
  </div>`,
};

// -------------------------------------------------------------- SourceGrid --
export const SourceGrid = {
  name: 'SourceGrid',
  props: { sources: { type: Array, default: () => [] } },
  computed: {
    groups() {
      const byGroup = {};
      for (const s of this.sources) (byGroup[s.group] || (byGroup[s.group] = [])).push(s);
      const known = SOURCE_GROUP_ORDER.filter((g) => byGroup[g]).map((g) => ({ key: g, ...SOURCE_GROUPS[g], items: byGroup[g] }));
      const other = Object.keys(byGroup)
        .filter((g) => !SOURCE_GROUP_ORDER.includes(g))
        .map((g) => ({ key: g, label: g, icon: 'globe', items: byGroup[g] }));
      return known.concat(other);
    },
  },
  methods: {
    statusIcon(s) {
      return s.status === 'done' ? 'check' : s.status === 'error' ? 'x' : 'loader';
    },
  },
  template: `
  <div class="sources-grid">
    <empty-state v-if="!sources.length" icon="sources" title="Waiting for sources"
      hint="Source cards appear as the run starts pulling from each feed."/>
    <div v-for="g in groups" :key="g.key">
      <div class="source-group__head"><icon :name="g.icon" :size="13"/>{{ g.label }}</div>
      <div class="source-group__cards">
        <div v-for="s in g.items" :key="s.key" class="source-card">
          <span class="source-card__status" :class="'source-card__status--'+(s.status==='done'?'done':s.status==='error'?'error':'running')">
            <icon :name="statusIcon(s)" :size="14" :class="{spin: s.status==='running'}"/>
          </span>
          <div class="source-card__body">
            <div class="source-card__name truncate">{{ s.name }}</div>
            <div class="source-card__meta">
              <span v-if="s.status==='error'" style="color:var(--error)" class="truncate">{{ s.error || 'failed' }}</span>
              <template v-else>
                <span class="tabular">{{ s.count ?? 0 }} items</span>
                <span v-if="s.new" class="source-card__new tabular">+{{ s.new }} new</span>
                <span v-if="s.ms!=null" class="tabular">{{ s.ms }}ms</span>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>`,
};

// ----------------------------------------------------------------- RunLog --
export const RunLog = {
  name: 'RunLog',
  props: { logs: { type: Array, default: () => [] } },
  data() {
    return { paused: false };
  },
  watch: {
    logs() {
      if (this.paused) return;
      this.$nextTick(() => {
        const el = this.$refs.pane;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
  },
  methods: {
    time(ts) {
      const t = Date.parse(ts);
      return Number.isNaN(t) ? '--:--:--' : fmtClock(t);
    },
  },
  template: `
  <div class="run-log" ref="pane" @mouseenter="paused=true" @mouseleave="paused=false">
    <empty-state v-if="!logs.length" icon="live" title="No log output yet" hint="" style="font-family:var(--font-sans)"/>
    <div v-for="(l,i) in logs" :key="i" class="log-line" :class="'log-line--'+l.level">
      <span class="log-line__time tabular">{{ time(l.ts) }}</span>
      <span class="log-line__origin">{{ l.origin }}</span>
      <span class="log-line__msg">{{ l.msg }}</span>
    </div>
  </div>`,
};

export function register(app) {
  app.component('run-stepper', RunStepper);
  app.component('command-bar', CommandBar);
  app.component('source-grid', SourceGrid);
  app.component('run-log', RunLog);
}
