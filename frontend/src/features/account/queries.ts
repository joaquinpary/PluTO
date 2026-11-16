import { useMutation } from '@tanstack/react-query';
import { api, unwrap } from '../../shared/api/client';
import { setTokens } from '../../shared/api/tokens';

export function useChangePassword() {
  return useMutation({
    mutationFn: async (body: { current_password: string; new_password: string }) =>
      unwrap(await api.POST('/api/auth/password', { body })),
    // Every session ended; the server sent a new pair for this one.
    onSuccess: (tokens) => setTokens(tokens),
  });
}
