import { Group, NativeSelect, Stack, Table, Text } from '@mantine/core';
import { useState } from 'react';
import { api } from '../../api/client';
import { useOrders, type OrderFilters } from '../../api/queries';
import { ApiErrorAlert } from '../../components/ApiErrorAlert';
import { CsvButton } from '../../components/CsvButton';
import { CursorPager } from '../../components/CursorPager';
import { RangeInput } from '../../components/RangeInput';
import { BoardSelect } from '../../components/ResourceSelects';
import { formatDateTime } from '../../lib/format';
import { cell, defaultRange, formatEpochMs, toRangeQuery, type DateRange } from '../../lib/history';

const REASONS: Record<string, string> = {
  end: 'Fin de la trayectoria',
  limits: 'Fuera de los límites',
  expired: 'Puntos vencidos',
  stopped: 'Plugin detenido',
};

const parseKind = (value: string): OrderFilters['kind'] => (value === 'BATCH' || value === 'HOLD' ? value : undefined);
const parseReason = (value: string): OrderFilters['reason'] =>
  value === 'end' || value === 'limits' || value === 'expired' || value === 'stopped' ? value : undefined;

export function OrdersTab({ board, onBoardChange }: { board: string; onBoardChange: (board: string) => void }) {
  const [kind, setKind] = useState('');
  const [reason, setReason] = useState('');
  const [range, setRange] = useState<DateRange>(() => defaultRange());
  const [cursor, setCursor] = useState<string>();
  const filters: OrderFilters = {
    board: board || undefined,
    kind: parseKind(kind),
    reason: parseReason(reason),
    ...toRangeQuery(range),
  };
  const page = useOrders({ ...filters, cursor });
  // A new filter starts again from the newest page.
  const resetting = <T,>(set: (value: T) => void) => (value: T) => {
    setCursor(undefined);
    set(value);
  };

  return (
    <Stack>
      <Group align="end">
        <BoardSelect value={board} onChange={resetting(onBoardChange)} allowAll />
        <NativeSelect
          label="Tipo de orden"
          value={kind}
          onChange={(event) => resetting(setKind)(event.currentTarget.value)}
          data={[{ value: '', label: 'Todos' }, 'BATCH', 'HOLD']}
        />
        <NativeSelect
          label="Motivo"
          value={reason}
          onChange={(event) => resetting(setReason)(event.currentTarget.value)}
          data={[{ value: '', label: 'Todos' }, ...Object.entries(REASONS).map(([value, label]) => ({ value, label }))]}
        />
        <RangeInput value={range} onChange={resetting(setRange)} />
        <CsvButton
          filename="ordenes.csv"
          download={() => api.GET('/api/orders', { params: { query: { ...filters, format: 'csv' } }, parseAs: 'blob' })}
        />
      </Group>
      <ApiErrorAlert error={page.error} title="No se pudieron cargar las órdenes" />
      {page.data?.results.length === 0 && <Text c="dimmed">No hay órdenes con esos filtros.</Text>}
      {page.data && page.data.results.length > 0 && (
        <>
          <Table.ScrollContainer minWidth={900}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Hora</Table.Th>
                  <Table.Th>Placa</Table.Th>
                  <Table.Th>Instancia</Table.Th>
                  <Table.Th>Tipo</Table.Th>
                  <Table.Th>Motivo</Table.Th>
                  <Table.Th>Puntos</Table.Th>
                  <Table.Th>Desde</Table.Th>
                  <Table.Th>Hasta</Table.Th>
                  <Table.Th>Enviada</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {page.data.results.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{formatDateTime(row.created_at)}</Table.Td>
                    <Table.Td>{cell(row.board)}</Table.Td>
                    <Table.Td>{cell(row.plugin)}</Table.Td>
                    <Table.Td>{row.kind}</Table.Td>
                    <Table.Td>{REASONS[row.reason ?? ''] ?? cell(row.reason)}</Table.Td>
                    <Table.Td>{cell(row.point_count)}</Table.Td>
                    <Table.Td>{formatEpochMs(row.t0_ms)}</Table.Td>
                    <Table.Td>{formatEpochMs(row.t_end_ms)}</Table.Td>
                    <Table.Td>{formatEpochMs(row.t_sent_ms)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <CursorPager page={page.data} onCursor={setCursor} />
        </>
      )}
    </Stack>
  );
}
