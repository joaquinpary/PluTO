import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { getAccess, REFRESH_KEY, setTokens } from '../api/tokens';
import { renderRoutes } from '../../test/render';
import { server } from '../../test/server';
import { AppLayout } from './AppLayout';

function renderLayout(path: string) {
  return renderRoutes(
    [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <p>contenido</p> },
          { path: '*', element: <p>contenido</p> },
        ],
      },
    ],
    path,
  );
}

describe('AppLayout', () => {
  it('links every screen from the navigation', () => {
    renderLayout('/');

    const expected = [
      ['Inicio', '/'],
      ['Instancias', '/plugins'],
      ['Placas', '/boards'],
      ['Historial', '/history'],
      ['Logs', '/logs'],
      ['Cuenta', '/account'],
    ];
    for (const [label, href] of expected) {
      expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', href);
    }
    expect(screen.getByText('contenido')).toBeInTheDocument();
  });

  it('marks the section of the current page, not Inicio', () => {
    renderLayout('/boards/aabbccddeeff');

    expect(screen.getByRole('link', { name: 'Placas' })).toHaveAttribute('data-active', 'true');
    expect(screen.getByRole('link', { name: 'Inicio' })).not.toHaveAttribute('data-active');
  });

  it('logs out: blacklists the refresh token and forgets the session', async () => {
    setTokens({ access: 'a1', refresh: 'r1' });
    let blacklisted: unknown;
    server.use(
      http.post('/api/auth/token/blacklist', async ({ request }) => {
        blacklisted = await request.json();
        return HttpResponse.json({});
      }),
    );
    renderLayout('/');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Cerrar sesión' }));

    await waitFor(() => expect(blacklisted).toEqual({ refresh: 'r1' }));
    expect(getAccess()).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });
});
