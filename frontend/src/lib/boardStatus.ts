/**
 * A board whose last state is older than this shows "sin datos" (spec 6): it
 * publishes every 1 s while tracking and every 10 s at rest.
 */
export const STALE_AFTER_MS = 30_000;

export type BoardStatus = 'online' | 'offline' | 'no_data';

/** online and offline come from the board's own status; no_data is online but silent. */
export function boardStatus(board: { online: boolean; last_state_at: string | null }, now: number): BoardStatus {
  if (!board.online) return 'offline';
  if (board.last_state_at === null) return 'no_data';
  return now - Date.parse(board.last_state_at) > STALE_AFTER_MS ? 'no_data' : 'online';
}
