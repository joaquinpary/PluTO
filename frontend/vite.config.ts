import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    // The same origin the browser sees behind nginx, so development needs no CORS.
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Dates render in local time; a fixed zone keeps those tests the same on every machine.
    env: { TZ: 'America/Argentina/Buenos_Aires' },
  },
});
