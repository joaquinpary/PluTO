import { NativeSelect } from '@mantine/core';
import { useBoards } from '../boards/queries';
import { usePlugins } from '../plugins/queries';

interface Props {
  value: string;
  onChange: (value: string) => void;
  /** An empty option that means "every one" instead of "choose one". */
  allowAll?: boolean;
  label?: string;
}

export function BoardSelect({ value, onChange, allowAll = false, label = 'Placa' }: Props) {
  const boards = useBoards();
  return (
    <NativeSelect
      label={label}
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
      data={[
        { value: '', label: allowAll ? 'Todas' : 'Elegí una placa' },
        ...(boards.data ?? []).map((board) => ({ value: board.device_id, label: board.name || board.device_id })),
      ]}
    />
  );
}

export function PluginSelect({ value, onChange, allowAll = false, label = 'Instancia' }: Props) {
  const plugins = usePlugins();
  return (
    <NativeSelect
      label={label}
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
      data={[
        { value: '', label: allowAll ? 'Todas' : 'Elegí una instancia' },
        ...(plugins.data ?? []).map((plugin) => ({ value: plugin.plugin_uuid, label: plugin.name })),
      ]}
    />
  );
}
