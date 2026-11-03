import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderRoutes } from '../test/render';
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
  it('links every screen of the spec from the navigation', () => {
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

});
