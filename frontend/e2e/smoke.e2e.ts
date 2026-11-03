import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Needs an empty database: /setup only creates the user while there is none.
const USERNAME = 'operador';
const PASSWORD = 'antena-direccional-2026';
const PLUGIN_NAME = 'e2e-file-tracker';
// A board that only exists as a retained status in Mosquitto, the way a real
// one leaves it (docs/contracts/device-state.md): 12 hex digits.
const BOARD_ID = 'e2e000000001';

type ConfigField = { name: string; label: string; choices: [string, string][] | null };
type PluginType = { type: string; label: string; config_fields: ConfigField[] };

// npm run e2e runs from frontend/, so the compose file is one level up. The
// broker credentials are the ones the mosquitto container already has.
function publishBoardStatus(args: string) {
  execFileSync('docker', [
    'compose', '-f', resolve('..', 'docker-compose.yml'), 'exec', '-T', 'mosquitto', 'sh', '-c',
    `mosquitto_pub -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -q 1 -t device/${BOARD_ID}/status ${args}`,
  ]);
}

async function apiHeaders(request: APIRequestContext) {
  const login = await request.post('/api/auth/token', { data: { username: USERNAME, password: PASSWORD } });
  expect(login.status()).toBe(200);
  const { access } = await login.json();
  return { Authorization: `Bearer ${access}` };
}

// The label and option text of one choice field, as GET /api/plugin-types declares them.
function choice(pluginType: PluginType, name: string, value: string) {
  const field = pluginType.config_fields.find((candidate) => candidate.name === name);
  const match = field?.choices?.find(([candidate]) => candidate.toUpperCase() === value);
  if (!field || !match) throw new Error(`${pluginType.type} declares no ${name} = ${value}`);
  return { label: field.label, value: match[0], text: match[1] };
}

// A Mantine Select opens a listbox; a native <select> takes the option directly.
async function choose(page: Page, label: string, option: string) {
  const field = page.getByLabel(label, { exact: true });
  if ((await field.evaluate((element) => element.tagName)) === 'SELECT') {
    await field.selectOption({ label: option });
    return;
  }
  await field.click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

test.afterAll(() => {
  // An empty retained message deletes the retained status.
  publishBoardStatus('-r -n');
});

test('first run: user, login, home, a file_tracker instance and its board', async ({ page, request }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  // The stack was just started: wait for Django behind nginx.
  await expect
    .poll(async () => (await request.get('/api/health').catch(() => null))?.status() ?? 0, { timeout: 60_000 })
    .toBe(200);

  // First run: with no user yet, the app sends us to /setup. Creating the user
  // logs in with it and lands on the home page. The labels carry Mantine's
  // " *" (the fields are required), hence the regular expressions.
  await page.goto('/');
  await expect(page).toHaveURL(/\/setup$/);
  await page.getByLabel(/^Usuario/).fill(USERNAME);
  await page.getByLabel(/^Contraseña/).fill(PASSWORD);
  await page.getByLabel(/^Confirmación/).fill(PASSWORD);
  await page.getByRole('button', { name: 'Crear usuario' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: 'Inicio', exact: true })).toBeVisible();

  // Log out and back in: the login returns to where the session ended.
  await page.getByRole('button', { name: 'Cerrar sesión' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel(/^Usuario/).fill(USERNAME);
  await page.getByLabel(/^Contraseña/).fill(PASSWORD);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: 'Inicio', exact: true })).toBeVisible();

  // A file_tracker instance with a valid pair (ENU + POLAR). The labels come
  // from the API, so the test does not repeat the handler's texts.
  const headers = await apiHeaders(request);
  const types: PluginType[] = await (await request.get('/api/plugin-types', { headers })).json();
  const fileTracker = types.find((pluginType) => pluginType.type === 'file_tracker');
  if (!fileTracker) throw new Error('GET /api/plugin-types does not list file_tracker');
  const coordType = choice(fileTracker, 'coord_type', 'ENU');
  const coordFormat = choice(fileTracker, 'coord_format', 'POLAR');

  await page.getByRole('link', { name: 'Instancias', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Instancias', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Nueva instancia', exact: true }).click();
  await expect(page).toHaveURL(/\/plugins\/new$/);
  await choose(page, 'Tipo', fileTracker.label);
  await page.getByLabel('Nombre', { exact: true }).fill(PLUGIN_NAME);
  await choose(page, coordType.label, coordType.text);
  await choose(page, coordFormat.label, coordFormat.text);
  await page.getByRole('button', { name: 'Crear instancia' }).click();

  // Its detail page, and what the server stored.
  await expect(page).toHaveURL(/\/plugins\/[0-9a-f-]{36}$/);
  await expect(page.getByRole('heading', { name: PLUGIN_NAME, exact: true })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Archivo de coordenadas' })).toBeVisible();
  const uuid = new URL(page.url()).pathname.split('/').pop();
  const stored = await (await request.get(`/api/plugins/${uuid}`, { headers })).json();
  expect(stored).toMatchObject({
    name: PLUGIN_NAME,
    plugin_type: 'file_tracker',
    status: 'STOPPED',
    config: { coord_type: coordType.value, coord_format: coordFormat.value },
  });

  // Boards: the scan finds the simulated board and the list shows it.
  publishBoardStatus('-r -m online');
  await page.getByRole('link', { name: 'Placas', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Placas', exact: true })).toBeVisible();
  const scan = page.waitForResponse((response) => response.url().endsWith('/api/boards/scan'));
  await page.getByRole('button', { name: 'Buscar placas' }).click();
  expect((await scan).status()).toBe(200);
  await expect(page.getByText(BOARD_ID).first()).toBeVisible();

  // Bind that board to the instance from its detail (PUT /api/plugins/<uuid>/board, PR #32).
  await page.getByRole('link', { name: 'Instancias', exact: true }).click();
  await page.getByRole('link', { name: PLUGIN_NAME, exact: true }).click();
  await expect(page.getByRole('heading', { name: PLUGIN_NAME, exact: true })).toBeVisible();
  const boardSelect = page.getByLabel('Placa', { exact: true });
  await expect(boardSelect.locator(`option[value="${BOARD_ID}"]`)).toHaveCount(1);
  const bind = page.waitForResponse(
    (response) => response.url().endsWith(`/api/plugins/${uuid}/board`) && response.request().method() === 'PUT',
  );
  await boardSelect.selectOption(BOARD_ID);
  expect((await bind).status()).toBe(200);
  await expect(page.getByText('Placa vinculada.')).toBeVisible();
  const bound = await (await request.get(`/api/plugins/${uuid}`, { headers })).json();
  expect(bound.board).toBe(BOARD_ID);

  expect(pageErrors).toEqual([]);
});
