import { Alert, Anchor, Badge, Button, Code, Group, Stack, Table, Text, Title } from '@mantine/core';
import { Link } from 'react-router-dom';
import { useBoards, useScanBoards } from '../../api/queries';
import { ApiErrorAlert } from '../../components/ApiErrorAlert';
import { formatDateTime } from '../../lib/format';
import { notifySuccess } from '../../lib/notify';
import { scanErrorMessage, scanSummary } from '../../lib/scan';

// status is optional in the generated BoardPlugin (COMPONENT_SPLIT_REQUEST), though the server always sends it.
function linkedPlugins(plugins: readonly { name: string; status?: string }[]): string {
  if (plugins.length === 0) return '—';
  return plugins.map((plugin) => (plugin.status === 'RUNNING' ? `${plugin.name} (en ejecución)` : plugin.name)).join(', ');
}

export function BoardsPage() {
  const boards = useBoards();
  const scan = useScanBoards();

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Placas</Title>
        <Button
          loading={scan.isPending}
          onClick={() => scan.mutate(undefined, { onSuccess: (found) => notifySuccess(scanSummary(found.length)) })}
        >
          Buscar placas
        </Button>
      </Group>
      {scan.isError && <Alert color="red">{scanErrorMessage(scan.error)}</Alert>}
      <ApiErrorAlert error={boards.error} title="No se pudieron cargar las placas" />
      {boards.data?.length === 0 && (
        <Text c="dimmed">Todavía no hay placas registradas. Encendé una placa y tocá «Buscar placas».</Text>
      )}
      {boards.data && boards.data.length > 0 && (
        <Table.ScrollContainer minWidth={640}>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Nombre</Table.Th>
                <Table.Th>device_id</Table.Th>
                <Table.Th>Estado</Table.Th>
                <Table.Th>Último dato</Table.Th>
                <Table.Th>Instancias</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {boards.data.map((board) => (
                <Table.Tr key={board.device_id}>
                  <Table.Td>
                    <Anchor component={Link} to={`/boards/${board.device_id}`}>
                      {board.name || board.device_id}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>
                    <Code>{board.device_id}</Code>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light" color={board.online ? 'green' : 'gray'}>
                      {board.online ? 'online' : 'offline'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{board.last_state_at ? formatDateTime(board.last_state_at) : 'Sin datos'}</Table.Td>
                  <Table.Td>{linkedPlugins(board.plugins)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}
