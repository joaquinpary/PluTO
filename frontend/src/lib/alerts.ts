import type { BoardLive, Plugin } from '../api/types';

export type Alert = { key: string; color: 'red' | 'yellow'; message: string };

const HOLD_MESSAGES: Record<string, string> = {
  limits: 'la trayectoria salió de sus límites',
  expired: 'los puntos llegaron vencidos',
};

/** The Home's alerts, from the same data the cards show. */
export function alertsFor(boards: BoardLive[], plugins: Plugin[]): Alert[] {
  const alerts: Alert[] = [];

  for (const board of boards) {
    const name = board.name || board.device_id;
    const key = (what: string) => `${board.device_id}:${what}`;

    if (!board.online) {
      alerts.push({ key: key('offline'), color: 'red', message: `${name} está offline.` });
    }
    if (board.state?.batch_accepted === false) {
      const why = board.state.batch_error ? `: ${board.state.batch_error}` : '';
      alerts.push({ key: key('batch'), color: 'red', message: `${name} rechazó el último batch${why}.` });
    }
    if (board.state?.clock_synced === false) {
      alerts.push({
        key: key('clock'),
        color: 'yellow',
        message: `${name} tiene el reloj sin sincronizar: descarta todo batch.`,
      });
    }
    const hold = board.last_hold_reason ? HOLD_MESSAGES[board.last_hold_reason] : undefined;
    if (hold) {
      alerts.push({ key: key('hold'), color: 'yellow', message: `${name} frenó: ${hold}.` });
    }
  }

  for (const plugin of plugins) {
    if (plugin.status === 'ERROR') {
      alerts.push({
        key: `${plugin.plugin_uuid}:error`,
        color: 'red',
        message: `La instancia ${plugin.name} está en error.`,
      });
    }
  }

  return alerts;
}
