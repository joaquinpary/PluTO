import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { Board, Plugin } from '../../shared/api/types';
import { OTHER_UUID, PLUGIN_TYPES, boardRow, pluginRow } from '../../test/fixtures';
import { renderRoutes } from '../../test/render';
import { server } from '../../test/server';
import { PluginDetailPage } from './PluginDetailPage';

const TINYGS = pluginRow({ config: { tinygs_device: 'My_TinyGS' } });

function renderDetail(plugin: Plugin, boards: Board[] = [boardRow()]) {
  server.use(
    http.get('/api/plugins/:uuid', () => HttpResponse.json(plugin)),
    http.get('/api/plugin-types', () => HttpResponse.json(PLUGIN_TYPES)),
    http.get('/api/boards', () => HttpResponse.json(boards)),
  );
  return renderRoutes([{ path: '/plugins/:uuid', element: <PluginDetailPage /> }], `/plugins/${plugin.plugin_uuid}`);
}

describe('PluginDetailPage', () => {
  it('keeps the type fixed and asks to relaunch after editing a running instance', async () => {
    let sent: unknown;
    server.use(
      http.patch('/api/plugins/:uuid', async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ ...TINYGS, status: 'RUNNING' });
      }),
    );
    const user = userEvent.setup();
    renderDetail({ ...TINYGS, status: 'RUNNING', docker_status: 'running' });

    expect(await screen.findByRole('heading', { name: TINYGS.name })).toBeInTheDocument();
    expect(await screen.findByText(/Tipo: TinyGS/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Tipo' })).not.toBeInTheDocument();
    expect(await screen.findByLabelText('Dispositivo TinyGS')).toHaveValue('My_TinyGS');

    const elevation = screen.getByLabelText('Elevación mínima (°)');
    await user.clear(elevation);
    await user.type(elevation, '15');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByText('Relanzá para aplicar los cambios')).toBeInTheDocument();
    expect(sent).toEqual({
      name: TINYGS.name,
      config: { tinygs_device: 'My_TinyGS', min_elevation_deg: 15, lookahead_minutes: 20, sample_seconds: 1, tle_ttl_hours: 12 },
    });
  });

  it('names the running instance that already drives the chosen board', async () => {
    server.use(
      http.put('/api/plugins/:uuid/board', () =>
        HttpResponse.json({ detail: 'Another running plugin instance already drives that board (RF-31.1).' }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    renderDetail(TINYGS, [boardRow({ plugins: [{ plugin_uuid: OTHER_UUID, name: 'tinygs-omni', status: 'RUNNING' }] })]);

    await screen.findByRole('option', { name: /Terraza/ });
    await user.selectOptions(screen.getByLabelText('Placa'), 'a1b2c3d4e5f6');

    expect(await screen.findByText(/Esa placa ya la maneja tinygs-omni/)).toBeInTheDocument();
  });

  it('says so when the broker does not answer a scan', async () => {
    server.use(http.post('/api/boards/scan', () => HttpResponse.json({ detail: 'Could not reach the broker.' }, { status: 503 })));
    const user = userEvent.setup();
    renderDetail(TINYGS);

    await user.click(await screen.findByRole('button', { name: 'Buscar placas' }));

    expect(await screen.findByText('No se pudo consultar el broker.')).toBeInTheDocument();
  });

  it('explains why an instance with data cannot be deleted and offers to stop it, also from ERROR', async () => {
    let stopped = false;
    server.use(
      http.delete('/api/plugins/:uuid', () => HttpResponse.json({ detail: 'The instance has stored data.' }, { status: 409 })),
      http.post('/api/plugins/:uuid/stop', () => {
        stopped = true;
        return HttpResponse.json({ ...TINYGS, status: 'STOPPED' });
      }),
    );
    const user = userEvent.setup();
    renderDetail({ ...TINYGS, status: 'ERROR' });

    await user.click(await screen.findByRole('button', { name: 'Borrar' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Borrar' }));
    expect(await within(dialog).findByText(/No se puede borrar/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Detenerla en su lugar' }));
    await waitFor(() => expect(stopped).toBe(true));
  });

  it('takes a coordinates file only for file_tracker, up to 1 MiB', async () => {
    const user = userEvent.setup();
    renderDetail(pluginRow({ plugin_type: 'file_tracker', config: { coord_type: 'ENU', coord_format: 'POLAR' } }));

    await user.click(await screen.findByRole('tab', { name: 'Archivo de coordenadas' }));
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('The coordinates tab has no file input');
    const tooBig = new File([new Uint8Array(1024 * 1024 + 1)], 'pass.txt', { type: 'text/plain' });
    fireEvent.change(input, { target: { files: [tooBig] } });
    await user.click(screen.getByRole('button', { name: 'Enviar archivo' }));

    expect(await screen.findByText('El archivo supera 1 MiB.')).toBeInTheDocument();
  });

  it('has no coordinates tab for tinygs', async () => {
    renderDetail(TINYGS);

    expect(await screen.findByRole('tab', { name: 'Logs' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Archivo de coordenadas' })).not.toBeInTheDocument();
  });

  it('shows the warnings the server computes, like a threshold below the board one', async () => {
    renderDetail({
      ...TINYGS,
      warnings: [
        'min_elevation_deg (5) is below the minimum of the board (10): every pass that starts below the board minimum is dropped.',
      ],
    });

    expect(await screen.findByText(/min_elevation_deg \(5\) is below the minimum of the board/)).toBeInTheDocument();
  });
});
