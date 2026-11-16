import { useQuery } from '@tanstack/react-query';
import { api, ApiError, unwrap } from './client';

/** Whether the only user still has to be created. */
export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup'],
    queryFn: async () => unwrap(await api.GET('/api/setup')),
    staleTime: Infinity,
  });
}

// Two retries a second apart before erroring; data keeps the last good answer.
// A 404 is an answer (no instance, no container), not a failure.
export const POLL_RETRY = {
  retry: (failureCount: number, error: unknown) =>
    failureCount < 2 && !(error instanceof ApiError && error.status === 404),
  retryDelay: 1000,
};
