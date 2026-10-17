import { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  Code2,
  Cpu,
  ExternalLink,
  Eye,
  EyeOff,
  Globe,
  Key,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Store,
  Terminal,
  Trash2,
  Wrench,
  X,
  Zap,
} from 'lucide-react';
import { api, userFacingError } from '../api';
import type { DiscoveryResult, PluginCatalogItem, PluginItem } from '../types';
import { Button, StatusBadge, Toggle } from './ui';
import { ErrorBoundary } from './ErrorBoundary';

function getDisplayUrl(val: unknown): string {
  if (!val) return '';
  if (typeof val === 'string') return val;
  if (typeof val === 'object' && val !== null) {
    const obj = val as Record<string, unknown>;
    if (typeof obj.url === 'string') return obj.url;
    if (typeof obj.link === 'string') return obj.link;
  }
  return '';
}

function PluginLogo({
  icon,
  homepage,
  baseUrl,
  name,
  className = 'w-9 h-9',
}: {
  icon?: string;
  homepage?: string;
  baseUrl?: string;
  name: string;
  className?: string;
}) {
  const [imgFailed, setImgFailed] = useState(false);

  const isUrl = typeof icon === 'string' && (
    icon.startsWith('http://') ||
    icon.startsWith('https://') ||
    icon.startsWith('data:image/') ||
    icon.startsWith('/')
  );

  const linkUrl = getDisplayUrl(homepage || baseUrl);
  const domain = linkUrl ? linkUrl.replace(/^https?:\/\//i, '').split('/')[0] : '';
  const domainFavicon = domain && !domain.includes('localhost') && !domain.includes('127.0.0.1')
    ? `https://www.google.com/s2/favicons?domain=${domain}&sz=64`
    : '';

  const activeImgSrc = (!imgFailed && isUrl) ? icon : (!imgFailed && domainFavicon) ? domainFavicon : null;

  if (activeImgSrc) {
    return (
      <div className={`${className} rounded-xl bg-white/[0.04] p-1 border border-white/10 flex items-center justify-center shrink-0 shadow-sm overflow-hidden`}>
        <img
          src={activeImgSrc}
          alt={name}
          className="w-full h-full object-contain rounded-lg"
          loading="lazy"
          onError={() => setImgFailed(true)}
        />
      </div>
    );
  }

  const displayEmoji = (icon && !isUrl) ? icon : '🧩';
  return (
    <div className={`${className} rounded-xl bg-gradient-to-br from-violet-500/15 via-white/[0.03] to-purple-500/10 border border-violet-500/20 flex items-center justify-center shrink-0 shadow-sm text-lg select-none`}>
      {displayEmoji}
    </div>
  );
}

type Tab = 'connect' | 'installed' | 'marketplace' | 'claude';

type Props = {
  isOpen: boolean;
  onClose: () => void;
  onToolsUpdated?: () => Promise<void>;
};

const FALLBACK_CATALOG: PluginCatalogItem[] = [
  {
    id: 'open_meteo',
    name: 'Open-Meteo Weather',
    category: 'Data & Environment',
    kind: 'openapi',
    description: 'Accurate worldwide weather forecast, temperature, humidity, wind, and precipitation. No API key needed.',
    icon: '🌤️',
    author: 'Open-Meteo',
    homepage: 'https://open-meteo.com',
    base_url: 'https://api.open-meteo.com',
    auth_type: 'none',
  },
  {
    id: 'coingecko',
    name: 'CoinGecko Crypto',
    category: 'Finance & Web3',
    kind: 'openapi',
    description: 'Live cryptocurrency prices, market caps, 24h volume, and market trends across thousands of tokens.',
    icon: '🪙',
    author: 'CoinGecko',
    homepage: 'https://coingecko.com',
    base_url: 'https://api.coingecko.com/api/v3',
    auth_type: 'none',
  },
  {
    id: 'hackernews',
    name: 'HackerNews Reader',
    category: 'Tech & News',
    kind: 'openapi',
    description: 'Official Firebase HackerNews API for top stories, new items, and developer discussions.',
    icon: '📰',
    author: 'Y Combinator',
    homepage: 'https://news.ycombinator.com',
    base_url: 'https://hacker-news.firebaseio.com/v0',
    auth_type: 'none',
  },
  {
    id: 'github_mcp',
    name: 'GitHub MCP Server',
    category: 'Developer Tools',
    kind: 'mcp_stdio',
    description: 'Model Context Protocol server for inspecting repositories, issues, commits, and pull requests.',
    icon: '🐙',
    author: 'Model Context Protocol',
    homepage: 'https://github.com/modelcontextprotocol/servers',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-github'],
    auth_type: 'api_key',
    auth_hint: 'Set GITHUB_PERSONAL_ACCESS_TOKEN in env',
  },
  {
    id: 'sqlite_mcp',
    name: 'SQLite MCP Explorer',
    category: 'Databases',
    kind: 'mcp_stdio',
    description: 'Directly execute read-only queries and inspect schema on local SQLite database files.',
    icon: '🗄️',
    author: 'Model Context Protocol',
    homepage: 'https://github.com/modelcontextprotocol/servers',
    command: 'uvx',
    args: ['mcp-server-sqlite', '--db-path', 'data/makima.db'],
    auth_type: 'none',
  },
  {
    id: 'fetch_mcp',
    name: 'Web Fetch & Markdown MCP',
    category: 'Web & Search',
    kind: 'mcp_stdio',
    description: 'Fetches web pages and efficiently converts HTML to clean markdown for the AI model.',
    icon: '🌐',
    author: 'Model Context Protocol',
    homepage: 'https://github.com/modelcontextprotocol/servers',
    command: 'uvx',
    args: ['mcp-server-fetch'],
    auth_type: 'none',
  },
];

export function PluginsModal({ isOpen, onClose, onToolsUpdated }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('connect');
  const [installed, setInstalled] = useState<PluginItem[]>([]);
  const [catalog, setCatalog] = useState<PluginCatalogItem[]>(FALLBACK_CATALOG);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Tab 1: Discovery & Connect
  const [targetUrl, setTargetUrl] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [discoveryResult, setDiscoveryResult] = useState<DiscoveryResult | null>(null);
  const [authType, setAuthType] = useState<'none' | 'bearer' | 'api_key'>('none');
  const [tokenInput, setTokenInput] = useState('');
  const [headerNameInput, setHeaderNameInput] = useState('Authorization');
  const [showToken, setShowToken] = useState(false);
  const [connecting, setConnecting] = useState(false);

  // Tab 2: Config Drawer for Installed
  const [configuringPluginId, setConfiguringPluginId] = useState<string | null>(null);
  const [editToken, setEditToken] = useState('');
  const [editHeaderName, setEditHeaderName] = useState('Authorization');
  const [savingKey, setSavingKey] = useState(false);

  // Tab 3: Marketplace
  const [installingCatalogId, setInstallingCatalogId] = useState<string | null>(null);
  const [marketSearch, setMarketSearch] = useState('');
  const [registryUrl, setRegistryUrl] = useState(() => {
    return localStorage.getItem('makima_marketplace_registry_url') || '';
  });
  const [registryInput, setRegistryInput] = useState(() => {
    return localStorage.getItem('makima_marketplace_registry_url') || '';
  });
  const [showCustomRegistry, setShowCustomRegistry] = useState(false);

  // Tab 4: Claude Config Import
  const [claudeJsonInput, setClaudeJsonInput] = useState(`{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "data/makima.db"]
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    }
  }
}`);
  const [importingClaude, setImportingClaude] = useState(false);

  const dialogRef = useRef<HTMLDivElement>(null);

  const loadData = async (overrideRegistryUrl?: string) => {
    setLoading(true);
    setError('');
    const activeRegistry = overrideRegistryUrl !== undefined ? overrideRegistryUrl : registryUrl;
    try {
      const pluginsPromise = api.plugins().catch(() => ({ plugins: [] }));
      const catalogPromise = activeRegistry
        ? api.pluginCatalog(activeRegistry)
        : api.pluginCatalog().catch(() => ({ catalog: FALLBACK_CATALOG }));

      const [pluginsRes, catalogRes] = await Promise.all([pluginsPromise, catalogPromise]);
      setInstalled(pluginsRes.plugins || []);
      if (catalogRes.catalog && catalogRes.catalog.length > 0) {
        setCatalog(catalogRes.catalog);
      } else if (!activeRegistry) {
        setCatalog(FALLBACK_CATALOG);
      } else {
        setCatalog([]);
        setError(`Custom registry at "${activeRegistry}" returned 0 plugins.`);
      }
    } catch (err) {
      setError(userFacingError(err, 'Failed to load plugins.'));
      if (!activeRegistry) {
        setCatalog((prev) => (prev.length > 0 ? prev : FALLBACK_CATALOG));
      } else {
        setCatalog([]);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleApplyRegistry = async (url: string) => {
    const trimmed = url.trim();
    setRegistryUrl(trimmed);
    setRegistryInput(trimmed);
    if (trimmed) {
      localStorage.setItem('makima_marketplace_registry_url', trimmed);
      setSuccessMsg(`Marketplace connected to custom registry: ${trimmed}`);
    } else {
      localStorage.removeItem('makima_marketplace_registry_url');
      setShowCustomRegistry(false);
      setSuccessMsg('Marketplace reset to official Makima curated registry.');
    }
    await loadData(trimmed);
  };

  useEffect(() => {
    if (isOpen) {
      loadData();
    }
  }, [isOpen]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Actions
  const handleDiscover = async () => {
    if (!targetUrl.trim()) return;
    setDiscovering(true);
    setError('');
    setSuccessMsg('');
    setDiscoveryResult(null);
    try {
      const res = await api.discoverPlugin(targetUrl.trim());
      if (!res.ok) {
        setError(res.error || 'Could not find OpenAPI spec or plugin manifest on this domain.');
      } else {
        setDiscoveryResult(res);
        if (res.auth_type === 'bearer' || res.auth_type === 'api_key') {
          setAuthType(res.auth_type);
        } else {
          setAuthType('none');
        }
        if (res.auth_header_name) {
          setHeaderNameInput(res.auth_header_name);
        }
      }
    } catch (err) {
      setError(userFacingError(err, 'Auto-discovery probe failed.'));
    } finally {
      setDiscovering(false);
    }
  };

  const handleConnectDiscovered = async () => {
    if (!discoveryResult) return;
    setConnecting(true);
    setError('');
    try {
      await api.installPlugin({
        name: discoveryResult.name || 'Connected API',
        kind: 'openapi',
        description: discoveryResult.description,
        icon: discoveryResult.icon || '🌐',
        spec_url: discoveryResult.spec_url,
        spec_raw: discoveryResult.spec_raw,
        base_url: discoveryResult.base_url,
        auth_type: authType,
        token: tokenInput.trim() || undefined,
        header_name: authType === 'api_key' ? headerNameInput : undefined,
      });
      setSuccessMsg(`Successfully connected ${discoveryResult.name}! AI tools are now active.`);
      setDiscoveryResult(null);
      setTargetUrl('');
      setTokenInput('');
      await loadData();
      if (onToolsUpdated) await onToolsUpdated();
      setActiveTab('installed');
    } catch (err) {
      setError(userFacingError(err, 'Failed to activate plugin.'));
    } finally {
      setConnecting(false);
    }
  };

  const handleToggle = async (plugin: PluginItem) => {
    try {
      await api.togglePlugin(plugin.id, !plugin.enabled);
      setInstalled((prev) =>
        prev.map((p) => (p.id === plugin.id ? { ...p, enabled: !p.enabled } : p))
      );
      if (onToolsUpdated) await onToolsUpdated();
    } catch (err) {
      setError(userFacingError(err, 'Could not toggle plugin.'));
    }
  };

  const handleUninstall = async (pluginId: string) => {
    if (!confirm('Are you sure you want to uninstall this plugin?')) return;
    try {
      await api.uninstallPlugin(pluginId);
      setInstalled((prev) => prev.filter((p) => p.id !== pluginId));
      if (onToolsUpdated) await onToolsUpdated();
    } catch (err) {
      setError(userFacingError(err, 'Could not uninstall plugin.'));
    }
  };

  const handleSaveKey = async (pluginId: string) => {
    setSavingKey(true);
    setError('');
    try {
      await api.configurePlugin(pluginId, editToken.trim(), editHeaderName.trim());
      setConfiguringPluginId(null);
      setEditToken('');
      setSuccessMsg('API credentials updated successfully.');
      await loadData();
    } catch (err) {
      setError(userFacingError(err, 'Failed to save credentials.'));
    } finally {
      setSavingKey(false);
    }
  };

  const handleInstallCatalog = async (item: PluginCatalogItem) => {
    setInstallingCatalogId(item.id);
    setError('');
    try {
      await api.installPlugin(item as Record<string, unknown>);
      setSuccessMsg(`Installed ${item.name}!`);
      await loadData();
      if (onToolsUpdated) await onToolsUpdated();
    } catch (err) {
      setError(userFacingError(err, `Failed to install ${item.name}.`));
    } finally {
      setInstallingCatalogId(null);
    }
  };

  const handleImportClaude = async () => {
    setImportingClaude(true);
    setError('');
    try {
      const parsed = JSON.parse(claudeJsonInput);
      const res = await api.importClaudeConfig(parsed);
      setSuccessMsg(res.message || 'Imported MCP servers successfully!');
      await loadData();
      if (onToolsUpdated) await onToolsUpdated();
      setActiveTab('installed');
    } catch (err) {
      setError(userFacingError(err, 'Invalid JSON or import error.'));
    } finally {
      setImportingClaude(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        className="w-full max-w-4xl max-h-[90vh] flex flex-col bg-[#121316] border border-white/10 rounded-2xl shadow-2xl overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-white/[0.02]">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-violet-500/10 border border-violet-500/20 text-violet-400">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white tracking-tight flex items-center gap-2">
                Makima Extensibility Hub
                <span className="text-xs px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300 font-mono">
                  ChatGPT & MCP
                </span>
              </h2>
              <p className="text-xs text-white/50">
                Connect websites, REST APIs, OpenAPI 3.0 specs, and Claude Desktop MCP servers
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/40 hover:text-white rounded-lg hover:bg-white/5 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="flex items-center gap-1 px-6 pt-3 border-b border-white/5 bg-white/[0.01]">
          <button
            onClick={() => setActiveTab('connect')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium rounded-t-lg transition-all border-b-2 ${
              activeTab === 'connect'
                ? 'border-violet-500 text-white bg-white/5'
                : 'border-transparent text-white/50 hover:text-white/80'
            }`}
          >
            <Globe className="w-4 h-4 text-emerald-400" />
            Connect Website / OpenAPI
          </button>
          <button
            onClick={() => setActiveTab('installed')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium rounded-t-lg transition-all border-b-2 ${
              activeTab === 'installed'
                ? 'border-violet-500 text-white bg-white/5'
                : 'border-transparent text-white/50 hover:text-white/80'
            }`}
          >
            <Wrench className="w-4 h-4 text-violet-400" />
            Installed Extensions ({installed.length})
          </button>
          <button
            onClick={() => {
              setActiveTab('marketplace');
              if (catalog.length === 0) void loadData();
            }}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium rounded-t-lg transition-all border-b-2 ${
              activeTab === 'marketplace'
                ? 'border-violet-500 text-white bg-white/5'
                : 'border-transparent text-white/50 hover:text-white/80'
            }`}
          >
            <Store className="w-4 h-4 text-amber-400" />
            1-Click Marketplace ({catalog.length})
          </button>
          <button
            onClick={() => setActiveTab('claude')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium rounded-t-lg transition-all border-b-2 ${
              activeTab === 'claude'
                ? 'border-violet-500 text-white bg-white/5'
                : 'border-transparent text-white/50 hover:text-white/80'
            }`}
          >
            <Terminal className="w-4 h-4 text-sky-400" />
            Import Claude MCP
          </button>
        </div>

        {/* Feedback Messages */}
        {error && (
          <div className="mx-6 mt-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs flex items-center gap-2 animate-fade-in">
            <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
            <span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="mx-6 mt-4 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs flex items-center gap-2 animate-fade-in">
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            <span>{successMsg}</span>
          </div>
        )}

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* TAB 1: CONNECT WEBSITE / OPENAPI */}
          {activeTab === 'connect' && (
            <div className="space-y-6">
              <div className="p-5 rounded-2xl bg-white/[0.02] border border-white/5 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Globe className="w-4 h-4 text-emerald-400" />
                    Connect Website or REST API
                  </h3>
                  <p className="text-xs text-white/50 mt-1">
                    Enter any website domain (e.g. <code className="text-emerald-400">api.weather.gov</code>) or direct OpenAPI 3.0 URL. Makima probes manifests, auto-synthesizes endpoints, and injects authentication securely.
                  </p>
                </div>

                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <input
                      type="text"
                      placeholder="e.g. api.weather.gov or https://petstore.swagger.io/v2/swagger.json"
                      value={targetUrl}
                      onChange={(e) => setTargetUrl(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleDiscover()}
                      className="w-full px-4 py-2.5 rounded-xl bg-black/40 border border-white/10 text-white placeholder-white/30 text-xs focus:outline-none focus:border-violet-500 transition-colors"
                    />
                  </div>
                  <Button
                    onClick={handleDiscover}
                    disabled={discovering || !targetUrl.trim()}
                    className="flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium rounded-xl transition-all"
                  >
                    {discovering ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                    Discover & Inspect
                  </Button>
                </div>

                <div className="flex items-center gap-2 text-[11px] text-white/40">
                  <span>Popular quick links:</span>
                  <button
                    onClick={() => setTargetUrl('api.weather.gov')}
                    className="text-violet-400 hover:underline"
                  >
                    Weather.gov
                  </button>
                  <span>•</span>
                  <button
                    onClick={() => setTargetUrl('https://petstore.swagger.io/v2/swagger.json')}
                    className="text-violet-400 hover:underline"
                  >
                    Swagger Petstore
                  </button>
                  <span>•</span>
                  <button
                    onClick={() => setTargetUrl('https://api.github.com')}
                    className="text-violet-400 hover:underline"
                  >
                    GitHub REST
                  </button>
                </div>
              </div>

              {/* Discovery Result Preview */}
              {discoveryResult && (
                <div className="p-5 rounded-2xl bg-emerald-500/[0.03] border border-emerald-500/20 space-y-4 animate-fade-in">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2.5">
                        <PluginLogo
                          icon={discoveryResult.icon}
                          baseUrl={discoveryResult.base_url}
                          name={discoveryResult.name}
                          className="w-8 h-8"
                        />
                        <h4 className="text-sm font-semibold text-white">{discoveryResult.name}</h4>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-mono">
                          {discoveryResult.plugin_type === 'chatgpt_plugin' ? 'ChatGPT Plugin' : 'OpenAPI 3.0'}
                        </span>
                      </div>
                      <p className="text-xs text-white/60 mt-1">{discoveryResult.description || 'No description provided.'}</p>
                    </div>
                    <span className="text-xs font-mono px-2.5 py-1 rounded-lg bg-white/5 text-white/80 border border-white/5">
                      {discoveryResult.endpoints_count} endpoints found
                    </span>
                  </div>

                  {/* Endpoints Pills */}
                  {discoveryResult.endpoints.length > 0 && (
                    <div>
                      <label className="text-[11px] font-medium text-white/50 block mb-1.5">
                        Detected Callable Operations:
                      </label>
                      <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto p-2 rounded-xl bg-black/40 border border-white/5">
                        {discoveryResult.endpoints.slice(0, 15).map((ep, i) => (
                          <span
                            key={i}
                            className="text-[10px] font-mono px-2 py-1 rounded-md bg-white/5 text-white/70 flex items-center gap-1 border border-white/5"
                          >
                            <span
                              className={`font-bold ${
                                ep.method === 'GET' ? 'text-emerald-400' : 'text-sky-400'
                              }`}
                            >
                              {ep.method}
                            </span>
                            <span>{ep.path}</span>
                          </span>
                        ))}
                        {discoveryResult.endpoints.length > 15 && (
                          <span className="text-[10px] text-white/40 self-center px-1">
                            +{discoveryResult.endpoints.length - 15} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Authentication Configuration */}
                  <div className="pt-2 border-t border-white/5 space-y-3">
                    <label className="text-xs font-medium text-white flex items-center gap-1.5">
                      <Key className="w-3.5 h-3.5 text-amber-400" />
                      Authentication Method
                    </label>

                    <div className="flex gap-4">
                      <label className="flex items-center gap-2 text-xs text-white/70 cursor-pointer">
                        <input
                          type="radio"
                          name="authType"
                          value="none"
                          checked={authType === 'none'}
                          onChange={() => setAuthType('none')}
                          className="accent-violet-500"
                        />
                        None (Public API)
                      </label>
                      <label className="flex items-center gap-2 text-xs text-white/70 cursor-pointer">
                        <input
                          type="radio"
                          name="authType"
                          value="bearer"
                          checked={authType === 'bearer'}
                          onChange={() => setAuthType('bearer')}
                          className="accent-violet-500"
                        />
                        Bearer Token
                      </label>
                      <label className="flex items-center gap-2 text-xs text-white/70 cursor-pointer">
                        <input
                          type="radio"
                          name="authType"
                          value="api_key"
                          checked={authType === 'api_key'}
                          onChange={() => setAuthType('api_key')}
                          className="accent-violet-500"
                        />
                        API Key Header
                      </label>
                    </div>

                    {authType !== 'none' && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1 animate-fade-in">
                        {authType === 'api_key' && (
                          <div>
                            <label className="text-[11px] text-white/50 block mb-1">Header Name</label>
                            <input
                              type="text"
                              value={headerNameInput}
                              onChange={(e) => setHeaderNameInput(e.target.value)}
                              placeholder="e.g. X-API-KEY or Authorization"
                              className="w-full px-3 py-2 rounded-xl bg-black/40 border border-white/10 text-white text-xs"
                            />
                          </div>
                        )}
                        <div className={authType === 'api_key' ? '' : 'col-span-2'}>
                          <label className="text-[11px] text-white/50 block mb-1">Token or Secret Key</label>
                          <div className="relative">
                            <input
                              type={showToken ? 'text' : 'password'}
                              value={tokenInput}
                              onChange={(e) => setTokenInput(e.target.value)}
                              placeholder="Enter API key or personal access token"
                              className="w-full px-3 py-2 rounded-xl bg-black/40 border border-white/10 text-white text-xs pr-10"
                            />
                            <button
                              type="button"
                              onClick={() => setShowToken(!showToken)}
                              className="absolute right-3 top-2.5 text-white/40 hover:text-white"
                            >
                              {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="flex justify-end gap-2 pt-2">
                    <Button
                      onClick={handleConnectDiscovered}
                      disabled={connecting}
                      className="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium rounded-xl transition-all shadow-lg shadow-emerald-900/20"
                    >
                      {connecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                      Connect & Activate AI Tools
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: INSTALLED PLUGINS */}
          {activeTab === 'installed' && (
            <div className="space-y-4">
              {installed.length === 0 ? (
                <div className="text-center py-12 border border-dashed border-white/10 rounded-2xl space-y-3">
                  <div className="w-12 h-12 rounded-full bg-white/5 flex items-center justify-center mx-auto text-white/40">
                    <Wrench className="w-6 h-6" />
                  </div>
                  <h4 className="text-sm font-medium text-white">No custom plugins installed yet</h4>
                  <p className="text-xs text-white/40 max-w-sm mx-auto">
                    Connect any website API from the first tab or install free pre-configured tools from the Marketplace!
                  </p>
                  <Button
                    onClick={() => setActiveTab('marketplace')}
                    className="text-xs px-4 py-2 bg-violet-600 text-white rounded-xl"
                  >
                    Browse Marketplace
                  </Button>
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-3">
                  {installed.map((plugin) => (
                    <div
                      key={plugin.id}
                      className="p-4 rounded-2xl bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors space-y-3"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-start gap-3">
                          <PluginLogo
                            icon={plugin.icon}
                            homepage={plugin.homepage}
                            baseUrl={plugin.base_url}
                            name={plugin.name}
                            className="w-10 h-10 mt-0.5"
                          />
                          <div>
                            <div className="flex items-center gap-2">
                              <h4 className="text-sm font-semibold text-white">{plugin.name}</h4>
                              <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/60 font-mono">
                                {plugin.kind}
                              </span>
                              {plugin.auth_type !== 'none' && (
                                <span
                                  className={`text-[10px] px-2 py-0.5 rounded-full font-mono ${
                                    plugin.auth_configured
                                      ? 'bg-emerald-500/10 text-emerald-300'
                                      : 'bg-amber-500/10 text-amber-300'
                                  }`}
                                >
                                  {plugin.auth_configured ? 'Key Configured' : 'Needs Key'}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-white/50 mt-1">{plugin.description || 'No description'}</p>
                            <div className="flex items-center gap-3 mt-2 text-[11px] text-white/40">
                              <span>Tools: <b className="text-white/80">{plugin.tools_count}</b> active</span>
                              {plugin.base_url && <span>Host: {plugin.base_url}</span>}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          <Toggle
                            checked={plugin.enabled}
                            onChange={() => handleToggle(plugin)}
                            label={plugin.enabled ? 'Enabled' : 'Disabled'}
                          />
                          <button
                            onClick={() => {
                              setConfiguringPluginId(configuringPluginId === plugin.id ? null : plugin.id);
                              setEditToken('');
                            }}
                            className="p-2 text-white/50 hover:text-white rounded-lg hover:bg-white/5 transition-colors"
                            title="Configure Credentials"
                          >
                            <Key className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleUninstall(plugin.id)}
                            className="p-2 text-red-400/60 hover:text-red-400 rounded-lg hover:bg-red-500/10 transition-colors"
                            title="Uninstall Plugin"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      {/* Expandable Key Configuration Drawer */}
                      {configuringPluginId === plugin.id && (
                        <div className="pt-3 border-t border-white/5 grid grid-cols-1 md:grid-cols-3 gap-2 animate-fade-in">
                          <div className="md:col-span-2">
                            <input
                              type="password"
                              placeholder="New API Key or Token"
                              value={editToken}
                              onChange={(e) => setEditToken(e.target.value)}
                              className="w-full px-3 py-2 rounded-xl bg-black/40 border border-white/10 text-white text-xs"
                            />
                          </div>
                          <Button
                            onClick={() => handleSaveKey(plugin.id)}
                            disabled={savingKey || !editToken.trim()}
                            className="flex items-center justify-center gap-1.5 px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white text-xs rounded-xl"
                          >
                            {savingKey ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                            Save Key
                          </Button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: 1-CLICK MARKETPLACE */}
          {activeTab === 'marketplace' && (
            <ErrorBoundary name="Marketplace Tab">
              <div className="space-y-4">
                {/* Marketplace Registry Source Selector (IDE-Style) */}
              <div className="p-3.5 rounded-2xl bg-gradient-to-r from-violet-500/[0.06] via-purple-500/[0.03] to-transparent border border-violet-500/15 space-y-2.5">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-2">
                    <Store className="w-4 h-4 text-amber-400" />
                    <span className="text-xs font-semibold text-white">Marketplace Registry Source:</span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full font-mono bg-white/5 text-violet-300 border border-white/10 truncate max-w-[260px]">
                      {registryUrl ? registryUrl : 'Official Curated Feed'}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => handleApplyRegistry('')}
                      className={`text-[11px] px-2.5 py-1 rounded-lg transition-colors ${
                        !registryUrl
                          ? 'bg-violet-600 text-white font-medium shadow-sm'
                          : 'bg-white/5 text-white/60 hover:text-white'
                      }`}
                      title="Use official curated tools"
                    >
                      Official Store
                    </button>
                    <button
                      onClick={() => {
                        setShowCustomRegistry(true);
                      }}
                      className={`text-[11px] px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1 ${
                        registryUrl || showCustomRegistry
                          ? 'bg-violet-600 text-white font-medium shadow-sm'
                          : 'bg-white/5 text-white/60 hover:text-white'
                      }`}
                      title="Connect custom registry URL or feed"
                    >
                      <span>Custom Registry URL</span>
                    </button>
                  </div>
                </div>

                {/* Custom Registry URL Input Drawer */}
                {(showCustomRegistry || registryUrl) && (
                  <div className="space-y-2 pt-1 animate-fade-in">
                    <div className="flex items-center gap-2">
                      <div className="relative flex-1">
                        <input
                          type="text"
                          placeholder="Enter registry URL (e.g. https://registry.modelcontextprotocol.io/v0/servers)"
                          value={registryInput}
                          onChange={(e) => setRegistryInput(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleApplyRegistry(registryInput)}
                          className="w-full px-3 py-1.5 rounded-xl bg-black/50 border border-white/10 text-white placeholder-white/30 text-xs focus:outline-none focus:border-violet-500 font-mono transition-colors"
                        />
                      </div>
                      <Button
                        onClick={() => handleApplyRegistry(registryInput)}
                        disabled={loading || !registryInput.trim()}
                        className="text-xs px-3.5 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded-xl shrink-0 font-medium"
                      >
                        {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Connect & Load'}
                      </Button>
                      {registryUrl && (
                        <button
                          onClick={() => {
                            setShowCustomRegistry(false);
                            handleApplyRegistry('');
                          }}
                          className="text-[11px] px-2.5 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-white/60 hover:text-white transition-colors shrink-0"
                        >
                          Reset
                        </button>
                      )}
                    </div>

                    {/* Popular Online Registry Preset */}
                    <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
                      <span className="text-white/40">Presets:</span>
                      <button
                        type="button"
                        onClick={() => {
                          const url = 'https://registry.modelcontextprotocol.io/v0/servers';
                          setRegistryInput(url);
                          handleApplyRegistry(url);
                        }}
                        className="px-2 py-0.5 rounded-md bg-white/5 hover:bg-violet-500/20 text-sky-300 hover:text-white border border-white/5 transition-colors font-mono"
                        title="Official Global Model Context Protocol Registry"
                      >
                        🌐 Official MCP Global Registry
                      </button>
                    </div>

                    {/* External Marketplaces Links */}
                    <div className="flex items-center gap-2 pt-1 border-t border-white/5 text-[11px] text-white/40 flex-wrap">
                      <span>Explore Public Hubs:</span>
                      <a
                        href="https://smithery.ai"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-violet-400 hover:text-violet-300 hover:underline flex items-center gap-0.5"
                      >
                        Smithery.ai <ExternalLink className="w-2.5 h-2.5" />
                      </a>
                      <span>•</span>
                      <a
                        href="https://glama.ai/mcp/servers"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-violet-400 hover:text-violet-300 hover:underline flex items-center gap-0.5"
                      >
                        Glama.ai <ExternalLink className="w-2.5 h-2.5" />
                      </a>
                      <span>•</span>
                      <a
                        href="https://github.com/modelcontextprotocol/servers"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-violet-400 hover:text-violet-300 hover:underline flex items-center gap-0.5"
                      >
                        Anthropic MCP <ExternalLink className="w-2.5 h-2.5" />
                      </a>
                    </div>
                  </div>
                )}
              </div>

              {/* Marketplace Search & Action Header */}
              <div className="flex items-center justify-between gap-3 p-3 rounded-2xl bg-white/[0.02] border border-white/5">
                <div className="relative flex-1">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-white/40" />
                  <input
                    type="text"
                    placeholder="Search tools by name, category, or keyword..."
                    value={marketSearch}
                    onChange={(e) => setMarketSearch(e.target.value)}
                    className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-black/40 border border-white/10 text-white placeholder-white/30 text-xs focus:outline-none focus:border-violet-500 transition-colors"
                  />
                  {marketSearch && (
                    <button
                      onClick={() => setMarketSearch('')}
                      className="absolute right-2.5 top-2 text-white/40 hover:text-white"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
                <button
                  onClick={() => loadData()}
                  disabled={loading}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-white/70 hover:text-white text-xs border border-white/10 transition-colors shrink-0"
                  title="Refresh marketplace catalog from server"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-violet-400' : ''}`} />
                  <span>Refresh</span>
                </button>
              </div>

              {/* Loading State */}
              {loading && catalog.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 space-y-3">
                  <Loader2 className="w-8 h-8 text-violet-400 animate-spin" />
                  <p className="text-xs text-white/50">Loading curated marketplace tools...</p>
                </div>
              ) : null}

              {/* Filtered Grid or Empty State */}
              {(() => {
                const filtered = catalog.filter((item) => {
                  if (!item) return false;
                  const q = marketSearch.trim().toLowerCase();
                  if (!q) return true;
                  const name = typeof item.name === 'string' ? item.name : String(item.name || '');
                  const category = typeof item.category === 'string' ? item.category : String(item.category || '');
                  const desc = typeof item.description === 'string' ? item.description : String(item.description || '');
                  return (
                    name.toLowerCase().includes(q) ||
                    category.toLowerCase().includes(q) ||
                    desc.toLowerCase().includes(q)
                  );
                });

                if (filtered.length === 0) {
                  return (
                    <div className="text-center py-12 border border-dashed border-white/10 rounded-2xl space-y-3">
                      <div className="w-12 h-12 rounded-full bg-white/5 flex items-center justify-center mx-auto text-white/40">
                        <Store className="w-6 h-6" />
                      </div>
                      <h4 className="text-sm font-medium text-white">
                        {catalog.length === 0 ? 'No marketplace extensions found' : 'No tools match your search'}
                      </h4>
                      <p className="text-xs text-white/40 max-w-sm mx-auto">
                        {catalog.length === 0
                          ? 'Could not connect to the catalog API. Click below to retry.'
                          : `No tools found matching "${marketSearch}". Try searching something else.`}
                      </p>
                      {catalog.length === 0 ? (
                        <Button
                          onClick={() => loadData()}
                          className="flex items-center gap-1.5 mx-auto text-xs px-4 py-2 bg-violet-600 text-white rounded-xl"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                          Retry Loading
                        </Button>
                      ) : (
                        <Button
                          onClick={() => setMarketSearch('')}
                          className="text-xs px-4 py-2 bg-white/10 text-white rounded-xl"
                        >
                          Clear Search Filter
                        </Button>
                      )}
                    </div>
                  );
                }

                return (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {filtered.map((item, idx) => {
                      const itemName = typeof item.name === 'string' ? item.name : String(item.name || 'Extension');
                      const itemCategory = typeof item.category === 'string' ? item.category : 'Community';
                      const itemDesc = typeof item.description === 'string' ? item.description : String(item.description || '');
                      const linkUrl = getDisplayUrl(item.homepage || item.base_url);
                      const isInstalled = installed.some(
                        (p) => (item.id && p.id === item.id) || (itemName && p.name === itemName)
                      );
                      const uniqueKey = item.id || `${itemName}-${idx}`;

                      return (
                        <div
                          key={uniqueKey}
                          className="p-4 rounded-2xl bg-white/[0.02] border border-white/5 hover:border-white/10 transition-all flex flex-col justify-between space-y-3"
                        >
                          <div>
                            <div className="flex items-center justify-between">
                              <PluginLogo
                                icon={item.icon}
                                homepage={item.homepage}
                                baseUrl={item.base_url}
                                name={itemName}
                              />
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/5 text-white/50 border border-white/5">
                                {itemCategory}
                              </span>
                            </div>
                            <h4 className="text-sm font-semibold text-white mt-2">{itemName}</h4>
                            <p className="text-xs text-white/50 mt-1 line-clamp-2">{itemDesc}</p>
                            {linkUrl && (
                              <div className="flex items-center gap-2 mt-2 pt-1">
                                <a
                                  href={linkUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 text-[11px] text-violet-400 hover:text-violet-300 hover:underline font-mono"
                                  title="Open documentation / homepage"
                                >
                                  <span>{linkUrl.replace(/^https?:\/\//, '')}</span>
                                  <ExternalLink className="w-3 h-3 shrink-0" />
                                </a>
                              </div>
                            )}
                          </div>

                          <div className="pt-2 border-t border-white/5 flex items-center justify-between">
                            <span className="text-[11px] text-white/40">
                              {item.auth_type === 'none' ? 'Free • No Key' : 'Requires API Key'}
                            </span>
                            {isInstalled ? (
                              <span className="flex items-center gap-1 text-xs text-emerald-400 font-medium px-3 py-1.5 rounded-lg bg-emerald-500/10">
                                <Check className="w-3.5 h-3.5" /> Installed
                              </span>
                            ) : (
                              <Button
                                onClick={() => handleInstallCatalog(item)}
                                disabled={installingCatalogId === item.id}
                                className="flex items-center gap-1 text-xs px-3.5 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition-colors font-medium"
                              >
                                {installingCatalogId === item.id ? (
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                ) : (
                                  <Plus className="w-3.5 h-3.5" />
                                )}
                                Install
                              </Button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          </ErrorBoundary>
        )}

          {/* TAB 4: IMPORT CLAUDE MCP */}
          {activeTab === 'claude' && (
            <div className="space-y-4">
              <div className="p-4 rounded-2xl bg-white/[0.02] border border-white/5 space-y-2">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-sky-400" />
                  Import Claude Desktop Configuration
                </h3>
                <p className="text-xs text-white/50">
                  If you already use Claude Desktop, paste the contents of your <code className="text-sky-300">claude_desktop_config.json</code> below. Makima will automatically convert all declared MCP servers (e.g. SQLite, GitHub, Filesystem) into native Makima tools!
                </p>
              </div>

              <div>
                <textarea
                  rows={10}
                  value={claudeJsonInput}
                  onChange={(e) => setClaudeJsonInput(e.target.value)}
                  className="w-full font-mono text-xs p-4 rounded-2xl bg-black/50 border border-white/10 text-emerald-400 focus:outline-none focus:border-violet-500 transition-colors"
                />
              </div>

              <div className="flex justify-end">
                <Button
                  onClick={handleImportClaude}
                  disabled={importingClaude || !claudeJsonInput.trim()}
                  className="flex items-center gap-2 px-5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium rounded-xl transition-all"
                >
                  {importingClaude ? <Loader2 className="w-4 h-4 animate-spin" /> : <Layers className="w-4 h-4" />}
                  Import All MCP Servers
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-white/10 bg-white/[0.01] flex items-center justify-between text-xs text-white/40">
          <span>Zero-Leak Guarantee: Credentials remain server-side in ~/.makima/plugins/.secrets.json</span>
          <Button onClick={onClose} className="px-4 py-1.5 bg-white/5 hover:bg-white/10 text-white rounded-lg">
            Done
          </Button>
        </div>
      </div>
    </div>
  );
}
