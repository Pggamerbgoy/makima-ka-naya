import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const settings = {
  theme: 'dark', persona: 'Makima', active_backend: 'demo', language: 'en', max_turns: 15,
  temperature: 0.7, response_density: 'balanced', local_session_persistence: true,
  read_aloud: false, wake_word_enabled: true, voice_name: 'Aoede', voice_speed: 1,
  ws_url: '/ws', system_prompt: '',
};

async function mockLocalApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const body = method === 'POST' ? JSON.parse(route.request().postData() || '{}') as Record<string, unknown> : {};
    let payload: unknown = {};
    if (url.pathname === '/api/status') payload = { status: 'operational', system: { cpu_percent: 12, ram_percent: 42, disk_percent: 38 }, providers: { configured_backends: 1, backends: { demo: { id: 'demo', model: 'Demo model', adapter: 'mock', available: true, status: 'available', latency_tier: 'fast' } } }, settings };
    else if (url.pathname === '/api/settings' && method === 'GET') payload = { settings };
    else if (url.pathname === '/api/settings' && method === 'POST') payload = { settings: { ...settings, ...body }, saved: true };
    else if (url.pathname === '/api/connectors') payload = { connectors: [{ id: 'whatsapp', name: 'WhatsApp Web', category: 'messaging', auth_type: 'phone', enabled: false, configured: false, health: 'not_configured', description: 'Send and receive WhatsApp messages.', detail: 'Authorization required.', supported: true }, { id: 'github', name: 'GitHub', category: 'developer', auth_type: 'token', enabled: false, configured: false, health: 'not_configured', description: 'Repositories and pull requests.', detail: 'Authorization required.', supported: true }] };
    else if (url.pathname === '/api/tools') payload = { tools: [{ type: 'function', function: { name: 'search_demo', description: 'Search demo data' }, enabled: true, category: 'search', is_destructive: false, live: true, status: 'ready' }] };
    else if (url.pathname === '/api/telemetry') payload = { events: [] };
    else if (url.pathname === '/api/voice/capabilities') payload = { model: 'Gemini Live', server_ready: false, voices: ['Aoede'], input_sample_rate_hz: 16000, output_sample_rate_hz: 24000, credentials_exposed: false };
    else if (url.pathname === '/api/diagnostics') payload = { credentials_exposed: false };
    else if (url.pathname === '/api/sessions' && method === 'GET') payload = { sessions: [{ id: 'sess-1', title: 'Python Snippet', active_backend: 'demo', pinned: false, archived: false, created_at: Date.now(), updated_at: Date.now(), message_count: 2, preview: 'code snippet' }] };
    else if (url.pathname === '/api/sessions/sess-1') payload = { session: { id: 'sess-1', title: 'Python Snippet', active_backend: 'demo', pinned: false, archived: false, created_at: Date.now(), updated_at: Date.now(), message_count: 2, preview: 'code snippet', messages: [{ id: 'msg-1', role: 'user', content: 'Generate python code', created_at: 1000 }, { id: 'msg-2', role: 'assistant', content: 'Here is your snippet:\n\n```python\nprint("canvas test")\n```', created_at: 1001 }] } };
    else if (url.pathname.startsWith('/api/connectors/')) payload = { connector: { id: url.pathname.split('/')[3], name: url.pathname.split('/')[3] === 'whatsapp' ? 'WhatsApp Web' : 'GitHub', enabled: Boolean(body.enabled ?? true), configured: false, health: Boolean(body.enabled ?? true) ? 'not_configured' : 'disabled', description: 'External integration', detail: 'Authorization required.' }, ok: false };
    else if (url.pathname.startsWith('/api/tools/')) payload = { name: 'search_demo', enabled: Boolean(body.enabled ?? true), status: 'ready', ok: true };
    else { await route.continue(); return; }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  await page.route('**/health', async (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', version: '2.0.0' }) }));
}

test.beforeEach(async ({ page }) => { await mockLocalApi(page); });

test('opens every settings surface and closes with Escape', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('What shall we make?')).toBeVisible();
  await page.getByRole('button', { name: 'Settings' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  for (const label of ['Models', 'General', 'Connectors', 'Voice', 'Developer', 'Tools']) {
    await dialog.getByRole('tab', { name: new RegExp(`^${label}`) }).click();
    await expect(dialog.getByRole('heading', { name: label, exact: true })).toBeVisible();
  }
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('shows real app connectors and file attachment controls', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('tab', { name: /^Connectors/ }).click();
  await expect(dialog.getByText('WhatsApp Web')).toBeVisible();
  await expect(dialog.getByText('GitHub')).toBeVisible();
  await dialog.getByRole('button', { name: /Close settings/ }).click();
  await expect(page.getByRole('button', { name: 'Attach files' })).toBeVisible();
});

test('accepts a bounded text attachment before sending', async ({ page }) => {
  await page.goto('/');
  await page.locator('input[type="file"]').setInputFiles({ name: 'notes.md', mimeType: 'text/markdown', buffer: Buffer.from('# Release notes\nReady') });
  await expect(page.getByText('notes.md')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Remove notes.md' })).toBeVisible();
});

test('persists a general setting and keeps the modal accessible', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('tab', { name: /^General/ }).click();
  await dialog.getByLabel('Theme').selectOption('light');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  const results = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
  expect(results.violations).toEqual([]);
});

test('supports narrow desktop and reduced-motion rendering', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 640, height: 720 });
  await page.goto('/');
  await expect(page.getByText('What shall we make?')).toBeVisible();
  await expect(page.locator('.sidebar')).toBeVisible();
  const duration = await page.locator('.welcome').evaluate((node) => getComputedStyle(node).animationDuration);
  expect(['0.001ms', '1e-06s']).toContain(duration);
});

test('opens interactive Canvas split editor, edits buffer, toggles modes, and saves changes', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Python Snippet/ }).click();
  await expect(page.getByText('print("canvas test")').first()).toBeVisible();

  await page.getByRole('button', { name: 'Open in Canvas' }).first().click();
  const canvasDrawer = page.locator('aside[aria-label="Canvas Workspace"]');
  await expect(canvasDrawer).toBeVisible();
  await expect(canvasDrawer.getByText('● Synced')).toBeVisible();

  await canvasDrawer.getByRole('tab', { name: 'Split' }).click();
  await expect(canvasDrawer.locator('.canvas-workspace-body.mode-split')).toBeVisible();

  await canvasDrawer.getByRole('tab', { name: 'Preview' }).click();
  await expect(canvasDrawer.locator('.canvas-workspace-body.mode-preview')).toBeVisible();

  await canvasDrawer.getByRole('tab', { name: 'Edit' }).click();
  await expect(canvasDrawer.locator('.canvas-workspace-body.mode-edit')).toBeVisible();

  const textarea = canvasDrawer.getByLabel('Canvas content editor');
  await textarea.fill('print("canvas test - modified")');
  await expect(canvasDrawer.getByText('● Unsaved edits')).toBeVisible();

  await canvasDrawer.getByRole('button', { name: 'Save changes' }).click();
  await expect(canvasDrawer.getByText('● Synced')).toBeVisible();

  await expect(canvasDrawer.getByText('Makima Canvas Assistant')).toBeVisible();
  await expect(canvasDrawer.getByText('⚡ Fix bugs & optimize')).toBeVisible();
  await expect(canvasDrawer.getByText('📝 Add comments & docs')).toBeVisible();

  await canvasDrawer.getByRole('button', { name: 'Close Canvas' }).click();
  await expect(canvasDrawer).toBeHidden();
});
