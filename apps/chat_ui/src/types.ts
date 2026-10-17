export type ArtifactKind = 'markdown' | 'image' | 'video' | 'audio' | 'chart' | 'diagram' | 'table' | 'code' | 'html' | 'document' | 'diff' | 'log' | 'json';

export type Artifact = {
  id: string;
  kind: ArtifactKind;
  title?: string;
  mime_type?: string;
  content?: string;
  url?: string;
  language?: string;
  data?: unknown;
  downloadable?: boolean;
  metadata?: Record<string, unknown>;
};

export type Backend = {
  id: string; model: string; adapter: string; available: boolean; status: string;
  quota_exhausted?: boolean; circuit_breaker?: string; latency_tier?: string; latency_ms?: number;
  cache_strategy?: string;
};

export type UiSettings = {
  theme: 'dark' | 'light'; persona: string; active_backend: string; language: string; max_turns: number;
  temperature: number; response_density: 'compact' | 'balanced' | 'detailed';
  local_session_persistence: boolean; read_aloud: boolean; wake_word_enabled: boolean; voice_name: string;
  voice_speed: number; ws_url: string; system_prompt: string;
  thinking_mode?: 'off' | 'auto' | 'on';
  jarvis_mode?: boolean;
  wake_words?: string[];
  followup_window_s?: number;
  auto_listen_on_start?: boolean;
};

export type ToolInfo = { type: string; function?: { name: string; description?: string }; enabled: boolean; category: string; is_destructive: boolean; live: boolean; source?: string; status?: string };
export type Connector = { id: string; name?: string; category?: string; auth_type?: string; enabled: boolean; configured?: boolean; health: string; description: string; detail?: string; last_checked?: number | null; supported?: boolean };
export type StreamEvent = { type: string; task_id?: string; session_id?: string; [key: string]: unknown };
export type SessionMessage = { id: string; role: 'user' | 'assistant' | 'system'; content: string; parent_message_id?: string | null; variant_id?: string | null; metadata?: Record<string, unknown>; created_at: number };
export type SessionSummary = { id: string; title: string; project_id?: string | null; active_backend: string; pinned: boolean; archived: boolean; created_at: number; updated_at: number; message_count: number; preview: string };
export type Session = SessionSummary & { messages: SessionMessage[] };
export type SystemStatus = {
  status: string;
  system: Record<string, number>;
  providers: {
    configured_backends: number;
    backends: Record<string, Backend>;
    cache?: {
      total_requests: number;
      cache_hits: number;
      cache_hit_rate: number;
      total_prompt_tokens: number;
      total_cached_tokens: number;
      estimated_token_savings_pct: number;
    };
  };
  settings: UiSettings;
};
export type VoiceCapabilities = {
  model: string; server_ready: boolean; voices: string[]; input_sample_rate_hz: number;
  output_sample_rate_hz: number; credentials_exposed: boolean;
};

export const DEFAULT_SETTINGS: UiSettings = {
  theme: 'dark', persona: 'Makima', active_backend: '', language: 'en', max_turns: 30, temperature: 0.7,
  response_density: 'balanced', local_session_persistence: true, read_aloud: false, wake_word_enabled: true,
  voice_name: '', voice_speed: 1, ws_url: '/ws', system_prompt: '', thinking_mode: 'off',
  jarvis_mode: true, wake_words: ['makima', 'hey makima', 'jarvis', 'suno makima'],
  followup_window_s: 10, auto_listen_on_start: true,
};

export type PluginItem = {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
  trusted: boolean;
  description: string;
  icon?: string;
  version?: string;
  author?: string;
  homepage?: string;
  spec_url?: string;
  base_url?: string;
  auth_type?: string;
  auth_configured?: boolean;
  tools_count: number;
  health: string;
  last_error?: string;
};

export type PluginCatalogItem = {
  id: string;
  name: string;
  category: string;
  kind: string;
  description: string;
  icon?: string;
  author?: string;
  homepage?: string;
  auth_type: string;
  auth_hint?: string;
  spec_url?: string;
  base_url?: string;
  spec_raw?: Record<string, unknown>;
  command?: string;
  args?: string[];
};

export type DiscoveryEndpoint = {
  path: string;
  method: string;
  operation_id: string;
  summary: string;
  parameters_count: number;
};

export type DiscoveryResult = {
  ok: boolean;
  source_url: string;
  plugin_type: string;
  name: string;
  description: string;
  icon?: string;
  spec_url?: string;
  spec_raw?: Record<string, unknown>;
  base_url?: string;
  auth_type: string;
  auth_header_name?: string;
  endpoints: DiscoveryEndpoint[];
  endpoints_count: number;
  error?: string;
};

