import { LineChart } from '@mantine/charts';
import { Group, Stack, Table, Text } from '@mantine/core';
import { useState } from 'react';
import { api } from '../../shared/api/client';
import { useStateSeries, useStates } from './queries';
import { ApiErrorAlert } from '../../shared/components/ApiErrorAlert';
import { CsvButton } from './CsvButton';
import { CursorPager } from './CursorPager';
import { RangeInput } from './RangeInput';
import { BoardSelect } from './ResourceSelects';
import { formatDateTime } from '../../shared/lib/format';
import { cell, defaultRange, degrees, toDegrees, toRangeQuery, type DateRange } from './history';

const batchLabel = (accepted: boolean | null | undefined) =>
  accepted === true ? 'Aceptado' : accepted === false ? 'Rechazado' : '';

export function StatesTab({ board, onBoardChange }: { board: string; onBoardChange: (board: string) => void }) {
  const [range, setRange] = useState<DateRange>(() => defaultRange());
  const [cursor, setCursor] = useState<string>();
  const query = toRangeQuery(range);
  const series = useStateSeries(board, query);
  const page = useStates(board, { ...query, cursor });

  const chartData = (series.data?.points ?? []).map((point) => ({
    t: formatDateTime(point.t),
    az: toDegrees(point.az_cdeg),
    el: toDegrees(point.el_cdeg),
  }));

  return (
    <Stack>
      <Group align="end">
        <BoardSelect value={board} onChange={(next) => { setCursor(undefined); onBoardChange(next); }} />
        <RangeInput value={range} onChange={(next) => { setCursor(undefined); setRange(next); }} />
        <CsvButton
          filename={`posiciones-${board}.csv`}
          disabled={!board}
          download={() =>
            api.GET('/api/boards/{device_id}/states', {
              params: { path: { device_id: board }, query: { ...query, format: 'csv' } },
              parseAs: 'blob',
            })
          }
        />
      </Group>
      {!board && <Text c="dimmed">Elegí una placa para ver sus posiciones.</Text>}
      <ApiErrorAlert error={series.error ?? page.error} title="No se pudo cargar el historial" />
      {board && series.data && chartData.length === 0 && <Text c="dimmed">No hay posiciones en ese rango.</Text>}
      {chartData.length > 0 && (
        <LineChart
          h={280}
          data={chartData}
          dataKey="t"
          withDots={false}
          series={[
            { name: 'az', label: 'Azimut (°)', color: 'blue.6' },
            { name: 'el', label: 'Elevación (°)', color: 'teal.6' },
          ]}
        />
      )}
      {page.data && page.data.results.length > 0 && (
        <>
          <Table.ScrollContainer minWidth={900}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Hora</Table.Th>
                  <Table.Th>Modo</Table.Th>
                  <Table.Th>Az (°)</Table.Th>
                  <Table.Th>El (°)</Table.Th>
                  <Table.Th>pan_mode</Table.Th>
                  <Table.Th>Batch</Table.Th>
                  <Table.Th>Error del batch</Table.Th>
                  <Table.Th>Latencia (ms)</Table.Th>
                  <Table.Th>Reloj sincronizado</Table.Th>
                  <Table.Th>Error (°)</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {page.data.results.map((row, index) => (
                  <Table.Tr key={`${row.received_at}-${index}`}>
                    <Table.Td>{formatDateTime(row.received_at)}</Table.Td>
                    <Table.Td>{cell(row.mode)}</Table.Td>
                    <Table.Td>{degrees(row.az_cdeg)}</Table.Td>
                    <Table.Td>{degrees(row.el_cdeg)}</Table.Td>
                    <Table.Td>{cell(row.pan_mode)}</Table.Td>
                    <Table.Td>{batchLabel(row.batch_accepted)}</Table.Td>
                    <Table.Td>{cell(row.batch_error)}</Table.Td>
                    <Table.Td>{cell(row.latency_ms)}</Table.Td>
                    <Table.Td>{cell(row.clock_synced)}</Table.Td>
                    <Table.Td>{degrees(row.err_cdeg)}</Table.Td>
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
