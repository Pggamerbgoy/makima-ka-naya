import { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, ChevronDown, Search, Sparkles, X, Zap } from 'lucide-react';
import type { Backend } from '../types';

export interface ModelPickerProps {
  backends: Backend[];
  activeBackend: string;
  onSelect: (backendId: string) => void;
  disabled?: boolean;
}

const PROVIDER_NAMES: Record<string, string> = {
  gemini: 'Google Gemini',
  groq: 'Groq (Ultra-Fast)',
  ollama: 'Ollama (Local)',
  openrouter: 'OpenRouter',
  openai: 'OpenAI Compatible',
  dashscope: 'Alibaba DashScope (Qwen)',
};

export function ModelPicker({ backends, activeBackend, onSelect, disabled = false }: ModelPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close when clicking outside container
  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [isOpen]);

  // Focus search input on open, and handle Escape key to close & refocus trigger
  useEffect(() => {
    if (isOpen) {
      const timer = window.setTimeout(() => searchInputRef.current?.focus(), 50);
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          setIsOpen(false);
          triggerRef.current?.focus();
        }
      };
      window.addEventListener('keydown', handleKeyDown);
      return () => {
        window.clearTimeout(timer);
        window.removeEventListener('keydown', handleKeyDown);
      };
    }
  }, [isOpen]);

  const activeModelObj = useMemo(() => {
    return backends.find((backend) => backend.id === activeBackend);
  }, [backends, activeBackend]);

  const activeLabel = activeModelObj ? (activeModelObj.model || activeModelObj.id) : 'Auto cascade';

  // Group backends dynamically without hardcoding model lists
  const groupedBackends = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    const filtered = backends.filter((backend) => {
      if (!query) return true;
      return (
        (backend.model && backend.model.toLowerCase().includes(query)) ||
        backend.id.toLowerCase().includes(query) ||
        (backend.adapter && backend.adapter.toLowerCase().includes(query))
      );
    });

    const groups: Record<string, Backend[]> = {};
    for (const backend of filtered) {
      let groupKey = backend.adapter || 'other';
      const idLower = backend.id.toLowerCase();
      if (idLower.startsWith('groq') || idLower.includes('_groq_') || backend.adapter === 'groq') {
        groupKey = 'groq';
      } else if (idLower.startsWith('openrouter') || backend.adapter === 'openrouter') {
        groupKey = 'openrouter';
      } else if (idLower.startsWith('gemini') || idLower.includes('google') || backend.adapter === 'gemini') {
        groupKey = 'gemini';
      } else if (idLower.startsWith('ollama') || backend.adapter === 'ollama') {
        groupKey = 'ollama';
      } else if (idLower.includes('dashscope') || idLower.includes('alibaba') || idLower.includes('qwen')) {
        groupKey = 'dashscope';
      }

      const groupName = PROVIDER_NAMES[groupKey] || (groupKey.charAt(0).toUpperCase() + groupKey.slice(1));
      if (!groups[groupName]) {
        groups[groupName] = [];
      }
      groups[groupName].push(backend);
    }
    return groups;
  }, [backends, searchQuery]);

  const showAutoCascade = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) return true;
    return 'auto cascade'.includes(query) || 'pareto'.includes(query) || 'frontier'.includes(query);
  }, [searchQuery]);

  const handleSelect = (backendId: string) => {
    onSelect(backendId);
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className="model-picker-wrap" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`model-picker-trigger ${isOpen ? 'active' : ''}`}
        onClick={() => setIsOpen((open) => !open)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        title={`Active model: ${activeLabel} (Click to change)`}
      >
        {activeBackend ? (
          <Bot size={14} className="model-picker-icon" />
        ) : (
          <Sparkles size={14} className="model-picker-icon accent" />
        )}
        <span className="model-picker-label">{activeLabel}</span>
        {activeModelObj?.latency_tier && (
          <span className={`model-picker-chip ${activeModelObj.latency_tier}`}>{activeModelObj.latency_tier}</span>
        )}
        <ChevronDown size={13} className={`model-picker-chevron ${isOpen ? 'open' : ''}`} />
      </button>

      {isOpen && (
        <div className="model-picker-popover" role="listbox" aria-label="Select AI model">
          <div className="model-picker-header">
            <div className="model-picker-search">
              <Search size={14} className="muted" />
              <input
                ref={searchInputRef}
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search models, providers…"
                aria-label="Filter models"
              />
              {searchQuery && (
                <button
                  type="button"
                  className="model-picker-clear"
                  onClick={() => setSearchQuery('')}
                  aria-label="Clear search"
                >
                  <X size={13} />
                </button>
              )}
            </div>
          </div>

          <div className="model-picker-list">
            {/* Auto Cascade Option */}
            {showAutoCascade && (
              <div
                role="option"
                aria-selected={activeBackend === ''}
                className={`model-picker-item auto-option ${activeBackend === '' ? 'selected' : ''}`}
                onClick={() => handleSelect('')}
              >
                <div className="model-picker-item-main">
                  <div className="model-picker-item-title">
                    <Sparkles size={14} className="accent" />
                    <strong>Auto cascade</strong>
                    <span className="model-picker-badge auto">Pareto Frontier</span>
                  </div>
                  <small className="muted">Automatically routes across available models with zero-cost failover</small>
                </div>
                {activeBackend === '' && <Check size={14} className="model-picker-check" />}
              </div>
            )}

            {/* Dynamically Grouped Models */}
            {Object.entries(groupedBackends).map(([providerName, items]) => (
              <div key={providerName} className="model-picker-group">
                <div className="model-picker-group-title">
                  <span>{providerName}</span>
                  <em>{items.length}</em>
                </div>
                {items.map((backend) => {
                  const isSelected = activeBackend === backend.id;
                  const statusDotClass = backend.available ? 'good' : backend.quota_exhausted ? 'warn' : 'bad';

                  return (
                    <div
                      key={backend.id}
                      role="option"
                      aria-selected={isSelected}
                      className={`model-picker-item ${isSelected ? 'selected' : ''} ${!backend.available ? 'muted-item' : ''}`}
                      onClick={() => handleSelect(backend.id)}
                    >
                      <span
                        className={`status-dot ${statusDotClass}`}
                        title={backend.available ? 'Ready' : backend.quota_exhausted ? 'Quota exhausted' : backend.status || 'Offline'}
                      />
                      <div className="model-picker-item-main">
                        <div className="model-picker-item-title">
                          <strong>{backend.model || backend.id}</strong>
                          <span className="model-picker-badge">{backend.adapter}</span>
                          {backend.latency_tier && (
                            <span className={`model-picker-badge ${backend.latency_tier}`}>{backend.latency_tier}</span>
                          )}
                          {typeof backend.latency_ms === 'number' && (
                            <span className="model-picker-latency">{backend.latency_ms}ms</span>
                          )}
                        </div>
                        <small className="muted">
                          {backend.available
                            ? 'Ready for requests'
                            : backend.quota_exhausted
                              ? 'Quota exhausted — auto fallback active'
                              : backend.status || 'Offline'}
                        </small>
                      </div>
                      {isSelected && <Check size={14} className="model-picker-check" />}
                    </div>
                  );
                })}
              </div>
            ))}

            {Object.keys(groupedBackends).length === 0 && !showAutoCascade && (
              <div className="model-picker-empty">
                <span>No models found matching "{searchQuery}"</span>
              </div>
            )}
          </div>

          <div className="model-picker-footer">
            <Zap size={12} className="accent" />
            <span>Auto cascade stays active — preferred model falls back gracefully if quota exhausts.</span>
          </div>
        </div>
      )}
    </div>
  );
}
