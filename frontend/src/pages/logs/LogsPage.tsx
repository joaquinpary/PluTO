import { NativeSelect, Stack, Title } from '@mantine/core';
import { useState } from 'react';
import { usePlugins, type LogService, type LogSource } from '../../api/queries';
import { LogPanel } from '../../components/LogPanel';

const SERVICES: { value: LogService; label: string }[] = [
  { value: 'server', label: 'server (Django)' },
  { value: 'coord_transform', label: 'coord_transform' },
];

/** The select's value is "service:<name>" or "plugin:<uuid>". */
export function parseSource(value: string): LogSource {
  const [kind, id = ''] = value.split(':');
  if (kind === 'plugin') return { kind: 'plugin', uuid: id };
  return { kind: 'service', service: SERVICES.find((service) => service.value === id)?.value ?? 'server' };
}

export function LogsPage() {
  const plugins = usePlugins();
  const [value, setValue] = useState('service:server');

  return (
    <Stack>
      <Title order={2}>Logs</Title>
      <NativeSelect
        label="Fuente"
        maw={360}
        value={value}
        onChange={(event) => setValue(event.currentTarget.value)}
        data={[
          { group: 'Servicios', items: SERVICES.map((service) => ({ value: `service:${service.value}`, label: service.label })) },
          {
            group: 'Instancias',
            items: (plugins.data ?? []).map((plugin) => ({ value: `plugin:${plugin.plugin_uuid}`, label: plugin.name })),
          },
        ]}
      />
      <LogPanel source={parseSource(value)} />
    </Stack>
  );
}
