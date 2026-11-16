import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './schema';
import { getAccess, refreshOnce } from './tokens';

// fetch() consumes the body, so keep a copy to retry after a refresh.
const copies = new WeakMap<Request, Request>();

const auth: Middleware = {
  onRequest({ request, schemaPath }) {
    // Their 401 means bad credentials, not an expired token.
    if (schemaPath.startsWith('/api/auth/token')) return undefined;
    const token = getAccess();
    if (token !== null) request.headers.set('Authorization', `Bearer ${token}`);
    copies.set(request, request.clone());
    return request;
  },

  async onResponse({ request, response }) {
    const copy = copies.get(request);
    if (response.status !== 401 || copy === undefined) return response;

    // Another request may have refreshed while this one was on the wire.
    const current = getAccess();
    const alreadyRenewed = current !== null && request.headers.get('Authorization') !== `Bearer ${current}`;
    if (!alreadyRenewed && !(await refreshOnce())) return response;

    copy.headers.set('Authorization', `Bearer ${getAccess()}`);
    return fetch(copy); // once; a second 401 goes to the caller
  },
};

export const api = createClient<paths>({
  // Absolute: Node's fetch (tests) doesn't resolve relative URLs.
  baseUrl: window.location.origin,
  // Read per call so MSW can patch it in tests.
  fetch: (request) => globalThis.fetch(request),
});
api.use(auth);

/** Non-2xx answer with its parsed body. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

/** For queryFns: the data, or throws ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) throw new ApiError(result.response.status, result.error);
  return result.data as T;
}

/** DRF {"field": ["msg", ...]} to one message per field. */
export function fieldErrors(body: unknown): Record<string, string> {
  if (typeof body !== 'object' || body === null) return {};
  const errors: Record<string, string> = {};
  for (const [field, value] of Object.entries(body)) {
    errors[field] = Array.isArray(value) ? String(value[0]) : String(value);
  }
  return errors;
}
