import { Alert, Button, Code, Group, NumberInput, Stack, Switch, Text } from '@mantine/core';
import { useState } from 'react';
import { errorMessage, isStatus } from '../../shared/api/errors';
import { LOGS_DEFAULT_TAIL, LOGS_MAX_TAIL, useLogs, type LogSource } from './queries';

function logsErrorMessage(error: unknown, source: LogSource): string {
  // Stopping an instance removes its container (PluginOrchestrator.kill_plugin).
  if (source.kind === 'plugin' && isStatus(error, 404)) {
    return 'La instancia no tiene contenedor: no está lanzada, y al detenerla su contenedor se borra.';
  }
  return errorMessage(error);
}

/** The last lines of a container, with an optional refresh every 3 s. */
export function LogPanel({ source }: { source: LogSource }) {
  const [tail, setTail] = useState(LOGS_DEFAULT_TAIL);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const logs = useLogs(source, tail, autoRefresh);

  return (
    <Stack>
      <Group align="end">
        <NumberInput
          label="Líneas"
          w={120}
          min={1}
          max={LOGS_MAX_TAIL}
          allowDecimal={false}
          value={tail}
          onChange={(value) => {
            if (typeof value === 'number' && value >= 1) setTail(Math.min(value, LOGS_MAX_TAIL));
          }}
        />
        <Switch
          label="Actualizar cada 3 s"
          checked={autoRefresh}
          onChange={(event) => setAutoRefresh(event.currentTarget.checked)}
        />
        <Button variant="default" onClick={() => logs.refetch()} loading={logs.isFetching && !autoRefresh}>
          Actualizar
        </Button>
      </Group>
      {logs.isError && <Alert color="red">{logsErrorMessage(logs.error, source)}</Alert>}
      {logs.data &&
        (logs.data.lines.length === 0 ? (
          <Text c="dimmed">No hay líneas.</Text>
        ) : (
          <Code block style={{ maxHeight: 480, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
            {logs.data.lines.join('\n')}
          </Code>
        ))}
    </Stack>
  );
}
