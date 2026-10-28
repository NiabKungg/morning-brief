import { api } from '../api.js';
import { pushToast } from '../store.js';
import { sanitizeTelegramHtml } from '../sanitize.js';
import { langColor, fmtMoney, fmtChangePct, fmtTime, fmtNum, titleCase } from '../format.js';

// ------------------------------------------------------------------ CiteChip
export const CiteChip = {
  name: 'CiteChip',
  props: {
    n: { type: Number, required: true },
    sources: { type: Array, default: () => [] },
  },
  computed: {
    src() {
      return this.sources.find((s) => s.n === this.n);
    },
  },
  template: `
    <a v-if="src" class="cite-chip" :href="src.url" target="_blank" rel="noopener" :title="src.title">{{ n }}</a>
    <span v-else class="cite-chip cite-chip--static">{{ n }}</span>`,
};

// -------------------------------------------------------------------- DocBody
// Canonical renderer for a DOC object, reused by the full Brief reader page
// and by the live Brief preview once the authoritative doc has arrived.
export const DocBody = {
  name: 'DocBody',
  props: { doc: { type: Object, required: true } },
  computed: {
    sourcesList() {
      return this.doc.sources || [];
    },
  },
  methods: { langColor, fmtMoney, fmtChangePct, fmtTime, fmtNum, titleCase },
  template: `
    <div>
      <div v-if="doc.tldr && doc.tldr.length" class="reader__tldr">
        <div class="reader__tldr-label">TL;DR</div>
        <ul>
          <li v-for="(t,i) in doc.tldr" :key="i">{{ t.text }}<cite-chip v-for="c in (t.cites||[])" :key="c" :n="c" :sources="sourcesList"/></li>
        </ul>
      </div>

      <template v-if="doc.connections && doc.connections.length">
        <h2><icon name="link" :size="14"/>Connections</h2>
        <div class="connections-grid">
          <div v-for="(c,i) in doc.connections" :key="i" class="connection-card">
            <div class="connection-card__title">{{ c.title }}</div>
            <div class="connection-card__text">{{ c.text }}<cite-chip v-for="n in (c.cites||[])" :key="n" :n="n" :sources="sourcesList"/></div>
          </div>
        </div>
      </template>

      <template v-for="sec in (doc.sections||[])" :key="sec.key">
        <div class="section-block">
          <div class="section-block__label">{{ sec.label || titleCase(sec.key) }}</div>
          <ul>
            <li v-for="(b,i) in sec.bullets" :key="i">{{ b.text }}<cite-chip v-for="n in (b.cites||[])" :key="n" :n="n" :sources="sourcesList"/></li>
          </ul>
        </div>
      </template>

      <template v-if="doc.github && doc.github.length">
        <h2><icon name="github" :size="14"/>GitHub Trending</h2>
        <div>
          <div v-for="r in doc.github" :key="r.url" class="repo-row">
            <div class="repo-row__main">
              <a class="repo-row__name" :href="r.url" target="_blank" rel="noopener">{{ r.name }}</a>
              <div v-if="r.description" class="repo-row__desc">{{ r.description }}</div>
              <div v-if="r.language" class="repo-row__lang"><span class="lang-dot" :style="{background: langColor(r.language)}"></span>{{ r.language }}</div>
            </div>
            <div class="repo-row__stars">
              <div class="repo-row__stars-today tabular">+{{ fmtNum(r.stars_today) }}</div>
              <div class="repo-row__stars-total tabular">{{ fmtNum(r.stars) }} total</div>
            </div>
          </div>
        </div>
      </template>

      <template v-if="doc.markets && doc.markets.quotes && doc.markets.quotes.length">
        <h2><icon name="markets" :size="14"/>Markets</h2>
        <p v-if="doc.markets.note" class="muted" style="margin-bottom:10px">{{ doc.markets.note }}</p>
        <div class="table-wrap">
        <table class="markets-table">
          <thead><tr><th>Symbol</th><th>Name</th><th>Price</th><th>Change</th></tr></thead>
          <tbody>
            <tr v-for="q in doc.markets.quotes" :key="q.symbol">
              <td class="mono">{{ q.symbol }}</td>
              <td class="muted">{{ q.name }}</td>
              <td class="num tabular">{{ fmtMoney(q.price, q.currency) }}</td>
              <td class="num tabular" :class="fmtChangePct(q.change_pct).cls">{{ fmtChangePct(q.change_pct).text }}</td>
            </tr>
          </tbody>
        </table>
        </div>
      </template>

      <template v-if="doc.agenda && doc.agenda.events && doc.agenda.events.length">
        <h2><icon name="calendar" :size="14"/>Agenda</h2>
        <p v-if="doc.agenda.note" class="muted" style="margin-bottom:10px">{{ doc.agenda.note }}</p>
        <div class="agenda">
          <div v-for="(e,i) in doc.agenda.events" :key="i" class="agenda-item">
            <div class="agenda-item__time tabular">{{ e.all_day ? 'All day' : fmtTime(e.start) }}</div>
            <div class="agenda-item__body">
              <div class="agenda-item__title">{{ e.title }}</div>
              <div v-if="e.location" class="agenda-item__loc">{{ e.location }}</div>
            </div>
          </div>
        </div>
      </template>

      <template v-if="doc.watch && doc.watch.length">
        <h2><icon name="eye" :size="14"/>Watch today</h2>
        <div class="watch-list">
          <span v-for="(w,i) in doc.watch" :key="i" class="watch-chip">{{ w }}</span>
        </div>
      </template>

      <template v-if="sourcesList.length">
        <h2><icon name="sources" :size="14"/>Sources</h2>
        <div class="sources-list">
          <div v-for="s in sourcesList" :key="s.n" class="source-ref">
            <span class="source-ref__n tabular">{{ s.n }}.</span>
            <a :href="s.url" target="_blank" rel="noopener" :title="s.title" class="truncate">{{ s.title }}</a>
            <span class="source-ref__name">{{ s.source_name }}</span>
          </div>
        </div>
      </template>
    </div>`,
};

// -------------------------------------------------------------- TelegramPreview
export const TelegramPreview = {
  name: 'TelegramPreview',
  props: { chunks: { type: Array, default: () => [] } },
  methods: {
    html(c) {
      return sanitizeTelegramHtml(c);
    },
  },
  template: `
    <div class="tg-chat">
      <div v-if="!chunks.length" class="muted" style="text-align:center;padding:24px">No Telegram content for this brief.</div>
      <div v-for="(c,i) in chunks" :key="i" class="tg-bubble" v-html="html(c)"></div>
    </div>`,
};

// ------------------------------------------------------------------ BriefReader
export const BriefReader = {
  name: 'BriefReader',
  props: { brief: { type: Object, required: true } },
  data() {
    return { showTelegram: false, delivering: false, copied: false, deliverResults: null };
  },
  computed: {
    doc() {
      return this.brief.doc;
    },
  },
  methods: {
    async copyMarkdown() {
      try {
        await navigator.clipboard.writeText(this.brief.markdown || '');
        this.copied = true;
        pushToast('Markdown copied to clipboard.', 'ok');
        setTimeout(() => {
          this.copied = false;
        }, 2000);
      } catch {
        pushToast('Could not copy to clipboard.', 'error');
      }
    },
    async deliver() {
      this.delivering = true;
      try {
        const res = await api.deliverBrief(this.brief.id);
        this.deliverResults = res.results;
        const allOk = res.results.every((r) => r.ok);
        pushToast(allOk ? 'Sent to all configured channels.' : 'Delivery finished with errors.', allOk ? 'ok' : 'warn');
      } catch (e) {
        pushToast(e.message || 'Delivery failed.', 'error');
      } finally {
        this.delivering = false;
      }
    },
  },
  template: `
    <article class="reader">
      <div class="reader__date">{{ doc.date_label }}<span v-if="doc.kind==='web'" class="badge" style="margin-left:8px">web crawl</span></div>
      <h1 class="reader__headline">{{ doc.headline }}</h1>
      <div class="reader__body"><doc-body :doc="doc"/></div>
      <div class="reader__actions">
        <button class="btn btn--primary" :disabled="delivering" @click="deliver"><icon name="send" :size="14"/>Send to Telegram</button>
        <button class="btn" @click="copyMarkdown"><icon :name="copied?'check':'copy'" :size="14"/>{{ copied ? 'Copied' : 'Copy Markdown' }}</button>
        <button class="btn" :class="{'btn--primary': showTelegram}" @click="showTelegram=!showTelegram"><icon name="eye" :size="14"/>Telegram preview</button>
      </div>
      <div v-if="deliverResults" class="delivery-results">
        <div v-for="r in deliverResults" :key="r.channel" class="delivery-result">
          <icon :name="r.ok?'check-circle':'x-circle'" :size="14" :style="{color: r.ok?'var(--ok)':'var(--error)'}"/>
          <span style="text-transform:capitalize">{{ r.channel }}</span>
          <span class="muted">{{ r.ok ? 'delivered' : (r.error || 'failed') }}</span>
        </div>
      </div>
      <transition name="disclosure">
        <div v-if="showTelegram" style="margin-top:var(--sp-5)"><telegram-preview :chunks="brief.telegram_html"/></div>
      </transition>
    </article>`,
};

export function register(app) {
  app.component('cite-chip', CiteChip);
  app.component('doc-body', DocBody);
  app.component('telegram-preview', TelegramPreview);
  app.component('brief-reader', BriefReader);
}
