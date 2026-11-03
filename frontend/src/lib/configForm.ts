/**
 * The form of a plugin's config, built from the config_fields its type
 * declares (GET /api/plugin-types). validate() mirrors validate_config in
 * server_core/plugin_handlers/fields.py, so most mistakes show up next to the
 * field before any request; the server checks again and has the last word.
 */

/** Lenient on purpose: the generated ConfigField of schema.d.ts fits in it. */
export interface ConfigField {
  name: string;
  label?: string;
  help?: string;
  /** 'string' | 'integer' | 'number' | 'boolean' | 'choice' */
  type: string;
  required?: boolean;
  default?: unknown;
  min?: number | null;
  max?: number | null;
  /** [value, label] pairs, for 'choice'. */
  choices?: readonly (readonly unknown[])[] | null;
  /** Matched against the whole value, like Python's re.fullmatch. */
  pattern?: string | null;
}

export type FormValue = string | number | boolean;
export type FormValues = Record<string, FormValue>;
export type FormErrors = Record<string, string>;

export const REQUIRED = 'Este campo es obligatorio.';

const isNumeric = (field: ConfigField) => field.type === 'integer' || field.type === 'number';

/** Like fields.py: an empty string counts as missing. */
const isEmpty = (value: FormValue | undefined) => value === undefined || value === '';

export function asConfig(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function toFormValue(field: ConfigField, value: unknown): FormValue {
  if (field.type === 'boolean') return value === true;
  if (typeof value === 'number' || typeof value === 'string') return value;
  return value === null || value === undefined ? '' : String(value);
}

export function initialValues(fields: readonly ConfigField[], config: Record<string, unknown> = {}): FormValues {
  const values: FormValues = {};
  for (const field of fields) {
    values[field.name] = toFormValue(field, field.name in config ? config[field.name] : field.default);
  }
  return values;
}

function toNumber(value: FormValue): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function checkValue(field: ConfigField, value: FormValue): string | null {
  if (isNumeric(field)) {
    const number = toNumber(value);
    if (number === null) return 'Tiene que ser un número.';
    if (field.type === 'integer' && !Number.isInteger(number)) return 'Tiene que ser un número entero.';
    if (field.min != null && number < field.min) return `Tiene que ser mayor o igual a ${field.min}.`;
    if (field.max != null && number > field.max) return `Tiene que ser menor o igual a ${field.max}.`;
    return null;
  }
  if (field.type === 'choice') {
    const known = (field.choices ?? []).some(([choice]) => String(choice) === String(value));
    return known ? null : 'Elegí una de las opciones.';
  }
  if (field.type === 'string' && field.pattern && !new RegExp(`^(?:${field.pattern})$`).test(String(value))) {
    return 'No tiene el formato esperado.';
  }
  return null;
}

export function validate(fields: readonly ConfigField[], values: FormValues): FormErrors {
  const errors: FormErrors = {};
  for (const field of fields) {
    if (field.type === 'boolean') continue; // a switch is always true or false
    const value = values[field.name];
    if (isEmpty(value)) {
      if (field.required) errors[field.name] = REQUIRED;
      continue;
    }
    const error = checkValue(field, value);
    if (error) errors[field.name] = error;
  }
  return errors;
}

/**
 * The config to send. Keys the type does not declare are kept from `original`,
 * so editing a field never drops something set elsewhere; an optional field
 * left empty is removed, and the server fills in its default.
 */
export function toConfig(
  fields: readonly ConfigField[],
  values: FormValues,
  original: Record<string, unknown> = {},
): Record<string, unknown> {
  const config = { ...original };
  for (const field of fields) {
    const value = values[field.name];
    if (field.type === 'boolean') config[field.name] = value === true;
    else if (isEmpty(value)) delete config[field.name];
    else config[field.name] = isNumeric(field) ? toNumber(value) : value;
  }
  return config;
}
