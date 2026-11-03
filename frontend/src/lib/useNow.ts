import { useEffect, useState } from 'react';

/** The current time, refreshed every intervalMs: ages like "hace 4 s" keep counting without new data. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
