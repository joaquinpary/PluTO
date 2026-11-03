import type { Board, BoardLive, LiveState, Plugin, PluginType } from '../shared/api/types';

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

// --- Instances and boards ----------------------------------------------------

export const OTHER_UUID = '7f1e2d3c-4b5a-4968-8776-655443322110';

type ConfigFieldRow = PluginType['config_fields'][number];

function configField(field: Pick<ConfigFieldRow, 'name' | 'label' | 'type'> & Partial<ConfigFieldRow>): ConfigFieldRow {
  return { help: '', required: false, default: null, min: null, max: null, choices: null, pattern: null, ...field };
}

// Labels, choices and patterns as the handlers declare them
// (plugin_handlers/tinygs.py and file_tracker.py), so a fixture reads like the real API.
export const TINYGS_TYPE: PluginType = {
  type: 'tinygs',
  label: 'TinyGS',
  message_types: ['tracking', 'rx'],
  config_fields: [
    configField({ name: 'tinygs_device', label: 'Dispositivo TinyGS', type: 'string', required: true, pattern: '[A-Za-z0-9_-]+' }),
    configField({ name: 'tinygs_topic_prefix', label: 'Prefijo de los tópicos', type: 'string', pattern: '[^/+#\\s]+' }),
    configField({ name: 'min_elevation_deg', label: 'Elevación mínima (°)', type: 'number', default: 10, min: -90, max: 90 }),
    configField({ name: 'lookahead_minutes', label: 'Anticipación (min)', type: 'number', default: 20, min: 1 }),
    configField({ name: 'sample_seconds', label: 'Paso entre puntos (s)', type: 'number', default: 1, min: 0.1 }),
    configField({ name: 'tle_ttl_hours', label: 'Vigencia del TLE (h)', type: 'number', default: 12, min: 1 }),
  ],
};

export const FILE_TRACKER_TYPE: PluginType = {
  type: 'file_tracker',
  label: 'Archivo de coordenadas',
  message_types: [],
  config_fields: [
    configField({ name: 'coord_type', label: 'Sistema de referencia', type: 'choice', required: true,
      choices: [['ECEF', 'ECEF'], ['ECI', 'ECI'], ['ENU', 'ENU (local)']] }),
    configField({ name: 'coord_format', label: 'Formato', type: 'choice', required: true,
      choices: [['CARTESIAN', 'Cartesianas'], ['GEO', 'Geográficas'], ['POLAR', 'Polares']] }),
  ],
};

export const PLUGIN_TYPES: PluginType[] = [TINYGS_TYPE, FILE_TRACKER_TYPE];

export function boardRow(overrides: Partial<Board> = {}): Board {
  return {
    device_id: 'a1b2c3d4e5f6',
    name: 'Terraza',
    online: true,
    status_changed_at: '2026-10-12T11:00:00Z',
    last_state_at: '2026-10-12T12:29:59Z',
    latitude_deg: -31.4201,
    longitude_deg: -64.1888,
    altitude_m: 420,
    min_elevation_deg: 10,
    min_azimuth_deg: null,
    max_azimuth_deg: null,
    plugins: [],
    ...overrides,
  };
}
