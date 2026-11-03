import { describe, expect, it } from 'vitest';
import { asConfig, initialValues, toConfig, validate, type ConfigField, type FormValues } from './configForm';

const FIELDS: ConfigField[] = [
  { name: 'device', label: 'Estación', type: 'string', required: true, pattern: '[A-Za-z0-9_-]+' },
  { name: 'prefix', label: 'Prefijo', type: 'string', required: false, pattern: '[^/+#\\s]+' },
  { name: 'min_elevation_deg', label: 'Elevación mínima', type: 'number', required: false, default: 10, min: -90, max: 90 },
  { name: 'retries', label: 'Reintentos', type: 'integer', required: false, default: null, min: 0, max: null },
  { name: 'verbose', label: 'Detallado', type: 'boolean', required: false, default: false },
  { name: 'coord_type', label: 'Sistema', type: 'choice', required: true, choices: [['ECEF', 'ECEF'], ['ENU', 'ENU']] },
];

const VALID: FormValues = {
  device: 'My_TinyGS', prefix: '', min_elevation_deg: 10, retries: '', verbose: false, coord_type: 'ECEF',
};

describe('initialValues', () => {
  it('takes the saved config first, then the default, then an empty value', () => {
    expect(initialValues(FIELDS, { device: 'My_TinyGS', min_elevation_deg: 15 })).toEqual({
      device: 'My_TinyGS', prefix: '', min_elevation_deg: 15, retries: '', verbose: false, coord_type: '',
    });
    expect(initialValues(FIELDS).min_elevation_deg).toBe(10);
  });
});

describe('validate', () => {
  it('accepts a complete form with the optional fields empty', () => {
    expect(validate(FIELDS, VALID)).toEqual({});
  });

  it('asks for the required fields left empty', () => {
    expect(validate(FIELDS, { ...VALID, device: '', coord_type: '' })).toEqual({
      device: 'Este campo es obligatorio.',
      coord_type: 'Este campo es obligatorio.',
    });
  });

  it('matches the pattern against the whole value, like re.fullmatch', () => {
    expect(validate(FIELDS, { ...VALID, device: 'My TinyGS' })).toEqual({ device: 'No tiene el formato esperado.' });
    expect(validate(FIELDS, { ...VALID, device: '   ' })).toEqual({ device: 'No tiene el formato esperado.' });
    expect(validate(FIELDS, { ...VALID, prefix: 'a/b' })).toEqual({ prefix: 'No tiene el formato esperado.' });
  });

  it('checks numbers, integers and their range, both ends included', () => {
    expect(validate(FIELDS, { ...VALID, min_elevation_deg: -90 })).toEqual({});
    expect(validate(FIELDS, { ...VALID, min_elevation_deg: 90.5 }))
      .toEqual({ min_elevation_deg: 'Tiene que ser menor o igual a 90.' });
    expect(validate(FIELDS, { ...VALID, min_elevation_deg: 'abc' }))
      .toEqual({ min_elevation_deg: 'Tiene que ser un número.' });
    expect(validate(FIELDS, { ...VALID, retries: 1.5 })).toEqual({ retries: 'Tiene que ser un número entero.' });
    expect(validate(FIELDS, { ...VALID, retries: -1 })).toEqual({ retries: 'Tiene que ser mayor o igual a 0.' });
  });

  it('only accepts one of the declared choices', () => {
    expect(validate(FIELDS, { ...VALID, coord_type: 'ECI' })).toEqual({ coord_type: 'Elegí una de las opciones.' });
  });
});

describe('toConfig', () => {
  it('sends numbers as numbers and leaves out the optional fields left empty', () => {
    expect(toConfig(FIELDS, { ...VALID, min_elevation_deg: '12.5', verbose: true, coord_type: 'ENU' }))
      .toEqual({ device: 'My_TinyGS', min_elevation_deg: 12.5, verbose: true, coord_type: 'ENU' });
  });

  it('keeps the keys the type does not declare and removes the ones cleared', () => {
    const original = { device: 'Old', prefix: 'tinygs', legacy: 1 };
    const values = { ...initialValues(FIELDS, original), prefix: '', coord_type: 'ECEF' };
    expect(toConfig(FIELDS, values, original))
      .toEqual({ device: 'Old', legacy: 1, min_elevation_deg: 10, verbose: false, coord_type: 'ECEF' });
  });
});

describe('asConfig', () => {
  it('copies a plain object and turns anything else into an empty one', () => {
    expect(asConfig({ a: 1 })).toEqual({ a: 1 });
    expect(asConfig(null)).toEqual({});
    expect(asConfig([1])).toEqual({});
  });
});
