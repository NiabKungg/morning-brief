import { api } from '../api.js';
import { pushToast } from '../store.js';

const { reactive, ref, onMounted, watch } = Vue;

export const ItemsView = {
  name: 'ItemsView',
  setup() {
    const items = ref([]);
    const total = ref(0);
    const loading = ref(false);
    const filters = reactive({ q: '', source: '', status: 'all', hours: 24, limit: 200 });
    let debounceTimer = null;

    async function load() {
      loading.value = true;
      try {
        const res = await api.getItems({
          q: filters.q,
          source: filters.source,
          status: filters.status,
          hours: filters.hours,
          limit: filters.limit,
        });
        items.value = res.items;
        total.value = res.total;
      } catch (e) {
        pushToast(e.message || 'Could not load items.', 'error');
      } finally {
        loading.value = false;
      }
    }

    function loadMore() {
      filters.limit += 200;
      load();
    }

    watch(() => [filters.source, filters.status, filters.hours], load);
    watch(
      () => filters.q,
      () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(load, 300);
      },
    );

    onMounted(load);

    return { items, total, loading, filters, loadMore };
  },
  template: `
  <div class="view">
    <div class="view-head">
      <div>
        <h1>Items</h1>
        <p class="tabular">{{ total }} matched &middot; showing {{ items.length }}</p>
      </div>
    </div>
    <div class="panel">
      <div class="panel__body">
        <div class="toolbar">
          <input class="input" v-model="filters.q" placeholder="Search title or summary…"/>
          <select class="select" v-model="filters.source">
            <option value="">All sources</option>
            <option value="rss">RSS</option>
            <option value="github">GitHub</option>
            <option value="reddit">Reddit</option>
            <option value="markets">Markets</option>
            <option value="calendar">Calendar</option>
            <option value="web">Web</option>
          </select>
          <select class="select" v-model="filters.status">
            <option value="all">All statuses</option>
            <option value="kept">Kept</option>
            <option value="dropped">Dropped</option>
            <option value="untriaged">Untriaged</option>
          </select>
          <select class="select" v-model.number="filters.hours">
            <option :value="1">Last 1h</option>
            <option :value="6">Last 6h</option>
            <option :value="12">Last 12h</option>
            <option :value="24">Last 24h</option>
            <option :value="48">Last 48h</option>
            <option :value="168">Last 7d</option>
          </select>
        </div>
      </div>
    </div>
    <empty-state v-if="!loading && !items.length" icon="search" title="No items match"
      hint="Try widening the time window or clearing filters."/>
    <div v-else class="feed" style="max-height:none">
      <item-row v-for="it in items" :key="it.id" :item="it"/>
    </div>
    <div v-if="items.length < total" style="text-align:center">
      <button class="btn" @click="loadMore" :disabled="loading">Load more</button>
    </div>
  </div>`,
};
