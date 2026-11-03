import { skyXY } from '../lib/sky';

export type SkyAntenna = { id: string; label: string; az_cdeg: number; el_cdeg: number };
export type SkyTrack = { id: string; points: { az_cdeg: number; el_cdeg: number }[] };

const R = 100; // the horizon's radius, in SVG units

function xy(az_cdeg: number, el_cdeg: number, radius = R) {
  return skyXY(az_cdeg / 100, el_cdeg / 100, radius);
}

// Two decimals are plenty on a 230-unit canvas, and keep "-0" out of the markup.
const n = (value: number) => String(Math.round(value * 100) / 100);

const CARDINALS: [string, number][] = [
  ['N', 0],
  ['E', 9000],
  ['S', 18000],
  ['O', 27000],
];

/** Polar sky: zenith in the centre, horizon on the rim, rings every 30° of elevation (spec 4.1). */
export function SkyPlot({ antennas, tracks }: { antennas: SkyAntenna[]; tracks: SkyTrack[] }) {
  const line = 'var(--mantine-color-dimmed)';

  return (
    <svg viewBox="-115 -115 230 230" width="100%" style={{ maxWidth: 360 }} role="img" aria-label="Gráfico del cielo">
      {[0, 30, 60].map((el) => (
        <circle key={el} r={(R * (90 - el)) / 90} fill="none" stroke={line} strokeWidth={0.5} />
      ))}
      <line x1={-R} y1={0} x2={R} y2={0} stroke={line} strokeWidth={0.5} />
      <line x1={0} y1={-R} x2={0} y2={R} stroke={line} strokeWidth={0.5} />
      {CARDINALS.map(([label, az]) => {
        const p = xy(az, 0, R + 8);
        return (
          <text key={label} x={n(p.x)} y={n(p.y)} textAnchor="middle" dominantBaseline="middle" fontSize={8} fill={line}>
            {label}
          </text>
        );
      })}

      {tracks
        .filter((track) => track.points.length > 0)
        .map((track) => (
          <polyline
            key={track.id}
            points={track.points
              .map((point) => {
                const p = xy(point.az_cdeg, point.el_cdeg);
                return `${n(p.x)},${n(p.y)}`;
              })
              .join(' ')}
            fill="none"
            stroke="var(--mantine-color-blue-5)"
            strokeWidth={1}
          />
        ))}

      {antennas.map((antenna) => {
        const p = xy(antenna.az_cdeg, antenna.el_cdeg);
        return (
          <g key={antenna.id}>
            <circle cx={n(p.x)} cy={n(p.y)} r={3} fill="var(--mantine-color-red-6)" aria-label={antenna.label} />
            <text x={n(p.x + 5)} y={n(p.y)} dominantBaseline="middle" fontSize={7} fill="currentColor">
              {antenna.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
