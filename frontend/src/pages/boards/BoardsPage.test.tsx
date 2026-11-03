import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { boardRow, pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { BoardsPage } from './BoardsPage';

const PLUGIN = pluginRow();

describe('BoardsPage', () => {
  it('lists the boards, with "Sin datos" for one that never reported a state', async () => {
    server.use(
      http.get('/api/boards', () =>
        HttpResponse.json([
          boardRow({ plugins: [{ plugin_uuid: PLUGIN.plugin_uuid, name: PLUGIN.name, status: 'RUNNING' }] }),
          boardRow({ device_id: '0a0b0c0d0e0f', name: '', online: false, last_state_at: null }),
        ]),
      ),
    );
    renderWithProviders(<BoardsPage />, '/boards');

    expect(screen.getByRole('heading', { name: 'Placas' })).toBeInTheDocument();
    const terraza = await screen.findByRole('row', { name: /Terraza/ });
    expect(terraza).toHaveTextContent('a1b2c3d4e5f6');
    expect(terraza).toHaveTextContent('online');
    expect(terraza).toHaveTextContent(`${PLUGIN.name} (en ejecución)`);
    const fresh = screen.getByRole('row', { name: /0a0b0c0d0e0f/ });
    expect(fresh).toHaveTextContent('offline');
    expect(fresh).toHaveTextContent('Sin datos');
  });

  it('scans for boards and shows the new list', async () => {
    server.use(
      http.get('/api/boards', () => HttpResponse.json([])),
      http.post('/api/boards/scan', () => HttpResponse.json([boardRow()])),
    );
    const user = userEvent.setup();
    renderWithProviders(<BoardsPage />, '/boards');

    expect(await screen.findByText(/Todavía no hay placas/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Buscar placas' }));

    expect(await screen.findByRole('row', { name: /Terraza/ })).toBeInTheDocument();
    expect(await screen.findByText('Búsqueda terminada: 1 placa.')).toBeInTheDocument();
  });

  it('says so when the broker does not answer, and keeps the list', async () => {
    server.use(
      http.get('/api/boards', () => HttpResponse.json([boardRow()])),
      http.post('/api/boards/scan', () => HttpResponse.json({ detail: 'Could not reach the broker.' }, { status: 503 })),
    );
    const user = userEvent.setup();
    renderWithProviders(<BoardsPage />, '/boards');

    await screen.findByRole('row', { name: /Terraza/ });
    await user.click(screen.getByRole('button', { name: 'Buscar placas' }));

    expect(await screen.findByText('No se pudo consultar el broker.')).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Terraza/ })).toBeInTheDocument();
  });
});
