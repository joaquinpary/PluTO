import { Button, Code, Group, NativeSelect, Stack, Table, Text } from '@mantine/core';
import { Fragment, useState } from 'react';
import { api } from '../../api/client';
import { usePluginData, usePluginTypes, usePlugins, type PluginDataFilters } from '../../api/queries';
import { ApiErrorAlert } from '../../components/ApiErrorAlert';
import { CsvButton } from '../../components/CsvButton';
import { CursorPager } from '../../components/CursorPager';
import { RangeInput } from '../../components/RangeInput';
import { PluginSelect } from '../../components/ResourceSelects';
import { formatDateTime } from '../../lib/format';
import { cell, defaultRange, satelliteText, toRangeQuery, type DateRange } from '../../lib/history';

const COLUMNS = 9;

export function PluginDataTab() {
  const types = usePluginTypes();
  const plugins = usePlugins();
  const [plugin, setPlugin] = useState('');
  const [type, setType] = useState('');
  const [range, setRange] = useState<DateRange>(() => defaultRange());
  const [cursor, setCursor] = useState<string>();
  const [openRow, setOpenRow] = useState<number | null>(null);
  const filters: PluginDataFilters = { plugin: plugin || undefined, type: type || undefined, ...toRangeQuery(range) };
  const page = usePluginData({ ...filters, cursor });
  const messageTypes = [...new Set((types.data ?? []).flatMap((pluginType) => pluginType.message_types))];
  const names = new Map((plugins.data ?? []).map((candidate) => [candidate.plugin_uuid, candidate.name]));
  // A new filter starts again from the newest page.
  const resetting = <T,>(set: (value: T) => void) => (value: T) => {
    setCursor(undefined);
    set(value);
  };

  return (
    <Stack>
      <Group align="end">
        <PluginSelect value={plugin} onChange={resetting(setPlugin)} allowAll />
        <NativeSelect
          label="Tipo de mensaje"
          value={type}
          onChange={(event) => resetting(setType)(event.currentTarget.value)}
          data={[{ value: '', label: 'Todos' }, ...messageTypes]}
        />
        <RangeInput value={range} onChange={resetting(setRange)} />
        <CsvButton
          filename="datos-de-plugins.csv"
          download={() => api.GET('/api/plugin-data', { params: { query: { ...filters, format: 'csv' } }, parseAs: 'blob' })}
        />
      </Group>
      <ApiErrorAlert error={page.error} title="No se pudieron cargar los datos" />
      {page.data?.results.length === 0 && <Text c="dimmed">No hay datos con esos filtros.</Text>}
      {page.data && page.data.results.length > 0 && (
        <>
          <Table.ScrollContainer minWidth={900}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Recibido</Table.Th>
                  <Table.Th>Instancia</Table.Th>
                  <Table.Th>Tipo</Table.Th>
                  <Table.Th>Dispositivo</Table.Th>
                  <Table.Th>RSSI</Table.Th>
                  <Table.Th>SNR</Table.Th>
                  <Table.Th>Error de CRC</Table.Th>
                  <Table.Th>Satélite</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {page.data.results.map((row) => (
                  <Fragment key={row.id}>
                    <Table.Tr>
                      <Table.Td>{formatDateTime(row.received_at ?? row.created_at)}</Table.Td>
                      <Table.Td>{names.get(String(row.plugin)) ?? cell(row.plugin)}</Table.Td>
                      <Table.Td>{row.message_type}</Table.Td>
                      <Table.Td>{cell(row.device)}</Table.Td>
                      <Table.Td>{cell(row.rssi)}</Table.Td>
                      <Table.Td>{cell(row.snr)}</Table.Td>
                      <Table.Td>{cell(row.crc_error)}</Table.Td>
                      <Table.Td>{satelliteText(row.satellite)}</Table.Td>
                      <Table.Td>
                        <Button size="compact-xs" variant="subtle" onClick={() => setOpenRow(openRow === row.id ? null : row.id)}>
                          {openRow === row.id ? 'Ocultar JSON' : 'Ver JSON'}
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                    {openRow === row.id && (
                      <Table.Tr>
                        <Table.Td colSpan={COLUMNS}>
                          <Code block>{JSON.stringify(row.payload, null, 2)}</Code>
                        </Table.Td>
                      </Table.Tr>
                    )}
                  </Fragment>
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
