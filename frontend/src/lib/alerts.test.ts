import { describe, expect, it } from 'vitest';
import { liveBoard, liveState, pluginRow } from '../test/fixtures';
import { alertsFor } from './alerts';

const messages = (...args: Parameters<typeof alertsFor>) => alertsFor(...args).map((alert) => alert.message);

describe('alertsFor', () => {
  it('says nothing about a healthy station', () => {
    expect(alertsFor([liveBoard()], [pluginRow({ status: 'RUNNING' })])).toEqual([]);
  });

  it('warns about an offline board', () => {
    expect(messages([liveBoard({ online: false })], [])).toEqual(['Terraza está offline.']);
  });

  it('shows why the last batch was rejected', () => {
    const board = liveBoard({ state: liveState({ batch_accepted: false, batch_error: 'all_expired' }) });

    expect(messages([board], [])).toEqual(['Terraza rechazó el último batch: all_expired.']);
  });

  it('warns about a board with its clock out of sync', () => {
    const board = liveBoard({ state: liveState({ clock_synced: false }) });

    expect(messages([board], [])).toEqual(['Terraza tiene el reloj sin sincronizar: descarta todo batch.']);
  });

  it('warns about a HOLD for limits or expired points, not for the end of a pass', () => {
    expect(messages([liveBoard({ last_hold_reason: 'limits' })], [])).toEqual([
      'Terraza frenó: la trayectoria salió de sus límites.',
    ]);
    expect(messages([liveBoard({ last_hold_reason: 'expired' })], [])).toEqual([
      'Terraza frenó: los puntos llegaron vencidos.',
    ]);
    expect(messages([liveBoard({ last_hold_reason: 'end' })], [])).toEqual([]);
  });

  it('warns about an instance in ERROR', () => {
    expect(messages([], [pluginRow({ status: 'ERROR' })])).toEqual(['La instancia tinygs-terraza está en error.']);
  });

  it('names a board without a name by its device_id, and survives one without state', () => {
    const board = liveBoard({ name: '', online: false, state: null, last_state_at: null });

    expect(messages([board], [])).toEqual(['aabbccddeeff está offline.']);
  });

  it('gives each alert its own key', () => {
    const board = liveBoard({
      online: false,
      last_hold_reason: 'limits',
      state: liveState({ batch_accepted: false, clock_synced: false }),
    });

    const keys = alertsFor([board], [pluginRow({ status: 'ERROR' })]).map((alert) => alert.key);

    expect(new Set(keys).size).toBe(5);
  });
});
