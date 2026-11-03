import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, unwrap } from '../../shared/api/client';
import { POLL_RETRY } from '../../shared/api/queries';
import type { Plugin, PluginFilters } from '../../shared/api/types';

// Not while the tab is hidden.
export const PLUGINS_INTERVAL_MS = 5000;

/** GET /api/plugins every 5 s, with the list's filters. */
export function usePlugins(filters: PluginFilters = {}) {
  return useQuery({
    queryKey: ['plugins', filters],
    queryFn: async () => unwrap(await api.GET('/api/plugins', { params: { query: filters } })),
    refetchInterval: PLUGINS_INTERVAL_MS,
    refetchIntervalInBackground: false,
    ...POLL_RETRY,
  });
}

export type PluginAction = 'launch' | 'stop' | 'sync';

export interface PluginInput {
  name: string;
  /** The enum the schema declares: PluginSerializer.plugin_type is a ChoiceField. */
  plugin_type: Plugin['plugin_type'];
  config: Record<string, unknown>;
}

const pluginPath = (uuid: string) => ({ params: { path: { plugin_uuid: uuid } } });

export function usePluginTypes() {
  return useQuery({
    queryKey: ['plugin-types'],
    queryFn: async () => unwrap(await api.GET('/api/plugin-types')),
    staleTime: Infinity,
  });
}

export function usePlugin(uuid: string) {
  return useQuery({
    queryKey: ['plugins', 'detail', uuid],
    queryFn: async () => unwrap(await api.GET('/api/plugins/{plugin_uuid}', pluginPath(uuid))),
    refetchInterval: PLUGINS_INTERVAL_MS,
    refetchIntervalInBackground: false,
    ...POLL_RETRY,
  });
}

/** After any change to an instance: its lists, its detail and the boards that show it. */
function useRefreshPlugins() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['plugins'] }),
      queryClient.invalidateQueries({ queryKey: ['boards'] }),
    ]);
}

export function useCreatePlugin() {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async (body: PluginInput) => unwrap(await api.POST('/api/plugins', { body })),
    onSuccess: refresh,
  });
}

export function useUpdatePlugin(uuid: string) {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async (body: Pick<PluginInput, 'name' | 'config'>) =>
      unwrap(await api.PATCH('/api/plugins/{plugin_uuid}', { ...pluginPath(uuid), body })),
    onSuccess: refresh,
  });
}

export function usePluginAction() {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async ({ uuid, action }: { uuid: string; action: PluginAction }) => {
      if (action === 'launch') return unwrap(await api.POST('/api/plugins/{plugin_uuid}/launch', pluginPath(uuid)));
      if (action === 'stop') return unwrap(await api.POST('/api/plugins/{plugin_uuid}/stop', pluginPath(uuid)));
      return unwrap(await api.POST('/api/plugins/{plugin_uuid}/sync', pluginPath(uuid)));
    },
    // A failed launch leaves the instance in ERROR, so refresh either way.
    onSettled: refresh,
  });
}

export function useDeletePlugin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (uuid: string) => unwrap(await api.DELETE('/api/plugins/{plugin_uuid}', pluginPath(uuid))),
    onSuccess: () =>
      Promise.all([
        // Not the detail: the instance is gone, and it would answer 404 before the page leaves.
        queryClient.invalidateQueries({ predicate: ({ queryKey }) => queryKey[0] === 'plugins' && queryKey[1] !== 'detail' }),
        queryClient.invalidateQueries({ queryKey: ['boards'] }),
      ]),
  });
}

export function useSetPluginBoard(uuid: string) {
  const refresh = useRefreshPlugins();
  return useMutation({
    mutationFn: async (deviceId: string | null) =>
      deviceId
        ? unwrap(await api.PUT('/api/plugins/{plugin_uuid}/board', { ...pluginPath(uuid), body: { device_id: deviceId } }))
        : unwrap(await api.DELETE('/api/plugins/{plugin_uuid}/board', pluginPath(uuid))),
    onSuccess: refresh,
  });
}

export function useUploadCoordinates(uuid: string) {
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append('file', file);
      return unwrap(
        await api.POST('/api/plugins/{plugin_uuid}/coordinates-file', {
          ...pluginPath(uuid),
          // openapi-typescript types a binary field as a string; what goes on
          // the wire is the FormData, and the browser sets its multipart boundary.
          body: form as never,
          bodySerializer: (body) => body,
        }),
      );
    },
  });
}
