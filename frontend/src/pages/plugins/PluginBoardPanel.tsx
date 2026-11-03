import { Alert, Button, Group, NativeSelect, Paper, Stack } from '@mantine/core';
import { errorMessage, isStatus } from '../../api/errors';
import { useBoards, useScanBoards, useSetPluginBoard } from '../../api/queries';
import type { Board, Plugin } from '../../api/types';
import { notifySuccess } from '../../lib/notify';
import { scanErrorMessage, scanSummary } from '../../lib/scan';

/** The 409 of PUT .../board in words, naming the instance in the way when there is one. */
function bindErrorMessage(
  error: unknown,
  plugin: Plugin,
  boards: readonly Board[] | undefined,
  deviceId: string | null | undefined,
): string {
  if (!isStatus(error, 409)) return errorMessage(error);
  if (plugin.status === 'RUNNING') return 'La instancia está en ejecución: detenela para cambiarle la placa.';
  const driver = boards
    ?.find((board) => board.device_id === deviceId)
    ?.plugins.find((other) => other.status === 'RUNNING' && other.plugin_uuid !== plugin.plugin_uuid);
  return driver
    ? `Esa placa ya la maneja ${driver.name}, que está en ejecución (RF-31.1). Detenela antes de vincular esta instancia.`
    : errorMessage(error);
}

export function PluginBoardPanel({ plugin }: { plugin: Plugin }) {
  const boards = useBoards();
  const scan = useScanBoards();
  const bind = useSetPluginBoard(plugin.plugin_uuid);

  const options = [
    { value: '', label: 'Sin placa' },
    ...(boards.data ?? []).map((board) => ({
      value: board.device_id,
      label: `${board.name || board.device_id} · ${board.online ? 'online' : 'offline'}`,
    })),
  ];

  function choose(deviceId: string) {
    bind.mutate(deviceId || null, {
      onSuccess: () => notifySuccess(deviceId ? 'Placa vinculada.' : 'Placa desvinculada.'),
    });
  }

  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        <Group align="end">
          <NativeSelect
            label="Placa"
            style={{ flex: 1 }}
            value={plugin.board ?? ''}
            data={options}
            onChange={(event) => choose(event.currentTarget.value)}
            disabled={bind.isPending}
            description={
              plugin.status === 'RUNNING'
                ? 'Con la instancia en ejecución la placa no se puede cambiar.'
                : 'La placa le llega a la instancia cuando se lanza.'
            }
          />
          <Button
            variant="default"
            loading={scan.isPending}
            onClick={() => scan.mutate(undefined, { onSuccess: (found) => notifySuccess(scanSummary(found.length)) })}
          >
            Buscar placas
          </Button>
        </Group>
        {scan.isError && <Alert color="red">{scanErrorMessage(scan.error)}</Alert>}
        {bind.isError && (
          <Alert color="red" title="No se pudo cambiar la placa">
            {bindErrorMessage(bind.error, plugin, boards.data, bind.variables)}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
