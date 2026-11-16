import { Center, Loader } from '@mantine/core';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useHasSession } from '../../shared/api/auth';
import { useSetupStatus } from '../../shared/api/queries';

/** No user yet: /setup. No session: /login, which returns to `from`. */
export function RequireAuth() {
  const location = useLocation();
  const setup = useSetupStatus();
  const hasSession = useHasSession();

  if (setup.isPending) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (setup.data?.needs_setup) return <Navigate to="/setup" replace />;
  if (!hasSession) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}
