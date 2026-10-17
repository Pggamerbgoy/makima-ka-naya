import type { Backend, Connector, DiscoveryResult, PluginCatalogItem, PluginItem, Session, SessionSummary, SystemStatus, ToolInfo, UiSettings, VoiceCapabilities } from './types';

const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');
const REQUEST_TIMEOUT_MS = 12_000;

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

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${base}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
      signal: init?.signal ?? controller.signal,
    });
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      let message = body;
      try { message = String((JSON.parse(body) as { detail?: unknown }).detail ?? body); } catch { /* plain text response */ }
      throw new ApiError(response.status, path, message || `Request failed (${response.status}).`);
    }
    return response.json() as Promise<T>;
  } finally {
    window.clearTimeout(timeout);
  }
};

export const api = {
  health: () => request<{ status: string; version: string }>('/health'),
  status: () => request<SystemStatus>('/api/status'),
  settings: () => request<{ settings: UiSettings }>('/api/settings'),
  saveSettings: (settings: Partial<UiSettings>) => request<{ settings: UiSettings }>('/api/settings', { method: 'POST', body: JSON.stringify(settings) }),
  connectors: () => request<{ connectors: Connector[] }>('/api/connectors'),
  saveConnector: (id: string, enabled: boolean) => request<{ connector: Connector }>(`/api/connectors/${encodeURIComponent(id)}`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  checkConnector: (id: string) => request<{ connector: Connector; ok: boolean }>(`/api/connectors/${encodeURIComponent(id)}/check`, { method: 'POST' }),
  configureConnector: (id: string, credential: string, bridgeUrl?: string) => request<{ connector: Connector; ok: boolean; message: string }>(`/api/connectors/${encodeURIComponent(id)}/configure`, { method: 'POST', body: JSON.stringify({ credential, bridge_url: bridgeUrl }) }),
  disconnectConnector: (id: string) => request<{ connector: Connector; ok: boolean; message: string }>(`/api/connectors/${encodeURIComponent(id)}/disconnect`, { method: 'POST' }),
  tools: () => request<{ tools: ToolInfo[] }>('/api/tools'),
  saveTool: (name: string, enabled: boolean) => request(`/api/tools/${encodeURIComponent(name)}/enabled`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  checkTool: (name: string) => request<{ name: string; ok: boolean; enabled: boolean; status: string }>(`/api/tools/${encodeURIComponent(name)}/check`, { method: 'POST' }),
  telemetry: () => request<{ events: Array<Record<string, unknown>> }>('/api/telemetry?n=50'),
  voiceCapabilities: () => request<VoiceCapabilities>('/api/voice/capabilities'),
  diagnostics: () => request<Record<string, unknown>>('/api/diagnostics'),
  sessions: (query = '', includeArchived = false) => request<{ sessions: SessionSummary[] }>(`/api/sessions?q=${encodeURIComponent(query)}&include_archived=${includeArchived}`),
  createSession: (title = 'New session', activeBackend = '') => request<{ session: Session }>('/api/sessions', { method: 'POST', body: JSON.stringify({ title, active_backend: activeBackend }) }),
  getSession: (id: string) => request<{ session: Session }>(`/api/sessions/${encodeURIComponent(id)}`),
  updateSession: (id: string, patch: Partial<Pick<SessionSummary, 'title' | 'project_id' | 'active_backend' | 'pinned' | 'archived'>>) => request<{ session: Session }>(`/api/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteSession: (id: string) => request<{ deleted: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  exportSession: (id: string) => request<Record<string, unknown>>(`/api/sessions/${encodeURIComponent(id)}/export`),
  plugins: () => request<{ plugins: PluginItem[]; count: number }>('/api/plugins'),
  pluginCatalog: (registryUrl?: string) =>
    request<{ catalog: PluginCatalogItem[]; count?: number; source?: string }>(
      registryUrl ? `/api/plugins/catalog?url=${encodeURIComponent(registryUrl)}` : '/api/plugins/catalog'
    ),
  discoverPlugin: (url: string) => request<DiscoveryResult>('/api/plugins/discover', { method: 'POST', body: JSON.stringify({ url }) }),
  installPlugin: (payload: Record<string, unknown>) => request<{ ok: boolean; plugin: PluginItem; message: string }>('/api/plugins/install', { method: 'POST', body: JSON.stringify(payload) }),
  togglePlugin: (id: string, enabled: boolean) => request<{ ok: boolean; plugin: PluginItem; enabled: boolean }>(`/api/plugins/${encodeURIComponent(id)}/toggle`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  configurePlugin: (id: string, token: string, headerName?: string) => request<{ ok: boolean; plugin: PluginItem; message: string }>(`/api/plugins/${encodeURIComponent(id)}/configure`, { method: 'POST', body: JSON.stringify({ token, header_name: headerName }) }),
  uninstallPlugin: (id: string) => request<{ ok: boolean; message: string }>(`/api/plugins/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  importClaudeConfig: (config: unknown) => request<{ ok: boolean; imported_count: number; message: string }>('/api/plugins/import/claude', { method: 'POST', body: JSON.stringify({ config }) }),
  syncPlugins: () => request<{ ok: boolean; loaded: Record<string, string[]> }>('/api/plugins/sync', { method: 'POST' }),
};

export function websocketUrl(configured: string): string {
  if (/^wss?:\/\//.test(configured)) return configured;
  if (import.meta.env.DEV) return `ws://127.0.0.1:8000${configured.startsWith('/') ? configured : `/${configured}`}`;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${configured.startsWith('/') ? configured : `/${configured}`}`;
}
