import { defineConfig, devices } from '@playwright/test';

// Runs against the whole stack (docker compose up), not a dev server, and
// needs an empty database: see "Prueba de punta a punta" in the README.
// E2E_BASE_URL is for a web port other than 80 (PLUTO_WEB_PORT).
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  timeout: 120_000,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
