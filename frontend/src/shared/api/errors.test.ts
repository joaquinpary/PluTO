import { describe, expect, it } from 'vitest';
import { ApiError } from './client';
import { errorMessage, isStatus, splitErrors } from './errors';

describe('splitErrors', () => {
  it('maps DRF field errors and flattens the config of a plugin', () => {
    expect(splitErrors({
      name: ['Ya existe una instancia con ese nombre.'],
      config: { tinygs_device: ['Formato inválido.', 'Muy largo.'] },
    })).toEqual({
      fields: { name: 'Ya existe una instancia con ese nombre.', tinygs_device: 'Formato inválido. Muy largo.' },
      general: [],
    });
  });

  it('treats detail, non_field_errors (top level or inside config) and a config list as general', () => {
    expect(splitErrors({
      detail: 'No.',
      non_field_errors: ['Media ventana.'],
      config: { non_field_errors: ['Combinación inválida.'] },
    })).toEqual({ fields: {}, general: ['No.', 'Media ventana.', 'Combinación inválida.'] });
    expect(splitErrors({ config: ['Must be a JSON object.'] })).toEqual({ fields: {}, general: ['Must be a JSON object.'] });
  });

  it('ignores bodies that are not an object', () => {
    expect(splitErrors('<html>Bad Gateway</html>')).toEqual({ fields: {}, general: [] });
    expect(splitErrors(null)).toEqual({ fields: {}, general: [] });
  });
});

describe('errorMessage', () => {
  it('prefers the messages the server sent', () => {
    expect(errorMessage(new ApiError(409, { detail: 'Board busy.' }))).toBe('Board busy.');
    expect(errorMessage(new ApiError(400, { name: ['Obligatorio.'] }))).toBe('name: Obligatorio.');
  });

  it('falls back to the status, and to a connection error for anything else', () => {
    expect(errorMessage(new ApiError(502, '<html>'))).toBe('Error del servidor (502).');
    expect(errorMessage(new ApiError(404, undefined))).toBe('El servidor rechazó el pedido (404).');
    expect(errorMessage(new TypeError('Failed to fetch'))).toBe('No se pudo conectar con el servidor.');
  });
});

describe('isStatus', () => {
  it('matches only an ApiError with that status', () => {
    expect(isStatus(new ApiError(409, {}), 409)).toBe(true);
    expect(isStatus(new ApiError(400, {}), 409)).toBe(false);
    expect(isStatus(new Error('409'), 409)).toBe(false);
  });
});
