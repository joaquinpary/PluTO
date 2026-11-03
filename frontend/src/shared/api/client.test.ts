import { delay, http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { server } from '../../test/server';
import { api } from './client';
import { getAccess, REFRESH_KEY, setTokens, subscribe } from './tokens';

// A route that only answers the given access token, like Django after it expires.
function onlyFor(access: string) {
  return ({ request }: { request: Request }) =>
    request.headers.get('Authorization') === `Bearer ${access}`
      ? HttpResponse.json([])
      : HttpResponse.json({ detail: 'Given token not valid for any token type' }, { status: 401 });
}

describe('api client', () => {
  it('keeps the session when another tab rotated the refresh token first', async () => {
    // Two tabs reopened together both refresh with r1: the one that loses gets
    // a 401, but r2 is already in localStorage and the session is still good.
    setTokens({ access: 'expired', refresh: 'r1' });
    const used: string[] = [];
    server.use(
      http.post('/api/auth/token/refresh', async ({ request }) => {
        const { refresh } = (await request.json()) as { refresh: string };
        used.push(refresh);
        if (refresh === 'r1') {
          localStorage.setItem(REFRESH_KEY, 'r2'); // the other tab won
          return HttpResponse.json({ detail: 'Token is blacklisted' }, { status: 401 });
        }
        return HttpResponse.json({ access: 'a3', refresh: 'r3' });
      }),
      http.get('/api/boards', onlyFor('a3')),
    );

    const { response } = await api.GET('/api/boards');

    expect(response.status).toBe(200);
    expect(used).toEqual(['r1', 'r2']);
    expect(localStorage.getItem(REFRESH_KEY)).toBe('r3');
  });

  it('sends the access token', async () => {
    setTokens({ access: 'a1', refresh: 'r1' });
    server.use(http.get('/api/boards', onlyFor('a1')));

    const { response } = await api.GET('/api/boards');

    expect(response.status).toBe(200);
  });

  it('refreshes ONCE when two requests get 401 at the same time', async () => {
    setTokens({ access: 'expired', refresh: 'r1' });
    const refreshBodies: unknown[] = [];
    server.use(
      http.post('/api/auth/token/refresh', async ({ request }) => {
        refreshBodies.push(await request.json());
        await delay(50); // keeps the first refresh in flight while the second 401 arrives
        return HttpResponse.json({ access: 'a2', refresh: 'r2' });
      }),
      http.get('/api/boards', onlyFor('a2')),
      http.get('/api/boards/live', onlyFor('a2')),
    );

    const [boards, live] = await Promise.all([api.GET('/api/boards'), api.GET('/api/boards/live')]);

    expect(boards.response.status).toBe(200);
    expect(live.response.status).toBe(200);
    expect(refreshBodies).toEqual([{ refresh: 'r1' }]);
    expect(getAccess()).toBe('a2');
    expect(localStorage.getItem(REFRESH_KEY)).toBe('r2');
  });

  it('does not refresh again for a 401 that arrives after another request already did', async () => {
    setTokens({ access: 'expired', refresh: 'r1' });
    let refreshes = 0;
    server.use(
      http.post('/api/auth/token/refresh', () => {
        refreshes += 1;
        return HttpResponse.json({ access: 'a2', refresh: 'r2' });
      }),
      http.get('/api/boards', onlyFor('a2')),
      http.get('/api/boards/live', async ({ request }) => {
        await delay(100); // answers 401 once the other request has refreshed
        return onlyFor('a2')({ request });
      }),
    );

    const [boards, live] = await Promise.all([api.GET('/api/boards'), api.GET('/api/boards/live')]);

    expect(boards.response.status).toBe(200);
    expect(live.response.status).toBe(200);
    expect(refreshes).toBe(1);
  });

  it('forgets the session when the refresh token is rejected', async () => {
    setTokens({ access: 'expired', refresh: 'used' });
    const onChange = vi.fn();
    const unsubscribe = subscribe(onChange);
    server.use(
      http.post('/api/auth/token/refresh', () =>
        HttpResponse.json({ detail: 'Token is blacklisted' }, { status: 401 }),
      ),
      http.get('/api/boards', onlyFor('never')),
    );

    const { response } = await api.GET('/api/boards');
    unsubscribe();

    expect(response.status).toBe(401);
    expect(getAccess()).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
    expect(onChange).toHaveBeenCalled();
  });

  it('does not try to refresh a failed login', async () => {
    server.use(
      http.post('/api/auth/token', () =>
        HttpResponse.json({ detail: 'No active account found with the given credentials' }, { status: 401 }),
      ),
    );

    const { response } = await api.POST('/api/auth/token', { body: { username: 'pluto', password: 'mala' } });

    // An unhandled POST to /refresh would have failed the test (onUnhandledRequest: 'error').
    expect(response.status).toBe(401);
  });
});
