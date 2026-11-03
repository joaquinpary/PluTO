/**
 * Where an az/el direction falls on a polar sky plot of the given radius,
 * centred on (0, 0): the zenith in the centre, the horizon on the rim, north
 * up and east to the right. In SVG coordinates, so y grows downwards. A point
 * below the horizon stays on the rim.
 */
export function skyXY(az_deg: number, el_deg: number, radius: number): { x: number; y: number } {
  const el = Math.min(90, Math.max(0, el_deg));
  const r = (radius * (90 - el)) / 90;
  const az = (az_deg * Math.PI) / 180;
  return { x: r * Math.sin(az), y: -r * Math.cos(az) };
}
