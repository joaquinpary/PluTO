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

/** The previous `days` and the latest `days`, ending today. */
export function comparisonRanges(now = new Date(), days = 7): [DateRange, DateRange] {
  const today = startOfDay(now);
  return [
    [addDays(today, -2 * days + 1), addDays(today, -days)],
    [addDays(today, -days + 1), today],
  ];
}

/** Local days to UTC instants; `to` is exclusive, so it's the midnight after the last day. */
export function toRangeQuery([start, end]: DateRange): RangeQuery {
  const query: RangeQuery = {};
  if (start) query.from = startOfDay(start).toISOString();
  if (end) query.to = addDays(end, 1).toISOString();
  return query;
}

/** Type guard: series and results answer 400 without both ends. */
export function hasRange(query: RangeQuery): query is Required<RangeQuery> {
  return query.from !== undefined && query.to !== undefined;
}

/** Only the query matters: the link's host may be server:8000. */
export function cursorFrom(link: string | null | undefined): string | undefined {
  if (!link) return undefined;
  return new URL(link, 'http://localhost').searchParams.get('cursor') ?? undefined;
}

/** null/undefined render empty, not "null". */
export function cell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'Sí' : 'No';
  return String(value);
}

/** {name, norad} | null, which cell() would print as "[object Object]". */
export function satelliteText(satellite: { name?: string | null; norad?: number | null } | null | undefined): string {
  if (!satellite) return '';
  const name = satellite.name ?? '';
  if (satellite.norad == null) return name;
  return name ? `${name} (NORAD ${satellite.norad})` : `NORAD ${satellite.norad}`;
}

export function toDegrees(cdeg: number | null | undefined): number | null {
  return cdeg === null || cdeg === undefined ? null : cdeg / 100;
}

/** cdeg to degrees, two decimals. */
export function degrees(cdeg: number | null | undefined): string {
  const value = toDegrees(cdeg);
  return value === null ? '' : value.toFixed(2);
}

export function fixed(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits);
}

/** Epoch ms (t0_ms, t_end_ms, t_sent_ms) in local time. */
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

/** Daily means weighted by each day's packets. */
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
