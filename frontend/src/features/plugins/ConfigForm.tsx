import { NativeSelect, NumberInput, Stack, Switch, TextInput } from '@mantine/core';
import type { ConfigField, FormErrors, FormValue, FormValues } from './configForm';

interface Props {
  fields: readonly ConfigField[];
  values: FormValues;
  errors: FormErrors;
  onChange: (name: string, value: FormValue) => void;
}

/**
 * One input per declared field: a new plugin type needs no change here (HU-04).
 * No asterisks: the end-to-end test finds each field by its exact label, and
 * Mantine's " *" is part of the label's text. A missing field shows its error.
 */
export function ConfigForm({ fields, values, errors, onChange }: Props) {
  return (
    <Stack gap="sm">
      {fields.map((field) => (
        <ConfigInput
          key={field.name}
          field={field}
          value={values[field.name]}
          error={errors[field.name]}
          onChange={(value) => onChange(field.name, value)}
        />
      ))}
    </Stack>
  );
}

interface InputProps {
  field: ConfigField;
  value: FormValue | undefined;
  error: string | undefined;
  onChange: (value: FormValue) => void;
}

function ConfigInput({ field, value, error, onChange }: InputProps) {
  const label = field.label || field.name;
  const description = field.help || undefined;

  if (field.type === 'boolean') {
    return (
      <Switch
        label={label}
        description={description}
        error={error}
        checked={value === true}
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
    );
  }

  if (field.type === 'integer' || field.type === 'number') {
    return (
      <NumberInput
        label={label}
        description={description}
        error={error}
        value={typeof value === 'boolean' || value === undefined ? '' : value}
        onChange={onChange}
        min={field.min ?? undefined}
        max={field.max ?? undefined}
        allowDecimal={field.type === 'number'}
        // Out of range stays as typed, so validate() can say why instead of clamping it silently.
        clampBehavior="none"
      />
    );
  }

  if (field.type === 'choice') {
    const options = (field.choices ?? []).map(([choice, text]) => ({
      value: String(choice),
      label: String(text ?? choice),
    }));
    return (
      <NativeSelect
        label={label}
        description={description}
        error={error}
        value={String(value ?? '')}
        onChange={(event) => onChange(event.currentTarget.value)}
        data={[{ value: '', label: 'Elegí una opción' }, ...options]}
      />
    );
  }

  return (
    <TextInput
      label={label}
      description={description}
      error={error}
      value={String(value ?? '')}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  );
}
