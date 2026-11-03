import { Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import type { ReactNode } from 'react';
import { Icon, type IconName } from './icons';

/** What a list says when it has nothing to show yet. */
export function EmptyState({ icon, children }: { icon: IconName; children: ReactNode }) {
  return (
    <Paper withBorder p="xl">
      <Stack align="center" gap="sm">
        <ThemeIcon variant="light" size={48} radius="xl">
          <Icon name={icon} size={24} />
        </ThemeIcon>
        <Text c="dimmed" ta="center">
          {children}
        </Text>
      </Stack>
    </Paper>
  );
}
