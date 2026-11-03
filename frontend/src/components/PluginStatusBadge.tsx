import { Badge } from '@mantine/core';

export type PluginStatus = 'STOPPED' | 'RUNNING' | 'ERROR';

export const PLUGIN_STATUS_OPTIONS: { value: PluginStatus; label: string }[] = [
  { value: 'STOPPED', label: 'Detenida' },
  { value: 'RUNNING', label: 'En ejecución' },
  { value: 'ERROR', label: 'Error' },
];

const COLORS: Record<string, string> = { STOPPED: 'gray', RUNNING: 'green', ERROR: 'red' };

export function parseStatus(value: string): PluginStatus | undefined {
  return PLUGIN_STATUS_OPTIONS.find((option) => option.value === value)?.value;
}

export function statusLabel(status: string): string {
  return PLUGIN_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

export function PluginStatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="light" color={COLORS[status] ?? 'gray'}>
      {statusLabel(status)}
    </Badge>
  );
}
