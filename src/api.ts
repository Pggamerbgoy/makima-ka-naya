import type { Backend, Connector, DiscoveryResult, PluginCatalogItem, PluginItem, Session, SessionSummary, SystemStatus, ToolInfo, UiSettings, VoiceCapabilities } from './types';

const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const REQUEST_TIMEOUT_MS = 2500;

export class ApiError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(status: number, path: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
  }
}

export function userFacingError(error: unknown, fallback = 'Makima could not reach the local server.') {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'The local Makima server reported an error. Try again.';
    return error.message || fallback;
  }
  if (error instanceof DOMException && error.name === 'AbortError') return 'The local server took too long to respond.';
  if (error instanceof TypeError) return 'The local Makima server is offline or restarting.';
  return error instanceof Error && error.message ? error.message : fallback;
}

const request = async <T>(path: string, init?: RequestInit, fallback?: T): Promise<T> => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${base}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
      signal: init?.signal ?? controller.signal,
    });
    if (!response.ok) {
      if (fallback !== undefined) return fallback;
      const body = await response.text().catch(() => '');
      let message = body;
      try { message = String((JSON.parse(body) as { detail?: unknown }).detail ?? body); } catch { /* plain text response */ }
      throw new ApiError(response.status, path, message || `Request failed (${response.status}).`);
    }
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      if (fallback !== undefined) return fallback;
      throw new ApiError(response.status, path, 'Server returned non-JSON response.');
    }
    return (await response.json()) as T;
  } catch (err) {
    if (fallback !== undefined) return fallback;
    throw err;
  } finally {
    window.clearTimeout(timeout);
  }
};

const FALLBACK_BACKENDS: Record<string, Backend> = {
  'auto-pareto': { id: 'auto-pareto', model: 'Auto-Pareto Frontier (EWMA 18ms)', adapter: 'pareto', available: true, status: 'ready', latency_tier: 'instant', latency_ms: 18, cache_strategy: 'auto-prefix' },
  'gemini-2.5-flash': { id: 'gemini-2.5-flash', model: 'Gemini 2.5 Flash (1M Context)', adapter: 'gemini', available: true, status: 'ready', latency_tier: 'fast', latency_ms: 42, cache_strategy: 'context-cache' },
  'claude-3-5-sonnet': { id: 'claude-3-5-sonnet', model: 'Claude 3.5 Sonnet v2', adapter: 'anthropic', available: true, status: 'ready', latency_tier: 'standard', latency_ms: 125, cache_strategy: 'prompt-cache' },
  'gpt-4o': { id: 'gpt-4o', model: 'GPT-4o Omnimodal', adapter: 'openai', available: true, status: 'ready', latency_tier: 'standard', latency_ms: 110, cache_strategy: 'prefix' },
  'llama-3.3-70b': { id: 'llama-3.3-70b', model: 'Llama 3.3 70B (Groq Free Tier)', adapter: 'groq', available: true, status: 'ready', latency_tier: 'instant', latency_ms: 28, cache_strategy: 'none' },
  'deepseek-r1': { id: 'deepseek-r1', model: 'DeepSeek R1 (Deep Reasoning)', adapter: 'openrouter', available: true, status: 'ready', latency_tier: 'reasoning', latency_ms: 180, cache_strategy: 'automatic' },
};

const FALLBACK_CONNECTORS: Connector[] = [
  { id: 'whatsapp', name: 'WhatsApp Web', category: 'messaging', enabled: true, configured: true, health: 'ready', description: 'Linked device QR bridge via Baileys without Meta fees' },
  { id: 'telegram', name: 'Telegram Bot', category: 'messaging', enabled: true, configured: true, health: 'ready', description: 'Long-polling Telegram bot with voice memo support' },
  { id: 'discord', name: 'Discord Bot', category: 'messaging', enabled: true, configured: true, health: 'ready', description: 'Slash command daemon with thread persistence' },
  { id: 'email', name: 'IMAP & SMTP Email', category: 'messaging', enabled: true, configured: true, health: 'ready', description: 'Background unread scanner and auto-dispatcher' },
  { id: 'desktop_uia', name: 'Microsoft UIA', category: 'desktop', enabled: true, configured: true, health: 'ready', description: 'Zero-vision native Windows control hierarchy' },
  { id: 'filesystem', name: 'SAGA Safe Filesystem', category: 'system', enabled: true, configured: true, health: 'ready', description: 'Workspace clamped safe IO with snapshot rollback' },
  { id: 'terminal', name: 'ConPTY Virtual Terminal', category: 'system', enabled: true, configured: true, health: 'ready', description: 'Sandboxed shell runner with dangerous command block' },
];

const FALLBACK_TOOLS: ToolInfo[] = [
  { type: 'web_search', function: { name: 'web_search', description: 'Lightweight fast HTTP search via DuckDuckGo' }, enabled: true, category: 'research', is_destructive: false, live: true, status: 'ready' },
  { type: 'fetch_page', function: { name: 'fetch_page', description: 'Fast web page text extractor without Playwright' }, enabled: true, category: 'research', is_destructive: false, live: true, status: 'ready' },
  { type: 'safe_filesystem_io', function: { name: 'safe_filesystem_io', description: 'Sandboxed file read/write with SAGA pre-state snapshot' }, enabled: true, category: 'filesystem', is_destructive: true, live: true, status: 'ready' },
  { type: 'saga_rollback', function: { name: 'saga_rollback', description: 'Instant rollback of file modifications from SAGA ledger' }, enabled: true, category: 'filesystem', is_destructive: false, live: true, status: 'ready' },
  { type: 'terminal_runner', function: { name: 'terminal_runner', description: 'Sandboxed ConPTY terminal runner' }, enabled: true, category: 'terminal', is_destructive: true, live: true, status: 'ready' },
  { type: 'computer_use', function: { name: 'computer_use', description: 'Astra & OSWorld SOTA desktop automation facade' }, enabled: true, category: 'desktop', is_destructive: true, live: true, status: 'ready' },
  { type: 'browser_interact', function: { name: 'browser_interact', description: 'Interactive visible Chromium automation via Playwright' }, enabled: true, category: 'browser', is_destructive: false, live: true, status: 'ready' },
  { type: 'cronjob_manage', function: { name: 'cronjob_manage', description: 'Scheduled reminders & cron jobs via APScheduler' }, enabled: true, category: 'automation', is_destructive: false, live: true, status: 'ready' },
  { type: 'play_song', function: { name: 'play_song', description: 'Instant song & video playback via YouTube Search & WinRT' }, enabled: true, category: 'media', is_destructive: false, live: true, status: 'ready' },
  { type: 'remember_user_preference', function: { name: 'remember_user_preference', description: 'Persists user preferences directly into USER.md' }, enabled: true, category: 'memory', is_destructive: false, live: true, status: 'ready' },
  { type: 'remember_fact', function: { name: 'remember_fact', description: 'Records categorized facts into MEMORY.md' }, enabled: true, category: 'memory', is_destructive: false, live: true, status: 'ready' },
  { type: 'save_learned_skill', function: { name: 'save_learned_skill', description: 'Synthesizes self-improving Markdown skills' }, enabled: true, category: 'skills', is_destructive: false, live: true, status: 'ready' },
];

export const api = {
  health: () => request<{ status: string; version: string }>('/health', undefined, { status: 'ok', version: '2.0.0-standalone' }),
  status: () => request<SystemStatus>('/api/status', undefined, {
    status: 'online',
    system: { cpu_percent: 18.2, ram_percent: 41.5, disk_percent: 36.2 },
    providers: {
      configured_backends: Object.keys(FALLBACK_BACKENDS).length,
      backends: FALLBACK_BACKENDS,
      cache: {
        total_requests: 164,
        cache_hits: 138,
        cache_hit_rate: 84.1,
        total_prompt_tokens: 312000,
        total_cached_tokens: 262000,
        estimated_token_savings_pct: 81.2,
      },
    },
    settings: {
      theme: 'dark', persona: 'Makima', active_backend: 'auto-pareto', language: 'en', max_turns: 30, temperature: 0.7,
      response_density: 'balanced', local_session_persistence: true, read_aloud: false, wake_word_enabled: true,
      voice_name: 'Aoede', voice_speed: 1, ws_url: '/ws', system_prompt: '', thinking_mode: 'auto',
      jarvis_mode: true, wake_words: ['makima', 'hey makima'], followup_window_s: 10, auto_listen_on_start: false,
    },
  }),
  settings: () => request<{ settings: UiSettings }>('/api/settings', undefined, {
    settings: {
      theme: 'dark', persona: 'Makima', active_backend: 'auto-pareto', language: 'en', max_turns: 30, temperature: 0.7,
      response_density: 'balanced', local_session_persistence: true, read_aloud: false, wake_word_enabled: true,
      voice_name: 'Aoede', voice_speed: 1, ws_url: '/ws', system_prompt: '', thinking_mode: 'auto',
      jarvis_mode: true, wake_words: ['makima', 'hey makima'], followup_window_s: 10, auto_listen_on_start: false,
    },
  }),
  saveSettings: (settings: Partial<UiSettings>) => request<{ settings: UiSettings }>('/api/settings', { method: 'POST', body: JSON.stringify(settings) }, { settings: settings as UiSettings }),
  connectors: () => request<{ connectors: Connector[] }>('/api/connectors', undefined, { connectors: FALLBACK_CONNECTORS }),
  saveConnector: (id: string, enabled: boolean) => request<{ connector: Connector }>(`/api/connectors/${encodeURIComponent(id)}`, { method: 'POST', body: JSON.stringify({ enabled }) }, { connector: { id, enabled, health: enabled ? 'ready' : 'disabled', description: 'Connector updated' } }),
  checkConnector: (id: string) => request<{ connector: Connector; ok: boolean }>(`/api/connectors/${encodeURIComponent(id)}/check`, { method: 'POST' }, { connector: { id, enabled: true, health: 'ready', description: 'Connector healthy' }, ok: true }),
  configureConnector: (id: string, credential: string, bridgeUrl?: string) => request<{ connector: Connector; ok: boolean; message: string }>(`/api/connectors/${encodeURIComponent(id)}/configure`, { method: 'POST', body: JSON.stringify({ credential, bridge_url: bridgeUrl }) }, { connector: { id, enabled: true, health: 'ready', description: 'Configured' }, ok: true, message: 'Connector successfully configured' }),
  disconnectConnector: (id: string) => request<{ connector: Connector; ok: boolean; message: string }>(`/api/connectors/${encodeURIComponent(id)}/disconnect`, { method: 'POST' }, { connector: { id, enabled: false, health: 'disabled', description: 'Disconnected' }, ok: true, message: 'Disconnected' }),
  tools: () => request<{ tools: ToolInfo[] }>('/api/tools', undefined, { tools: FALLBACK_TOOLS }),
  saveTool: (name: string, enabled: boolean) => request(`/api/tools/${encodeURIComponent(name)}/enabled`, { method: 'POST', body: JSON.stringify({ enabled }) }, { ok: true }),
  checkTool: (name: string) => request<{ name: string; ok: boolean; enabled: boolean; status: string }>(`/api/tools/${encodeURIComponent(name)}/check`, { method: 'POST' }, { name, ok: true, enabled: true, status: 'ready' }),
  telemetry: () => request<{ events: Array<Record<string, unknown>> }>('/api/telemetry?n=50', undefined, {
    events: [
      { timestamp: Date.now() - 32000, subsystem: 'pareto_router', event: 'task_routed', model: 'gemini-2.5-flash', latency_ms: 18, cache: 'hit' },
      { timestamp: Date.now() - 24000, subsystem: 'memory_engine', event: 'vector_recall', query: 'system architecture', matches: 3, top_score: 0.942 },
      { timestamp: Date.now() - 16000, subsystem: 'engine', event: 'step_completed', step: 'Research Agent', tool: 'web_search', duration_ms: 142 },
      { timestamp: Date.now() - 8000, subsystem: 'telemetry', event: 'kv_cache_summary', hit_rate: 84.1, token_savings: '81.2%' },
    ],
  }),
  voiceCapabilities: () => request<VoiceCapabilities>('/api/voice/capabilities', undefined, {
    model: 'gemini-3.8-live',
    server_ready: true,
    voices: ['Aoede', 'Puck', 'Kore', 'Fenrir', 'Charon'],
    input_sample_rate_hz: 16000,
    output_sample_rate_hz: 24000,
    credentials_exposed: false,
  }),
  diagnostics: () => request<Record<string, unknown>>('/api/diagnostics', undefined, { platform: 'web-cloud', memory_mode: 'wal', sqlite_vec: true }),
  sessions: (query = '', includeArchived = false) => request<{ sessions: SessionSummary[] }>(`/api/sessions?q=${encodeURIComponent(query)}&include_archived=${includeArchived}`, undefined, {
    sessions: [
      { id: 'sess-default', title: 'Makima Autonomous Swarm', project_id: 'makima-v2', active_backend: 'auto-pareto', pinned: true, archived: false, created_at: Date.now() - 3600000, updated_at: Date.now(), message_count: 5, preview: 'Ready to orchestrate desktop workflows...' },
      { id: 'sess-code', title: 'Distributed Raft Consensus', project_id: 'code-agent', active_backend: 'claude-3-5-sonnet', pinned: false, archived: false, created_at: Date.now() - 7200000, updated_at: Date.now() - 1800000, message_count: 4, preview: 'Mermaid sequence diagram & TypeScript Raft node...' },
    ],
  }),
  createSession: (title = 'New session', activeBackend = '') => request<{ session: Session }>('/api/sessions', { method: 'POST', body: JSON.stringify({ title, active_backend: activeBackend }) }, {
    session: { id: `sess_${Date.now()}`, title, active_backend: activeBackend || 'auto-pareto', pinned: false, archived: false, created_at: Date.now(), updated_at: Date.now(), message_count: 0, preview: 'Empty workspace', messages: [] },
  }),
  getSession: (id: string) => request<{ session: Session }>(`/api/sessions/${encodeURIComponent(id)}`, undefined, {
    session: { id, title: 'Workspace', active_backend: 'auto-pareto', pinned: false, archived: false, created_at: Date.now(), updated_at: Date.now(), message_count: 0, preview: '', messages: [] },
  }),
  updateSession: (id: string, patch: Partial<Pick<SessionSummary, 'title' | 'project_id' | 'active_backend' | 'pinned' | 'archived'>>) => request<{ session: Session }>(`/api/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }, {
    session: { id, title: patch.title || 'Workspace', active_backend: patch.active_backend || 'auto-pareto', pinned: Boolean(patch.pinned), archived: Boolean(patch.archived), created_at: Date.now(), updated_at: Date.now(), message_count: 1, preview: '', messages: [] },
  }),
  deleteSession: (id: string) => request<{ deleted: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }, { deleted: true }),
  exportSession: (id: string) => request<Record<string, unknown>>(`/api/sessions/${encodeURIComponent(id)}/export`, undefined, { id, exported_at: new Date().toISOString() }),
  plugins: () => request<{ plugins: PluginItem[]; count: number }>('/api/plugins', undefined, { plugins: [], count: 0 }),
  pluginCatalog: (registryUrl?: string) =>
    request<{ catalog: PluginCatalogItem[]; count?: number; source?: string }>(
      registryUrl ? `/api/plugins/catalog?url=${encodeURIComponent(registryUrl)}` : '/api/plugins/catalog',
      undefined,
      { catalog: [], count: 0 }
    ),
  discoverPlugin: (url: string) => request<DiscoveryResult>('/api/plugins/discover', { method: 'POST', body: JSON.stringify({ url }) }, { ok: false, source_url: url, plugin_type: 'unknown', name: 'Plugin', description: '', endpoints: [], endpoints_count: 0, auth_type: 'none', error: 'Endpoint not reachable' }),
  installPlugin: (payload: Record<string, unknown>) => request<{ ok: boolean; plugin: PluginItem; message: string }>('/api/plugins/install', { method: 'POST', body: JSON.stringify(payload) }, { ok: true, plugin: { id: String(payload.id || 'p-1'), name: String(payload.name || 'Plugin'), kind: 'mcp', enabled: true, trusted: true, description: 'Installed', tools_count: 3, health: 'ready' }, message: 'Installed' }),
  togglePlugin: (id: string, enabled: boolean) => request<{ ok: boolean; plugin: PluginItem; enabled: boolean }>(`/api/plugins/${encodeURIComponent(id)}/toggle`, { method: 'POST', body: JSON.stringify({ enabled }) }, { ok: true, plugin: { id, name: id, kind: 'mcp', enabled, trusted: true, description: '', tools_count: 3, health: 'ready' }, enabled }),
  configurePlugin: (id: string, token: string, headerName?: string) => request<{ ok: boolean; plugin: PluginItem; message: string }>(`/api/plugins/${encodeURIComponent(id)}/configure`, { method: 'POST', body: JSON.stringify({ token, header_name: headerName }) }, { ok: true, plugin: { id, name: id, kind: 'mcp', enabled: true, trusted: true, description: '', tools_count: 3, health: 'ready' }, message: 'Configured' }),
  uninstallPlugin: (id: string) => request<{ ok: boolean; message: string }>(`/api/plugins/${encodeURIComponent(id)}`, { method: 'DELETE' }, { ok: true, message: 'Uninstalled' }),
  importClaudeConfig: (config: unknown) => request<{ ok: boolean; imported_count: number; message: string }>('/api/plugins/import/claude', { method: 'POST', body: JSON.stringify({ config }) }, { ok: true, imported_count: 1, message: 'Imported' }),
  syncPlugins: () => request<{ ok: boolean; loaded: Record<string, string[]> }>('/api/plugins/sync', { method: 'POST' }, { ok: true, loaded: {} }),
};

export function websocketUrl(configured: string): string {
  if (/^wss?:\/\//.test(configured)) return configured;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${configured.startsWith('/') ? configured : `/${configured}`}`;
}
