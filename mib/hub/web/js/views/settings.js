import { api } from '../api.js';
import { state, pushToast, onEvent } from '../store.js';
import { deepDiff } from '../settings-diff.js';

const { reactive, ref, computed, onMounted, onUnmounted } = Vue;

export const SettingsView = {
  name: 'SettingsView',
  setup() {
    const original = ref(null);
    const draft = reactive({ profile: null, schedule: null, pipeline: null, delivery: null });
    const tgStatus = ref({ set: false, hint: null });
    const discordStatus = ref({ set: false, hint: null });
    const tgTokenEdit = ref(undefined);
    const discordWebhookEdit = ref(undefined);
    const loading = ref(true);
    const saving = ref(false);
    const testing = ref(false);
    const testResults = ref(null);

    function hydrate(settings) {
      draft.profile = structuredClone(settings.profile);
      draft.schedule = structuredClone(settings.schedule);
      draft.pipeline = structuredClone(settings.pipeline);
      draft.delivery = {
        telegram: { enabled: settings.delivery.telegram.enabled, chat_id: settings.delivery.telegram.chat_id },
        discord: { enabled: settings.delivery.discord.enabled },
      };
      tgStatus.value = settings.delivery.telegram.token || { set: false, hint: null };
      discordStatus.value = settings.delivery.discord.webhook || { set: false, hint: null };
      tgTokenEdit.value = undefined;
      discordWebhookEdit.value = undefined;
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
    const unsub = onEvent((evt) => {
      if (evt.type === 'settings' && !dirty.value) hydrate(evt.settings);
    });
    onUnmounted(unsub);

    const dirty = computed(() => {
      if (!original.value) return false;
      const o = original.value;
      const current = { profile: draft.profile, schedule: draft.schedule, pipeline: draft.pipeline, delivery: draft.delivery };
      const base = {
        profile: o.profile,
        schedule: o.schedule,
        pipeline: o.pipeline,
        delivery: {
          telegram: { enabled: o.delivery.telegram.enabled, chat_id: o.delivery.telegram.chat_id },
          discord: { enabled: o.delivery.discord.enabled },
        },
      };
      const d = deepDiff(current, base);
      return (d && Object.keys(d).length > 0) || tgTokenEdit.value !== undefined || discordWebhookEdit.value !== undefined;
    });

    function addCollectTime() {
      draft.schedule.collect_times.push('00:30');
    }
    function removeCollectTime(i) {
      draft.schedule.collect_times.splice(i, 1);
    }

    async function save() {
      if (!dirty.value) return;
      saving.value = true;
      try {
        const o = original.value;
        const current = { profile: draft.profile, schedule: draft.schedule, pipeline: draft.pipeline, delivery: draft.delivery };
        const base = {
          profile: o.profile,
          schedule: o.schedule,
          pipeline: o.pipeline,
          delivery: {
            telegram: { enabled: o.delivery.telegram.enabled, chat_id: o.delivery.telegram.chat_id },
            discord: { enabled: o.delivery.discord.enabled },
          },
        };
        const patch = deepDiff(current, base) || {};
        if (tgTokenEdit.value !== undefined) {
          patch.delivery = patch.delivery || {};
          patch.delivery.telegram = { ...(patch.delivery.telegram || {}), token: tgTokenEdit.value };
        }
        if (discordWebhookEdit.value !== undefined) {
          patch.delivery = patch.delivery || {};
          patch.delivery.discord = { ...(patch.delivery.discord || {}), webhook: discordWebhookEdit.value };
        }
        const updated = await api.putSettings(patch);
        pushToast('Settings saved.', 'ok');
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
    async function sendTest() {
      testing.value = true;
      testResults.value = null;
      try {
        const res = await api.testDelivery();
        testResults.value = res.results;
        const allOk = res.results.every((r) => r.ok);
        pushToast(allOk ? 'Test delivery sent.' : 'Test delivery finished with errors.', allOk ? 'ok' : 'warn');
      } catch (e) {
        pushToast(e.message || 'Could not send test delivery.', 'error');
      } finally {
        testing.value = false;
      }
    }

    return {
      state,
      draft,
      loading,
      saving,
      dirty,
      tgStatus,
      discordStatus,
      tgTokenEdit,
      discordWebhookEdit,
      testing,
      testResults,
      addCollectTime,
      removeCollectTime,
      save,
      discard,
      sendTest,
    };
  },
  template: `
  <div class="view">
    <div class="view-head"><div><h1>Settings</h1><p>Profile, schedule, pipeline tuning and delivery channels.</p></div></div>

    <div v-if="loading" class="panel"><div class="panel__body"><span class="muted">Loading&hellip;</span></div></div>
    <div v-else class="settings-grid">
      <div style="display:flex;flex-direction:column;gap:var(--sp-5)">
        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="settings" :size="15"/>Profile</div></div>
          <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-4)">
            <div class="field">
              <label class="field__label">Name</label>
              <input class="input" v-model="draft.profile.name"/>
            </div>
            <div class="field">
              <label class="field__label">Interests</label>
              <textarea class="textarea" style="font-family:var(--font-sans)" rows="4" v-model="draft.profile.interests"
                placeholder="What should the brief pay extra attention to?"></textarea>
            </div>
            <div class="field" style="max-width:200px">
              <label class="field__label">Language</label>
              <select class="select" v-model="draft.profile.language"><option value="en">English</option><option value="th">Thai</option></select>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel__head">
            <div class="panel__title"><icon name="clock" :size="15"/>Schedule</div>
            <label class="switch"><input type="checkbox" v-model="draft.schedule.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
          </div>
          <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-4)">
            <div class="field">
              <label class="field__label">Collection times</label>
              <div class="feed-list">
                <div v-for="(t,i) in draft.schedule.collect_times" :key="i" class="feed-row">
                  <input class="input" type="time" v-model="draft.schedule.collect_times[i]" style="max-width:140px"/>
                  <button type="button" class="btn btn--icon btn--ghost" @click="removeCollectTime(i)" aria-label="Remove"><icon name="trash" :size="14"/></button>
                </div>
              </div>
              <button type="button" class="btn btn--sm btn--add" style="margin-top:8px" @click="addCollectTime"><icon name="plus" :size="13"/>Add time</button>
            </div>
            <div class="field-grid">
              <div class="field">
                <label class="field__label">Brief time</label>
                <input class="input" type="time" v-model="draft.schedule.brief_time"/>
              </div>
              <div class="field">
                <label class="field__label">Prep minutes</label>
                <input class="input" type="number" min="0" v-model.number="draft.schedule.prep_minutes"/>
                <span class="field__hint">Lead time before brief_time to begin collection.</span>
              </div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="cpu" :size="15"/>Pipeline</div></div>
          <div class="panel__body field-grid">
            <div class="field">
              <label class="field__label">Window (hours)</label>
              <input class="input" type="number" min="1" v-model.number="draft.pipeline.window_hours"/>
            </div>
            <div class="field">
              <label class="field__label">Triage threshold</label>
              <input class="input" type="number" min="0" max="10" v-model.number="draft.pipeline.triage_threshold"/>
              <span class="field__hint">Minimum 0&ndash;10 score to keep an item.</span>
            </div>
            <div class="field">
              <label class="field__label">Max brief items</label>
              <input class="input" type="number" min="1" v-model.number="draft.pipeline.max_brief_items"/>
            </div>
            <div class="field">
              <label class="field__label">Enrich limit</label>
              <input class="input" type="number" min="0" v-model.number="draft.pipeline.enrich_limit"/>
            </div>
          </div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:var(--sp-5)">
        <div class="panel">
          <div class="panel__head">
            <div class="panel__title"><icon name="send" :size="15"/>Telegram</div>
            <label class="switch"><input type="checkbox" v-model="draft.delivery.telegram.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
          </div>
          <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-4)">
            <secret-field label="Bot token" v-model="tgTokenEdit" :status="tgStatus" placeholder="123456:ABC-token"/>
            <div class="field" style="max-width:260px">
              <label class="field__label">Chat ID <span class="muted" style="font-weight:500;text-transform:none">(optional)</span></label>
              <input class="input" v-model="draft.delivery.telegram.chat_id" placeholder="-100123456789"/>
              <span class="field__hint">Leave empty and send /start to your bot to link this chat automatically.</span>
            </div>

            <div class="tg-status">
              <div class="tg-status__row">
                <icon name="send" :size="14" style="color:var(--text-3)"/>
                <a v-if="state.telegram.bot_username" :href="state.telegram.link_url" target="_blank" rel="noopener">@{{ state.telegram.bot_username }}</a>
                <span v-else class="muted">Bot not verified yet</span>
                <span class="tg-status__poll" :class="{'tg-status__poll--on': state.telegram.polling}">
                  <span class="status-dot" :class="state.telegram.polling ? 'status-dot--ok status-dot--pulse' : ''"></span>{{ state.telegram.polling ? 'polling' : 'idle' }}
                </span>
              </div>
              <div v-if="state.telegram.chat_id" class="tg-status__line" style="color:var(--ok)">
                <icon name="check-circle" :size="13"/>Linked to <strong>{{ state.telegram.chat_title || 'this chat' }}</strong>&nbsp;<span class="muted">({{ state.telegram.chat_id }})</span>
              </div>
              <div v-else-if="state.telegram.enabled && state.telegram.token_set" class="tg-status__line" style="color:var(--warn)">
                <icon name="alert-triangle" :size="13"/>Not linked yet &mdash; open
                <a v-if="state.telegram.link_url" :href="state.telegram.link_url" target="_blank" rel="noopener">t.me/{{ state.telegram.bot_username }}</a><span v-else>&nbsp;your bot</span>
                and send <code>/start</code>
              </div>
              <div v-if="state.telegram.error" class="tg-status__line" style="color:var(--error)"><icon name="x-circle" :size="13"/>{{ state.telegram.error }}</div>
            </div>

            <div class="tg-steps">
              <div class="tg-step"><span class="tg-step__num">1</span><span>Create a bot with <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> and copy its token.</span></div>
              <div class="tg-step"><span class="tg-step__num">2</span><span>Paste the token above and save.</span></div>
              <div class="tg-step"><span class="tg-step__num">3</span><span>Open your bot and send <code>/start</code> to link this chat.</span></div>
            </div>
            <p class="field__hint">Send <code>/now</code> any time for an instant brief.</p>
          </div>
        </div>

        <div class="panel">
          <div class="panel__head">
            <div class="panel__title"><icon name="link" :size="15"/>Discord</div>
            <label class="switch"><input type="checkbox" v-model="draft.delivery.discord.enabled"/><span class="switch__track"><span class="switch__thumb"></span></span><span class="switch__label">Enabled</span></label>
          </div>
          <div class="panel__body">
            <secret-field label="Webhook URL" v-model="discordWebhookEdit" :status="discordStatus" placeholder="https://discord.com/api/webhooks/…"/>
          </div>
        </div>

        <div class="panel">
          <div class="panel__head"><div class="panel__title"><icon name="check-circle" :size="15"/>Test delivery</div></div>
          <div class="panel__body" style="display:flex;flex-direction:column;gap:var(--sp-3)">
            <p class="muted" style="font-size:12.5px">Sends a short test message to every enabled, configured channel using the saved settings.</p>
            <button type="button" class="btn" :disabled="testing" @click="sendTest" style="align-self:flex-start"><icon name="send" :size="14"/>Send test</button>
            <div v-if="testResults" class="delivery-results">
              <div v-for="r in testResults" :key="r.channel" class="delivery-result">
                <icon :name="r.ok?'check-circle':'x-circle'" :size="14" :style="{color: r.ok?'var(--ok)':'var(--error)'}"/>
                <span style="text-transform:capitalize">{{ r.channel }}</span>
                <span class="muted">{{ r.ok ? 'delivered' : (r.error || 'failed') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="dirty" class="unsaved-bar">
      <span class="unsaved-bar__msg"><icon name="alert-triangle" :size="14"/>You have unsaved changes.</span>
      <div style="display:flex;gap:8px">
        <button type="button" class="btn btn--ghost btn--sm" :disabled="saving" @click="discard">Discard</button>
        <button type="button" class="btn btn--primary btn--sm" :disabled="saving" @click="save"><icon name="check" :size="13"/>Save changes</button>
      </div>
    </div>
  </div>`,
};
