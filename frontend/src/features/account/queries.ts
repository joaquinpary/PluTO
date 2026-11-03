import { useMutation } from '@tanstack/react-query';
import { api, unwrap } from '../../shared/api/client';
import { setTokens } from '../../shared/api/tokens';

export function useChangePassword() {
  return useMutation({
    mutationFn: async (body: { current_password: string; new_password: string }) =>
      unwrap(await api.POST('/api/auth/password', { body })),
    // The server ended every session, this one included, and sent a new pair for it.
    onSuccess: (tokens) => setTokens(tokens),
  });
}
