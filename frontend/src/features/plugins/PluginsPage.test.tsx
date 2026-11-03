import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { PLUGIN_TYPES, pluginRow } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { PluginsPage } from './PluginsPage';

const PLUGIN = pluginRow();

describe('PluginsPage', () => {
  it('lists the instances and filters them by status', async () => {
    const urls: URL[] = [];
    server.use(
      http.get('/api/plugin-types', () => HttpResponse.json(PLUGIN_TYPES)),
      http.get('/api/plugins', ({ request }) => {
        urls.push(new URL(request.url));
        return HttpResponse.json([pluginRow({ board: 'a1b2c3d4e5f6' })]);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PluginsPage />, '/plugins');

    expect(screen.getByRole('heading', { name: 'Instancias' })).toBeInTheDocument();
    const row = await screen.findByRole('row', { name: new RegExp(PLUGIN.name) });
    expect(await within(row).findByText('TinyGS')).toBeInTheDocument();
    expect(row).toHaveTextContent('Detenida');
    expect(row).toHaveTextContent('a1b2c3d4e5f6');
    expect(screen.getByRole('link', { name: 'Nueva instancia' })).toHaveAttribute('href', '/plugins/new');

    await user.selectOptions(screen.getByLabelText('Estado'), 'RUNNING');
    await waitFor(() => expect(urls[urls.length - 1].searchParams.get('status')).toBe('RUNNING'));
  });

  it('launches an instance from its row', async () => {
    let launched = '';
    server.use(
      http.get('/api/plugin-types', () => HttpResponse.json(PLUGIN_TYPES)),
      http.get('/api/plugins', () => HttpResponse.json([PLUGIN])),
      http.post('/api/plugins/:uuid/launch', ({ params }) => {
        launched = String(params.uuid);
        return HttpResponse.json(pluginRow({ status: 'RUNNING', docker_status: 'running' }));
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PluginsPage />, '/plugins');

    const row = await screen.findByRole('row', { name: new RegExp(PLUGIN.name) });
    await user.click(within(row).getByRole('button', { name: 'Lanzar' }));

    expect(await screen.findByText(`${PLUGIN.name} está en ejecución.`)).toBeInTheDocument();
    expect(launched).toBe(PLUGIN.plugin_uuid);
  });
});
