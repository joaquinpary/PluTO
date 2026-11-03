import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { clearTokens, setTokens } from '../../shared/api/tokens';
import { LoginPage } from './LoginPage';
import { renderRoutes } from '../../test/render';
import { server } from '../../test/server';
import { RequireAuth } from './RequireAuth';

const routes = [
  { path: '/setup', element: <p>pantalla de setup</p> },
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      { path: '/', element: <p>inicio</p> },
      { path: '/boards', element: <p>placas</p> },
    ],
  },
];

function setupAnswers(needs_setup: boolean) {
  server.use(http.get('/api/setup', () => HttpResponse.json({ needs_setup })));
}

describe('RequireAuth', () => {
  it('sends a fresh install to the setup screen', async () => {
    setupAnswers(true);

    renderRoutes(routes, '/boards');

    expect(await screen.findByText('pantalla de setup')).toBeInTheDocument();
  });

  it('lets a session through', async () => {
    setupAnswers(false);
    setTokens({ access: 'a1', refresh: 'r1' });

    renderRoutes(routes, '/boards');

    expect(await screen.findByText('placas')).toBeInTheDocument();
  });

  it('asks for the login and then returns to the page that was asked for', async () => {
    setupAnswers(false);
    server.use(
      http.post('/api/auth/token', async ({ request }) => {
        const body = (await request.json()) as { username: string; password: string };
        return body.password === 'correcta'
          ? HttpResponse.json({ access: 'a1', refresh: 'r1' })
          : HttpResponse.json({ detail: 'No active account found with the given credentials' }, { status: 401 });
      }),
    );
    const { router } = renderRoutes(routes, '/boards');
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText(/^Usuario/), 'pluto');
    await user.type(screen.getByLabelText(/^Contraseña/), 'mala');
    await user.click(screen.getByRole('button', { name: 'Entrar' }));
    expect(await screen.findByText('Usuario o contraseña incorrectos.')).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/^Contraseña/));
    await user.type(screen.getByLabelText(/^Contraseña/), 'correcta');
    await user.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(await screen.findByText('placas')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/boards');
    expect(localStorage.getItem('pluto.refresh')).toBe('r1');
  });

  it('goes to the login when the session ends from inside, e.g. a rejected refresh', async () => {
    setupAnswers(false);
    setTokens({ access: 'a1', refresh: 'r1' });
    renderRoutes(routes, '/boards');
    await screen.findByText('placas');

    act(() => clearTokens());

    expect(await screen.findByLabelText(/^Usuario/)).toBeInTheDocument();
  });
});
