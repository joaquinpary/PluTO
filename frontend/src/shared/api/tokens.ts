// Access token in memory only; refresh token in localStorage so a reload keeps the session.
export const REFRESH_KEY = 'pluto.refresh';

let access: string | null = null;
let inFlight: Promise<boolean> | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  listeners.forEach((listener) => listener());
}

export function setTokens(tokens: { access: string; refresh: string }): void {
  access = tokens.access;
  localStorage.setItem(REFRESH_KEY, tokens.refresh);
  notify();
}

export function clearTokens(): void {
  access = null;
  localStorage.removeItem(REFRESH_KEY);
  notify();
}

export function getAccess(): string | null {
  return access;
}

export function getRefresh(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

/** An access token, or a refresh token to get one. */
export function hasSession(): boolean {
  return access !== null || getRefresh() !== null;
}

/** Fires on every setTokens/clearTokens. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// One shared refresh: tokens rotate and are blacklisted once used, so a second
// refresh with the same one would log the user out.
export function refreshOnce(): Promise<boolean> {
  inFlight ??= refresh().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

async function refresh(): Promise<boolean> {
  const token = getRefresh();
  if (token === null) return false;

  let response: Response;
  try {
    // Plain fetch, not the api client: its 401 handling would call back in here.
    response = await fetch(new URL('/api/auth/token/refresh', window.location.origin), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: token }),
    });
  } catch {
    return false; // The server is unreachable; the refresh token may still be good.
  }

  if (response.status === 401) {
    // Another tab may have rotated it first: retry with the stored one.
    const current = getRefresh();
    if (current !== null && current !== token) return refresh();
    clearTokens(); // Expired or already used: only a new login helps.
    return false;
  }
  if (!response.ok) return false;
  setTokens(await response.json());
  return true;
}
