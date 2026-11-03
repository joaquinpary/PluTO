import { describe, expect, it } from 'vitest';
import { boardStatus, STALE_AFTER_MS } from './boardStatus';

const now = Date.parse('2026-10-12T15:00:00Z');
const secondsAgo = (s: number) => new Date(now - s * 1000).toISOString();

describe('boardStatus', () => {
  it('is online with a recent state', () => {
    expect(boardStatus({ online: true, last_state_at: secondsAgo(5) }, now)).toBe('online');
  });

  it('turns to no_data after 30 s without a state', () => {
    expect(STALE_AFTER_MS).toBe(30_000);
    expect(boardStatus({ online: true, last_state_at: secondsAgo(30) }, now)).toBe('online');
    expect(boardStatus({ online: true, last_state_at: secondsAgo(31) }, now)).toBe('no_data');
  });

  it('is no_data for a new board that never sent a state (Review Focus 2)', () => {
    expect(boardStatus({ online: true, last_state_at: null }, now)).toBe('no_data');
  });

  it('is offline when the board says so, however fresh its last state', () => {
    expect(boardStatus({ online: false, last_state_at: secondsAgo(1) }, now)).toBe('offline');
    expect(boardStatus({ online: false, last_state_at: null }, now)).toBe('offline');
  });
});
