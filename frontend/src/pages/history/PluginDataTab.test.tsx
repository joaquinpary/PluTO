import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { PLUGIN_TYPES, pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { PluginDataTab } from './PluginDataTab';

const PLUGIN = pluginRow();

function row(id: number, message_type: string, device: string, payload: Record<string, unknown>, extra = {}) {
  return {
    id, plugin: PLUGIN.plugin_uuid, message_type, device, received_at: null, created_at: '2026-10-12T12:00:00Z',
    rssi: null, snr: null, crc_error: null, satellite: null, payload, ...extra,
  };
}

describe('PluginDataTab (Review Focus 5)', () => {
  it('leaves the missing fields empty, survives an unknown type and keeps the raw JSON', async () => {
    const urls: URL[] = [];
    server.use(
      http.get('/api/plugin-types', () => HttpResponse.json(PLUGIN_TYPES)),
      http.get('/api/plugins', () => HttpResponse.json([PLUGIN])),
      http.get('/api/plugin-data', ({ request }) => {
        urls.push(new URL(request.url));
        return HttpResponse.json({
          next: null,
          previous: null,
          results: [
            row(3, 'tracking', 'Other_GS', { satellite: 'NOAA 19', NORAD: 33591 }, { satellite: { name: 'NOAA 19', norad: 33591 } }),
            row(2, 'rx', 'My_TinyGS', { frequency: 436.7 }),
            row(1, 'weather', '', { value: 'raw text' }),
          ],
        });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PluginDataTab />);

    const rx = await screen.findByRole('row', { name: /My_TinyGS/ });
    const cells = within(rx).getAllByRole('cell');
    expect(cells.slice(4, 8).map((td) => td.textContent)).toEqual(['', '', '', '']);
    expect(await within(rx).findByText(PLUGIN.name)).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /weather/ })).toBeInTheDocument();
    // A satellite is a {name, norad} object: shown as text, never "[object Object]".
    expect(screen.getByRole('row', { name: /Other_GS/ })).toHaveTextContent('NOAA 19 (NORAD 33591)');

    await user.click(within(rx).getByRole('button', { name: 'Ver JSON' }));
    expect(screen.getByText(/"frequency": 436.7/)).toBeInTheDocument();

    await screen.findByRole('option', { name: 'rx' });
    await user.selectOptions(screen.getByLabelText('Tipo de mensaje'), 'rx');
    await waitFor(() => expect(urls[urls.length - 1].searchParams.get('type')).toBe('rx'));
  });
});
