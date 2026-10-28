// Pure formatting helpers shared across components. No DOM/Vue dependency.

const nf = new Intl.NumberFormat('en-US');

export function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return nf.format(n);
}

export function fmtBytes(bytes, digits = 1) {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '—';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024)));
  const v = bytes / 1024 ** i;
  return `${v.toFixed(i === 0 ? 0 : digits)} ${units[i]}`;
}

export function fmtPct(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return `${n.toFixed(digits)}%`;
}

export function fmtTemp(c) {
  if (c === null || c === undefined || Number.isNaN(c)) return '—';
  return `${Math.round(c)}°C`;
}

export function fmtMoney(price, currency) {
  if (price === null || price === undefined || Number.isNaN(price)) return '—';
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency || 'USD',
      maximumFractionDigits: Math.abs(price) < 10 ? 4 : 2,
    }).format(price);
  } catch {
    return `${price} ${currency || ''}`.trim();
  }
}

export function fmtChangePct(pct) {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return { text: '—', cls: 'muted' };
  const sign = pct > 0 ? '+' : '';
  return { text: `${sign}${pct.toFixed(2)}%`, cls: pct > 0 ? 'pos' : pct < 0 ? 'neg' : 'muted' };
}

// Seconds -> "2m 14s" / "1h 03m" / "3d 02h"
export function fmtDuration(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined || Number.isNaN(totalSeconds) || totalSeconds < 0) return '—';
  const s = Math.floor(totalSeconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = s % 60;
  if (days > 0) return `${days}d ${String(hours).padStart(2, '0')}h`;
  if (hours > 0) return `${hours}h ${String(mins).padStart(2, '0')}m`;
  if (mins > 0) return `${mins}m ${String(secs).padStart(2, '0')}s`;
  return `${secs}s`;
}

export function elapsedSeconds(startIso, endIso, nowMs) {
  if (!startIso) return null;
  const start = Date.parse(startIso);
  if (Number.isNaN(start)) return null;
  const end = endIso ? Date.parse(endIso) : nowMs ?? Date.now();
  return Math.max(0, (end - start) / 1000);
}

// "in 3h 12m" / "in 42m" / "overdue" for a future iso timestamp.
export function fmtCountdown(iso, nowMs) {
  if (!iso) return '—';
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return '—';
  const now = nowMs ?? Date.now();
  let diff = Math.round((target - now) / 1000);
  if (diff <= 0) return 'any moment';
  const hours = Math.floor(diff / 3600);
  const mins = Math.floor((diff % 3600) / 60);
  if (hours > 0) return `in ${hours}h ${String(mins).padStart(2, '0')}m`;
  if (mins > 0) return `in ${mins}m`;
  return `in <1m`;
}

// "3m ago" / "just now" / "in 5m" for a past-or-future iso timestamp.
export function fmtRelative(iso, nowMs) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const now = nowMs ?? Date.now();
  const diffS = Math.round((now - t) / 1000);
  const abs = Math.abs(diffS);
  const future = diffS < 0;
  if (abs < 10) return 'just now';
  const units = [
    ['y', 31536000],
    ['mo', 2592000],
    ['d', 86400],
    ['h', 3600],
    ['m', 60],
  ];
  for (const [label, secs] of units) {
    if (abs >= secs) {
      const v = Math.floor(abs / secs);
      return future ? `in ${v}${label}` : `${v}${label} ago`;
    }
  }
  return future ? `in ${abs}s` : `${abs}s ago`;
}

export function fmtClock(nowMs, tz) {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: tz || undefined,
    }).format(nowMs ?? Date.now());
  } catch {
    const d = new Date(nowMs ?? Date.now());
    return d.toTimeString().slice(0, 8);
  }
}

export function fmtTime(iso, tz) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  try {
    return new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: tz || undefined,
    }).format(t);
  } catch {
    return new Date(t).toTimeString().slice(0, 5);
  }
}

export function fmtDateTime(iso) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(t);
}

export function fmtDate(iso) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  return new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric' }).format(t);
}

export function truncate(str, n) {
  if (!str) return '';
  return str.length > n ? `${str.slice(0, n - 1)}…` : str;
}

export function hostFromUrl(url) {
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return url || '';
  }
}

export function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

const LANG_COLORS = {
  JavaScript: '#f1e05a',
  TypeScript: '#3178c6',
  Python: '#3572A5',
  Rust: '#dea584',
  Go: '#00ADD8',
  Java: '#b07219',
  'C++': '#f34b7d',
  C: '#555555',
  'C#': '#178600',
  Ruby: '#701516',
  PHP: '#4F5D95',
  Swift: '#F05138',
  Kotlin: '#A97BFF',
  Shell: '#89e051',
  HTML: '#e34c26',
  CSS: '#563d7c',
  Vue: '#41b883',
  Dart: '#00B4AB',
  Elixir: '#6e4a7e',
  Haskell: '#5e5086',
  Scala: '#c22d40',
  Lua: '#000080',
};

export function langColor(lang) {
  if (!lang) return '#8b93a7';
  if (LANG_COLORS[lang]) return LANG_COLORS[lang];
  let hash = 0;
  for (let i = 0; i < lang.length; i++) hash = (hash * 31 + lang.charCodeAt(i)) >>> 0;
  return `hsl(${hash % 360} 60% 62%)`;
}

export function titleCase(s) {
  return s ? String(s).replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : s;
}

// 0 (red) through 5 (amber) to 10 (green).
export function scoreColor(score) {
  const t = Math.max(0, Math.min(10, score)) / 10;
  return `hsl(${Math.round(t * 130)} 70% 55%)`;
}

// Derives a {v,label,short,pulse} status for the Telegram bot link, used by the topbar pill,
// topology node and Settings status block. `v` matches the status-pill variants (ok|warn|error|muted);
// `short` fits a pill on any screen, `label` is the full text (tooltip / status block).
export function telegramStatus(t) {
  if (!t || !t.enabled || !t.token_set) return { v: 'muted', label: 'not set up', short: 'not set up', pulse: false };
  if (t.error) return { v: 'error', label: t.error, short: 'error', pulse: false };
  if (!t.chat_id) return { v: 'warn', label: 'waiting for /start', short: 'send /start', pulse: true };
  return { v: 'ok', label: t.bot_username ? `@${t.bot_username}` : 'linked', short: 'linked', pulse: false };
}

export function triggerLabel(trigger) {
  if (trigger === 'telegram') return 'via Telegram /now';
  if (trigger === 'schedule') return 'Scheduled';
  return 'Manual';
}
