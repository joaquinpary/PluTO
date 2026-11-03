import type { BoardLive, LiveState, Plugin } from '../api/types';

// API rows for tests, with defaults that pass for a healthy station. If tsc
// complains here, the schema changed: follow it.

export function liveState(overrides: Partial<LiveState> = {}): LiveState {
  return {
    received_at: new Date().toISOString(),
    mode: 'tracking',
    az_cdeg: 12345,
    el_cdeg: 4500,
    pan_mode: 'normal',
    batch_accepted: true,
    batch_error: '',
    clock_synced: true,
    rejected_total: 0,
    meas: null,
    err_cdeg: null,
    ...overrides,
  };
}

export function liveBoard(overrides: Partial<BoardLive> = {}): BoardLive {
  const state = overrides.state === undefined ? liveState() : overrides.state;
  return {
    device_id: 'aabbccddeeff',
    name: 'Terraza',
    online: true,
    status_changed_at: null,
    last_state_at: state ? state.received_at : null,
    state,
    running_plugin: null,
    satellite: null,
    last_hold_reason: null,
    ...overrides,
  };
}

export function pluginRow(overrides: Partial<Plugin> = {}): Plugin {
  return {
    plugin_uuid: '0b7e4c1a-6a52-4f0e-9a43-3f1d2c5b8e90',
    name: 'tinygs-terraza',
    plugin_type: 'tinygs',
    config: {},
    status: 'STOPPED',
    docker_status: 'exited',
    board: null,
    created_at: '2026-10-01T12:00:00Z',
    updated_at: '2026-10-01T12:00:00Z',
    warnings: [],
    ...overrides,
  };
}
