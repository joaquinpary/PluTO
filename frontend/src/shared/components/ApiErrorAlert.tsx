import { Alert } from '@mantine/core';
import { errorMessage } from '../api/errors';

/** The error of a query or a mutation, or nothing when there is none. */
export function ApiErrorAlert({ error, title = 'No se pudo completar la acción' }: { error: unknown; title?: string }) {
  if (!error) return null;
  return (
    <Alert color="red" title={title}>
      {errorMessage(error)}
    </Alert>
  );
}
