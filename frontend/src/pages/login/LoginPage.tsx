import { Alert, Button, Center, Paper, PasswordInput, Stack, TextInput, Title } from '@mantine/core';
import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { login } from '../../api/auth';
import { useSetupStatus } from '../../api/queries';

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const setup = useSetupStatus();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (setup.data?.needs_setup) return <Navigate to="/setup" replace />;
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (await login(username, password)) navigate(from, { replace: true });
      else setError('Usuario o contraseña incorrectos.');
    } catch {
      setError('No se pudo conectar con el servidor.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Center mih="100vh" p="md">
      <Paper withBorder p="lg" w={360} maw="100%">
        <form onSubmit={submit}>
          <Stack>
            <Title order={2}>PluTO</Title>
            <TextInput
              label="Usuario"
              autoComplete="username"
              required
              value={username}
              onChange={(event) => setUsername(event.currentTarget.value)}
            />
            <PasswordInput
              label="Contraseña"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.currentTarget.value)}
            />
            {error && <Alert color="red">{error}</Alert>}
            <Button type="submit" loading={busy}>
              Entrar
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
