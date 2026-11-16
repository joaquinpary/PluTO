/** Boards publish every 1 s while tracking and every 10 s idle. */
export const STALE_AFTER_MS = 30_000;

export type BoardStatus = 'online' | 'offline' | 'no_data';

/** no_data: online but silent. */
export function boardStatus(board: { online: boolean; last_state_at: string | null }, now: number): BoardStatus {
  if (!board.online) return 'offline';
  if (board.last_state_at === null) return 'no_data';
  return now - Date.parse(board.last_state_at) > STALE_AFTER_MS ? 'no_data' : 'online';
}
