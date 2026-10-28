import { clock } from '../store.js';
import { titleCase } from '../format.js';

// -------------------------------------------------------------- LlmConsole
export const LlmConsole = {
  name: 'LlmConsole',
  props: { phases: { type: Array, default: () => [] } },
  setup() {
    return { clock };
  },
  data() {
    return { paused: false };
  },
  watch: {
    phases: {
      handler() {
        if (this.paused) return;
        this.$nextTick(() => {
          const el = this.$refs.pane;
          if (el) el.scrollTop = el.scrollHeight;
        });
      },
      deep: true,
    },
  },
  methods: {
    tps(p) {
      if (p.stats) return p.stats.gen_tps.toFixed(1);
      const elapsed = (this.clock - p.startedAt) / 1000;
      if (elapsed < 0.3) return '…';
      return (p.approxTokens / elapsed).toFixed(1);
    },
  },
  template: `
  <div class="console" ref="pane" @mouseenter="paused=true" @mouseleave="paused=false">
    <div v-if="!phases.length" class="muted" style="font-family:var(--font-sans)">Model output streams here once a job touches the LLM.</div>
    <div v-for="(p,i) in phases" :key="i" class="llm-phase">
      <div class="llm-phase__head">
        <span class="badge">{{ p.phase }}</span>
        <span class="llm-phase__label">{{ p.label || p.phase }}</span>
        <span class="llm-phase__tps tabular">{{ tps(p) }} tok/s<template v-if="!p.endedAt"> (est.)</template></span>
      </div>
      <div class="llm-phase__text">{{ p.text }}<span v-if="!p.endedAt" class="llm-cursor"></span></div>
      <div v-if="p.stats" class="llm-phase__stats tabular">
        <span>{{ p.stats.prompt_tokens }} prompt</span>
        <span>{{ p.stats.gen_tokens }} gen</span>
        <span>{{ p.stats.prompt_tps.toFixed(1) }} p-tok/s</span>
        <span>{{ p.stats.gen_tps.toFixed(1) }} gen-tok/s</span>
        <span>{{ (p.stats.ms/1000).toFixed(1) }}s</span>
      </div>
    </div>
  </div>`,
};

// ------------------------------------------------------------- BriefPreview
// Progressive render of the synth/web token stream; swaps to the
// authoritative DOC (via doc-body) once the brief event + fetch resolve.
export const BriefPreview = {
  name: 'BriefPreview',
  props: { brief: { type: Object, required: true } },
  methods: { titleCase },
  template: `
  <div>
    <div v-if="brief.full" class="brief-live">
      <div class="brief-live__ready">
        <icon name="check-circle" :size="14"/>Brief ready
        <a :href="'#/briefs/'+brief.full.id" class="btn btn--sm"><icon name="external-link" :size="12"/>Open brief</a>
      </div>
      <div class="brief-live__headline">{{ brief.full.doc.headline }}</div>
      <div class="reader reader--compact"><doc-body :doc="brief.full.doc"/></div>
    </div>
    <div v-else-if="brief.partialDoc" class="brief-live">
      <div v-if="brief.partialDoc.headline" class="brief-live__headline">{{ brief.partialDoc.headline }}<span class="llm-cursor"></span></div>
      <div v-if="brief.partialDoc.tldr && brief.partialDoc.tldr.length" class="brief-live__section">
        <div class="brief-live__section-title">TL;DR</div>
        <ul class="brief-live__bullets"><li v-for="(t,i) in brief.partialDoc.tldr" :key="i">{{ t.text }}</li></ul>
      </div>
      <div v-for="(sec,i) in (brief.partialDoc.sections||[])" :key="i" class="brief-live__section">
        <div class="brief-live__section-title">{{ titleCase(sec.key) }}</div>
        <ul class="brief-live__bullets"><li v-for="(b,j) in (sec.bullets||[])" :key="j">{{ b.text }}</li></ul>
      </div>
      <p v-if="brief.partialDoc.watch && brief.partialDoc.watch.length" class="muted" style="margin-top:14px;font-size:12.5px">
        Watching: {{ brief.partialDoc.watch.join(', ') }}
      </p>
    </div>
    <empty-state v-else icon="briefs" title="No brief yet"
      hint="The Executive Summary writes itself here once synthesis begins."/>
  </div>`,
};

export function register(app) {
  app.component('llm-console', LlmConsole);
  app.component('brief-preview', BriefPreview);
}
