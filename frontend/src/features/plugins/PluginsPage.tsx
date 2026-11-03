import { Anchor, Button, Group, NativeSelect, Stack, Table, TextInput, Title } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { usePluginTypes, usePlugins } from './queries';
import type { Plugin } from '../../shared/api/types';
import { ApiErrorAlert } from '../../shared/components/ApiErrorAlert';
import { EmptyState } from '../../shared/components/EmptyState';
import { PLUGIN_STATUS_OPTIONS, PluginStatusBadge, parseStatus } from './PluginStatusBadge';
import { formatDateTime } from '../../shared/lib/format';
import { usePluginCommands } from './usePluginCommands';

function QuickActions({ plugin }: { plugin: Plugin }) {
  const commands = usePluginCommands();
  return (
    <Group gap="xs" wrap="nowrap">
      <Button
        size="xs"
        onClick={() => commands.run(plugin, 'launch')}
        loading={commands.pending === 'launch'}
        disabled={plugin.status === 'RUNNING' || commands.busy}
      >
        Lanzar
      </Button>
      <Button
        size="xs"
        variant="light"
        color="orange"
        onClick={() => commands.run(plugin, 'stop')}
        loading={commands.pending === 'stop'}
        disabled={plugin.status === 'STOPPED' || commands.busy}
      >
        Detener
      </Button>
    </Group>
  );
}

export function PluginsPage() {
  const types = usePluginTypes();
  const [type, setType] = useState('');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search.trim(), 300);
  const plugins = usePlugins({
    type: type || undefined,
    status: parseStatus(status),
    search: debouncedSearch || undefined,
  });
  const typeLabels = new Map((types.data ?? []).map((candidate) => [candidate.type, candidate.label]));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Instancias</Title>
        <Button component={Link} to="/plugins/new">
          Nueva instancia
        </Button>
      </Group>

      <Group align="end">
        <TextInput label="Buscar" placeholder="Nombre" value={search} onChange={(event) => setSearch(event.currentTarget.value)} />
        <NativeSelect
          label="Tipo"
          value={type}
          onChange={(event) => setType(event.currentTarget.value)}
          data={[{ value: '', label: 'Todos' }, ...(types.data ?? []).map((candidate) => ({ value: candidate.type, label: candidate.label }))]}
        />
        <NativeSelect
          label="Estado"
          value={status}
          onChange={(event) => setStatus(event.currentTarget.value)}
          data={[{ value: '', label: 'Todos' }, ...PLUGIN_STATUS_OPTIONS]}
        />
      </Group>

      <ApiErrorAlert error={plugins.error} title="No se pudieron cargar las instancias" />
      {plugins.data?.length === 0 && <EmptyState icon="cpu">No hay instancias con esos filtros.</EmptyState>}
      {plugins.data && plugins.data.length > 0 && (
        <Table.ScrollContainer minWidth={760}>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Nombre</Table.Th>
                <Table.Th>Tipo</Table.Th>
                <Table.Th>Estado</Table.Th>
                <Table.Th>Docker</Table.Th>
                <Table.Th>Placa</Table.Th>
                <Table.Th>Actualizada</Table.Th>
                <Table.Th>Acciones</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {plugins.data.map((plugin) => (
                <Table.Tr key={plugin.plugin_uuid}>
                  <Table.Td>
                    <Anchor component={Link} to={`/plugins/${plugin.plugin_uuid}`}>
                      {plugin.name}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>{typeLabels.get(plugin.plugin_type) ?? plugin.plugin_type}</Table.Td>
                  <Table.Td>
                    <PluginStatusBadge status={plugin.status} />
                  </Table.Td>
                  <Table.Td>{plugin.docker_status}</Table.Td>
                  <Table.Td>{plugin.board ?? '—'}</Table.Td>
                  <Table.Td>{formatDateTime(plugin.updated_at)}</Table.Td>
                  <Table.Td>
                    <QuickActions plugin={plugin} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}
