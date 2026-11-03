/** Date ranges, cursors and cells of the history tabs. */

export type DateRange = [Date | null, Date | null];

export interface RangeQuery {
  from?: string;
  to?: string;
}

const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
const addDays = (date: Date, days: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);

/** Yesterday and today, in local time. */
export function defaultRange(now = new Date()): DateRange {
  const today = startOfDay(now);
  return [addDays(today, -1), today];
}

/** Two back-to-back periods of `days` days ending today: the one before, and the latest. */
export function comparisonRanges(now = new Date(), days = 7): [DateRange, DateRange] {
  const today = startOfDay(now);
  return [
    [addDays(today, -2 * days + 1), addDays(today, -days)],
    [addDays(today, -days + 1), today],
  ];
}

/**
 * The date picker gives local midnights and the API wants UTC instants, with
 * `to` excluded. The last day counts whole, so `to` is the midnight after it.
 */
export function toRangeQuery([start, end]: DateRange): RangeQuery {
  const query: RangeQuery = {};
  if (start) query.from = startOfDay(start).toISOString();
  if (end) query.to = addDays(end, 1).toISOString();
  return query;
}

/**
 * The series and the results answer 400 without both ends (Tasks 9 and 10),
 * and their schema marks from and to as required. A type guard, so a caller
 * that checked it can pass the query where both are required.
 */
export function hasRange(query: RangeQuery): query is Required<RangeQuery> {
  return query.from !== undefined && query.to !== undefined;
}

/** The cursor in a DRF next/previous link. Its host may be server:8000, so only the query matters. */
export function cursorFrom(link: string | null | undefined): string | undefined {
  if (!link) return undefined;
  return new URL(link, 'http://localhost').searchParams.get('cursor') ?? undefined;
}

/** A table cell: a missing value stays empty instead of printing "null". */
export function cell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'Sí' : 'No';
  return String(value);
}

/**
 * The satellite of a plugin data row ({name, norad} | null, the shape of
 * GET /api/boards/live): cell() would print "[object Object]".
 */
export function satelliteText(satellite: { name?: string | null; norad?: number | null } | null | undefined): string {
  if (!satellite) return '';
  const name = satellite.name ?? '';
  if (satellite.norad == null) return name;
  return name ? `${name} (NORAD ${satellite.norad})` : `NORAD ${satellite.norad}`;
}

export function toDegrees(cdeg: number | null | undefined): number | null {
  return cdeg === null || cdeg === undefined ? null : cdeg / 100;
}

/** Centidegrees as degrees with two decimals, or empty. */
export function degrees(cdeg: number | null | undefined): string {
  const value = toDegrees(cdeg);
  return value === null ? '' : value.toFixed(2);
}

export function fixed(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits);
}

/** An epoch in milliseconds (t0_ms, t_end_ms, t_sent_ms) in local time, like formatDateTime. */
export function formatEpochMs(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? '' : new Date(ms).toLocaleString('es-AR');
}

export interface ReceptionDayLike {
  date: string;
  packets: number;
  crc_errors: number;
  rssi_mean: number | null;
  snr_mean: number | null;
}

/** A period's totals; the daily means are weighed by that day's packets. */
export function receptionSummary(days: readonly ReceptionDayLike[]) {
  let packets = 0;
  let crcErrors = 0;
  let rssiSum = 0;
  let rssiWeight = 0;
  let snrSum = 0;
  let snrWeight = 0;
  for (const day of days) {
    packets += day.packets;
    crcErrors += day.crc_errors;
    if (day.rssi_mean !== null) {
      rssiSum += day.rssi_mean * day.packets;
      rssiWeight += day.packets;
    }
    if (day.snr_mean !== null) {
      snrSum += day.snr_mean * day.packets;
      snrWeight += day.packets;
    }
  }
  return {
    packets,
    crc_errors: crcErrors,
    rssi_mean: rssiWeight ? rssiSum / rssiWeight : null,
    snr_mean: snrWeight ? snrSum / snrWeight : null,
  };
}
