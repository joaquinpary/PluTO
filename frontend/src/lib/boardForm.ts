/**
 * The board form (PATCH /api/boards/<device_id>). validateBoard() mirrors the
 * validators of Rotor and Rotor.clean(): an azimuth window takes both ends or
 * none, and a start above the end wraps through north (300 → 60); latitude
 * and longitude go together too.
 */

/** What a NumberInput holds: a number, or '' while empty. */
export type NumberValue = number | string;

export interface BoardFormValues {
  name: string;
  latitude_deg: NumberValue;
  longitude_deg: NumberValue;
  altitude_m: NumberValue;
  min_elevation_deg: NumberValue;
  min_azimuth_deg: NumberValue;
  max_azimuth_deg: NumberValue;
}

export interface BoardSettings {
  name: string;
  latitude_deg: number | null;
  longitude_deg: number | null;
  altitude_m: number | null;
  min_elevation_deg: number;
  min_azimuth_deg: number | null;
  max_azimuth_deg: number | null;
}

/**
 * A Board as the API answers it. With COMPONENT_SPLIT_REQUEST the schema only
 * promises the read-only fields of an answer, so the editable ones are optional.
 */
export type BoardSource = { [K in keyof BoardSettings]?: BoardSettings[K] | null };

/** Rotor.min_elevation_deg's default, for an answer that leaves it out. */
const DEFAULT_MIN_ELEVATION_DEG = 10;

type NumberKey = Exclude<keyof BoardFormValues, 'name'>;

const LIMITS: [NumberKey, number | null, number | null][] = [
  ['latitude_deg', -90, 90],
  ['longitude_deg', -180, 180],
  ['altitude_m', null, null],
  ['min_elevation_deg', -90, 90],
  ['min_azimuth_deg', 0, 360],
  ['max_azimuth_deg', 0, 360],
];

export const HALF_WINDOW = 'Completá los dos extremos de la ventana de azimut, o dejá los dos vacíos.';
export const HALF_LOCATION = 'Completá la latitud y la longitud, o dejá las dos vacías.';

const isBlank = (value: NumberValue) => typeof value === 'string' && value.trim() === '';

function toNumber(value: NumberValue): number | null {
  if (isBlank(value)) return null;
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

export function boardFormValues(board: BoardSource): BoardFormValues {
  const value = (number: number | null | undefined) => number ?? '';
  return {
    name: board.name ?? '',
    latitude_deg: value(board.latitude_deg),
    longitude_deg: value(board.longitude_deg),
    altitude_m: value(board.altitude_m),
    min_elevation_deg: board.min_elevation_deg ?? DEFAULT_MIN_ELEVATION_DEG,
    min_azimuth_deg: value(board.min_azimuth_deg),
    max_azimuth_deg: value(board.max_azimuth_deg),
  };
}

export function validateBoard(values: BoardFormValues): Record<string, string> {
  const errors: Record<string, string> = {};
  if (values.name.length > 100) errors.name = 'Hasta 100 caracteres.';

  for (const [key, min, max] of LIMITS) {
    const raw = values[key];
    if (isBlank(raw)) {
      if (key === 'min_elevation_deg') errors[key] = 'Este campo es obligatorio.';
      continue;
    }
    const number = toNumber(raw);
    if (number === null) errors[key] = 'Tiene que ser un número.';
    else if (min !== null && max !== null && (number < min || number > max)) {
      errors[key] = `Tiene que estar entre ${min} y ${max}.`;
    }
  }

  // Half a window says nothing: is 200 a floor or a ceiling? (Rotor.clean)
  const hasStart = !isBlank(values.min_azimuth_deg);
  const hasEnd = !isBlank(values.max_azimuth_deg);
  if (hasStart !== hasEnd) errors[hasStart ? 'max_azimuth_deg' : 'min_azimuth_deg'] = HALF_WINDOW;

  // Half a location is no place at all, and would silently mean none (Rotor.clean).
  const hasLatitude = !isBlank(values.latitude_deg);
  const hasLongitude = !isBlank(values.longitude_deg);
  if (hasLatitude !== hasLongitude) errors[hasLatitude ? 'longitude_deg' : 'latitude_deg'] = HALF_LOCATION;
  return errors;
}

/** Only called once validateBoard() returned no errors. */
export function toBoardPatch(values: BoardFormValues): BoardSettings {
  return {
    name: values.name.trim(),
    latitude_deg: toNumber(values.latitude_deg),
    longitude_deg: toNumber(values.longitude_deg),
    altitude_m: toNumber(values.altitude_m),
    min_elevation_deg: Number(values.min_elevation_deg),
    min_azimuth_deg: toNumber(values.min_azimuth_deg),
    max_azimuth_deg: toNumber(values.max_azimuth_deg),
  };
}

/** The window in words, or null while it has only one end. */
export function azimuthWindowText(values: Pick<BoardFormValues, 'min_azimuth_deg' | 'max_azimuth_deg'>): string | null {
  const start = toNumber(values.min_azimuth_deg);
  const end = toNumber(values.max_azimuth_deg);
  if (start === null && end === null) return 'Sin restricción de azimut.';
  if (start === null || end === null) return null;
  if (start <= end) return `Puede apuntar de ${start}° a ${end}°.`;
  return `Cruza el norte: de ${start}° a 360° y de 0° a ${end}°.`;
}
