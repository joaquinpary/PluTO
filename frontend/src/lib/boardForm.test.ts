import { describe, expect, it } from 'vitest';
import {
  HALF_LOCATION,
  HALF_WINDOW,
  azimuthWindowText,
  boardFormValues,
  toBoardPatch,
  validateBoard,
  type BoardFormValues,
} from './boardForm';

const BASE: BoardFormValues = {
  name: 'Terraza',
  latitude_deg: -31.42,
  longitude_deg: -64.19,
  altitude_m: 420,
  min_elevation_deg: 10,
  min_azimuth_deg: '',
  max_azimuth_deg: '',
};

describe('validateBoard', () => {
  it('accepts no azimuth window at all', () => {
    expect(validateBoard(BASE)).toEqual({});
  });

  it('accepts a window that wraps through north (300 → 60)', () => {
    expect(validateBoard({ ...BASE, min_azimuth_deg: 300, max_azimuth_deg: 60 })).toEqual({});
  });

  it('rejects half a window, on the end that is missing', () => {
    expect(validateBoard({ ...BASE, min_azimuth_deg: 300 })).toEqual({ max_azimuth_deg: HALF_WINDOW });
    expect(validateBoard({ ...BASE, max_azimuth_deg: 60 })).toEqual({ min_azimuth_deg: HALF_WINDOW });
  });

  it('rejects half a location, on the coordinate that is missing, like Rotor.clean()', () => {
    expect(validateBoard({ ...BASE, longitude_deg: '' })).toEqual({ longitude_deg: HALF_LOCATION });
    expect(validateBoard({ ...BASE, latitude_deg: '', altitude_m: '' })).toEqual({ latitude_deg: HALF_LOCATION });
    // No location at all is fine: the board just has none yet.
    expect(validateBoard({ ...BASE, latitude_deg: '', longitude_deg: '', altitude_m: '' })).toEqual({});
  });

  it('checks the ranges of the location and of the limits', () => {
    expect(validateBoard({ ...BASE, latitude_deg: 91, longitude_deg: -181, min_azimuth_deg: 361, max_azimuth_deg: 0 })).toEqual({
      latitude_deg: 'Tiene que estar entre -90 y 90.',
      longitude_deg: 'Tiene que estar entre -180 y 180.',
      min_azimuth_deg: 'Tiene que estar entre 0 y 360.',
    });
  });

  it('requires the minimum elevation and rejects what is not a number', () => {
    expect(validateBoard({ ...BASE, min_elevation_deg: '' })).toEqual({ min_elevation_deg: 'Este campo es obligatorio.' });
    expect(validateBoard({ ...BASE, altitude_m: '-' })).toEqual({ altitude_m: 'Tiene que ser un número.' });
  });
});

describe('toBoardPatch', () => {
  it('sends empty fields as null and keeps a wrapping window as typed', () => {
    expect(toBoardPatch({ ...BASE, name: ' Terraza ', altitude_m: '', min_azimuth_deg: 300, max_azimuth_deg: '60' })).toEqual({
      name: 'Terraza',
      latitude_deg: -31.42,
      longitude_deg: -64.19,
      altitude_m: null,
      min_elevation_deg: 10,
      min_azimuth_deg: 300,
      max_azimuth_deg: 60,
    });
  });
});

describe('boardFormValues', () => {
  it('shows a missing value as an empty field', () => {
    const empty = {
      name: '', latitude_deg: '', longitude_deg: '', altitude_m: '',
      min_elevation_deg: 10, min_azimuth_deg: '', max_azimuth_deg: '',
    };
    expect(boardFormValues({
      name: '', latitude_deg: null, longitude_deg: null, altitude_m: null,
      min_elevation_deg: 10, min_azimuth_deg: null, max_azimuth_deg: null,
    })).toEqual(empty);
    // What the schema leaves optional may not come at all; the elevation falls back to Rotor's default.
    expect(boardFormValues({})).toEqual(empty);
  });
});

describe('azimuthWindowText', () => {
  it('describes the window, including one that wraps through north', () => {
    expect(azimuthWindowText({ min_azimuth_deg: '', max_azimuth_deg: '' })).toBe('Sin restricción de azimut.');
    expect(azimuthWindowText({ min_azimuth_deg: 90, max_azimuth_deg: 270 })).toBe('Puede apuntar de 90° a 270°.');
    expect(azimuthWindowText({ min_azimuth_deg: 300, max_azimuth_deg: 60 }))
      .toBe('Cruza el norte: de 300° a 360° y de 0° a 60°.');
    expect(azimuthWindowText({ min_azimuth_deg: 300, max_azimuth_deg: '' })).toBeNull();
  });
});
