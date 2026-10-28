// Topology card: Pi4 Worker -> Pi5 Brain (LFM3) -> Telegram, with live
// metrics, sparklines and animated edges that flow while data is in motion.

import { cpuHistory, state } from '../store.js';
import { fmtPct, fmtTemp, fmtBytes, fmtRelative, telegramStatus } from '../format.js';

export const TopologyCard = {
  name: 'TopologyCard',
  props: {
    run: { type: Object, default: null },
  },
  setup() {
    return { state, cpuHistory };
  },
  computed: {
    worker() {
      const ws = this.state.workers;
      return ws.find((w) => w.id === 'pi4') || ws[0] || null;
    },
    workerHistory() {
      return (this.worker && cpuHistory.workers[this.worker.id]) || [];
    },
    hubHistory() {
      return cpuHistory.hub;
    },
    llm() {
      return this.state.llm;
    },
    llmStatus() {
      if (!this.llm || !this.llm.online) return { v: 'muted', label: 'Offline' };
      if (this.llm.busy) return { v: 'warn', label: 'Busy' };
      return { v: 'ok', label: 'Ready' };
    },
    telegram() {
      return this.state.telegram;
    },
    tgStatus() {
      return telegramStatus(this.state.telegram);
    },
    telegramLast() {
      const b = this.state.latest_brief;
      return b && b.delivery && b.delivery.telegram ? b.delivery.telegram : null;
    },
    activity() {
      const steps = (this.run && this.run.steps) || [];
      const byKey = {};
      for (const s of steps) byKey[s.key] = s.status;
      return {
        collect: ['collect', 'enrich', 'crawl'].some((k) => byKey[k] === 'active'),
        brain: ['dedupe', 'triage', 'synthesize', 'summarize'].some((k) => byKey[k] === 'active') || !!(this.llm && this.llm.busy),
        deliver: byKey.deliver === 'active',
      };
    },
  },
  methods: {
    fmtPct,
    fmtTemp,
    fmtBytes,
    fmtRelative,
    ramPct(sys) {
      if (!sys || !sys.mem_total) return 0;
      return Math.min(100, (sys.mem_used / sys.mem_total) * 100);
    },
  },
  template: `
  <div class="panel">
    <div class="panel__head">
      <div class="panel__title"><icon name="live" :size="15"/>Topology</div>
      <div class="panel__sub">Worker &rarr; Brain &rarr; Telegram</div>
    </div>
    <div class="topology">
      <!-- Worker node -->
      <div class="node node--worker" :class="{ 'node--offline': !worker || !worker.online }">
        <div class="node__head">
          <div class="node__icon"><icon name="cpu" :size="17"/></div>
          <div class="node__titles">
            <div class="node__title">Pi 4 &middot; Worker</div>
            <div class="node__sub">{{ worker ? worker.host : 'not connected' }}</div>
          </div>
          <div class="node__state">
            <status-pill :status="worker && worker.online ? (worker.busy ? 'warn' : 'ok') : 'muted'" :pulse="!!(worker && worker.busy)" :label="worker ? (worker.online ? (worker.busy ? 'busy' : 'online') : 'offline') : 'offline'"/>
          </div>
        </div>
        <template v-if="worker && worker.sys">
          <div class="node__metrics">
            <div class="node__metric">
              <span class="node__metric-label"><icon name="cpu" :size="10"/>CPU</span>
              <span class="node__metric-value tabular">{{ fmtPct(worker.sys.cpu_pct) }}</span>
            </div>
            <div class="node__metric">
              <span class="node__metric-label"><icon name="thermometer" :size="10"/>Temp</span>
              <span class="node__metric-value tabular">{{ fmtTemp(worker.sys.temp_c) }}</span>
            </div>
            <div class="node__metric">
              <span class="node__metric-label"><icon name="clock" :size="10"/>Load</span>
              <span class="node__metric-value tabular">{{ worker.sys.load ? worker.sys.load[0].toFixed(2) : '—' }}</span>
            </div>
          </div>
          <div class="node__metric-label" style="margin-top:12px"><icon name="ram" :size="10"/>RAM {{ fmtBytes(worker.sys.mem_used) }} / {{ fmtBytes(worker.sys.mem_total) }}</div>
          <div class="node__bar"><div class="node__bar-fill" :style="{width: ramPct(worker.sys)+'%'}"></div></div>
          <div class="node__spark"><sparkline :data="workerHistory" :height="26"/></div>
        </template>
        <div v-else class="node__foot">Waiting for worker heartbeat&hellip;</div>
      </div>

      <div class="edge-wrap">
        <svg class="edge-svg" width="56" height="36" viewBox="0 0 56 36">
          <path class="edge-path" :class="{ 'edge-path--active': activity.collect }" d="M2 18 H54" />
          <path class="edge-arrow" :class="{ 'edge-arrow--active': activity.collect }" d="M46 13 L56 18 L46 23 Z" />
        </svg>
      </div>

      <!-- Brain node -->
      <div class="node node--brain" :class="{ 'node--active': activity.brain, 'node--offline': !llm.online }">
        <div class="node__head">
          <div class="node__icon"><icon name="brain" :size="18"/></div>
          <div class="node__titles">
            <div class="node__title">Pi 5 &middot; Brain</div>
            <div class="node__sub">{{ llm.model || 'LFM3-1.7B' }}</div>
          </div>
          <div class="node__state"><status-pill :status="llmStatus.v" :pulse="llmStatus.v==='warn'" :label="llmStatus.label"/></div>
        </div>
        <template v-if="state.hub.sys">
          <div class="node__metrics">
            <div class="node__metric">
              <span class="node__metric-label"><icon name="cpu" :size="10"/>CPU</span>
              <span class="node__metric-value tabular">{{ fmtPct(state.hub.sys.cpu_pct) }}</span>
            </div>
            <div class="node__metric">
              <span class="node__metric-label"><icon name="thermometer" :size="10"/>Temp</span>
              <span class="node__metric-value tabular">{{ fmtTemp(state.hub.sys.temp_c) }}</span>
            </div>
            <div class="node__metric">
              <span class="node__metric-label">ctx</span>
              <span class="node__metric-value tabular">{{ llm.ctx ? (llm.ctx/1024)+'k' : '—' }}</span>
            </div>
          </div>
          <div class="node__metric-label" style="margin-top:12px"><icon name="ram" :size="10"/>RAM {{ fmtBytes(state.hub.sys.mem_used) }} / {{ fmtBytes(state.hub.sys.mem_total) }}</div>
          <div class="node__bar"><div class="node__bar-fill" :style="{width: ramPct(state.hub.sys)+'%'}"></div></div>
          <div class="node__spark"><sparkline :data="hubHistory" :height="26"/></div>
        </template>
        <div class="node__foot" v-if="llm.last">
          last {{ llm.last.phase }} &middot; {{ llm.last.gen_tps.toFixed(1) }} tok/s &middot; {{ fmtRelative(llm.last.at) }}
        </div>
      </div>

      <div class="edge-wrap">
        <svg class="edge-svg" width="56" height="36" viewBox="0 0 56 36">
          <path class="edge-path" :class="{ 'edge-path--active': activity.deliver }" d="M2 18 H54" />
          <path class="edge-arrow" :class="{ 'edge-arrow--active': activity.deliver }" d="M46 13 L56 18 L46 23 Z" />
        </svg>
      </div>

      <!-- Telegram node -->
      <div class="node node--telegram" :class="{ 'node--offline': tgStatus.v==='muted' }">
        <div class="node__head">
          <div class="node__icon"><icon name="send" :size="16"/></div>
          <div class="node__titles">
            <div class="node__title">Telegram</div>
            <div class="node__sub">{{ telegram.bot_username ? '@'+telegram.bot_username : '07:30 daily delivery' }}</div>
          </div>
          <div class="node__state"><status-pill :status="tgStatus.v" :pulse="tgStatus.pulse" :label="tgStatus.short" :title="tgStatus.label"/></div>
        </div>
        <div class="node__foot" v-if="telegram.error" style="color:var(--error)">{{ telegram.error }}</div>
        <div class="node__foot" v-else-if="telegram.enabled && telegram.token_set && !telegram.chat_id">Open the bot and send <code>/start</code> to link.</div>
        <div class="node__foot" v-else-if="telegramLast">
          <span v-if="telegramLast.ok" style="color:var(--ok)">Delivered {{ fmtRelative(telegramLast.at) }}</span>
          <span v-else style="color:var(--error)">Failed {{ fmtRelative(telegramLast.at) }}</span>
        </div>
        <div class="node__foot" v-else-if="telegram.chat_id">Linked to {{ telegram.chat_title || telegram.chat_id }}</div>
        <div class="node__foot" v-else>No deliveries yet this session.</div>
      </div>
    </div>
  </div>`,
};

export function register(app) {
  app.component('topology-card', TopologyCard);
}
