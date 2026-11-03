import { Alert, Badge, Group, Loader, Stack, Tabs, Text, Title } from '@mantine/core';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { isStatus } from '../../api/errors';
import { usePlugin, usePluginTypes } from '../../api/queries';
import { ApiErrorAlert } from '../../components/ApiErrorAlert';
import { LogPanel } from '../../components/LogPanel';
import { PluginStatusBadge } from '../../components/PluginStatusBadge';
import { CoordinatesFilePanel } from './CoordinatesFilePanel';
import { PluginActions } from './PluginActions';
import { PluginBoardPanel } from './PluginBoardPanel';
import { PluginConfigPanel } from './PluginConfigPanel';

export function PluginDetailPage() {
  const { uuid = '' } = useParams();
  const plugin = usePlugin(uuid);
  const types = usePluginTypes();
  // Set when the config of a running instance is saved; a launch or a stop clears it.
  const [relaunchNeeded, setRelaunchNeeded] = useState(false);

  if (plugin.isPending) return <Loader />;
  if (plugin.isError) {
    return isStatus(plugin.error, 404) ? (
      <Alert color="yellow">No existe esa instancia.</Alert>
    ) : (
      <ApiErrorAlert error={plugin.error} title="No se pudo cargar la instancia" />
    );
  }

  const data = plugin.data;
  const pluginType = types.data?.find((candidate) => candidate.type === data.plugin_type);
  const isFileTracker = data.plugin_type === 'file_tracker';

  return (
    <Stack>
      <Group justify="space-between" align="start">
        <div>
          <Title order={2}>{data.name}</Title>
          <Text c="dimmed" size="sm">
            Tipo: {pluginType?.label ?? data.plugin_type}. El tipo no se cambia después del alta.
          </Text>
        </div>
        <Group gap="xs">
          <PluginStatusBadge status={data.status} />
          <Badge variant="outline" color="gray">
            Docker: {data.docker_status}
          </Badge>
        </Group>
      </Group>

      <PluginActions plugin={data} onLifecycle={() => setRelaunchNeeded(false)} />

      {relaunchNeeded && data.status === 'RUNNING' && (
        <Alert color="yellow" title="Relanzá para aplicar los cambios">
          La instancia sigue corriendo con la configuración anterior: detenela y volvé a lanzarla.
        </Alert>
      )}
      {data.warnings.map((warning) => (
        <Alert key={warning} color="yellow">
          {warning}
        </Alert>
      ))}

      <Tabs defaultValue="config" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="config">Configuración</Tabs.Tab>
          {isFileTracker && <Tabs.Tab value="file">Archivo de coordenadas</Tabs.Tab>}
          <Tabs.Tab value="logs">Logs</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="config" pt="md">
          <Stack>
            <PluginBoardPanel plugin={data} />
            {pluginType ? (
              <PluginConfigPanel
                key={data.plugin_uuid}
                plugin={data}
                fields={pluginType.config_fields}
                onSaved={() => setRelaunchNeeded(data.status === 'RUNNING')}
              />
            ) : (
              <ApiErrorAlert error={types.error} title="No se pudieron cargar los campos del tipo" />
            )}
          </Stack>
        </Tabs.Panel>
        {isFileTracker && (
          <Tabs.Panel value="file" pt="md">
            <CoordinatesFilePanel uuid={data.plugin_uuid} />
          </Tabs.Panel>
        )}
        <Tabs.Panel value="logs" pt="md">
          <LogPanel source={{ kind: 'plugin', uuid: data.plugin_uuid }} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
