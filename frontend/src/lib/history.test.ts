import { describe, expect, it } from 'vitest';
import {
  cell, comparisonRanges, cursorFrom, defaultRange, degrees, fixed, formatEpochMs, hasRange, receptionSummary,
  satelliteText, toDegrees, toRangeQuery,
} from './history';

describe('toRangeQuery', () => {
  it('sends local midnights as UTC instants and includes the whole last day ([from, to))', () => {
    expect(toRangeQuery([new Date(2026, 9, 1), new Date(2026, 9, 3)])).toEqual({
      from: '2026-10-01T03:00:00.000Z',
      to: '2026-10-04T03:00:00.000Z',
    });
  });

  it('leaves out the ends that are not chosen, and only a full range counts', () => {
    expect(toRangeQuery([null, null])).toEqual({});
    expect(toRangeQuery([new Date(2026, 9, 1), null])).toEqual({ from: '2026-10-01T03:00:00.000Z' });
    expect(hasRange(toRangeQuery([new Date(2026, 9, 1), null]))).toBe(false);
    expect(hasRange(toRangeQuery([new Date(2026, 9, 1), new Date(2026, 9, 1)]))).toBe(true);
  });
});

describe('defaultRange and comparisonRanges', () => {
  const now = new Date(2026, 9, 12, 15, 30);

  it('defaults to yesterday and today', () => {
    expect(defaultRange(now)).toEqual([new Date(2026, 9, 11), new Date(2026, 9, 12)]);
  });

  it('compares the last seven days with the seven before them', () => {
    expect(comparisonRanges(now)).toEqual([
      [new Date(2026, 8, 29), new Date(2026, 9, 5)],
      [new Date(2026, 9, 6), new Date(2026, 9, 12)],
    ]);
  });
});

describe('cursorFrom', () => {
  it('takes the cursor out of a DRF next or previous link', () => {
    expect(cursorFrom('http://server:8000/api/orders?board=a1&cursor=cD0yMDI2&kind=HOLD')).toBe('cD0yMDI2');
    expect(cursorFrom(null)).toBeUndefined();
  });
});

describe('cells (Review Focus 5)', () => {
  it('leaves missing values empty instead of printing null', () => {
    expect(cell(null)).toBe('');
    expect(cell(undefined)).toBe('');
    expect(cell(-97.5)).toBe('-97.5');
    expect(cell(false)).toBe('No');
    expect(cell(true)).toBe('Sí');
    expect(degrees(null)).toBe('');
    expect(degrees(12345)).toBe('123.45');
    expect(toDegrees(undefined)).toBeNull();
    expect(fixed(null)).toBe('—');
    expect(fixed(-95.04)).toBe('-95.0');
    expect(formatEpochMs(null)).toBe('');
    expect(formatEpochMs(Date.parse('2026-10-12T15:00:00Z'))).toBe('12/10/2026, 12:00:00');
    expect(satelliteText(null)).toBe('');
    expect(satelliteText({ name: 'NOAA 19', norad: 33591 })).toBe('NOAA 19 (NORAD 33591)');
    expect(satelliteText({ name: 'NOAA 19', norad: null })).toBe('NOAA 19');
    expect(satelliteText({ name: null, norad: 33591 })).toBe('NORAD 33591');
  });
});

describe('receptionSummary', () => {
  it('adds the packets and weighs the daily means by packets', () => {
    expect(receptionSummary([
      { date: '2026-10-01', packets: 3, crc_errors: 1, rssi_mean: -100, snr_mean: 2 },
      { date: '2026-10-02', packets: 1, crc_errors: 0, rssi_mean: -80, snr_mean: null },
      { date: '2026-10-03', packets: 0, crc_errors: 0, rssi_mean: null, snr_mean: null },
    ])).toEqual({ packets: 4, crc_errors: 1, rssi_mean: -95, snr_mean: 2 });
  });

  it('has no means without packets', () => {
    expect(receptionSummary([])).toEqual({ packets: 0, crc_errors: 0, rssi_mean: null, snr_mean: null });
  });
});
