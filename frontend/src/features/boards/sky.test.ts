import { describe, expect, it } from 'vitest';
import { skyXY } from './sky';

function expectPoint(actual: { x: number; y: number }, x: number, y: number) {
  expect(actual.x).toBeCloseTo(x);
  expect(actual.y).toBeCloseTo(y);
}

describe('skyXY', () => {
  it('puts the zenith in the centre', () => {
    expectPoint(skyXY(123, 90, 100), 0, 0);
  });

  it('puts north up and east to the right, on the rim at the horizon', () => {
    expectPoint(skyXY(0, 0, 100), 0, -100); // SVG y grows downwards
    expectPoint(skyXY(90, 0, 100), 100, 0);
    expectPoint(skyXY(180, 0, 100), 0, 100);
    expectPoint(skyXY(270, 0, 100), -100, 0);
  });

  it('is linear in elevation', () => {
    expectPoint(skyXY(180, 45, 100), 0, 50);
    expectPoint(skyXY(90, 60, 90), 30, 0);
  });

  it('keeps a point below the horizon on the rim', () => {
    expectPoint(skyXY(90, -5, 100), 100, 0);
  });
});
