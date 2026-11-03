import { AppShell, Burger, Group, NavLink, Title } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useQueryClient } from '@tanstack/react-query';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { logout } from '../api/auth';

export const NAV_LINKS = [
  { to: '/', label: 'Inicio' },
  { to: '/plugins', label: 'Instancias' },
  { to: '/boards', label: 'Placas' },
  { to: '/history', label: 'Historial' },
  { to: '/logs', label: 'Logs' },
  { to: '/account', label: 'Cuenta' },
];

function isActive(to: string, pathname: string): boolean {
  return to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`);
}

/** Side navigation on a computer; on a phone it folds behind the burger (spec 4, RNF-13.1). */
export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname } = useLocation();
  const queryClient = useQueryClient();

  async function handleLogout() {
    await logout(); // RequireAuth sees the session end and goes to /login
    queryClient.clear();
  }

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md">
          <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Abrir el menú" />
          <Title order={3}>PluTO</Title>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <AppShell.Section grow>
          {NAV_LINKS.map((link) => (
            <NavLink
              key={link.to}
              component={Link}
              to={link.to}
              label={link.label}
              active={isActive(link.to, pathname)}
              onClick={close}
            />
          ))}
        </AppShell.Section>
        <AppShell.Section>
          <NavLink component="button" label="Cerrar sesión" onClick={handleLogout} />
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
