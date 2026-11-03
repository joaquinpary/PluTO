import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { theme } from '../theme';
import { createMemoryRouter, RouterProvider, type RouteObject } from 'react-router-dom';

/** Renders routes the way main.tsx does, starting at path, with a fresh query cache. */
export function renderRoutes(routes: RouteObject[], path = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    // env="test" turns off transitions and portals, so what opens is there at once.
    <MantineProvider theme={theme} env="test">
      <Notifications />
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} future={{ v7_startTransition: true }} />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { ...view, router, queryClient };
}

/** One element at any path: for a page that does not need its neighbours. */
export function renderWithProviders(ui: ReactElement, path = '/') {
  return renderRoutes([{ path: '*', element: ui }], path);
}
