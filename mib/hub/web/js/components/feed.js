import { langColor, fmtMoney, fmtChangePct, fmtNum, fmtRelative, fmtTime, scoreColor } from '../format.js';

// ---------------------------------------------------------------- TriageChip
export const TriageChip = {
  name: 'TriageChip',
  props: { triage: { type: Object, default: null } },
  computed: {
    label() {
      if (!this.triage) return 'pending';
      return this.triage.keep ? 'kept' : 'dropped';
    },
    cls() {
      if (!this.triage) return 'triage-chip--pending';
      return this.triage.keep ? 'triage-chip--kept' : 'triage-chip--dropped';
    },
    color() {
      return this.triage ? scoreColor(this.triage.score) : null;
    },
    tip() {
      return this.triage ? `${this.triage.category || ''} · ${this.triage.reason || ''}` : 'awaiting triage';
    },
  },
  template: `
    <span class="triage-chip" :class="cls" :title="tip">
      <icon v-if="!triage" name="loader" :size="10" class="spin"/>
      <span v-else class="triage-chip__score" :style="{color: color}">{{ triage.score }}</span>
      <span>{{ label }}</span>
      <span v-if="triage && triage.category" class="muted" style="font-weight:500">&middot; {{ triage.category }}</span>
    </span>`,
};

// ------------------------------------------------------------------ ItemRow
export const ItemRow = {
  name: 'ItemRow',
  props: { item: { type: Object, required: true } },
  computed: {
    m() {
      return this.item.metrics || {};
    },
    change() {
      return fmtChangePct(this.m.change_pct);
    },
    triageable() {
      return this.item.kind === 'article' || this.item.kind === 'post';
    },
  },
  methods: { langColor, fmtMoney, fmtNum, fmtRelative, fmtTime },
  template: `
    <div class="item-row">
      <div class="item-row__main">
        <div class="item-row__top">
          <span class="source-badge" :class="'src-'+item.source"><span class="source-dot"></span>{{ item.source_name || item.source }}</span>
          <a v-if="item.url" :href="item.url" target="_blank" rel="noopener" class="item-row__title truncate">{{ item.title }}</a>
          <span v-else class="item-row__title truncate">{{ item.title }}</span>
        </div>
        <div class="item-row__meta">
          <template v-if="item.kind==='repo'">
            <span v-if="m.stars_today!=null" class="pos tabular"><icon name="trend-up" :size="11"/>+{{ fmtNum(m.stars_today) }} today</span>
            <span v-if="m.language" class="repo-row__lang" style="margin:0"><span class="lang-dot" :style="{background: langColor(m.language)}"></span>{{ m.language }}</span>
            <span v-if="m.stars!=null" class="tabular">{{ fmtNum(m.stars) }} total</span>
          </template>
          <template v-else-if="item.kind==='quote'">
            <span class="tabular">{{ fmtMoney(m.price, m.currency) }}</span>
            <span class="tabular" :class="change.cls">{{ change.text }}</span>
          </template>
          <template v-else-if="item.kind==='event'">
            <span><icon name="calendar" :size="11"/>{{ m.all_day ? 'All day' : fmtTime(m.start) }}</span>
            <span v-if="m.location" class="truncate">{{ m.location }}</span>
          </template>
          <template v-else>
            <span v-if="item.author">{{ item.author }}</span>
            <span>{{ fmtRelative(item.published_at || item.first_seen_at) }}</span>
          </template>
        </div>
        <p v-if="item.summary" class="item-row__summary">{{ item.summary }}</p>
      </div>
      <div class="item-row__side">
        <triage-chip v-if="triageable" :triage="item.triage"/>
      </div>
    </div>`,
};

// ----------------------------------------------------------------- ItemFeed
export const ItemFeed = {
  name: 'ItemFeed',
  props: { items: { type: Array, default: () => [] } },
  data() {
    return { tab: 'all' };
  },
  computed: {
    kept() {
      return this.items.filter((i) => i.triage && i.triage.keep);
    },
    dropped() {
      return this.items.filter((i) => i.triage && i.triage.keep === false);
    },
    visible() {
      if (this.tab === 'kept') return this.kept;
      if (this.tab === 'dropped') return this.dropped;
      return this.items;
    },
  },
  template: `
    <div>
      <div class="tabs" style="margin-bottom:10px">
        <button type="button" class="tab" :class="{active: tab==='all'}" @click="tab='all'">All<span class="count">{{ items.length }}</span></button>
        <button type="button" class="tab" :class="{active: tab==='kept'}" @click="tab='kept'">Kept<span class="count">{{ kept.length }}</span></button>
        <button type="button" class="tab" :class="{active: tab==='dropped'}" @click="tab='dropped'">Dropped<span class="count">{{ dropped.length }}</span></button>
      </div>
      <empty-state v-if="!visible.length" icon="inbox" title="No items yet"/>
      <transition-group v-else tag="div" name="feed" class="feed">
        <item-row v-for="it in visible" :key="it.id" :item="it"/>
      </transition-group>
    </div>`,
};

// ---------------------------------------------------------------- CrawlFeed
export const CrawlFeed = {
  name: 'CrawlFeed',
  props: { pages: { type: Array, default: () => [] } },
  methods: {
    pillClass(code) {
      if (code == null) return 'status-code-pill--error';
      if (code < 300) return 'status-code-pill--ok';
      if (code < 400) return 'status-code-pill--warn';
      return 'status-code-pill--error';
    },
  },
  template: `
    <div>
      <empty-state v-if="!pages.length" icon="globe" title="No pages fetched yet"/>
      <transition-group v-else tag="div" name="feed" class="feed feed--compact">
        <div v-for="(p,i) in pages" :key="p.url+'_'+i" class="crawl-row">
          <span class="status-code-pill" :class="pillClass(p.status)">{{ p.status ?? 'ERR' }}</span>
          <span class="crawl-row__url truncate" :title="p.url">{{ p.title || p.url }}</span>
          <span v-if="p.rendered" class="badge">rendered</span>
          <span class="badge">{{ p.purpose }}</span>
          <span v-if="p.error" class="truncate" style="color:var(--error);flex-shrink:1">{{ p.error }}</span>
          <span v-else class="crawl-row__stats">
            <span>d{{ p.depth }}</span>
            <span>{{ p.ms }}ms</span>
            <span>{{ (p.chars/1000).toFixed(1) }}k</span>
          </span>
        </div>
      </transition-group>
    </div>`,
};

export function register(app) {
  app.component('triage-chip', TriageChip);
  app.component('item-row', ItemRow);
  app.component('item-feed', ItemFeed);
  app.component('crawl-feed', CrawlFeed);
}
