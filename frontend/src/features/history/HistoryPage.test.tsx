import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { boardRow, pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { HistoryPage } from './HistoryPage';

const DEVICE = 'a1b2c3d4e5f6';

function stateRow(received_at: string, mode: string) {
  return {
    received_at, mode, az_cdeg: 18000, el_cdeg: 4500, pan_mode: 'normal', batch_accepted: false,
    batch_error: 'late', latency_ms: 40, clock_synced: true, err_cdeg: null,
  };
}

describe('HistoryPage', () => {
  it('opens on the board of the link, plots the series and pages the states with the cursor', async () => {
    const stateUrls: URL[] = [];
    let seriesUrl: URL | undefined;
    server.use(
      http.get('/api/boards', () => HttpResponse.json([boardRow()])),
      http.get('/api/boards/:deviceId/states/series', ({ request }) => {
        seriesUrl = new URL(request.url);
        return HttpResponse.json({ points: [{ t: '2026-10-12T12:00:00Z', az_cdeg: 18000, el_cdeg: 4500 }] });
      }),
      http.get('/api/boards/:deviceId/states', ({ request }) => {
        const url = new URL(request.url);
        stateUrls.push(url);
        const older = url.searchParams.get('cursor') === 'older';
        return HttpResponse.json({
          next: older ? null : `http://server:8000/api/boards/${DEVICE}/states?cursor=older`,
          previous: older ? `http://server:8000/api/boards/${DEVICE}/states?cursor=newer` : null,
          results: [older ? stateRow('2026-10-12T11:00:00Z', 'idle') : stateRow('2026-10-12T12:00:00Z', 'tracking')],
        });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<HistoryPage />, `/history?board=${DEVICE}`);

    expect(screen.getByRole('heading', { name: 'Historial' })).toBeInTheDocument();
    const row = await screen.findByRole('row', { name: /tracking/ });
    expect(row).toHaveTextContent('180.00');
    expect(row).toHaveTextContent('Rechazado');
    await waitFor(() => expect(seriesUrl?.pathname).toBe(`/api/boards/${DEVICE}/states/series`));
    expect(seriesUrl?.searchParams.has('from')).toBe(true);
    expect(seriesUrl?.searchParams.has('to')).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Más antiguos' }));

    expect(await screen.findByRole('row', { name: /idle/ })).toBeInTheDocument();
    expect(stateUrls[stateUrls.length - 1].searchParams.get('cursor')).toBe('older');
  });

  it('filters the orders by kind', async () => {
    const urls: URL[] = [];
    const plugin = pluginRow();
    server.use(
      http.get('/api/boards', () => HttpResponse.json([boardRow()])),
      http.get('/api/orders', ({ request }) => {
        urls.push(new URL(request.url));
        return HttpResponse.json({
          next: null,
          previous: null,
          results: [{
            id: 7, board: DEVICE, plugin: plugin.plugin_uuid, kind: 'HOLD', reason: 'limits', t0_ms: 1760270400000,
            t_end_ms: 1760270400000, t_sent_ms: 1760270400000, point_count: 0, created_at: '2026-10-12T12:00:00Z',
          }],
        });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<HistoryPage />, '/history?tab=orders');

    expect(await screen.findByRole('row', { name: /Fuera de los límites/ })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Tipo de orden'), 'HOLD');

    await waitFor(() => expect(urls[urls.length - 1].searchParams.get('kind')).toBe('HOLD'));
  });
});
