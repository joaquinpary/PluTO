import {
  ActionIcon,
  AppShell,
  Burger,
  Group,
  NavLink,
  Text,
  Title,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useQueryClient } from '@tanstack/react-query';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { logout } from '../api/auth';
import { Icon, LogoMark, type IconName } from './icons';

export const NAV_LINKS: { to: string; label: string; icon: IconName }[] = [
  { to: '/', label: 'Inicio', icon: 'home' },
  { to: '/plugins', label: 'Instancias', icon: 'cpu' },
  { to: '/boards', label: 'Placas', icon: 'radio' },
  { to: '/history', label: 'Historial', icon: 'clock' },
  { to: '/logs', label: 'Logs', icon: 'terminal' },
  { to: '/account', label: 'Cuenta', icon: 'user' },
];

function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const dark = useComputedColorScheme('light') === 'dark';
  return (
    <ActionIcon
      variant="default"
      size="lg"
      onClick={() => setColorScheme(dark ? 'light' : 'dark')}
      aria-label={dark ? 'Pasar a modo claro' : 'Pasar a modo oscuro'}
    >
      <Icon name={dark ? 'sun' : 'moon'} />
    </ActionIcon>
  );
}

function isActive(to: string, pathname: string): boolean {
  return to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`);
}

/** Side navigation on a computer; on a phone it folds behind the burger (RNF-13.1). */
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
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Abrir el menú" />
            <LogoMark />
            <Title order={3}>PluTO</Title>
            <Text size="sm" c="dimmed" visibleFrom="sm">
              Estación terrena
            </Text>
          </Group>
          <ColorSchemeToggle />
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
              leftSection={<Icon name={link.icon} />}
              active={isActive(link.to, pathname)}
              onClick={close}
            />
          ))}
        </AppShell.Section>
        <AppShell.Section>
          <NavLink
            component="button"
            label="Cerrar sesión"
            leftSection={<Icon name="logout" />}
            c="dimmed"
            onClick={handleLogout}
          />
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main className="app-main">
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
