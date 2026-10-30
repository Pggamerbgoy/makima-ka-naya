import { beforeEach, describe, expect, it } from 'vitest';
import { clearSession, loadSession, saveSession } from './session';
import { DEFAULT_SETTINGS } from './types';

describe('session persistence', () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    } });
  });

  it('migrates the legacy keys into the current loader shape', () => {
    localStorage.setItem('makima.settings', JSON.stringify({ theme: 'light' }));
    localStorage.setItem('makima.messages', JSON.stringify([{ id: '1' }]));
    expect(loadSession()).toEqual({ settings: { theme: 'light' }, messages: [{ id: '1' }] });
  });

  it('writes a versioned bounded envelope and can clear it', () => {
    saveSession(DEFAULT_SETTINGS, Array.from({ length: 100 }, (_, index) => ({ id: String(index), content: 'x'.repeat(50_000) })));
    const stored = JSON.parse(localStorage.getItem('makima.session') ?? '{}') as { version: number; messages: unknown[] };
    expect(stored.version).toBe(1);
    expect(stored.messages.length).toBeLessThanOrEqual(20);
    clearSession();
    expect(localStorage.getItem('makima.session')).toBeNull();
  });

  it('cleans up pending generating stubs on session load to prevent stuck animations', () => {
    localStorage.setItem('makima.session', JSON.stringify({
      version: 1,
      messages: [
        { id: '1', role: 'user', content: 'hello' },
        { id: '2', role: 'assistant', content: '', pending: true },
        { id: '3', role: 'assistant', content: 'partial text', pending: true },
      ],
    }));
    const loaded = loadSession<{ id: string; role?: string; content?: string; pending?: boolean }>();
    expect(loaded.messages).toHaveLength(2);
    expect(loaded.messages[0].id).toBe('1');
    expect(loaded.messages[1].id).toBe('3');
    expect(loaded.messages[1].pending).toBe(false);
  });
});
