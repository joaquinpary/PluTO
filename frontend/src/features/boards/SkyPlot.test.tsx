import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SkyPlot } from './SkyPlot';

describe('SkyPlot', () => {
  it('draws each antenna where it points', () => {
    render(<SkyPlot antennas={[{ id: 'a', label: 'Terraza', az_cdeg: 9000, el_cdeg: 0 }]} tracks={[]} />);

    const dot = screen.getByLabelText('Terraza');
    expect(Number(dot.getAttribute('cx'))).toBeCloseTo(100); // east horizon: on the rim, to the right
    expect(Number(dot.getAttribute('cy'))).toBeCloseTo(0);
  });

  it('draws the pass in progress as a line through its points', () => {
    const { container } = render(
      <SkyPlot
        antennas={[]}
        tracks={[
          {
            id: 'a',
            points: [
              { az_cdeg: 0, el_cdeg: 9000 },
              { az_cdeg: 18000, el_cdeg: 4500 },
            ],
          },
        ]}
      />,
    );

    expect(container.querySelector('polyline')).toHaveAttribute('points', '0,0 0,50');
  });

  it('draws no line for a board without a pass', () => {
    const { container } = render(<SkyPlot antennas={[]} tracks={[{ id: 'a', points: [] }]} />);

    expect(container.querySelector('polyline')).toBeNull();
  });
});
