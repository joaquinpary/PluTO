import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, unwrap } from '../../shared/api/client';
import { hasRange, type RangeQuery } from './history';

export interface OrderFilters extends RangeQuery {
  board?: string;
  kind?: 'BATCH' | 'HOLD';
  reason?: 'end' | 'limits' | 'expired' | 'stopped';
  cursor?: string;
}

export interface PluginDataFilters extends RangeQuery {
  plugin?: string;
  type?: string;
  cursor?: string;
}

/** Unreachable: enabled already requires both ends. */
const NO_RANGE = 'A range needs both ends.';

/** Last state per interval, at most max_points (2000 by default). */
export function useStateSeries(deviceId: string, range: RangeQuery) {
  return useQuery({
    queryKey: ['history', 'series', deviceId, range],
    queryFn: async () => {
      // Narrows from/to, which the schema requires here.
      if (!hasRange(range)) throw new Error(NO_RANGE);
      return unwrap(
        await api.GET('/api/boards/{device_id}/states/series', { params: { path: { device_id: deviceId }, query: range } }),
      );
    },
    enabled: deviceId !== '' && hasRange(range),
  });
}

export function useStates(deviceId: string, query: RangeQuery & { cursor?: string }) {
  return useQuery({
    queryKey: ['history', 'states', deviceId, query],
    queryFn: async () =>
      unwrap(await api.GET('/api/boards/{device_id}/states', { params: { path: { device_id: deviceId }, query } })),
    enabled: deviceId !== '',
    placeholderData: keepPreviousData,
  });
}

export function useOrders(filters: OrderFilters) {
  return useQuery({
    queryKey: ['history', 'orders', filters],
    queryFn: async () => unwrap(await api.GET('/api/orders', { params: { query: filters } })),
    placeholderData: keepPreviousData,
  });
}

export function usePluginData(filters: PluginDataFilters) {
  return useQuery({
    queryKey: ['history', 'plugin-data', filters],
    queryFn: async () => unwrap(await api.GET('/api/plugin-data', { params: { query: filters } })),
    placeholderData: keepPreviousData,
  });
}

export function usePointingError(board: string, range: RangeQuery) {
  return useQuery({
    queryKey: ['results', 'pointing-error', board, range],
    queryFn: async () => {
      if (!hasRange(range)) throw new Error(NO_RANGE);
      return unwrap(await api.GET('/api/results/pointing-error', { params: { query: { board, ...range } } }));
    },
    enabled: board !== '' && hasRange(range),
  });
}

export function useReception(plugin: string, range: RangeQuery) {
  return useQuery({
    queryKey: ['results', 'reception', plugin, range],
    queryFn: async () => {
      if (!hasRange(range)) throw new Error(NO_RANGE);
      return unwrap(await api.GET('/api/results/reception', { params: { query: { plugin, ...range } } }));
    },
    enabled: plugin !== '' && hasRange(range),
  });
}
