import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { boardRow, pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { ResultsTab } from './ResultsTab';

const PLUGIN = pluginRow();

describe('ResultsTab', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows the error of each pass and compares two reception periods side by side', async () => {
    const receptionUrls: URL[] = [];
    const pointingUrls: URL[] = [];
    server.use(
      http.get('/api/boards', () => HttpResponse.json([boardRow()])),
      http.get('/api/plugins', () => HttpResponse.json([PLUGIN])),
      http.get('/api/results/pointing-error', ({ request }) => {
        const url = new URL(request.url);
        pointingUrls.push(url);
        if (url.searchParams.get('format') === 'csv') {
          return new HttpResponse('start,end\n', { headers: { 'Content-Type': 'text/csv' } });
        }
        return HttpResponse.json({
          passes: [
            { start: '2026-10-12T10:00:00Z', end: '2026-10-12T10:12:00Z', source: 'meas', samples: 720, mean_err_cdeg: 85, max_err_cdeg: 310 },
            { start: '2026-10-12T11:40:00Z', end: '2026-10-12T11:49:00Z', source: 'commanded', samples: 540, mean_err_cdeg: null, max_err_cdeg: null },
          ],
        });
      }),
      http.get('/api/results/reception', ({ request }) => {
        receptionUrls.push(new URL(request.url));
        return HttpResponse.json({ days: [{ date: '2026-10-06', packets: 4, crc_errors: 1, rssi_mean: -98.5, snr_mean: 3.2 }] });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ResultsTab board="a1b2c3d4e5f6" onBoardChange={() => {}} />);

    const measured = await screen.findByRole('row', { name: /Medido \(encoders\)/ });
    expect(measured).toHaveTextContent('0.85');
    expect(measured).toHaveTextContent('3.10');
    expect(screen.getByRole('row', { name: /Ordenado vs\. reportado/ })).toHaveTextContent('540');

    await screen.findByRole('option', { name: PLUGIN.name });
    await user.selectOptions(screen.getByLabelText('Instancia'), PLUGIN.plugin_uuid);

    await waitFor(() => expect(receptionUrls).toHaveLength(2));
    expect(new Set(receptionUrls.map((url) => url.searchParams.get('from'))).size).toBe(2);
    expect(receptionUrls.every((url) => url.searchParams.get('plugin') === PLUGIN.plugin_uuid)).toBe(true);
    expect(await screen.findAllByText(/4 paquetes/)).toHaveLength(2);

    // Exportar CSV: the first button is the pointing error's, the same query with format=csv.
    URL.createObjectURL = vi.fn(() => 'blob:passes');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const csvButtons = screen.getAllByRole('button', { name: 'Exportar CSV' });
    expect(csvButtons).toHaveLength(3);
    await user.click(csvButtons[0]);

    await waitFor(() => expect(click).toHaveBeenCalled());
    const csv = pointingUrls[pointingUrls.length - 1];
    expect(csv.searchParams.get('format')).toBe('csv');
    expect(csv.searchParams.get('board')).toBe('a1b2c3d4e5f6');
    expect(csv.searchParams.has('from')).toBe(true);
  });
});
