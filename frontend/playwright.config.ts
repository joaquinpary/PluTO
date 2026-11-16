import { defineConfig, devices } from '@playwright/test';

// Runs against docker compose up with an empty database (README, "Prueba de punta a punta").
// E2E_BASE_URL: for a PLUTO_WEB_PORT other than 80.
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
