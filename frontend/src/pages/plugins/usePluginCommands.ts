import { notifications } from '@mantine/notifications';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import { errorMessage, isStatus, splitErrors } from '../../api/errors';
import { usePluginAction, type PluginAction } from '../../api/queries';
import type { Board, Plugin } from '../../api/types';
import { statusLabel } from '../../components/PluginStatusBadge';
import { notifySuccess } from '../../lib/notify';

type Target = Pick<Plugin, 'plugin_uuid' | 'name' | 'status' | 'board'>;

const FAILED: Record<PluginAction, string> = {
  launch: 'No se pudo lanzar',
  stop: 'No se pudo detener',
  sync: 'No se pudo sincronizar',
};

/**
 * Launch answers 409 when the instance already runs or another running
 * instance drives its board (RF-31.1, Task 7), in English. The 409 is said in
 * Spanish, naming that other instance when the pages already know it.
 *
 * A launch that got no answer from Django (nginx gave up after 600 s, or the
 * connection dropped) may still have worked: the container could be up, and
 * Sync tells. A 502 that does carry a detail is Docker failing (Task 7).
 */
export function launchErrorMessage(error: unknown, driver?: string): string {
  if (isStatus(error, 409)) {
    return driver
      ? `Su placa ya la maneja ${driver}, que está en ejecución (RF-31.1). Detenela antes de lanzar esta.`
      : 'Ya está en ejecución, u otra instancia en ejecución maneja su placa (RF-31.1). Tocá «Sincronizar» para ver el estado real.';
  }
  const unanswered =
    !(error instanceof ApiError) || (error.status >= 502 && splitErrors(error.body).general.length === 0);
  return unanswered
    ? 'Se cortó la espera del lanzamiento. Tocá «Sincronizar» para ver el estado real.'
    : errorMessage(error);
}

/**
 * The other running instance on the same board, from what the pages already
 * loaded (an instance list or the board list): no extra request.
 */
function boardDriver(queryClient: QueryClient, plugin: Target): string | undefined {
  if (!plugin.board) return undefined;
  const isDriver = (other: { plugin_uuid: string; status?: string }) =>
    other.status === 'RUNNING' && other.plugin_uuid !== plugin.plugin_uuid;
  for (const [, data] of queryClient.getQueriesData<Plugin[] | Plugin>({ queryKey: ['plugins'] })) {
    // ['plugins', 'detail', uuid] holds a single instance, not a list.
    if (!Array.isArray(data)) continue;
    const driver = data.find((other) => other.board === plugin.board && isDriver(other));
    if (driver) return driver.name;
  }
  const boards = queryClient.getQueryData<Board[]>(['boards', 'list']);
  return boards?.find((board) => board.device_id === plugin.board)?.plugins.find(isDriver)?.name;
}

/** Launch, stop and sync with their notices; the list and the detail use them. */
export function usePluginCommands() {
  const mutation = usePluginAction();
  const queryClient = useQueryClient();

  function run(plugin: Target, action: PluginAction, onSuccess?: () => void) {
    const launchNotice = `launch-${plugin.plugin_uuid}`;
    if (action === 'launch') {
      notifications.show({
        id: launchNotice,
        loading: true,
        autoClose: false,
        withCloseButton: false,
        title: `Lanzando ${plugin.name}`,
        message: 'La primera vez se construye la imagen y puede tardar unos minutos.',
      });
    }
    mutation.mutate(
      { uuid: plugin.plugin_uuid, action },
      {
        onSuccess: (updated) => {
          if (action === 'launch') notifySuccess(`${plugin.name} está en ejecución.`);
          if (action === 'stop') notifySuccess(`${plugin.name} se detuvo.`);
          if (action === 'sync') notifySuccess(`${plugin.name}: ${statusLabel(updated.status)}, según Docker.`);
          onSuccess?.();
        },
        onError: (error) =>
          notifications.show({
            color: 'red',
            title: `${FAILED[action]} ${plugin.name}`,
            message: action === 'launch' ? launchErrorMessage(error, boardDriver(queryClient, plugin)) : errorMessage(error),
          }),
        onSettled: () => notifications.hide(launchNotice),
      },
    );
  }

  return {
    run,
    busy: mutation.isPending,
    pending: mutation.isPending ? mutation.variables?.action : undefined,
  };
}
