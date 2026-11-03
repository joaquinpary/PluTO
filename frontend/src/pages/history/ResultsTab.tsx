import { BarChart } from '@mantine/charts';
import { Group, Paper, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { useState } from 'react';
import { api } from '../../api/client';
import { usePointingError, useReception } from '../../api/queries';
import { ApiErrorAlert } from '../../components/ApiErrorAlert';
import { CsvButton } from '../../components/CsvButton';
import { RangeInput } from '../../components/RangeInput';
import { BoardSelect, PluginSelect } from '../../components/ResourceSelects';
import { formatDateTime } from '../../lib/format';
import {
  cell, comparisonRanges, defaultRange, degrees, fixed, hasRange, receptionSummary, toDegrees, toRangeQuery,
  type DateRange,
} from '../../lib/history';

const SOURCES: Record<string, string> = { meas: 'Medido (encoders)', commanded: 'Ordenado vs. reportado' };

function PointingErrorSection({ board, onBoardChange }: { board: string; onBoardChange: (board: string) => void }) {
  const [range, setRange] = useState<DateRange>(() => defaultRange());
  const query = toRangeQuery(range);
  const result = usePointingError(board, query);
  const passes = result.data?.passes ?? [];

  return (
    <Stack>
      <Title order={3}>Error de apuntamiento por pasada</Title>
      <Text size="sm" c="dimmed">
        Una pasada es la secuencia de órdenes hasta el HOLD que la cierra. Con encoders se usa el error medido; sin
        encoders, la distancia entre lo ordenado y lo que reportó la placa.
      </Text>
      <Group align="end">
        <BoardSelect value={board} onChange={onBoardChange} />
        <RangeInput value={range} onChange={setRange} />
        <CsvButton
          filename={`error-por-pasada-${board}.csv`}
          disabled={!board || !hasRange(query)}
          download={async () => {
            if (!hasRange(query)) throw new Error('A range needs both ends.');
            return api.GET('/api/results/pointing-error', {
              params: { query: { board, ...query, format: 'csv' } },
              parseAs: 'blob',
            });
          }}
        />
      </Group>
      <ApiErrorAlert error={result.error} title="No se pudo calcular el error" />
      {board && result.data && passes.length === 0 && <Text c="dimmed">No hay pasadas en ese rango.</Text>}
      {passes.length > 0 && (
        <>
          <BarChart
            h={240}
            dataKey="pass"
            data={passes.map((pass, index) => ({
              pass: `#${index + 1}`,
              mean: toDegrees(pass.mean_err_cdeg),
              max: toDegrees(pass.max_err_cdeg),
            }))}
            series={[
              { name: 'mean', label: 'Error medio (°)', color: 'blue.6' },
              { name: 'max', label: 'Error máximo (°)', color: 'red.6' },
            ]}
          />
          <Table.ScrollContainer minWidth={700}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>Inicio</Table.Th>
                  <Table.Th>Fin</Table.Th>
                  <Table.Th>Fuente</Table.Th>
                  <Table.Th>Muestras</Table.Th>
                  <Table.Th>Error medio (°)</Table.Th>
                  <Table.Th>Error máximo (°)</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {passes.map((pass, index) => (
                  <Table.Tr key={pass.start}>
                    <Table.Td>{index + 1}</Table.Td>
                    <Table.Td>{formatDateTime(pass.start)}</Table.Td>
                    <Table.Td>{formatDateTime(pass.end)}</Table.Td>
                    <Table.Td>{SOURCES[pass.source] ?? pass.source}</Table.Td>
                    <Table.Td>{cell(pass.samples)}</Table.Td>
                    <Table.Td>{degrees(pass.mean_err_cdeg)}</Table.Td>
                    <Table.Td>{degrees(pass.max_err_cdeg)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}
    </Stack>
  );
}

interface PeriodProps {
  plugin: string;
  label: string;
  initialRange: DateRange;
  csvName: string;
}

function ReceptionPeriod({ plugin, label, initialRange, csvName }: PeriodProps) {
  const [range, setRange] = useState<DateRange>(initialRange);
  const query = toRangeQuery(range);
  const reception = useReception(plugin, query);
  const days = reception.data?.days ?? [];
  const summary = receptionSummary(days);

  return (
    <Paper withBorder p="md">
      <Stack>
        <Group align="end">
          <RangeInput label={label} value={range} onChange={setRange} />
          <CsvButton
            filename={csvName}
            disabled={!plugin || !hasRange(query)}
            download={async () => {
              if (!hasRange(query)) throw new Error('A range needs both ends.');
              return api.GET('/api/results/reception', {
                params: { query: { plugin, ...query, format: 'csv' } },
                parseAs: 'blob',
              });
            }}
          />
        </Group>
        <ApiErrorAlert error={reception.error} title="No se pudo cargar la recepción" />
        {plugin && reception.data && (
          <>
            <Text size="sm">
              {summary.packets} paquetes · {summary.crc_errors} con error de CRC · RSSI medio {fixed(summary.rssi_mean)} dBm ·
              SNR medio {fixed(summary.snr_mean)} dB
            </Text>
            {days.length > 0 && (
              <BarChart h={200} dataKey="date" data={[...days]} series={[{ name: 'packets', label: 'Paquetes', color: 'teal.6' }]} />
            )}
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Día</Table.Th>
                  <Table.Th>Paquetes</Table.Th>
                  <Table.Th>CRC</Table.Th>
                  <Table.Th>RSSI (dBm)</Table.Th>
                  <Table.Th>SNR (dB)</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {days.map((day) => (
                  <Table.Tr key={day.date}>
                    <Table.Td>{day.date}</Table.Td>
                    <Table.Td>{day.packets}</Table.Td>
                    <Table.Td>{day.crc_errors}</Table.Td>
                    <Table.Td>{fixed(day.rssi_mean)}</Table.Td>
                    <Table.Td>{fixed(day.snr_mean)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )}
      </Stack>
    </Paper>
  );
}

function ReceptionSection() {
  const [plugin, setPlugin] = useState('');
  const [periods] = useState(() => comparisonRanges());

  return (
    <Stack>
      <Title order={3}>Recepción</Title>
      <Text size="sm" c="dimmed">
        RSSI, SNR y paquetes por día de una instancia en dos períodos, para compararlos (por ejemplo, la antena omni contra la
        direccional). Las medias de cada período se ponderan por paquetes.
      </Text>
      <PluginSelect value={plugin} onChange={setPlugin} />
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <ReceptionPeriod plugin={plugin} label="Período A" initialRange={periods[0]} csvName="recepcion-periodo-a.csv" />
        <ReceptionPeriod plugin={plugin} label="Período B" initialRange={periods[1]} csvName="recepcion-periodo-b.csv" />
      </SimpleGrid>
    </Stack>
  );
}

export function ResultsTab({ board, onBoardChange }: { board: string; onBoardChange: (board: string) => void }) {
  return (
    <Stack gap="xl">
      <PointingErrorSection board={board} onBoardChange={onBoardChange} />
      <ReceptionSection />
    </Stack>
  );
}
