import { Anchor, Badge, Card, Group, SimpleGrid, Text } from '@mantine/core';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { BoardLive } from '../api/types';
import { boardStatus, type BoardStatus } from '../lib/boardStatus';
import { formatAge, formatCdeg } from '../lib/format';

const STATUS: Record<BoardStatus, { color: string; label: string }> = {
  online: { color: 'green', label: 'Online' },
  offline: { color: 'red', label: 'Offline' },
  no_data: { color: 'gray', label: 'Sin datos' },
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600} lts={0.4}>
        {label}
      </Text>
      <Text size="sm" fw={500}>
        {children}
      </Text>
    </div>
  );
}

/** One board on the Home (spec 4.1). A board without any state yet shows "Sin datos" and nothing else. */
export function BoardCard({ board, now }: { board: BoardLive; now: number }) {
  const status = STATUS[boardStatus(board, now)];
  const { state, running_plugin: plugin, satellite } = board;

  return (
    <Card padding="md">
      <Group justify="space-between" mb="sm">
        <Anchor component={Link} to={`/boards/${board.device_id}`} fw={700} size="lg">
          {board.name || board.device_id}
        </Anchor>
        <Badge variant="dot" color={status.color}>
          {status.label}
        </Badge>
      </Group>

      <SimpleGrid cols={2} spacing="xs">
        <Field label="Último dato">
          {board.last_state_at ? formatAge(board.last_state_at, now) : 'ninguno todavía'}
        </Field>
        <Field label="Instancia">
          {plugin ? (
            <Anchor component={Link} to={`/plugins/${plugin.plugin_uuid}`}>
              {plugin.name}
            </Anchor>
          ) : (
            'ninguna en ejecución'
          )}
        </Field>
        {state && (
          <>
            <Field label="Modo">{state.mode || '—'}</Field>
            <Field label="Pan-tilt">{state.pan_mode || '—'}</Field>
            <Field label="Az / El comandados">{`${formatCdeg(state.az_cdeg)} / ${formatCdeg(state.el_cdeg)}`}</Field>
            {state.meas && (
              <Field label="Az / El medidos">{`${formatCdeg(state.meas.az_cdeg)} / ${formatCdeg(state.meas.el_cdeg)}`}</Field>
            )}
            {state.err_cdeg !== null && <Field label="Error">{formatCdeg(state.err_cdeg)}</Field>}
          </>
        )}
        {satellite && (
          <Field label="Satélite">
            {satellite.norad === null ? satellite.name : `${satellite.name} (NORAD ${satellite.norad})`}
          </Field>
        )}
      </SimpleGrid>
    </Card>
  );
}
