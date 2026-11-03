import { Center, Paper, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';
import { LogoMark } from './icons';

/** The login and the first setup: one card on a night sky. */
export function AuthCard({ children }: { children: ReactNode }) {
  return (
    <Center mih="100vh" p="md" className="auth-bg">
      <Paper shadow="xl" radius="lg" p="xl" w={380} maw="100%">
        <Stack align="center" gap={4} mb="lg">
          <LogoMark size={52} />
          <Title order={2}>PluTO</Title>
          <Text size="sm" c="dimmed">
            Estación terrena
          </Text>
        </Stack>
        {children}
      </Paper>
    </Center>
  );
}
