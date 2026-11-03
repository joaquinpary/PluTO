import {
  Alert, Anchor, Badge, Button, Group, Loader, NumberInput, Paper, SimpleGrid, Stack, Text, TextInput, Title,
} from '@mantine/core';
import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../../shared/api/client';
import { isStatus, splitErrors } from '../../shared/api/errors';
import { useBoard, useUpdateBoard } from './queries';
import { ApiErrorAlert } from '../../shared/components/ApiErrorAlert';
import { PluginStatusBadge } from '../plugins/PluginStatusBadge';
import {
  azimuthWindowText, boardFormValues, toBoardPatch, validateBoard,
  type BoardFormValues, type BoardSource, type NumberValue,
} from './boardForm';
import { formatDateTime } from '../../shared/lib/format';
import { notifySuccess } from '../../shared/lib/notify';

function BoardForm({ deviceId, board }: { deviceId: string; board: BoardSource }) {
  const update = useUpdateBoard(deviceId);
  const [values, setValues] = useState(() => boardFormValues(board));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const change = (key: keyof BoardFormValues, value: NumberValue) =>
    setValues((previous) => ({ ...previous, [key]: value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    const nextErrors = validateBoard(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    update.mutate(toBoardPatch(values), {
      onSuccess: () => notifySuccess('Placa guardada.'),
      onError: (error) => {
        if (error instanceof ApiError) setErrors(splitErrors(error.body).fields);
      },
    });
  }

  const numberInput = (key: Exclude<keyof BoardFormValues, 'name'>, label: string) => (
    <NumberInput
      label={label}
      value={values[key]}
      onChange={(value) => change(key, value)}
      error={errors[key]}
      decimalScale={6}
      clampBehavior="none"
    />
  );
  const windowText = azimuthWindowText(values);

  return (
    <Paper withBorder p="md">
      <form onSubmit={submit} noValidate>
        <Stack maw={560}>
          <TextInput
            label="Nombre"
            value={values.name}
            onChange={(event) => change('name', event.currentTarget.value)}
            error={errors.name}
            maxLength={100}
          />
          <Title order={4}>Ubicación</Title>
          <Text size="sm" c="dimmed">
            tinygs la usa para calcular las pasadas: sin latitud y longitud, no las calcula. La altitud vacía cuenta
            como 0 m.
          </Text>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            {numberInput('latitude_deg', 'Latitud (°)')}
            {numberInput('longitude_deg', 'Longitud (°)')}
            {numberInput('altitude_m', 'Altitud (m)')}
          </SimpleGrid>
          <Title order={4}>Límites</Title>
          {numberInput('min_elevation_deg', 'Elevación mínima (°)')}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {numberInput('min_azimuth_deg', 'Azimut desde (°)')}
            {numberInput('max_azimuth_deg', 'Azimut hasta (°)')}
          </SimpleGrid>
          {windowText && <Text size="sm">{windowText}</Text>}
          <ApiErrorAlert error={update.error} title="No se pudo guardar la placa" />
          <Button type="submit" loading={update.isPending} w="fit-content">
            Guardar
          </Button>
        </Stack>
      </form>
    </Paper>
  );
}

export function BoardDetailPage() {
  const { deviceId = '' } = useParams();
  const board = useBoard(deviceId);

  if (board.isPending) return <Loader />;
  if (board.isError) {
    return isStatus(board.error, 404) ? (
      <Alert color="yellow">No hay ninguna placa con ese device_id.</Alert>
    ) : (
      <ApiErrorAlert error={board.error} title="No se pudo cargar la placa" />
    );
  }

  const data = board.data;
  return (
    <Stack>
      <Group justify="space-between" align="start">
        <div>
          <Title order={2}>{data.name || data.device_id}</Title>
          <Text c="dimmed" size="sm">
            device_id {data.device_id} · último dato: {data.last_state_at ? formatDateTime(data.last_state_at) : 'Sin datos'}
          </Text>
        </div>
        <Group gap="xs">
          <Badge variant="dot" color={data.online ? 'green' : 'gray'}>
            {data.online ? 'online' : 'offline'}
          </Badge>
          <Button component={Link} to={`/history?board=${data.device_id}`} variant="default">
            Ver historial
          </Button>
        </Group>
      </Group>

      <BoardForm key={data.device_id} deviceId={data.device_id} board={data} />

      <Paper withBorder p="md">
        <Title order={4}>Instancias vinculadas</Title>
        {data.plugins.length === 0 ? (
          <Text c="dimmed">Ninguna instancia tiene esta placa.</Text>
        ) : (
          <Stack gap={4} mt="xs">
            {data.plugins.map((plugin) => (
              <Group key={plugin.plugin_uuid} gap="xs">
                <Anchor component={Link} to={`/plugins/${plugin.plugin_uuid}`}>
                  {plugin.name}
                </Anchor>
                <PluginStatusBadge status={plugin.status ?? ''} />
              </Group>
            ))}
          </Stack>
        )}
      </Paper>
    </Stack>
  );
}
