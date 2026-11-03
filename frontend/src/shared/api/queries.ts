import { useQuery } from '@tanstack/react-query';
import { api, ApiError, unwrap } from './client';

/** GET /api/setup: whether the only user still has to be created. */
export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup'],
    queryFn: async () => unwrap(await api.GET('/api/setup')),
    staleTime: Infinity,
  });
}

/**
 * How every polled query rides out a failure: two retries a second
 * apart before it turns to error, with data keeping the last good answer
 * meanwhile. A 404 is an answer (no such instance, no container), not a
 * failure, so it is not retried.
 */
export const POLL_RETRY = {
  retry: (failureCount: number, error: unknown) =>
    failureCount < 2 && !(error instanceof ApiError && error.status === 404),
  retryDelay: 1000,
};
