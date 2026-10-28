// Deep-partial diff: returns only the keys where `draft` differs from
// `original`, so PUT /api/settings only ever sends changed fields. Arrays
// are compared atomically (by content) — if they differ at all, the whole
// new array is included, matching how list-style fields are edited in the UI.

export function deepDiff(draft, original) {
  if (draft === original) return undefined;
  if (Array.isArray(draft) || Array.isArray(original)) {
    return JSON.stringify(draft) === JSON.stringify(original) ? undefined : draft;
  }
  if (draft && original && typeof draft === 'object' && typeof original === 'object') {
    const out = {};
    let changed = false;
    for (const key of Object.keys(draft)) {
      const d = deepDiff(draft[key], original[key]);
      if (d !== undefined) {
        out[key] = d;
        changed = true;
      }
    }
    return changed ? out : undefined;
  }
  return draft !== original ? draft : undefined;
}
