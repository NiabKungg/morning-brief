import { api } from '../api.js';
import { state, lastRun, onEvent, createTimeline } from '../store.js';

const { onMounted, onUnmounted, watch } = Vue;

export const LiveView = {
  name: 'LiveView',
  setup() {
    const timeline = createTimeline();
    let loadedId = null;
    let unsub = null;

    async function syncToRun(run) {
      if (!run) return;
      if (loadedId === run.id) {
        timeline.run = run;
        return;
      }
      loadedId = run.id;
      try {
        await timeline.load(run.id);
      } catch {
        // background sync failure (e.g. run no longer exists) - leave the
        // panel in its current state rather than surfacing an error
      }
    }

    watch(
      () => lastRun.value,
      (run) => {
        if (run) syncToRun(run);
      },
      { immediate: true },
    );

    onMounted(async () => {
      if (!lastRun.value) {
        try {
          const { runs } = await api.getRuns(1);
          if (!lastRun.value && runs && runs[0]) lastRun.value = runs[0];
        } catch {
          // no runs yet, or hub unreachable - command bar still usable
        }
      }
      unsub = onEvent((evt) => {
        if (loadedId === null) return;
        if (evt.type === 'run' && evt.run.id === loadedId) {
          timeline.apply(evt, { live: true });
        } else if ('run_id' in evt && evt.run_id === loadedId) {
          timeline.apply(evt, { live: true });
        }
      });
    });
    onUnmounted(() => {
      if (unsub) unsub();
    });

    return { state, timeline };
  },
  template: `
  <div class="view">
    <topology-card :run="timeline.run"/>
    <command-bar/>
    <run-stepper :run="timeline.run"/>

    <div class="live-grid">
      <div class="stack live-side">
        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="brain" :size="15"/>LLM console</div><div class="panel__sub">{{ state.llm.model }}</div></div>
          <div class="panel__body"><llm-console :phases="timeline.llmPhases"/></div>
        </div>
        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="briefs" :size="15"/>Brief preview</div></div>
          <div class="panel__body preview-pane"><brief-preview :brief="timeline.brief"/></div>
        </div>
      </div>

      <div class="stack live-main">
        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="sources" :size="15"/>Sources</div></div>
          <div class="panel__body"><source-grid :sources="timeline.sources"/></div>
        </div>
        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="items" :size="15"/>Live items</div><div class="panel__sub">{{ timeline.items.length }} seen this run</div></div>
          <div class="panel__body"><item-feed :items="timeline.items"/></div>
        </div>
        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="globe" :size="15"/>Crawl pages</div></div>
          <div class="panel__body"><crawl-feed :pages="timeline.pages"/></div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="panel__head"><div class="panel__title"><icon name="live" :size="15"/>Run log</div></div>
      <run-log :logs="timeline.logs"/>
    </div>
  </div>`,
};
