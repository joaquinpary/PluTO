import { Stack, Tabs, Title } from '@mantine/core';
import { useSearchParams } from 'react-router-dom';
import { OrdersTab } from './OrdersTab';
import { PluginDataTab } from './PluginDataTab';
import { ResultsTab } from './ResultsTab';
import { StatesTab } from './StatesTab';

/** ?tab= picks the tab and ?board= the board, so the board detail can link straight here. */
export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? 'states';
  const board = params.get('board') ?? '';

  function update(changes: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  }

  const onBoardChange = (value: string) => update({ board: value });

  return (
    <Stack>
      <Title order={2}>Historial</Title>
      <Tabs value={tab} onChange={(value) => update({ tab: value ?? 'states' })} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="states">Posiciones</Tabs.Tab>
          <Tabs.Tab value="orders">Órdenes</Tabs.Tab>
          <Tabs.Tab value="data">Datos</Tabs.Tab>
          <Tabs.Tab value="results">Resultados</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="states" pt="md">
          <StatesTab board={board} onBoardChange={onBoardChange} />
        </Tabs.Panel>
        <Tabs.Panel value="orders" pt="md">
          <OrdersTab board={board} onBoardChange={onBoardChange} />
        </Tabs.Panel>
        <Tabs.Panel value="data" pt="md">
          <PluginDataTab />
        </Tabs.Panel>
        <Tabs.Panel value="results" pt="md">
          <ResultsTab board={board} onBoardChange={onBoardChange} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
