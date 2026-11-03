/** How the pages turn a failed call (an ApiError from unwrap, or a network TypeError) into text. */
import { ApiError } from './client';

export function isStatus(error: unknown, status: number): error is ApiError {
  return error instanceof ApiError && error.status === status;
}

export interface SplitErrors {
  fields: Record<string, string>;
  general: string[];
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const joined = (messages: unknown): string =>
  Array.isArray(messages) ? messages.map(String).join(' ') : String(messages);

const GENERAL_KEYS = new Set(['detail', 'non_field_errors']);

/**
 * Splits a DRF error body into messages per field and general messages.
 * The config of a plugin comes back nested ({"config": {"tinygs_device": [...]}},
 * Task 6), so its keys land next to the top-level ones, where the form shows them.
 */
export function splitErrors(body: unknown): SplitErrors {
  const result: SplitErrors = { fields: {}, general: [] };
  if (!isObject(body)) return result;
  for (const [key, value] of Object.entries(body)) {
    if (GENERAL_KEYS.has(key)) {
      result.general.push(joined(value));
    } else if (key === 'config' && isObject(value)) {
      for (const [name, messages] of Object.entries(value)) {
        if (GENERAL_KEYS.has(name)) result.general.push(joined(messages));
        else result.fields[name] = joined(messages);
      }
    } else if (key === 'config') {
      result.general.push(joined(value));
    } else {
      result.fields[key] = joined(value);
    }
  }
  return result;
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'No se pudo conectar con el servidor.';
  const { fields, general } = splitErrors(error.body);
  const messages = [...general, ...Object.entries(fields).map(([field, message]) => `${field}: ${message}`)];
  if (messages.length > 0) return messages.join(' ');
  if (error.status >= 500) return `Error del servidor (${error.status}).`;
  return `El servidor rechazó el pedido (${error.status}).`;
}
