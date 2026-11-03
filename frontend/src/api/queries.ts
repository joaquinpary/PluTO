import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, unwrap } from './client';
import { setTokens } from './tokens';
import type { Plugin, PluginFilters } from './types';
import type { BoardSettings } from '../lib/boardForm';
import { hasRange, type RangeQuery } from '../lib/history';

/** GET /api/setup: whether the only user still has to be created (spec 3.4). */
export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup'],
    queryFn: async () => unwrap(await api.GET('/api/setup')),
    staleTime: Infinity,
  });
}

// Polling periods (spec 6). None of them runs while the tab is hidden.
export const LIVE_INTERVAL_MS = 1000;
export const PLUGINS_INTERVAL_MS = 5000;
export const TRACK_INTERVAL_MS = 5000;

/**
 * How every polled query rides out a failure (spec 6): two retries a second
 * apart before it turns to error, with data keeping the last good answer
 * meanwhile. A 404 is an answer (no such instance, no container), not a
 * failure, so it is not retried.
 */
export const POLL_RETRY = {
  retry: (failureCount: number, error: unknown) =>
    failureCount < 2 && !(error instanceof ApiError && error.status === 404),
  retryDelay: 1000,
};

/**
 * GET /api/boards/live every second. With POLL_RETRY, isError means three
 * failures in a row: that is when the Home shows its offline banner.
 */
export function useBoardsLive() {
  return useQuery({
    queryKey: ['boards', 'live'],
    queryFn: async () => unwrap(await api.GET('/api/boards/live')),
    refetchInterval: LIVE_INTERVAL_MS,
    refetchIntervalInBackground: false,
    ...POLL_RETRY,
  });
}

/** GET /api/plugins every 5 s, with the list's filters. */
export function usePlugins(filters: PluginFilters = {}) {
  return useQuery({
    queryKey: ['plugins', filters],
    queryFn: async () => unwrap(await api.GET('/api/plugins', { params: { query: filters } })),
    refetchInterval: PLUGINS_INTERVAL_MS,
    refetchIntervalInBackground: false,
    ...POLL_RETRY,
  });
}

/** The pass in progress of each board (GET /api/boards/<device_id>/track), every 5 s. */
export function useTracks(deviceIds: string[]) {
  return useQueries({
    queries: deviceIds.map((device_id) => ({
      queryKey: ['boards', device_id, 'track'],
      queryFn: async () =>
        unwrap(await api.GET('/api/boards/{device_id}/track', { params: { path: { device_id } } })),
      refetchInterval: TRACK_INTERVAL_MS,
      refetchIntervalInBackground: false,
      ...POLL_RETRY,
    })),
  });
}

// --- Instances, boards and logs (Task 16) ------------------------------------

export type PluginAction = 'launch' | 'stop' | 'sync';

export interface PluginInput {
  name: string;
  /** The enum the schema declares: PluginSerializer.plugin_type is a ChoiceField (Task 6). */
  plugin_type: Plugin['plugin_type'];
  config: Record<string, unknown>;
}

const pluginPath = (uuid: string) => ({ params: { path: { plugin_uuid: uuid } } });

export function usePluginTypes() {
  return useQuery({
    queryKey: ['plugin-types'],
    queryFn: async () => unwrap(await api.GET('/api/plugin-types')),
    staleTime: Infinity,
  });
}

export function usePlugin(uuid: string) {
  return useQuery({
    queryKey: ['plugins', 'detail', uuid],
    queryFn: async () => unwrap(await api.GET('/api/plugins/{plugin_uuid}', pluginPath(uuid))),
    refetchInterval: PLUGINS_INTERVAL_MS,
    refetchIntervalInBackground: false,
    ...POLL_RETRY,
  });
}

/** After any change to an instance: its lists, its detail and the boards that show it. */
function useRefreshPlugins() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['plugins'] }),
      queryClient.invalidateQueries({ queryKey: ['boards'] }),
    ]);
}

export function useCreatePlugin() {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async (body: PluginInput) => unwrap(await api.POST('/api/plugins', { body })),
    onSuccess: refresh,
  });
}

export function useUpdatePlugin(uuid: string) {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async (body: Pick<PluginInput, 'name' | 'config'>) =>
      unwrap(await api.PATCH('/api/plugins/{plugin_uuid}', { ...pluginPath(uuid), body })),
    onSuccess: refresh,
  });
}

export function usePluginAction() {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async ({ uuid, action }: { uuid: string; action: PluginAction }) => {
      if (action === 'launch') return unwrap(await api.POST('/api/plugins/{plugin_uuid}/launch', pluginPath(uuid)));
      if (action === 'stop') return unwrap(await api.POST('/api/plugins/{plugin_uuid}/stop', pluginPath(uuid)));
      return unwrap(await api.POST('/api/plugins/{plugin_uuid}/sync', pluginPath(uuid)));
    },
    // A failed launch leaves the instance in ERROR, so refresh either way.
    onSettled: refresh,
  });
}

export function useDeletePlugin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (uuid: string) => unwrap(await api.DELETE('/api/plugins/{plugin_uuid}', pluginPath(uuid))),
    onSuccess: () =>
      Promise.all([
        // Not the detail: the instance is gone, and it would answer 404 before the page leaves.
        queryClient.invalidateQueries({ predicate: ({ queryKey }) => queryKey[0] === 'plugins' && queryKey[1] !== 'detail' }),
        queryClient.invalidateQueries({ queryKey: ['boards'] }),
      ]),
  });
}

export function useSetPluginBoard(uuid: string) {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async (deviceId: string | null) =>
      deviceId
        ? unwrap(await api.PUT('/api/plugins/{plugin_uuid}/board', { ...pluginPath(uuid), body: { device_id: deviceId } }))
        : unwrap(await api.DELETE('/api/plugins/{plugin_uuid}/board', pluginPath(uuid))),
    onSuccess: refresh,
  });
}

export function useUploadCoordinates(uuid: string) {
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append('file', file);
      return unwrap(
        await api.POST('/api/plugins/{plugin_uuid}/coordinates-file', {
          ...pluginPath(uuid),
          // openapi-typescript types a binary field as a string; what goes on
          // the wire is the FormData, and the browser sets its multipart boundary.
          body: form as never,
          bodySerializer: (body) => body,
        }),
      );
    },
  });
}

export function useBoards() {
  return useQuery({
    queryKey: ['boards', 'list'],
    queryFn: async () => unwrap(await api.GET('/api/boards')),
  });
}

export function useScanBoards() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/boards/scan')),
    onSuccess: (boards) => queryClient.setQueryData(['boards', 'list'], boards),
  });
}

export type LogService = 'server' | 'coord_transform';
export type LogSource = { kind: 'plugin'; uuid: string } | { kind: 'service'; service: LogService };

export const LOGS_REFRESH_MS = 3000;
export const LOGS_DEFAULT_TAIL = 100;
export const LOGS_MAX_TAIL = 1000;

export function useLogs(source: LogSource, tail: number, autoRefresh: boolean) {
  return useQuery({
    queryKey: ['logs', source, tail],
    queryFn: async () =>
      source.kind === 'plugin'
        ? unwrap(await api.GET('/api/plugins/{plugin_uuid}/logs', { params: { path: { plugin_uuid: source.uuid }, query: { tail } } }))
        : unwrap(await api.GET('/api/logs/{service}', { params: { path: { service: source.service }, query: { tail } } })),
    refetchInterval: autoRefresh ? LOGS_REFRESH_MS : false,
    refetchIntervalInBackground: false,
    // A 404 (no container) is shown at once; anything else is retried like every poll.
    ...POLL_RETRY,
  });
}

// --- Boards (Task 17) ----------------------------------------------------------

export function useBoard(deviceId: string) {
  return useQuery({
    queryKey: ['boards', 'detail', deviceId],
    queryFn: async () => unwrap(await api.GET('/api/boards/{device_id}', { params: { path: { device_id: deviceId } } })),
  });
}

export function useUpdateBoard(deviceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: BoardSettings) =>
      unwrap(await api.PATCH('/api/boards/{device_id}', { params: { path: { device_id: deviceId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boards'] }),
  });
}

// --- History and results (Task 18) -------------------------------------------

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

/** Thrown only if a query that needs both ends runs without them; enabled already prevents it. */
const NO_RANGE = 'A range needs both ends.';

/**
 * The chart: the server keeps the last state of each interval and sends at
 * most max_points (2000 by default).
 */
export function useStateSeries(deviceId: string, range: RangeQuery) {
  return useQuery({
    queryKey: ['history', 'series', deviceId, range],
    queryFn: async () => {
      // The guard narrows from and to, which the schema marks as required here.
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

// --- Account (Task 19) -----------------------------------------------------------

export function useChangePassword() {
  return useMutation({
    mutationFn: async (body: { current_password: string; new_password: string }) =>
      unwrap(await api.POST('/api/auth/password', { body })),
    // The server ended every session, this one included, and sent a new pair for it.
    onSuccess: (tokens) => setTokens(tokens),
  });
}
