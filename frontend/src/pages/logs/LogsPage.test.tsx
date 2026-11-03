import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LOGS_REFRESH_MS } from '../../api/queries';
import { pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { LogsPage } from './LogsPage';

const PLUGIN = pluginRow();

describe('LogsPage', () => {
  afterEach(() => vi.useRealTimers());

  it('starts on the server logs, 100 lines, and switches to an instance', async () => {
    const seen: string[] = [];
    server.use(
      http.get('/api/plugins', () => HttpResponse.json([PLUGIN])),
      http.get('/api/logs/:service', ({ params, request }) => {
        seen.push(`${String(params.service)}?tail=${new URL(request.url).searchParams.get('tail')}`);
        return HttpResponse.json({ source: params.service, lines: ['gunicorn booted'] });
      }),
      http.get('/api/plugins/:uuid/logs', () => HttpResponse.json({ source: PLUGIN.name, lines: ['tracking NOAA 19'] })),
    );
    const user = userEvent.setup();
    renderWithProviders(<LogsPage />, '/logs');

    expect(await screen.findByText('gunicorn booted')).toBeInTheDocument();
    expect(seen).toEqual(['server?tail=100']);

    await screen.findByRole('option', { name: PLUGIN.name });
    await user.selectOptions(screen.getByLabelText('Fuente'), `plugin:${PLUGIN.plugin_uuid}`);

    expect(await screen.findByText('tracking NOAA 19')).toBeInTheDocument();
  });

  it('refreshes every 3 s only while the switch is on', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    server.use(
      http.get('/api/plugins', () => HttpResponse.json([])),
      http.get('/api/logs/:service', () => {
        calls += 1;
        return HttpResponse.json({ source: 'server', lines: [`call ${calls}`] });
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<LogsPage />, '/logs');
    expect(await screen.findByText('call 1')).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(LOGS_REFRESH_MS));
    expect(calls).toBe(1);

    await user.click(screen.getByRole('switch', { name: 'Actualizar cada 3 s' }));
    await act(() => vi.advanceTimersByTimeAsync(LOGS_REFRESH_MS));

    expect(await screen.findByText('call 2')).toBeInTheDocument();
  });
});
