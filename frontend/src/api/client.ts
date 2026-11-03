import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './schema';
import { getAccess, refreshOnce } from './tokens';

// A copy of each request as it was sent, to repeat it after a refresh:
// fetch() consumes the body of the original.
const copies = new WeakMap<Request, Request>();

const auth: Middleware = {
  onRequest({ request, schemaPath }) {
    // Log in, refresh and log out need no access token, and their 401 means bad credentials.
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
    return fetch(copy); // Once: if this one is also refused, the caller gets that answer.
  },
};

export const api = createClient<paths>({
  // Absolute, because Node's fetch (the tests) does not resolve relative URLs.
  baseUrl: window.location.origin,
  // Looked up on every call instead of captured now, so the tests' MSW sees it.
  fetch: (request) => globalThis.fetch(request),
});
api.use(auth);

/** A non-2xx answer: status and the parsed body, e.g. {"detail": "..."} or {"field": ["..."]}. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

/** The data of an openapi-fetch result, or an ApiError: what a queryFn returns. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) throw new ApiError(result.response.status, result.error);
  return result.data as T;
}

/** DRF's validation errors ({"field": ["msg", ...]}) as one message per field, plus detail. */
export function fieldErrors(body: unknown): Record<string, string> {
  if (typeof body !== 'object' || body === null) return {};
  const errors: Record<string, string> = {};
  for (const [field, value] of Object.entries(body)) {
    errors[field] = Array.isArray(value) ? String(value[0]) : String(value);
  }
  return errors;
}
