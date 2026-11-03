import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { getAccess } from '../../api/tokens';
import { renderRoutes } from '../../test/render';
import { server } from '../../test/server';
import { SetupPage } from './SetupPage';

const routes = [
  { path: '/setup', element: <SetupPage /> },
  { path: '/login', element: <p>pantalla de login</p> },
  { path: '/', element: <p>inicio</p> },
];

async function fillIn(password: string, confirmation: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(/^Usuario/), 'pluto');
  await user.type(screen.getByLabelText(/^Contraseña/), password);
  await user.type(screen.getByLabelText(/^Confirmación/), confirmation);
  await user.click(screen.getByRole('button', { name: 'Crear usuario' }));
}

describe('SetupPage', () => {
  it('creates the user, logs in and goes to the start page', async () => {
    let created: unknown;
    server.use(
      http.get('/api/setup', () => HttpResponse.json({ needs_setup: true })),
      http.post('/api/setup', async ({ request }) => {
        created = await request.json();
        return HttpResponse.json({ username: 'pluto' }, { status: 201 });
      }),
      http.post('/api/auth/token', () => HttpResponse.json({ access: 'a1', refresh: 'r1' })),
    );
    renderRoutes(routes, '/setup');

    await fillIn('antena-direccional', 'antena-direccional');

    expect(await screen.findByText('inicio')).toBeInTheDocument();
    expect(created).toEqual({ username: 'pluto', password: 'antena-direccional' });
    expect(getAccess()).toBe('a1');
  });

  it('does not send a password that does not match its confirmation', async () => {
    server.use(http.get('/api/setup', () => HttpResponse.json({ needs_setup: true })));
    renderRoutes(routes, '/setup');

    // A POST here would fail the test: MSW has no handler for it.
    await fillIn('antena-direccional', 'antena-omni');

    expect(await screen.findByText('Las contraseñas no coinciden.')).toBeInTheDocument();
  });

  it("shows Django's password errors next to the field", async () => {
    server.use(
      http.get('/api/setup', () => HttpResponse.json({ needs_setup: true })),
      http.post('/api/setup', () =>
        HttpResponse.json({ password: ['This password is too common.'] }, { status: 400 }),
      ),
    );
    renderRoutes(routes, '/setup');

    await fillIn('password123', 'password123');

    expect(await screen.findByText('This password is too common.')).toBeInTheDocument();
  });

  it('sends an install that already has its user to the login', async () => {
    server.use(http.get('/api/setup', () => HttpResponse.json({ needs_setup: false })));

    renderRoutes(routes, '/setup');

    expect(await screen.findByText('pantalla de login')).toBeInTheDocument();
  });
});
