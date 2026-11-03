import { Alert, Button, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { login, useHasSession } from '../../shared/api/auth';
import { api, fieldErrors } from '../../shared/api/client';
import { useSetupStatus } from '../../shared/api/queries';
import { AuthCard } from './AuthCard';

/** First start: creates the only user and logs in with it. */
export function SetupPage() {
  const queryClient = useQueryClient();
  const setup = useSetupStatus();
  const hasSession = useHasSession();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  // Also how a successful submit leaves: logged in, to the start page.
  if (setup.data && !setup.data.needs_setup) return <Navigate to={hasSession ? '/' : '/login'} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirmation) {
      setErrors({ confirmation: 'Las contraseñas no coinciden.' });
      return;
    }
    setBusy(true);
    setErrors({});
    try {
      const { response, error } = await api.POST('/api/setup', { body: { username, password } });
      if (response.status === 409) {
        // Someone created it meanwhile: the login is what is left.
        queryClient.setQueryData(['setup'], { needs_setup: false });
        return;
      }
      if (!response.ok) {
        setErrors(fieldErrors(error));
        return;
      }
      await login(username, password);
      queryClient.setQueryData(['setup'], { needs_setup: false });
    } catch {
      setErrors({ detail: 'No se pudo conectar con el servidor.' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard>
      <form onSubmit={submit}>
        <Stack>
          <Title order={4}>Crear usuario</Title>
          <Text size="sm" c="dimmed">
            PluTO todavía no tiene usuario. El que crees ahora es el único.
          </Text>
          <TextInput
            label="Usuario"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            error={errors.username}
          />
          <PasswordInput
            label="Contraseña"
            autoComplete="new-password"
            required
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            error={errors.password}
          />
          <PasswordInput
            label="Confirmación"
            autoComplete="new-password"
            required
            value={confirmation}
            onChange={(event) => setConfirmation(event.currentTarget.value)}
            error={errors.confirmation}
          />
          {errors.detail && <Alert color="red">{errors.detail}</Alert>}
          <Button type="submit" loading={busy}>
            Crear usuario
          </Button>
        </Stack>
      </form>
    </AuthCard>
  );
}
