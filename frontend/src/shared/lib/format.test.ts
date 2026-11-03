import { describe, expect, it } from 'vitest';
import { formatAge, formatCdeg, formatDateTime } from './format';

describe('formatCdeg', () => {
  it('turns centidegrees into degrees with two decimals', () => {
    expect(formatCdeg(12345)).toBe('123.45°');
    expect(formatCdeg(-50)).toBe('-0.50°');
    expect(formatCdeg(0)).toBe('0.00°');
  });

  it('shows a dash when there is nothing', () => {
    expect(formatCdeg(null)).toBe('—');
    expect(formatCdeg(undefined)).toBe('—');
  });
});

describe('formatAge', () => {
  const now = Date.parse('2026-10-12T15:00:00Z');

  it('counts seconds, minutes, hours and days', () => {
    expect(formatAge('2026-10-12T14:59:56Z', now)).toBe('hace 4 s');
    expect(formatAge('2026-10-12T14:57:00Z', now)).toBe('hace 3 min');
    expect(formatAge('2026-10-12T13:00:00Z', now)).toBe('hace 2 h');
    expect(formatAge('2026-10-07T15:00:00Z', now)).toBe('hace 5 d');
  });

  it('never says "hace -1 s" when the server clock is a bit ahead', () => {
    expect(formatAge('2026-10-12T15:00:01Z', now)).toBe('hace 0 s');
  });
});

describe('formatDateTime', () => {
  it('shows a UTC instant in local time (the tests run in Buenos Aires, UTC-3)', () => {
    expect(formatDateTime('2026-10-12T15:00:00Z')).toBe('12/10/2026, 12:00:00');
  });

  it('shows a dash for no date', () => {
    expect(formatDateTime(null)).toBe('—');
  });
});
