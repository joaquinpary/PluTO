import { Button, Paper, PasswordInput, Stack, Text, Title } from '@mantine/core';
import { useState, type ChangeEvent, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { logout } from '../../shared/api/auth';
import { ApiError } from '../../shared/api/client';
import { splitErrors } from '../../shared/api/errors';
import { useChangePassword } from './queries';
import { ApiErrorAlert } from '../../shared/components/ApiErrorAlert';
import { REQUIRED } from '../plugins/configForm';
import { notifySuccess } from '../../shared/lib/notify';

interface PasswordForm {
  current_password: string;
  new_password: string;
  confirm: string;
}

const EMPTY: PasswordForm = { current_password: '', new_password: '', confirm: '' };

/** Django's password validators run on the server and come back as a 400 on new_password. */
export function validatePasswordForm(values: PasswordForm): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const key of ['current_password', 'new_password', 'confirm'] as const) {
    if (!values[key]) errors[key] = REQUIRED;
  }
  if (values.new_password && values.confirm && values.new_password !== values.confirm) {
    errors.confirm = 'Las contraseñas no coinciden.';
  }
  return errors;
}

export function AccountPage() {
  const navigate = useNavigate();
  const change = useChangePassword();
  const [values, setValues] = useState<PasswordForm>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [leaving, setLeaving] = useState(false);

  const field = (key: keyof PasswordForm) => ({
    value: values[key],
    error: errors[key],
    onChange: (event: ChangeEvent<HTMLInputElement>) => {
      const { value } = event.currentTarget;
      setValues((previous) => ({ ...previous, [key]: value }));
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const nextErrors = validatePasswordForm(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    change.mutate(
      { current_password: values.current_password, new_password: values.new_password },
      {
        onSuccess: () => {
          setValues(EMPTY);
          notifySuccess('Contraseña cambiada.');
        },
        onError: (error) => {
          if (error instanceof ApiError) setErrors(splitErrors(error.body).fields);
        },
      },
    );
  }

  async function leave() {
    setLeaving(true);
    try {
      await logout();
    } finally {
      navigate('/login', { replace: true });
    }
  }

  return (
    <Stack maw={480}>
      <Title order={2}>Cuenta</Title>
      <Paper withBorder p="md">
        <form onSubmit={submit} noValidate>
          <Stack>
            <Title order={4}>Cambiar la contraseña</Title>
            <PasswordInput label="Contraseña actual" autoComplete="current-password" {...field('current_password')} />
            <PasswordInput label="Contraseña nueva" autoComplete="new-password" {...field('new_password')} />
            <PasswordInput label="Repetí la contraseña nueva" autoComplete="new-password" {...field('confirm')} />
            <ApiErrorAlert error={change.error} title="No se pudo cambiar la contraseña" />
            <Button type="submit" loading={change.isPending} w="fit-content">
              Cambiar contraseña
            </Button>
          </Stack>
        </form>
      </Paper>
      <Paper withBorder p="md">
        <Stack>
          <Text>Cerrar la sesión invalida el token de este navegador.</Text>
          <Button color="red" variant="light" onClick={leave} loading={leaving} w="fit-content">
            Cerrar sesión
          </Button>
        </Stack>
      </Paper>
    </Stack>
  );
}
