import { Alert, Anchor, Card, Center, Loader, SimpleGrid, Stack, Title } from '@mantine/core';
import { Link } from 'react-router-dom';
import { useBoardsLive, useTracks } from '../boards/queries';
import { usePlugins } from '../plugins/queries';
import { BoardCard } from '../boards/BoardCard';
import { EmptyState } from '../../shared/components/EmptyState';
import { SkyPlot, type SkyAntenna } from '../boards/SkyPlot';
import { alertsFor } from './alerts';
import { useNow } from '../../shared/lib/useNow';

/** Inicio: the boards live, the sky and the alerts. */
export function HomePage() {
  const now = useNow();
  const live = useBoardsLive();
  const plugins = usePlugins();
  const boards = live.data ?? [];
  const tracks = useTracks(boards.map((board) => board.device_id));

  const alerts = alertsFor(boards, plugins.data ?? []);
  const antennas: SkyAntenna[] = boards.flatMap((board) => {
    // Where it actually points when the board measures it, else where it was told to.
    const position = board.state?.meas ?? board.state;
    if (position?.az_cdeg == null || position.el_cdeg == null) return [];
    return [
      {
        id: board.device_id,
        label: board.name || board.device_id,
        az_cdeg: position.az_cdeg,
        el_cdeg: position.el_cdeg,
      },
    ];
  });

  return (
    <Stack>
      <Title order={2}>Inicio</Title>

      {live.isError && (
        <Alert color="red" title="Sin conexión con el servidor">
          Se muestran los últimos datos recibidos; se sigue reintentando.
        </Alert>
      )}
      {alerts.map((alert) => (
        <Alert key={alert.key} color={alert.color}>
          {alert.message}
        </Alert>
      ))}

      {live.data === undefined ? (
        !live.isError && (
          <Center>
            <Loader />
          </Center>
        )
      ) : boards.length === 0 ? (
        <EmptyState icon="radio">
          Todavía no hay placas. Buscalas en{' '}
          <Anchor component={Link} to="/boards">
            Placas
          </Anchor>
          .
        </EmptyState>
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {boards.map((board) => (
              <BoardCard key={board.device_id} board={board} now={now} />
            ))}
          </SimpleGrid>
          <Card>
            <Title order={4} mb="sm">
              Cielo
            </Title>
            <SkyPlot
              antennas={antennas}
              tracks={boards.map((board, i) => ({ id: board.device_id, points: tracks[i]?.data?.points ?? [] }))}
            />
          </Card>
        </>
      )}
    </Stack>
  );
}
