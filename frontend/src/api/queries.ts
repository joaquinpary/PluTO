import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from './client';

/** GET /api/setup: whether the only user still has to be created (spec 3.4). */
export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup'],
    queryFn: async () => unwrap(await api.GET('/api/setup')),
    staleTime: Infinity,
  });
}
