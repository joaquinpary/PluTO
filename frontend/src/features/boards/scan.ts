import { errorMessage, isStatus } from '../../shared/api/errors';

/** POST /api/boards/scan answers 503 when the broker does not. */
export function scanErrorMessage(error: unknown): string {
  return isStatus(error, 503) ? 'No se pudo consultar el broker.' : errorMessage(error);
}

export function scanSummary(count: number): string {
  return count === 1 ? 'Búsqueda terminada: 1 placa.' : `Búsqueda terminada: ${count} placas.`;
}
