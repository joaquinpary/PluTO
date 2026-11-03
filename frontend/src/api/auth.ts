import { useSyncExternalStore } from 'react';
import { api } from './client';
import { clearTokens, getRefresh, hasSession, setTokens, subscribe } from './tokens';

/** Logs in and keeps the tokens. false when Django rejects the credentials. */
export async function login(username: string, password: string): Promise<boolean> {
  const { data, response } = await api.POST('/api/auth/token', { body: { username, password } });
  if (data !== undefined) {
    setTokens(data);
    return true;
  }
  if (response.status === 401) return false;
  throw new Error(`Login answered HTTP ${response.status}`);
}

/** Forgets the session and blacklists its refresh token (spec 3.3). */
export async function logout(): Promise<void> {
  const refresh = getRefresh();
  clearTokens();
  if (refresh === null) return;
  // If the server is down the token simply expires within a day.
  await api.POST('/api/auth/token/blacklist', { body: { refresh } }).catch(() => undefined);
}

/** Re-renders when the session starts or ends, e.g. when a refresh is rejected. */
export function useHasSession(): boolean {
  return useSyncExternalStore(subscribe, hasSession);
}
