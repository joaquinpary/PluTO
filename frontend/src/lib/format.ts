/** 12345 centidegrees -> "123.45°"; nothing to show -> "—". */
export function formatCdeg(cdeg: number | null | undefined): string {
  return cdeg == null ? '—' : `${(cdeg / 100).toFixed(2)}°`;
}

/** How long ago an ISO instant was: "hace 4 s", "hace 3 min", "hace 2 h", "hace 5 d". */
export function formatAge(iso: string, now: number): string {
  // A server clock slightly ahead of the browser's would give a negative age.
  const seconds = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000));
  if (seconds < 60) return `hace ${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.floor(hours / 24)} d`;
}

/** An instant from the API (UTC, ISO 8601) in the browser's local time (spec 6). */
export function formatDateTime(iso: string | null): string {
  return iso === null ? '—' : new Date(iso).toLocaleString('es-AR');
}
