import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '../../shared/api/client';
import { POLL_RETRY } from '../../shared/api/queries';

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
