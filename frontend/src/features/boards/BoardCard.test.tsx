import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { liveBoard, liveState } from '../../test/fixtures';
import { renderWithProviders } from '../../test/render';
import { BoardCard } from './BoardCard';

const now = Date.parse('2026-10-12T15:00:00Z');

describe('BoardCard', () => {
  it('shows what the board reports', () => {
    const board = liveBoard({
      last_state_at: '2026-10-12T14:59:56Z',
      state: liveState({ mode: 'tracking', az_cdeg: 12345, el_cdeg: 4500, pan_mode: 'flipped' }),
      running_plugin: { plugin_uuid: '0b7e4c1a-6a52-4f0e-9a43-3f1d2c5b8e90', name: 'tinygs-terraza', plugin_type: 'tinygs' },
      satellite: { name: 'NORBY', norad: 46494 },
    });

    renderWithProviders(<BoardCard board={board} now={now} />);

    expect(screen.getByText('Online')).toBeInTheDocument();
    expect(screen.getByText('hace 4 s')).toBeInTheDocument();
    expect(screen.getByText('tracking')).toBeInTheDocument();
    expect(screen.getByText('flipped')).toBeInTheDocument();
    expect(screen.getByText('123.45° / 45.00°')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'tinygs-terraza' })).toHaveAttribute(
      'href',
      '/plugins/0b7e4c1a-6a52-4f0e-9a43-3f1d2c5b8e90',
    );
    expect(screen.getByText('NORBY (NORAD 46494)')).toBeInTheDocument();
    expect(screen.queryByText('Az / El medidos')).not.toBeInTheDocument();
  });

  it('shows the measured position and the error when the document brings them', () => {
    const board = liveBoard({
      last_state_at: '2026-10-12T14:59:59Z',
      state: liveState({ meas: { az_cdeg: 12300, el_cdeg: 4510 }, err_cdeg: 46 }),
    });

    renderWithProviders(<BoardCard board={board} now={now} />);

    expect(screen.getByText('123.00° / 45.10°')).toBeInTheDocument();
    expect(screen.getByText('0.46°')).toBeInTheDocument();
  });

  it('shows "Sin datos" for a board that never sent a state', () => {
    const board = liveBoard({ name: '', state: null, last_state_at: null });

    renderWithProviders(<BoardCard board={board} now={now} />);

    expect(screen.getByText('aabbccddeeff')).toBeInTheDocument();
    expect(screen.getByText('Sin datos')).toBeInTheDocument();
    expect(screen.getByText('ninguno todavía')).toBeInTheDocument();
    expect(screen.getByText('ninguna en ejecución')).toBeInTheDocument();
  });
});
