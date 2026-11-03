import { Button, NativeSelect, Stack, TextInput, Title } from '@mantine/core';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../../shared/api/client';
import { splitErrors } from '../../shared/api/errors';
import { useCreatePlugin, usePluginTypes } from './queries';
import type { Plugin } from '../../shared/api/types';
import { ApiErrorAlert } from '../../shared/components/ApiErrorAlert';
import { ConfigForm } from './ConfigForm';
import { initialValues, REQUIRED, toConfig, validate, type FormErrors, type FormValues } from './configForm';
import { notifySuccess } from '../../shared/lib/notify';

export function PluginNewPage() {
  const navigate = useNavigate();
  const types = usePluginTypes();
  const create = useCreatePlugin();
  const [typeName, setTypeName] = useState('');
  const [name, setName] = useState('');
  const [values, setValues] = useState<FormValues>({});
  const [errors, setErrors] = useState<FormErrors>({});
  const pluginType = types.data?.find((candidate) => candidate.type === typeName);

  function chooseType(next: string) {
    setTypeName(next);
    setValues(initialValues(types.data?.find((candidate) => candidate.type === next)?.config_fields ?? []));
    setErrors({});
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!pluginType) return;
    const nextErrors = validate(pluginType.config_fields, values);
    if (!name.trim()) nextErrors.name = REQUIRED;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    create.mutate(
      {
        name: name.trim(),
        // GET /api/plugin-types lists exactly the types the ChoiceField takes, but the
        // schema types PluginType.type as a plain string (making it a ChoiceField too
        // would clash with ConfigField.type's enum under --fail-on-warn).
        plugin_type: pluginType.type as Plugin['plugin_type'],
        config: toConfig(pluginType.config_fields, values),
      },
      {
        onSuccess: (plugin) => {
          notifySuccess(`Se creó ${plugin.name}.`);
          navigate(`/plugins/${plugin.plugin_uuid}`);
        },
        onError: (error) => {
          if (error instanceof ApiError) setErrors(splitErrors(error.body).fields);
        },
      },
    );
  }

  return (
    <Stack maw={560}>
      <Title order={2}>Nueva instancia</Title>
      <ApiErrorAlert error={types.error} title="No se pudieron cargar los tipos" />
      <form onSubmit={submit} noValidate>
        <Stack>
          <NativeSelect
            label="Tipo"
            value={typeName}
            onChange={(event) => chooseType(event.currentTarget.value)}
            data={[
              { value: '', label: 'Elegí un tipo' },
              ...(types.data ?? []).map((candidate) => ({ value: candidate.type, label: candidate.label })),
            ]}
          />
          {pluginType && (
            <>
              <TextInput
                label="Nombre"
                value={name}
                onChange={(event) => setName(event.currentTarget.value)}
                error={errors.name}
                maxLength={100}
              />
              <ConfigForm
                fields={pluginType.config_fields}
                values={values}
                errors={errors}
                onChange={(field, value) => setValues((previous) => ({ ...previous, [field]: value }))}
              />
              <ApiErrorAlert error={create.error} title="No se pudo crear la instancia" />
              <Button type="submit" loading={create.isPending} w="fit-content">
                Crear instancia
              </Button>
            </>
          )}
        </Stack>
      </form>
    </Stack>
  );
}
