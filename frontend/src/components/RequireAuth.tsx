import { Center, Loader } from '@mantine/core';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useHasSession } from '../api/auth';
import { useSetupStatus } from '../api/queries';

/**
 * The gate in front of the app: a fresh install goes to /setup, a visitor
 * without a session to /login (which comes back to `from`), and the rest in.
 */
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
