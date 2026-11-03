import { Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { isStatus } from '../../shared/api/errors';
import { useDeletePlugin } from './queries';
import type { Plugin } from '../../shared/api/types';
import { ApiErrorAlert } from '../../shared/components/ApiErrorAlert';
import { notifySuccess } from '../../shared/lib/notify';
import { usePluginCommands } from './usePluginCommands';

interface Props {
  plugin: Plugin;
  /** Called after a launch or a stop, the two actions that apply a saved config. */
  onLifecycle: () => void;
}

export function PluginActions({ plugin, onLifecycle }: Props) {
  const navigate = useNavigate();
  const commands = usePluginCommands();
  const remove = useDeletePlugin();
  const [confirming, setConfirming] = useState(false);
  const hasData = isStatus(remove.error, 409);

  function openConfirm() {
    remove.reset();
    setConfirming(true);
  }

  function confirmDelete() {
    remove.mutate(plugin.plugin_uuid, {
      onSuccess: () => {
        notifySuccess(`Se borró ${plugin.name}.`);
        navigate('/plugins');
      },
    });
  }

  function stopInstead() {
    setConfirming(false);
    commands.run(plugin, 'stop', onLifecycle);
  }

  return (
    <>
      <Group gap="xs">
        <Button
          onClick={() => commands.run(plugin, 'launch', onLifecycle)}
          loading={commands.pending === 'launch'}
          disabled={plugin.status === 'RUNNING' || commands.busy}
        >
          Lanzar
        </Button>
        <Button
          variant="light"
          color="orange"
          onClick={() => commands.run(plugin, 'stop', onLifecycle)}
          loading={commands.pending === 'stop'}
          disabled={plugin.status === 'STOPPED' || commands.busy}
        >
          Detener
        </Button>
        <Button
          variant="default"
          onClick={() => commands.run(plugin, 'sync')}
          loading={commands.pending === 'sync'}
          disabled={commands.busy}
        >
          Sincronizar
        </Button>
        <Button variant="subtle" color="red" onClick={openConfirm} disabled={commands.busy}>
          Borrar
        </Button>
      </Group>

      <Modal opened={confirming} onClose={() => setConfirming(false)} title={`Borrar ${plugin.name}`}>
        {hasData ? (
          <Stack>
            <Text>
              No se puede borrar: la instancia ya guardó datos (datos de plugins u órdenes enviadas a una placa), y el
              historial tiene que seguir apuntando a ella.
            </Text>
            {plugin.status === 'STOPPED' ? (
              <Text>Ya está detenida, así que no hace falta nada más.</Text>
            ) : (
              <Button onClick={stopInstead} w="fit-content">
                Detenerla en su lugar
              </Button>
            )}
          </Stack>
        ) : (
          <Stack>
            <Text>Si está en ejecución se detiene, y después se borra. No se puede deshacer.</Text>
            <ApiErrorAlert error={remove.error} title="No se pudo borrar" />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setConfirming(false)}>
                Cancelar
              </Button>
              <Button color="red" loading={remove.isPending} onClick={confirmDelete}>
                Borrar
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
