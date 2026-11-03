import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { logout } from '../../shared/api/auth';
import { REFRESH_KEY } from '../../shared/api/tokens';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/server';
import { AccountPage } from './AccountPage';

vi.mock('../../shared/api/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../shared/api/auth')>()),
  logout: vi.fn(async () => {}),
}));

async function fill(user: ReturnType<typeof userEvent.setup>, current: string, next: string, confirm: string) {
  await user.type(screen.getByLabelText('Contraseña actual'), current);
  await user.type(screen.getByLabelText('Contraseña nueva'), next);
  await user.type(screen.getByLabelText('Repetí la contraseña nueva'), confirm);
  await user.click(screen.getByRole('button', { name: 'Cambiar contraseña' }));
}

describe('AccountPage', () => {
  it('checks the confirmation before sending anything', async () => {
    let sent = false;
    server.use(
      http.post('/api/auth/password', () => {
        sent = true;
        return HttpResponse.json({ access: 'a9', refresh: 'r9' });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AccountPage />, '/account');

    await fill(user, 'vieja-1234', 'nueva-segura-5678', 'otra-cosa');

    expect(await screen.findByText('Las contraseñas no coinciden.')).toBeInTheDocument();
    expect(sent).toBe(false);
  });

  it('shows the errors of a 400 next to their fields, then changes the password', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post('/api/auth/password', async ({ request }) => {
        bodies.push(await request.json());
        return bodies.length === 1
          ? HttpResponse.json({ current_password: ['La contraseña actual no es correcta.'] }, { status: 400 })
          : HttpResponse.json({ access: 'a9', refresh: 'r9' });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AccountPage />, '/account');

    await fill(user, 'equivocada', 'nueva-segura-5678', 'nueva-segura-5678');
    expect(await screen.findByText('La contraseña actual no es correcta.')).toBeInTheDocument();

    await user.clear(screen.getByLabelText('Contraseña actual'));
    await user.type(screen.getByLabelText('Contraseña actual'), 'vieja-1234');
    await user.click(screen.getByRole('button', { name: 'Cambiar contraseña' }));

    expect(await screen.findByText('Contraseña cambiada.')).toBeInTheDocument();
    expect(bodies[1]).toEqual({ current_password: 'vieja-1234', new_password: 'nueva-segura-5678' });
    expect(screen.getByLabelText('Contraseña actual')).toHaveValue('');
    // The server ended every session, this one included: it lives on with the new pair.
    expect(localStorage.getItem(REFRESH_KEY)).toBe('r9');
  });

  it('logs out and goes to the login', async () => {
    const user = userEvent.setup();
    const { router } = renderWithProviders(<AccountPage />, '/account');

    await user.click(screen.getByRole('button', { name: 'Cerrar sesión' }));

    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(logout).toHaveBeenCalledOnce();
  });
});
