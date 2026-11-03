import { Button, Group } from '@mantine/core';
import { cursorFrom } from '../lib/history';

interface Page {
  next?: string | null;
  previous?: string | null;
}

/** Newest first: `next` goes back in time. */
export function CursorPager({ page, onCursor }: { page: Page | undefined; onCursor: (cursor: string | undefined) => void }) {
  if (!page || (!page.next && !page.previous)) return null;
  return (
    <Group justify="center">
      <Button variant="default" disabled={!page.previous} onClick={() => onCursor(cursorFrom(page.previous))}>
        Más recientes
      </Button>
      <Button variant="default" disabled={!page.next} onClick={() => onCursor(cursorFrom(page.next))}>
        Más antiguos
      </Button>
    </Group>
  );
}
