import { Button, Paper, Stack, TextInput } from '@mantine/core';
import { useState, type FormEvent } from 'react';
import { ApiError } from '../../shared/api/client';
import { splitErrors } from '../../shared/api/errors';
import { useUpdatePlugin } from './queries';
import type { Plugin } from '../../shared/api/types';
import { ApiErrorAlert } from '../../shared/components/ApiErrorAlert';
import { ConfigForm } from './ConfigForm';
import { asConfig, initialValues, REQUIRED, toConfig, validate, type ConfigField, type FormErrors } from './configForm';
import { notifySuccess } from '../../shared/lib/notify';

interface Props {
  plugin: Plugin;
  fields: readonly ConfigField[];
  onSaved: () => void;
}

export function PluginConfigPanel({ plugin, fields, onSaved }: Props) {
  const update = useUpdatePlugin(plugin.plugin_uuid);
  // Filled once: the detail refreshes every 5 s and must not undo what is being typed.
  const [name, setName] = useState(plugin.name);
  const [values, setValues] = useState(() => initialValues(fields, asConfig(plugin.config)));
  const [errors, setErrors] = useState<FormErrors>({});

  function submit(event: FormEvent) {
    event.preventDefault();
    const nextErrors = validate(fields, values);
    if (!name.trim()) nextErrors.name = REQUIRED;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    update.mutate(
      { name: name.trim(), config: toConfig(fields, values, asConfig(plugin.config)) },
      {
        onSuccess: () => {
          notifySuccess('Cambios guardados.');
          onSaved();
        },
        onError: (error) => {
          if (error instanceof ApiError) setErrors(splitErrors(error.body).fields);
        },
      },
    );
  }

  return (
    <Paper withBorder p="md">
      <form onSubmit={submit} noValidate>
        <Stack maw={560}>
          <TextInput
            label="Nombre"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            error={errors.name}
            maxLength={100}
          />
          <ConfigForm
            fields={fields}
            values={values}
            errors={errors}
            onChange={(field, value) => setValues((previous) => ({ ...previous, [field]: value }))}
          />
          <ApiErrorAlert error={update.error} title="No se pudieron guardar los cambios" />
          <Button type="submit" loading={update.isPending} w="fit-content">
            Guardar
          </Button>
        </Stack>
      </form>
    </Paper>
  );
}
