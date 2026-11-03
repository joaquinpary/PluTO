import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { PLUGIN_TYPES, pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { PluginNewPage } from './PluginNewPage';

const PLUGIN = pluginRow();

function renderNew() {
  server.use(http.get('/api/plugin-types', () => HttpResponse.json(PLUGIN_TYPES)));
  return renderWithProviders(<PluginNewPage />, '/plugins/new');
}

async function fillTinygs(user: ReturnType<typeof userEvent.setup>, device: string) {
  await screen.findByRole('option', { name: 'TinyGS' });
  await user.selectOptions(screen.getByLabelText('Tipo'), 'tinygs');
  await user.type(screen.getByLabelText('Nombre'), PLUGIN.name);
  await user.type(screen.getByLabelText('Dispositivo TinyGS'), device);
}

describe('PluginNewPage', () => {
  it('builds the form of the chosen type and creates the instance', async () => {
    let sent: unknown;
    server.use(
      http.post('/api/plugins', async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(PLUGIN, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const { router } = renderNew();

    await fillTinygs(user, 'My_TinyGS');
    expect(screen.getByLabelText('Elevación mínima (°)')).toHaveValue('10');
    await user.click(screen.getByRole('button', { name: 'Crear instancia' }));

    await waitFor(() => expect(router.state.location.pathname).toBe(`/plugins/${PLUGIN.plugin_uuid}`));
    expect(sent).toEqual({
      name: PLUGIN.name,
      plugin_type: 'tinygs',
      config: { tinygs_device: 'My_TinyGS', min_elevation_deg: 10, lookahead_minutes: 20, sample_seconds: 1, tle_ttl_hours: 12 },
    });
  });

  it('shows the field errors before sending anything', async () => {
    let posted = false;
    server.use(
      http.post('/api/plugins', () => {
        posted = true;
        return HttpResponse.json(PLUGIN, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderNew();

    await fillTinygs(user, 'My TinyGS');
    await user.click(screen.getByRole('button', { name: 'Crear instancia' }));

    expect(await screen.findByText('No tiene el formato esperado.')).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  it('puts the errors of a 400 next to their fields', async () => {
    server.use(
      http.post('/api/plugins', () =>
        HttpResponse.json(
          { name: ['Ya existe una instancia con ese nombre.'], config: { tinygs_device: ['La estación no existe.'] } },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderNew();

    await fillTinygs(user, 'My_TinyGS');
    await user.click(screen.getByRole('button', { name: 'Crear instancia' }));

    expect(await screen.findByText('Ya existe una instancia con ese nombre.')).toBeInTheDocument();
    expect(screen.getByText('La estación no existe.')).toBeInTheDocument();
  });
});
