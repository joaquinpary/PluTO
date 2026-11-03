import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, unwrap } from '../../shared/api/client';
import { POLL_RETRY } from '../../shared/api/queries';
import type { BoardSettings } from './boardForm';

// Polling periods. Neither runs while the tab is hidden.
export const LIVE_INTERVAL_MS = 1000;
export const TRACK_INTERVAL_MS = 5000;

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
