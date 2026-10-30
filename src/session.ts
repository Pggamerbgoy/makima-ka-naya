import type { UiSettings } from './types';

export const SESSION_VERSION = 1;
export const MAX_SESSION_BYTES = 2_000_000;
const SETTINGS_KEY = 'makima.settings';
const MESSAGES_KEY = 'makima.messages';

export type PersistedSession<TMessage> = {
  version: number;
  settings?: Partial<UiSettings>;
  messages?: TMessage[];
};

function parse<T>(value: string | null): T | undefined {
  if (!value) return undefined;
  try { return JSON.parse(value) as T; } catch { return undefined; }
}

export function loadSession<TMessage extends { pending?: boolean; content?: string }>(): { settings?: Partial<UiSettings>; messages: TMessage[] } {
  const envelope = parse<PersistedSession<TMessage>>(localStorage.getItem('makima.session'));
  const rawMessages: TMessage[] = (envelope?.version === SESSION_VERSION
    ? envelope.messages
    : parse<TMessage[]>(localStorage.getItem(MESSAGES_KEY))) ?? [];

  // Sanitize: messages loaded from cold storage must never be stuck in a pending generating state.
  // Empty pending placeholders from interrupted turns are filtered out; messages with content have pending cleared.
  const sanitizedMessages = rawMessages
    .filter((m) => !(m.pending && !m.content))
    .map((m) => (m.pending ? { ...m, pending: false } : m));

  const settings = envelope?.version === SESSION_VERSION
    ? envelope.settings
    : parse<Partial<UiSettings>>(localStorage.getItem(SETTINGS_KEY));

  return { settings, messages: sanitizedMessages };
}

export function saveSession<TMessage extends { pending?: boolean; content?: string }>(settings: UiSettings, messages: TMessage[]): void {
  // Never persist temporary pending: true state or empty in-flight stubs to localStorage
  const persistable = messages
    .filter((m) => !(m.pending && !m.content))
    .map((m) => (m.pending ? { ...m, pending: false } : m));

  const payload: PersistedSession<TMessage> = { version: SESSION_VERSION, settings, messages: persistable };
  const encoded = JSON.stringify(payload);
  if (encoded.length > MAX_SESSION_BYTES) {
    const trimmed = { ...payload, messages: persistable.slice(-20) };
    localStorage.setItem('makima.session', JSON.stringify(trimmed));
    return;
  }
  localStorage.setItem('makima.session', encoded);
}

export function clearSession(): void {
  localStorage.removeItem('makima.session');
  localStorage.removeItem(SETTINGS_KEY);
  localStorage.removeItem(MESSAGES_KEY);
}
