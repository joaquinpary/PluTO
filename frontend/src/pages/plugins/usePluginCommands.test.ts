import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { launchErrorMessage } from './usePluginCommands';

describe('launchErrorMessage', () => {
  it('suggests syncing when the launch never got an answer from Django', () => {
    expect(launchErrorMessage(new TypeError('Failed to fetch'))).toMatch(/Sincronizar/);
    expect(launchErrorMessage(new ApiError(504, '<html>Gateway Timeout</html>'))).toMatch(/Sincronizar/);
  });

  it('explains a 409 in Spanish, naming the instance that drives the board when it is known', () => {
    const busy = new ApiError(409, { detail: 'tinygs-omni already drives a1b2c3d4e5f6 (RF-31.1).' });

    expect(launchErrorMessage(busy, 'tinygs-omni')).toBe(
      'Su placa ya la maneja tinygs-omni, que está en ejecución (RF-31.1). Detenela antes de lanzar esta.',
    );
    expect(launchErrorMessage(busy)).toBe(
      'Ya está en ejecución, u otra instancia en ejecución maneja su placa (RF-31.1). Tocá «Sincronizar» para ver el estado real.',
    );
  });

  it('shows what the server said otherwise, a Docker 502 included', () => {
    expect(launchErrorMessage(new ApiError(502, { detail: 'Docker is not reachable.' }))).toBe('Docker is not reachable.');
  });
});
