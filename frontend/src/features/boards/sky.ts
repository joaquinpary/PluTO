/** az/el to SVG x/y on a polar plot centred at (0, 0), north up. Below the horizon clamps to the rim. */
export function skyXY(az_deg: number, el_deg: number, radius: number): { x: number; y: number } {
  const el = Math.min(90, Math.max(0, el_deg));
  const r = (radius * (90 - el)) / 90;
  const az = (az_deg * Math.PI) / 180;
  return { x: r * Math.sin(az), y: -r * Math.cos(az) };
}
