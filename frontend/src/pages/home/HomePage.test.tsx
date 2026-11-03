import { focusManager } from '@tanstack/react-query';
import { act, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { liveBoard, liveState, pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { HomePage } from './HomePage';

const NEW_BOARD = liveBoard({ device_id: '112233445566', name: 'Patio', state: null, last_state_at: null });

function api({ boards = [liveBoard()], plugins = [pluginRow()] } = {}) {
  server.use(
    http.get('/api/boards/live', () => HttpResponse.json(boards)),
    http.get('/api/plugins', () => HttpResponse.json(plugins)),
    http.get('/api/boards/:deviceId/track', ({ params }) =>
      HttpResponse.json({
        device_id: params.deviceId,
        points: [
          { t_ms: 1, az_cdeg: 9000, el_cdeg: 1000 },
          { t_ms: 2, az_cdeg: 12345, el_cdeg: 4500 },
        ],
      }),
    ),
  );
}

describe('HomePage', () => {
  it('shows a card per board, the sky and the pass in progress', async () => {
    api();

    renderWithProviders(<HomePage />);

    expect(await screen.findByRole('link', { name: 'Terraza' })).toBeInTheDocument();
    const sky = screen.getByRole('img', { name: 'Gráfico del cielo' });
    expect(within(sky).getByLabelText('Terraza')).toBeInTheDocument();
    await expect.poll(() => sky.querySelector('polyline')).not.toBeNull();
  });

  it('shows "Sin datos" for a board that never sent a state, next to a healthy one (Review Focus 2)', async () => {
    api({ boards: [liveBoard(), NEW_BOARD] });

    renderWithProviders(<HomePage />);

    expect(await screen.findByRole('link', { name: 'Patio' })).toBeInTheDocument();
    expect(screen.getByText('Sin datos')).toBeInTheDocument();
    expect(screen.getByText('Online')).toBeInTheDocument();
    // No position, so no dot on the sky for it.
    expect(screen.queryByLabelText('Patio')).not.toBeInTheDocument();
  });

  it('lists the alerts of boards and instances', async () => {
    api({
      boards: [liveBoard({ state: liveState({ batch_accepted: false, batch_error: 'all_expired' }) })],
      plugins: [pluginRow({ name: 'file-tracker-1', status: 'ERROR' })],
    });

    renderWithProviders(<HomePage />);

    expect(await screen.findByText('Terraza rechazó el último batch: all_expired.')).toBeInTheDocument();
    expect(await screen.findByText('La instancia file-tracker-1 está en error.')).toBeInTheDocument();
  });

  it('says how to find boards when there are none', async () => {
    api({ boards: [] });

    renderWithProviders(<HomePage />);

    expect(await screen.findByText(/Todavía no hay placas/)).toBeInTheDocument();
  });

  it('keeps the last data and shows the banner after three failed polls in a row', async () => {
    let calls = 0;
    api();
    server.use(
      http.get('/api/boards/live', () => {
        calls += 1;
        return calls === 1 ? HttpResponse.json([liveBoard()]) : HttpResponse.error();
      }),
    );

    renderWithProviders(<HomePage />);
    expect(await screen.findByRole('link', { name: 'Terraza' })).toBeInTheDocument();

    // The poll after 1 s fails, then its two retries a second apart.
    expect(await screen.findByText('Sin conexión con el servidor', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(calls).toBe(4);
    expect(screen.getByRole('link', { name: 'Terraza' })).toBeInTheDocument();
  }, 10_000);

  it('stops polling while the tab is hidden and picks up again when it comes back (spec 6)', async () => {
    let calls = 0;
    api();
    server.use(
      http.get('/api/boards/live', () => {
        calls += 1;
        return HttpResponse.json([liveBoard()]);
      }),
    );
    renderWithProviders(<HomePage />);
    expect(await screen.findByRole('link', { name: 'Terraza' })).toBeInTheDocument();

    try {
      // What TanStack Query hears from a visibilitychange to hidden.
      act(() => focusManager.setFocused(false));
      await new Promise((resolve) => setTimeout(resolve, 200)); // a poll already on the wire lands
      const hiddenAt = calls;
      await new Promise((resolve) => setTimeout(resolve, 2500));
      expect(calls).toBe(hiddenAt);

      act(() => focusManager.setFocused(true));
      await waitFor(() => expect(calls).toBeGreaterThan(hiddenAt));
    } finally {
      focusManager.setFocused(undefined); // back to following document.visibilityState
    }
  }, 10_000);
});
