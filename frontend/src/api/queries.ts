import { useQueries, useQuery } from '@tanstack/react-query';
import { api, ApiError, unwrap } from './client';
import type { PluginFilters } from './types';

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
