// Small shared presentational components, registered globally so any view
// or component template can use them without per-file registration.

import { toasts, dismissToast } from '../store.js';

export const StatusPill = {
  name: 'StatusPill',
  props: {
    status: { type: String, default: 'muted' }, // ok | warn | error | muted | accent
    label: { type: String, default: '' },
    pulse: { type: Boolean, default: false },
  },
  template: `<span class="pill" :class="'pill--'+status"><span class="status-dot" :class="['status-dot--'+status, pulse && 'status-dot--pulse']"></span><span v-if="label" class="pill__text">{{ label }}</span></span>`,
};

export const Sparkline = {
  name: 'Sparkline',
  props: {
    data: { type: Array, default: () => [] },
    width: { type: Number, default: 100 },
    height: { type: Number, default: 24 },
    max: { type: Number, default: 100 },
  },
  computed: {
    points() {
      const n = this.data.length;
      if (n < 2) return '';
      const w = this.width;
      const h = this.height;
      const max = Math.max(this.max, ...this.data, 1);
      return this.data
        .map((v, i) => {
          const x = (i / (n - 1)) * w;
          const y = h - (Math.max(0, Math.min(max, v)) / max) * (h - 3) - 1.5;
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
    },
  },
  template: `<svg class="sparkline-svg" :viewBox="'0 0 '+width+' '+height" preserveAspectRatio="none">
    <polyline v-if="points" :points="points" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`,
};

export const EmptyState = {
  name: 'EmptyState',
  props: { icon: { type: String, default: 'inbox' }, title: { type: String, default: '' }, hint: { type: String, default: '' } },
  template: `<div class="empty-state"><icon :name="icon" :size="26"/><div class="empty-state__title">{{ title }}</div><div v-if="hint" class="empty-state__hint">{{ hint }}</div></div>`,
};

export const ToastStack = {
  name: 'ToastStack',
  setup() {
    return { toasts, dismissToast };
  },
  methods: {
    iconFor(type) {
      return { error: 'x-circle', warn: 'alert-triangle', ok: 'check-circle' }[type] || 'send';
    },
  },
  template: `
    <div class="toasts">
      <transition-group name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="'toast--'+t.type">
          <icon class="toast__icon" :name="iconFor(t.type)" :size="16"/>
          <div>{{ t.message }}</div>
          <button class="toast__close" type="button" @click="dismissToast(t.id)" aria-label="Dismiss"><icon name="x" :size="13"/></button>
        </div>
      </transition-group>
    </div>`,
};

export const TagInput = {
  name: 'TagInput',
  props: {
    modelValue: { type: Array, default: () => [] },
    placeholder: { type: String, default: 'Add and press Enter…' },
    emptyLabel: { type: String, default: null },
  },
  emits: ['update:modelValue'],
  data() {
    return { draft: '' };
  },
  methods: {
    commit() {
      const v = this.draft.trim();
      if (v && !this.modelValue.includes(v)) this.$emit('update:modelValue', [...this.modelValue, v]);
      this.draft = '';
    },
    onKeydown(e) {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        this.commit();
      } else if (e.key === 'Backspace' && !this.draft && this.modelValue.length) {
        this.$emit('update:modelValue', this.modelValue.slice(0, -1));
      }
    },
    remove(i) {
      const next = this.modelValue.slice();
      next.splice(i, 1);
      this.$emit('update:modelValue', next);
    },
  },
  template: `
    <div class="tag-input" @click="$refs.inp.focus()">
      <span v-for="(t,i) in modelValue" :key="i" class="tag-chip" :class="{'tag-chip--placeholder': t===''}">{{ t===''&&emptyLabel ? emptyLabel : t }}<button type="button" @click.stop="remove(i)" aria-label="Remove"><icon name="x" :size="11"/></button></span>
      <input ref="inp" v-model="draft" :placeholder="modelValue.length ? '' : placeholder" @keydown="onKeydown" @blur="commit" />
    </div>`,
};

export const SecretField = {
  name: 'SecretField',
  props: {
    modelValue: { type: String, default: undefined },
    status: { type: Object, default: () => ({ set: false, hint: null }) },
    label: { type: String, default: '' },
    placeholder: { type: String, default: 'Paste new value…' },
  },
  emits: ['update:modelValue'],
  methods: {
    start() {
      this.$emit('update:modelValue', '');
      this.$nextTick(() => this.$refs.inp && this.$refs.inp.focus());
    },
    clear() {
      this.$emit('update:modelValue', '');
    },
    cancel() {
      this.$emit('update:modelValue', undefined);
    },
  },
  template: `
    <div class="field">
      <label class="field__label">{{ label }}</label>
      <div class="secret-field">
        <span class="secret-field__status">
          <template v-if="modelValue===''">Will be cleared on save.</template>
          <template v-else-if="modelValue">New value staged &mdash; will replace on save.</template>
          <template v-else-if="status.set">Set<template v-if="status.hint"> &middot; {{ status.hint }}</template></template>
          <template v-else>Not set.</template>
        </span>
        <input v-if="modelValue !== undefined" ref="inp" class="input" type="password" :value="modelValue"
          @input="$emit('update:modelValue', $event.target.value)" :placeholder="placeholder" style="max-width:260px"/>
        <button v-if="modelValue === undefined" type="button" class="btn btn--sm" @click="start">{{ status.set ? 'Replace' : 'Set' }}</button>
        <button v-if="modelValue === undefined && status.set" type="button" class="btn btn--sm btn--ghost" @click="clear">Clear</button>
        <button v-if="modelValue !== undefined" type="button" class="btn btn--sm btn--ghost" @click="cancel">Cancel</button>
      </div>
    </div>`,
};

export function register(app) {
  app.component('status-pill', StatusPill);
  app.component('sparkline', Sparkline);
  app.component('empty-state', EmptyState);
  app.component('toast-stack', ToastStack);
  app.component('tag-input', TagInput);
  app.component('secret-field', SecretField);
}
