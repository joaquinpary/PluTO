/**
 * The session (spec 3.3). The access token lives only in memory; the refresh
 * token goes to localStorage, so reopening the page does not ask for the
 * password again.
 */
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

/** Whether there is a session to try: an access token, or a refresh token to get one. */
export function hasSession(): boolean {
  return access !== null || getRefresh() !== null;
}

/** Called after every setTokens and clearTokens. Returns the unsubscribe. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Trades the refresh token for a new pair; true if it worked. Every caller
 * shares the request in flight: the refresh token rotates and is blacklisted
 * once used, so a second refresh with the same one would fail and log the
 * user out (Review Focus 1).
 */
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
    // Another tab may have used the same token first and stored the next one:
    // the session is still good, so try again with it.
    const current = getRefresh();
    if (current !== null && current !== token) return refresh();
    clearTokens(); // Expired or already used: only a new login helps.
    return false;
  }
  if (!response.ok) return false;
  setTokens(await response.json());
  return true;
}
