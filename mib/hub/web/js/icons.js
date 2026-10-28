// Hand-authored inline SVG icon set (24x24, stroke-based). No external
// requests, no icon fonts, no emoji. Each entry is trusted static markup
// (never derived from user input) rendered through a single <icon> component.

export const ICONS = {
  logo: '<path d="M4 16h16"/><path d="M7 16a5 5 0 0 1 10 0"/><path d="M12 7v2"/><path d="m8.5 8.5 1.4 1.4"/><path d="m15.5 8.5-1.4 1.4"/>',
  live: '<path d="M3 12h4l2-7 4 14 2-7h6"/>',
  briefs: '<path d="M7 3h7l4 4v13.5a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v4h4"/><path d="M9 12.5h6"/><path d="M9 16h6"/><path d="M9 9h2"/>',
  items: '<circle cx="5" cy="6" r="1.3"/><path d="M9 6h11"/><circle cx="5" cy="12" r="1.3"/><path d="M9 12h11"/><circle cx="5" cy="18" r="1.3"/><path d="M9 18h11"/>',
  runs: '<path d="M3 11a9 9 0 1 0 2.6-6.3"/><path d="M3 4v4h4"/><path d="M12 8v4l3 2"/>',
  sources: '<path d="m12 3 8 4.5-8 4.5-8-4.5L12 3Z"/><path d="m4 12 8 4.5 8-4.5"/><path d="m4 16.5 8 4.5 8-4.5"/>',
  settings: '<circle cx="12" cy="12" r="3.1"/><path d="M12 3v2.4M12 18.6V21M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M3 12h2.4M18.6 12H21M4.9 19.1l1.7-1.7M17.4 6.6l1.7-1.7"/>',
  wifi: '<path d="M2 8.5a15 15 0 0 1 20 0"/><path d="M5.5 12a10 10 0 0 1 13 0"/><path d="M9 15.5a5 5 0 0 1 6 0"/><circle cx="12" cy="19" r="1" fill="currentColor" stroke="none"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
  'check-circle': '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.5 2.5L16 9.5"/>',
  'x-circle': '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
  'alert-triangle': '<path d="M12 4 2.5 20h19L12 4Z"/><path d="M12 10v4"/><circle cx="12" cy="17.1" r=".6" fill="currentColor" stroke="none"/>',
  loader: '<path d="M20 12a8 8 0 1 1-8-8"/>',
  cpu: '<rect x="7" y="7" width="10" height="10" rx="1.5"/><rect x="10" y="10" width="4" height="4"/><path d="M9 3v2M12 3v2M15 3v2M9 19v2M12 19v2M15 19v2M3 9h2M3 12h2M3 15h2M19 9h2M19 12h2M19 15h2"/>',
  thermometer: '<rect x="10" y="3" width="4" height="11.5" rx="2"/><circle cx="12" cy="17.5" r="3"/><path d="M12 14.5v2.2"/>',
  ram: '<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"/><path d="M5 11.5v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"/>',
  send: '<path d="M21 3 3 10.5l7 2.5M21 3l-7.5 18-3.5-8M21 3 10.5 13.5"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18Z"/>',
  rss: '<circle cx="5.2" cy="18.8" r="1.6" fill="currentColor" stroke="none"/><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 5a15 15 0 0 1 15 15"/>',
  github: '<path d="M12 2a10 10 0 0 0-3.2 19.5c.5.1.7-.2.7-.5v-1.8c-2.8.6-3.4-1.3-3.4-1.3-.5-1.1-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.3 1.1 2.9.8.1-.7.4-1.1.6-1.4-2.3-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.6-.1-.3-.5-1.3.1-2.6 0 0 .8-.3 2.7 1a9.4 9.4 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.3.2 2.3.1 2.6.6.7 1 1.6 1 2.6 0 3.9-2.3 4.7-4.6 5 .4.3.7 1 .7 2v2.9c0 .3.2.6.7.5A10 10 0 0 0 12 2Z"/>',
  reddit: '<circle cx="12" cy="13.5" r="7.5"/><circle cx="9" cy="13" r="1.1" fill="currentColor" stroke="none"/><circle cx="15" cy="13" r="1.1" fill="currentColor" stroke="none"/><path d="M8.5 16.2c1.9 1.3 5.1 1.3 7 0"/><path d="M12 6V3M16 3.3a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6Z"/>',
  markets: '<path d="M3 17 9 11l4 4 8-9"/><path d="M14 8h6v6"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M3.5 10h17"/><path d="M8 3v4M16 3v4"/><path d="M8 14h.01M12 14h.01M16 14h.01M8 17.5h.01M12 17.5h.01"/>',
  play: '<path d="M7 4.5v15l13-7.5-13-7.5Z"/>',
  square: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.4M4 4v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.4M20 20v-5h-5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  trash: '<path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/><path d="M10 11v6M14 11v6"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
  'external-link': '<path d="M9 6H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"/><path d="M14 4h6v6"/><path d="M10 14 20 4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.3-4.3"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  'chevron-right': '<path d="m9 6 6 6-6 6"/>',
  link: '<path d="M9.5 14.5 14.5 9.5"/><path d="M11 6.5 12.6 5a3.6 3.6 0 0 1 5 5l-1.6 1.6"/><path d="M13 17.5 11.4 19a3.6 3.6 0 1 1-5-5l1.6-1.6"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.7"/>',
  'trend-up': '<path d="M7 17 17 7"/><path d="M9 7h8v8"/>',
  'trend-down': '<path d="M7 7 17 17"/><path d="M17 9V17H9"/>',
  inbox: '<path d="M3 13h5l1.5 2.5h5L16 13h5"/><path d="M5.5 5h13L21 13v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5L5.5 5Z"/>',
  filter: '<path d="M4 5h16l-6 7.5V19l-4 2v-8.5L4 5Z"/>',
  upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M5 16v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  brain: '<circle cx="12" cy="12" r="3"/><circle cx="4.5" cy="7" r="1.4"/><circle cx="19.5" cy="7" r="1.4"/><circle cx="4.5" cy="17" r="1.4"/><circle cx="19.5" cy="17" r="1.4"/><path d="M9.3 10.3 5.6 7.8M14.7 10.3l3.7-2.5M9.3 13.7l-3.7 2.5M14.7 13.7l3.7 2.5"/>',
};

export const Icon = {
  name: 'Icon',
  props: {
    name: { type: String, required: true },
    size: { type: [Number, String], default: 18 },
  },
  computed: {
    paths() {
      return ICONS[this.name] || '';
    },
  },
  template: `<svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="icon" aria-hidden="true" v-html="paths"></svg>`,
};

export function register(app) {
  app.component('icon', Icon);
}
