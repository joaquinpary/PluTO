import type { paths } from './schema';

/** The JSON body of the 200 answer to GET path, as the OpenAPI schema describes it. */
type Ok<P extends keyof paths> = paths[P] extends {
  get: { responses: { 200: { content: { 'application/json': infer T } } } };
}
  ? T
  : never;

export type BoardLive = Ok<'/api/boards/live'>[number];
export type LiveState = NonNullable<BoardLive['state']>;
export type Plugin = Ok<'/api/plugins'>[number];
export type PluginFilters = NonNullable<paths['/api/plugins']['get']['parameters']['query']>;
export type Track = Ok<'/api/boards/{device_id}/track'>;
