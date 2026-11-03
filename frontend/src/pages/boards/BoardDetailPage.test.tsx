import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { Board } from '../../api/types';
import { HALF_WINDOW } from '../../lib/boardForm';
import { boardRow, pluginRow } from '../../test/fixtures';
import { renderRoutes } from '../../test/render';
import { server } from '../../test/server';
import { BoardDetailPage } from './BoardDetailPage';

const DEVICE = 'a1b2c3d4e5f6';
const PLUGIN = pluginRow();

function renderBoard(board: Board = boardRow()) {
  server.use(http.get('/api/boards/:deviceId', () => HttpResponse.json(board)));
  return renderRoutes([{ path: '/boards/:deviceId', element: <BoardDetailPage /> }], `/boards/${DEVICE}`);
}

describe('BoardDetailPage', () => {
  it('shows a board without any state as "Sin datos", with its instances and its history', async () => {
    renderBoard(boardRow({ last_state_at: null, plugins: [{ plugin_uuid: PLUGIN.plugin_uuid, name: PLUGIN.name, status: 'STOPPED' }] }));

    expect(await screen.findByText(/último dato: Sin datos/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: PLUGIN.name })).toHaveAttribute('href', `/plugins/${PLUGIN.plugin_uuid}`);
    expect(screen.getByRole('link', { name: 'Ver historial' })).toHaveAttribute('href', `/history?board=${DEVICE}`);
  });

  it('saves an azimuth window that wraps through north', async () => {
    let sent: unknown;
    server.use(
      http.patch('/api/boards/:deviceId', async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(boardRow({ min_azimuth_deg: 300, max_azimuth_deg: 60 }));
      }),
    );
    const user = userEvent.setup();
    renderBoard();

    await user.type(await screen.findByLabelText('Azimut desde (°)'), '300');
    await user.type(screen.getByLabelText('Azimut hasta (°)'), '60');
    expect(screen.getByText('Cruza el norte: de 300° a 360° y de 0° a 60°.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByText('Placa guardada.')).toBeInTheDocument();
    expect(sent).toMatchObject({ name: 'Terraza', min_elevation_deg: 10, min_azimuth_deg: 300, max_azimuth_deg: 60 });
  });

  it('rejects half an azimuth window without sending it', async () => {
    let patched = false;
    server.use(
      http.patch('/api/boards/:deviceId', () => {
        patched = true;
        return HttpResponse.json(boardRow());
      }),
    );
    const user = userEvent.setup();
    renderBoard();

    await user.type(await screen.findByLabelText('Azimut desde (°)'), '300');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByText(HALF_WINDOW)).toBeInTheDocument();
    expect(patched).toBe(false);
  });
});
