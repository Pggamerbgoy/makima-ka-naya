import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Archive, ArrowDown, ArrowDownToLine, ChevronDown, Command, Cpu, FileText, Gauge, Info, Layers, Menu, MessageSquare, Mic, Moon, Paperclip, Plus, Search, Send, Settings, Sparkles, Square, Sun, Trash2, X, Zap } from 'lucide-react';
import { api, userFacingError } from './api';
import { detectArtifacts, normalizeArtifact } from './artifacts';
import { ChatMessage, type ChatMessageData } from './components/ChatMessage';
import { SettingsModal } from './components/SettingsModal';
import { PluginsModal } from './components/PluginsModal';
import { ArtifactWorkspace, CanvasPanel, FullscreenArtifact, TelemetryWorkspace } from './components/WorkspacePanels';
import { Button } from './components/ui';
import { VoiceControl } from './components/VoiceControl';
import { ModelPicker } from './components/ModelPicker';
import { useMakimaSocket, type ConnectionState } from './hooks/useMakimaSocket';
import { clearSession, loadSession as loadPersistedSession, saveSession } from './session';
import { launchConfetti } from './utils/confetti';
import { playChime, playWhoosh } from './utils/soundEffects';
import type { Artifact, Backend, Connector, SessionSummary, StreamEvent, SystemStatus, ToolInfo, UiSettings } from './types';
import { DEFAULT_SETTINGS } from './types';
import './index.css';

const MAKIMA_QUIPS = [
  'Watching all concurrent processes 👁️',
  'Sipping black coffee ☕',
  'Zero hallucinations detected ✨',
  'Control devil at your service 🖤',
  'Quantum circuits aligned ⚡',
  'Thinking at Pareto frontier 🧠',
  'Everything according to plan 🎯',
];

const SURPRISE_PROMPTS = [
  'Design an interactive ASCII cyberpunk city simulator in Python.',
  'Render a beautiful Mermaid sequence diagram of distributed Raft consensus.',
  'Write a high-performance cellular automaton simulation with explanation.',
  'Create a data table and chart comparing frontier AI inference speeds.',
  'Draft an eccentric sci-fi micro-story about a rogue OS assistant.',
  'Plan a complete micro-service architecture for real-time WebSocket telemetry.',
];

const HERO_ROTATING_WORDS = [
  'architect autonomous systems ⚡',
  'automate desktop workflows 🖥️',
  'debug & refactor codebases 🔍',
  'synthesize deep web research 🌐',
  'craft live Canvas artifacts 🎨',
  'analyze real-time telemetry 📊',
  'orchestrate 12 AI agents 🧠',
];

const TYPEWRITER_PROMPTS = [
  'Build a FastAPI microservice with persistent HTTP/2 pooling...',
  'Scan my repository for memory leaks and security vulnerabilities...',
  'Render an interactive system architecture diagram in Canvas...',
  'Summarize this week’s telemetry metrics into a chart and table...',
  'Automate my morning desktop workspace and play lofi beats...',
];

const FLOATING_KEYWORDS = [
  'Pareto Router',
  '12 AI Agents',
  'Canvas Studio',
  'EternalMemory',
  'Gemini Live Voice',
  'Zero-Latency',
];



export type ChatAttachment = { id: string; name: string; mimeType: string; size: number; textPreview?: string };
type Message = { id: string; role: 'user' | 'assistant'; content: string; attachments?: ChatAttachment[]; artifacts?: Artifact[]; pending?: boolean; error?: string; createdAt?: number; suggestions?: string[] };
type Tab = 'models' | 'general' | 'connectors' | 'voice' | 'developer' | 'tools';
type View = 'chat' | 'artifacts' | 'telemetry';
const uid = () => `${Date.now()}_${Math.random().toString(16).slice(2)}`;
const MAX_ATTACHMENTS = 5;
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_TEXT_PREVIEW = 120_000;
const TEXT_FILE_EXTENSIONS = new Set(['.txt', '.md', '.markdown', '.json', '.csv', '.tsv', '.xml', '.yaml', '.yml', '.log', '.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.scss', '.sql', '.toml', '.ini', '.env']);
const DEMO_IMAGE_URL = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22640%22 height=%22320%22 viewBox=%220 0 640 320%22%3E%3Cdefs%3E%3ClinearGradient id=%22g%22 x1=%220%22 y1=%220%22 x2=%221%22 y2=%221%22%3E%3Cstop stop-color=%22%237c3aed%22/%3E%3Cstop offset=%221%22 stop-color=%22%230ea5e9%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width=%22640%22 height=%22320%22 rx=%2224%22 fill=%22%23141124%22/%3E%3Ccircle cx=%22490%22 cy=%22100%22 r=%22120%22 fill=%22url(%23g)%22 opacity=%22.8%22/%3E%3Ccircle cx=%22140%22 cy=%22250%22 r=%22160%22 fill=%22%23ec4899%22 opacity=%22.35%22/%3E%3Ctext x=%2232%22 y=%22170%22 fill=%22white%22 font-size=%2240%22 font-family=%22Arial%22%3EMakima media preview%3C/text%3E%3C/svg%3E';
const DEMO_MESSAGES: Message[] = [
  { id: 'demo-user', role: 'user', content: 'Show me how text, code, diagrams, tables, charts, images and video render in Makima.', createdAt: Date.now() },
  { id: 'demo-text', role: 'assistant', content: '## Text and Markdown\nThis is a normal Makima response with **bold text**, a list, and `inline code`.\n\n- Clear hierarchy\n- Markdown support\n- Message actions below each response', createdAt: Date.now() },
  { id: 'demo-code', role: 'assistant', content: 'Here is a code artifact:', artifacts: [{ id: 'demo-code-artifact', kind: 'code', title: 'Python example', language: 'python', content: 'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n\nprint(greet("Makima"))' }], createdAt: Date.now() },
  { id: 'demo-diagram', role: 'assistant', content: 'Mermaid diagrams become interactive artifact cards with Preview and Source controls.', artifacts: [{ id: 'demo-diagram-artifact', kind: 'diagram', title: 'Message rendering flow', content: 'flowchart LR\n  U[User message] --> M[Makima] --> A[Artifact renderer]\n  A --> T[Text]\n  A --> D[Diagram]\n  A --> X[Media]' }], createdAt: Date.now() },
  { id: 'demo-data', role: 'assistant', content: 'Structured data renders as sortable table and chart cards.', artifacts: [{ id: 'demo-table-artifact', kind: 'table', title: 'Response formats', data: { headers: ['Format', 'Renderer', 'Status'], rows: [['Markdown', 'Chat bubble', 'Ready'], ['Mermaid', 'Diagram card', 'Ready'], ['Image', 'Media card', 'Ready'], ['Video', 'Media card', 'Ready']] } }, { id: 'demo-chart-artifact', kind: 'chart', title: 'Example usage', data: { labels: ['Text', 'Code', 'Diagram', 'Media'], values: [92, 78, 64, 51], type: 'bar' } }], createdAt: Date.now() },
  { id: 'demo-media', role: 'assistant', content: 'Media artifacts get their own safe preview area and controls. The image is self-contained; the video uses a public sample URL for preview.', artifacts: [{ id: 'demo-image-artifact', kind: 'image', title: 'Self-contained image preview', url: DEMO_IMAGE_URL, metadata: { alt: 'Makima gradient media preview' } }, { id: 'demo-video-artifact', kind: 'video', title: 'Video player preview', url: 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4' }], createdAt: Date.now() },
];

function isTextAttachment(file: File) {
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  return file.type.startsWith('text/') || TEXT_FILE_EXTENSIONS.has(extension) || file.type === 'application/json';
}

function connectionLabel(state: ConnectionState) {
  if (state === 'connected') return 'Live connection';
  if (state === 'connecting') return 'Connecting…';
  if (state === 'reconnecting') return 'Reconnecting…';
  if (state === 'offline') return 'Server offline';
  return 'Starting…';
}

function WelcomeHeroStage({
  onSurprise,
  onSelectDraft,
}: {
  onSurprise: () => void;
  onSelectDraft: (prompt: string) => void;
}) {
  const [wordIndex, setWordIndex] = useState(0);
  const [wordPhase, setWordPhase] = useState<'coming' | 'going'>('coming');
  const [promptIndex, setPromptIndex] = useState(0);
  const [typedText, setTypedText] = useState('');
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    let flipTimeout: number | null = null;
    const cycleTimer = window.setInterval(() => {
      setWordPhase('going');
      flipTimeout = window.setTimeout(() => {
        setWordIndex((prev) => (prev + 1) % HERO_ROTATING_WORDS.length);
        setWordPhase('coming');
      }, 340);
    }, 2800);

    return () => {
      window.clearInterval(cycleTimer);
      if (flipTimeout !== null) window.clearTimeout(flipTimeout);
    };
  }, []);

  useEffect(() => {
    const fullPrompt = TYPEWRITER_PROMPTS[promptIndex] ?? '';
    let timer: number;

    if (!isDeleting && typedText.length < fullPrompt.length) {
      timer = window.setTimeout(() => {
        setTypedText(fullPrompt.slice(0, typedText.length + 1));
      }, 36);
    } else if (!isDeleting && typedText.length === fullPrompt.length) {
      timer = window.setTimeout(() => {
        setIsDeleting(true);
      }, 1700);
    } else if (isDeleting && typedText.length > 0) {
      timer = window.setTimeout(() => {
        setTypedText(fullPrompt.slice(0, typedText.length - 1));
      }, 18);
    } else {
      timer = window.setTimeout(() => {
        setIsDeleting(false);
        setPromptIndex((prev) => (prev + 1) % TYPEWRITER_PROMPTS.length);
      }, 220);
    }

    return () => window.clearTimeout(timer);
  }, [typedText, isDeleting, promptIndex]);

  const activeFullPrompt = (TYPEWRITER_PROMPTS[promptIndex] ?? '').replace(/\.{3}$/, '');

  return (
    <div className="welcome">
      <div className="welcome-orbit-wrap">
        <div className="floating-keywords-cloud" aria-hidden="true">
          {FLOATING_KEYWORDS.map((kw, i) => (
            <span
              key={kw}
              className={`floating-keyword kw-${i}`}
              style={{ animationDelay: `${i * 0.95}s` }}
            >
              {kw}
            </span>
          ))}
        </div>
        <div className="welcome-icon"><Sparkles size={24} /></div>
      </div>

      <h1 className="hero-title-shimmer">What shall we make?</h1>

      <div className="hero-word-rotator" aria-live="polite">
        <span className="rotator-prefix">Ready to</span>
        <span className="rotator-window">
          <span key={wordIndex} className={`rotator-word ${wordPhase}`}>
            {HERO_ROTATING_WORDS[wordIndex]}
          </span>
        </span>
      </div>

      <p>Chat with Makima, inspect artifacts, and open any result in Canvas.</p>

      <button
        type="button"
        className="typewriter-showcase"
        onClick={() => onSelectDraft(activeFullPrompt)}
        title="Click to populate this prompt"
      >
        <span className="typewriter-badge"><Sparkles size={11} /> LIVE</span>
        <span className="typewriter-text">{typedText || '\u00A0'}</span>
        <span className="typewriter-caret" aria-hidden="true">▍</span>
      </button>

      <div className="suggestions">
        <button className="surprise-button" onClick={onSurprise}><Sparkles size={14} /> Surprise me 🎲</button>
        <button onClick={() => onSelectDraft('Inspect the current project and summarize the architecture')}>Inspect my project <ArrowDownToLine size={14} /></button>
        <button onClick={() => onSelectDraft('Create a chart from this week’s telemetry')}>Analyze telemetry <Activity size={14} /></button>
        <button onClick={() => onSelectDraft('Plan a safe OSWorld-style UI task')}>Plan a benchmark task <Zap size={14} /></button>
      </div>
    </div>
  );
}

function App() {
  const restored = useMemo(() => {
    const session = loadPersistedSession<Message>();
    const cleanedMessages = (session.messages ?? []).map((m) =>
      m.role === 'assistant' && m.pending
        ? { ...m, pending: false, error: m.error || 'Generation was interrupted (server closed or reloaded).' }
        : m
    );
    return { ...session, messages: cleanedMessages };
  }, []);
  const [settings, setSettings] = useState<UiSettings>({ ...DEFAULT_SETTINGS, ...(restored.settings ?? {}) });
  const [backends, setBackends] = useState<Backend[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [apiError, setApiError] = useState('');
  const [telemetry, setTelemetry] = useState<Array<Record<string, unknown>>>([]);
  const [messages, setMessages] = useState<Message[]>(new URLSearchParams(window.location.search).has('demo') ? DEMO_MESSAGES : restored.messages);
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [dropActive, setDropActive] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pluginsOpen, setPluginsOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('models');
  const [view, setView] = useState<View>('chat');
  const [canvas, setCanvas] = useState<Artifact | null>(null);
  const [fullscreen, setFullscreen] = useState<Artifact | null>(null);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const eventsBufferRef = useRef<StreamEvent[]>([]);
  const eventsFlushTimerRef = useRef<number | null>(null);
  const settingsOpenRef = useRef(settingsOpen);
  const scrollRafRef = useRef<number | null>(null);
  const [sessionName, setSessionName] = useState('New session');
  const [toast, setToast] = useState<{ message: string; tone: 'success' | 'error' | 'info' } | null>(null);
  const [copiedMessage, setCopiedMessage] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionSearch, setSessionSearch] = useState('');
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => {
    const saved = localStorage.getItem('makima_sidebar_open');
    return saved !== null ? saved === 'true' : true;
  });
  useEffect(() => {
    localStorage.setItem('makima_sidebar_open', String(sidebarOpen));
  }, [sidebarOpen]);
  useEffect(() => {
    settingsOpenRef.current = settingsOpen;
    if (settingsOpen) {
      setEvents(eventsBufferRef.current);
    }
  }, [settingsOpen]);
  useEffect(() => {
    return () => {
      if (scrollRafRef.current !== null) {
        window.cancelAnimationFrame(scrollRafRef.current);
      }
      if (eventsFlushTimerRef.current !== null) {
        window.clearTimeout(eventsFlushTimerRef.current);
      }
    };
  }, []);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState('');
  const [currentSessionId, setCurrentSessionId] = useState(() => localStorage.getItem('makima.current_session') || '');
  const [brandQuip, setBrandQuip] = useState<string | null>(null);
  const [showScrollBottom, setShowScrollBottom] = useState(false);
  const brandClicksRef = useRef<{ count: number; lastTime: number }>({ count: 0, lastTime: 0 });
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const lastSettingsRef = useRef(settings);
  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const handleBrandClick = () => {
    const now = Date.now();
    if (now - brandClicksRef.current.lastTime < 500) {
      brandClicksRef.current.count += 1;
    } else {
      brandClicksRef.current.count = 1;
    }
    brandClicksRef.current.lastTime = now;

    if (brandClicksRef.current.count >= 3) {
      launchConfetti();
      setBrandQuip('Celebration unlocked! 🚀✨');
      brandClicksRef.current.count = 0;
    } else {
      const randomQuip = MAKIMA_QUIPS[Math.floor(Math.random() * MAKIMA_QUIPS.length)];
      setBrandQuip(randomQuip);
    }

    window.setTimeout(() => setBrandQuip(null), 3200);
  };

  const handleSurprisePrompt = () => {
    const randomPrompt = SURPRISE_PROMPTS[Math.floor(Math.random() * SURPRISE_PROMPTS.length)];
    setDraft(randomPrompt);
    input.current?.focus();
  };

  const handleChatScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget;
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = window.requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const isUp = target.scrollHeight - target.scrollTop - target.clientHeight > 180;
      setShowScrollBottom((prev) => (prev !== isUp ? isUp : prev));
    });
  }, []);

  const adjustComposerHeight = useCallback((target: HTMLTextAreaElement) => {
    window.requestAnimationFrame(() => {
      target.style.height = 'auto';
      const nextHeight = `${Math.min(target.scrollHeight, 180)}px`;
      if (target.style.height !== nextHeight) {
        target.style.height = nextHeight;
      }
    });
  }, []);

  const scrollToBottom = () => {
    chatScrollRef.current?.scrollTo({
      top: chatScrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
    setShowScrollBottom(false);
  };

  const notify = useCallback((message: string, tone: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 2600);
  }, []);

  const handleEvent = useCallback((event: StreamEvent) => {
    eventsBufferRef.current = [...eventsBufferRef.current.slice(-99), event];
    if (settingsOpenRef.current) {
      if (eventsFlushTimerRef.current === null) {
        eventsFlushTimerRef.current = window.setTimeout(() => {
          eventsFlushTimerRef.current = null;
          if (settingsOpenRef.current) {
            setEvents(eventsBufferRef.current);
          }
        }, 200);
      }
    }
    const taskId = String(event.task_id ?? '');
    if (typeof event.session_id === 'string' && event.session_id.trim()) {
      const incomingSessionId = event.session_id.trim();
      setCurrentSessionId((prev) => {
        if (!prev) {
          localStorage.setItem('makima.current_session', incomingSessionId);
          return incomingSessionId;
        }
        return prev;
      });
    }
    if (event.type === 'message') {
      playChime();
      const content = String(event.content ?? '');
      const suggestions = Array.isArray(event.suggestions) ? event.suggestions.map(String).filter(Boolean) : [];
      const artifacts = (Array.isArray(event.artifacts) ? event.artifacts.map((item) => normalizeArtifact(item)) : []).concat(detectArtifacts(content));
      setMessages((current) => {
        const hasAssistant = current.some((item) => item.id === taskId && item.role === 'assistant');
        if (hasAssistant) {
          return current.map((item) => item.id === taskId && item.role === 'assistant' ? { ...item, content, artifacts, suggestions, pending: false } : item);
        }
        return [...current, { id: taskId, role: 'assistant', content, artifacts, suggestions, pending: false, createdAt: Date.now() }];
      });
      const currentSettings = lastSettingsRef.current;
      if (currentSettings.read_aloud && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(content);
        utterance.rate = currentSettings.voice_speed;
        window.speechSynthesis.speak(utterance);
      }
    } else if (event.type === 'artifact_ready' && event.artifact) {
      const artifact = normalizeArtifact(event.artifact);
      setMessages((current) => current.map((item) => item.id === taskId && item.role === 'assistant' ? { ...item, artifacts: [...(item.artifacts ?? []), artifact] } : item));
    } else if (event.type === 'artifact_error' || event.type === 'error') {
      setMessages((current) => current.map((item) => item.id === taskId && item.role === 'assistant' ? { ...item, pending: false, error: String(event.message ?? 'Makima could not complete this task.') } : item));
    } else if (event.type === 'task_cancelled') {
      setMessages((current) => current.map((item) => item.id === taskId && item.role === 'assistant' ? { ...item, pending: false, error: 'Task cancelled.' } : item));
    }
  }, []);

  const onSocketNotice = useCallback((message: string) => notify(message, 'error'), [notify]);
  const socket = useMakimaSocket({ configuredUrl: settings.ws_url, onEvent: handleEvent, onNotice: onSocketNotice });
  const connection = socket.connectionState;

  const handleStop = useCallback((targetTaskId?: string) => {
    socket.stop();
    setMessages((current) => current.map((item) =>
      item.role === 'assistant' && item.pending && (!targetTaskId || item.id === targetTaskId)
        ? { ...item, pending: false, error: 'Task cancelled.' }
        : item
    ));
    notify('Response generation stopped', 'info');
  }, [notify, socket]);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([api.status(), api.connectors(), api.tools(), api.telemetry()]);
    const [statusResult, connectorResult, toolsResult, telemetryResult] = results;
    if (statusResult.status === 'fulfilled') { setStatus(statusResult.value); setBackends(Object.values(statusResult.value.providers.backends)); }
    if (connectorResult.status === 'fulfilled') setConnectors(connectorResult.value.connectors);
    if (toolsResult.status === 'fulfilled') setTools(toolsResult.value.tools);
    if (telemetryResult.status === 'fulfilled') setTelemetry(telemetryResult.value.events.slice(-100));
    const rejected = results.find((result) => result.status === 'rejected');
    if (rejected?.status === 'rejected') {
      const message = userFacingError(rejected.reason);
      setApiError(message);
      throw rejected.reason;
    }
    setApiError('');
  }, []);

  useEffect(() => {
    lastSettingsRef.current = settings;
    document.documentElement.dataset.theme = settings.theme;
  }, [settings]);

  useEffect(() => {
    if (!settings.local_session_persistence) return;
    try { saveSession(settings, messages); } catch { notify('Session storage is full; older messages were not saved.', 'error'); }
  }, [messages, notify, settings]);

  useEffect(() => {
    refresh().catch((error) => notify(userFacingError(error), 'error'));
  }, [notify, refresh]);

  const refreshSessions = useCallback(async (query = sessionSearch) => {
    try {
      const response = await api.sessions(query, true);
      setSessions(response.sessions);
      const activeId = currentSessionId || localStorage.getItem('makima.current_session') || (response.sessions[0]?.id ?? '');
      if (activeId) {
        if (!currentSessionId) {
          setCurrentSessionId(activeId);
          localStorage.setItem('makima.current_session', activeId);
        }
        if (!messagesRef.current.length) {
          try {
            const detail = await api.getSession(activeId);
            if (detail.session?.messages?.length) {
              setSessionName(detail.session.title);
              setMessages(detail.session.messages.filter((m) => m.role !== 'system').map((message) => {
                const metadataArtifacts = Array.isArray(message.metadata?.artifacts)
                  ? (message.metadata.artifacts as unknown[]).map((item) => normalizeArtifact(item))
                  : [];
                const detected = message.role === 'assistant' ? detectArtifacts(message.content) : [];
                const artifacts = metadataArtifacts.concat(detected);
                return {
                  id: message.id,
                  role: message.role === 'assistant' ? 'assistant' : 'user',
                  content: message.content,
                  artifacts: artifacts.length ? artifacts : undefined,
                  suggestions: Array.isArray(message.metadata?.suggestions) ? (message.metadata.suggestions as string[]) : undefined,
                  createdAt: message.created_at,
                };
              }));
            }
          } catch {
            /* keep local cache */
          }
        }
      }
    } catch {
      // The local cache remains usable while the API is offline.
    }
  }, [currentSessionId, sessionSearch]);

  useEffect(() => { void refreshSessions(''); }, [refreshSessions]);

  useEffect(() => {
    if (view !== 'telemetry') return undefined;
    const timer = window.setInterval(() => { refresh().catch(() => undefined); }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh, view]);

  useEffect(() => {
    if (socket.taskState !== 'interrupted' && connection !== 'offline') return;
    setMessages((current) => current.map((item) =>
      item.role === 'assistant' && item.pending
        ? { ...item, pending: false, error: 'Connection interrupted (server stopped or disconnected). Review the prompt and retry explicitly.' }
        : item
    ));
  }, [connection, socket.taskState]);

  useEffect(() => {
    if (socket.taskState !== 'running') return undefined;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = 'A task is currently running in Makima. Leaving or going back will interrupt the task.';
      return event.returnValue;
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [socket.taskState]);

  useEffect(() => {
    // Push a defensive history state entry so accidental back button/swipe gestures are trapped inside Makima
    try {
      window.history.pushState({ makimaApp: true }, '', window.location.href);
    } catch {
      /* ignore */
    }

    const handlePopState = () => {
      // Re-push immediately so repeated back clicks or swipes remain trapped in Makima
      try {
        window.history.pushState({ makimaApp: true }, '', window.location.href);
      } catch {
        /* ignore */
      }

      if (socket.taskState === 'running') {
        notify('Accidental back prevented: Makima is currently working on your task.', 'info');
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, [notify, socket.taskState]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const modifier = event.ctrlKey || event.metaKey;
      if (event.key === 'Escape') {
        if (socket.activeTaskId || messagesRef.current.some((m) => m.role === 'assistant' && m.pending)) {
          handleStop();
          return;
        }
        setSettingsOpen(false);
        setCommandOpen(false);
      }
      if (modifier && event.key.toLowerCase() === 'k') { event.preventDefault(); setCommandOpen(true); setCommandQuery(''); }
      if (modifier && event.shiftKey && event.key.toLowerCase() === 'n') { event.preventDefault(); clearChat(); }
      if (modifier && event.shiftKey && event.key.toLowerCase() === 'o') { event.preventDefault(); input.current?.focus(); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [settingsOpen]);

  useEffect(() => {
    if (!settingsOpen) return;
    refresh().catch((error) => notify(userFacingError(error), 'error'));
  }, [notify, refresh, settingsOpen]);

  const updateSettings = async (patch: Partial<UiSettings>) => {
    const previous = settings;
    const next = { ...settings, ...patch };
    setSettings(next);
    try {
      const response = await api.saveSettings(patch);
      setSettings({ ...DEFAULT_SETTINGS, ...response.settings });
      notify('Settings saved', 'success');
    } catch (error) {
      setSettings(previous);
      notify(`Settings rolled back — ${userFacingError(error, 'backend save failed')}`, 'error');
      throw error;
    }
  };

  const updateConnector = async (id: string, enabled: boolean) => {
    const previous = connectors;
    setConnectors(previous.map((connector) => connector.id === id ? { ...connector, enabled, health: enabled ? 'checking' : 'disabled' } : connector));
    try {
      const response = await api.saveConnector(id, enabled);
      setConnectors((current) => current.map((connector) => connector.id === id ? response.connector : connector));
      notify(`${id} ${enabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (error) { setConnectors(previous); notify(`Connector change rolled back — ${userFacingError(error)}`, 'error'); throw error; }
  };

  const checkConnector = async (id: string) => {
    try { const response = await api.checkConnector(id); setConnectors((current) => current.map((connector) => connector.id === id ? response.connector : connector)); notify(`${id} health checked`, 'success'); }
    catch (error) { notify(userFacingError(error, 'Connector health check failed.'), 'error'); throw error; }
  };

  const configureConnector = async (id: string, credential: string, bridgeUrl?: string) => {
    try {
      const response = await api.configureConnector(id, credential, bridgeUrl);
      setConnectors((current) => current.map((c) => c.id === id ? response.connector : c));
      notify(response.message || `Authorized ${id}`, 'success');
      return response;
    } catch (error) {
      notify(userFacingError(error, `Failed to authorize ${id}`), 'error');
      throw error;
    }
  };

  const disconnectConnector = async (id: string) => {
    try {
      const response = await api.disconnectConnector(id);
      setConnectors((current) => current.map((c) => c.id === id ? response.connector : c));
      notify(response.message || `Disconnected ${id}`, 'info');
      return response;
    } catch (error) {
      notify(userFacingError(error, `Failed to disconnect ${id}`), 'error');
      throw error;
    }
  };

  const updateTool = async (name: string, enabled: boolean) => {
    const previous = tools;
    setTools(previous.map((tool) => tool.function?.name === name ? { ...tool, enabled, status: enabled ? 'checking' : 'disabled' } : tool));
    try { await api.saveTool(name, enabled); notify(`${name} ${enabled ? 'enabled' : 'disabled'}`, 'success'); }
    catch (error) { setTools(previous); notify(`Tool change rolled back — ${userFacingError(error)}`, 'error'); throw error; }
  };

  const checkTool = async (name: string) => {
    try { const response = await api.checkTool(name); setTools((current) => current.map((tool) => tool.function?.name === name ? { ...tool, status: response.status, enabled: response.enabled } : tool)); notify(`${name} health checked`, 'success'); }
    catch (error) { notify(userFacingError(error, 'Tool health check failed.'), 'error'); throw error; }
  };

  const reset = async () => {
    setSettings(DEFAULT_SETTINGS); setMessages([]); clearSession();
    try { await api.saveSettings(DEFAULT_SETTINGS); notify('Defaults restored', 'success'); }
    catch (error) { notify(`Defaults applied locally — ${userFacingError(error)}`, 'error'); }
  };

  const addFiles = async (files: FileList | File[]) => {
    const selected = Array.from(files);
    if (!selected.length) return;
    if (attachments.length + selected.length > MAX_ATTACHMENTS) {
      notify(`Attach up to ${MAX_ATTACHMENTS} files per message.`, 'error');
      return;
    }
    const next: ChatAttachment[] = [];
    for (const file of selected) {
      if (file.size > MAX_FILE_BYTES) {
        notify(`${file.name} is larger than 8 MB and was skipped.`, 'error');
        continue;
      }
      const attachment: ChatAttachment = { id: uid(), name: file.name.slice(0, 180), mimeType: file.type || 'application/octet-stream', size: file.size };
      if (isTextAttachment(file)) {
        try {
          attachment.textPreview = (await file.text()).slice(0, MAX_TEXT_PREVIEW);
          if (file.size > MAX_TEXT_PREVIEW) attachment.textPreview += '\n[…preview truncated for safety…]';
        } catch {
          notify(`Could not read ${file.name}.`, 'error');
          continue;
        }
      }
      next.push(attachment);
    }
    if (next.length) {
      setAttachments((current) => [...current, ...next]);
      notify(`${next.length} file${next.length === 1 ? '' : 's'} attached`, 'success');
    }
    if (fileInput.current) fileInput.current.value = '';
  };

  const send = async (customPrompt?: string) => {
    const isCustom = typeof customPrompt === 'string';
    const content = isCustom ? customPrompt.trim() : draft.trim();
    const activeAttachments = isCustom ? [] : attachments;
    if ((!content && !activeAttachments.length) || socket.activeTaskId || connection !== 'connected') return;
    let sessionId = currentSessionId;
    if (!sessionId) {
      try {
        const created = await api.createSession(sessionName, settings.active_backend);
        sessionId = created.session.id;
        setCurrentSessionId(sessionId);
        localStorage.setItem('makima.current_session', sessionId);
      } catch { /* the WebSocket remains usable without persistence */ }
    }
    const taskId = uid();
    const requestContent = content || 'Please inspect the attached file(s) and summarize anything important.';
    const thinkingMode = settings.thinking_mode || 'off';
    const payload = JSON.stringify({ type: 'user_message', task_id: taskId, message_id: `message_${taskId}`, session_id: sessionId || undefined, content: requestContent, attachments: activeAttachments.map(({ id, name, mimeType, size, textPreview }) => ({ id, name, mime_type: mimeType, size, text_preview: textPreview })), task: thinkingMode === 'on' ? 'deep_reasoning' : 'fast_chat', thinking_mode: thinkingMode, max_turns: settings.max_turns, temperature: settings.temperature, system_prompt: settings.system_prompt || undefined, backend: settings.active_backend || undefined });
    const createdAt = Date.now();
    playWhoosh();
    setMessages((current) => [
      ...current.map((item) => (item.pending ? { ...item, pending: false } : item)),
      { id: taskId, role: 'user', content: content || 'Please inspect the attached file(s).', attachments: activeAttachments, createdAt },
      { id: taskId, role: 'assistant', content: '', pending: true, createdAt },
    ]);
    if (!isCustom) {
      setDraft(''); setAttachments([]);
      if (input.current) input.current.style.height = 'auto';
    }
    setView('chat');
    if (!socket.send(payload, taskId)) notify('Makima is reconnecting. Send again when the connection is live.', 'info');
    void refreshSessions('');
  };

  const copyMessage = useCallback(async (id: string, content: string) => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessage(id);
      window.setTimeout(() => setCopiedMessage((current) => current === id ? null : current), 1500);
      notify('Message copied', 'success');
    } catch { notify('Clipboard access was not available.', 'error'); }
  }, [notify]);

  const handleCopy = useCallback((content: string, id?: string) => {
    if (id) {
      void copyMessage(id, content);
    }
  }, [copyMessage]);

  const clearChat = async () => {
    setMessages([]); setAttachments([]); setDraft(''); setView('chat'); setSessionName('New session');
    if (input.current) input.current.style.height = 'auto';
    try { const created = await api.createSession('New session', settings.active_backend); setCurrentSessionId(created.session.id); localStorage.setItem('makima.current_session', created.session.id); await refreshSessions(''); } catch { /* local blank session remains available */ }
    notify('New blank session ready', 'info');
  };
  const loadSession = async (summary: SessionSummary) => {
    try {
      const response = await api.getSession(summary.id);
      setCurrentSessionId(summary.id); localStorage.setItem('makima.current_session', summary.id);
      setSessionName(response.session.title);
      setMessages(response.session.messages.filter((message) => message.role !== 'system').map((message) => {
        const metadataArtifacts = Array.isArray(message.metadata?.artifacts)
          ? (message.metadata.artifacts as unknown[]).map((item) => normalizeArtifact(item))
          : [];
        const detected = message.role === 'assistant' ? detectArtifacts(message.content) : [];
        const artifacts = metadataArtifacts.concat(detected);
        return {
          id: message.id,
          role: message.role === 'assistant' ? 'assistant' : 'user',
          content: message.content,
          artifacts: artifacts.length ? artifacts : undefined,
          suggestions: Array.isArray(message.metadata?.suggestions) ? (message.metadata.suggestions as string[]) : undefined,
          createdAt: message.created_at,
        };
      }));
      setView('chat'); setSessionDrawerOpen(false);
    } catch { notify('Could not open that session.', 'error'); }
  };
  const updateSession = async (id: string, patch: Partial<Pick<SessionSummary, 'title' | 'pinned' | 'archived'>>) => {
    try { await api.updateSession(id, patch); await refreshSessions(sessionSearch); } catch (error) { notify(userFacingError(error), 'error'); }
  };
  const deleteSession = async (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      await api.deleteSession(id);
      notify('Chat deleted', 'info');
      if (id === currentSessionId) {
        await clearChat();
      } else {
        await refreshSessions(sessionSearch);
      }
    } catch (error) {
      notify(userFacingError(error, 'Could not delete session'), 'error');
    }
  };
  const exportCurrentSession = async () => {
    if (!currentSessionId) return;
    try { const payload = await api.exportSession(currentSessionId); const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }); const anchor = document.createElement('a'); anchor.href = URL.createObjectURL(blob); anchor.download = `${sessionName.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase() || 'makima-session'}.json`; anchor.click(); URL.revokeObjectURL(anchor.href); notify('Session exported', 'success'); } catch (error) { notify(userFacingError(error), 'error'); }
  };
  const handleRetry = useCallback((message: ChatMessageData) => {
    const original = messagesRef.current.find((item) => item.id === message.id && item.role === 'user');
    setDraft(original?.content ?? message.content);
    setAttachments(original?.attachments ?? message.attachments?.map((attachment) => ({ ...attachment, mimeType: 'application/octet-stream' })) ?? []);
    input.current?.focus();
    setView('chat');
  }, []);

  const sendRef = useRef(send);
  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  const handleSelectSuggestion = useCallback((suggestion: string) => {
    void sendRef.current(suggestion);
  }, []);
  const artifacts = useMemo(() => messages.flatMap((message) => message.artifacts ?? []), [messages]);

  const handleUpdateArtifact = useCallback((updated: Artifact) => {
    setCanvas(updated);
    setMessages((current) => current.map((message) => {
      if (!message.artifacts?.some((item) => item.id === updated.id)) return message;
      return {
        ...message,
        artifacts: message.artifacts.map((item) => item.id === updated.id ? updated : item),
      };
    }));
    notify(`Saved "${updated.title || updated.kind}" to workspace`, 'success');
  }, [notify]);

  const handleAskMakimaInCanvas = useCallback((instruction: string, currentContent: string, artifact: Artifact) => {
    const language = artifact.language || artifact.kind;
    const prompt = `[CANVAS COLLABORATIVE EDIT]
Artifact: ${artifact.title || artifact.kind} (${language})
Instruction: ${instruction}

Current Canvas Content:
\`\`\`${artifact.language || ''}
${currentContent}
\`\`\`

Please apply the requested changes, explain what was modified, and provide the updated version in an artifact/code block.`;
    void send(prompt);
    notify('Instruction sent to Makima. Watch chat for updates.', 'info');
  }, [notify, send]);

  const pageTitle = view === 'chat' ? sessionName : view === 'artifacts' ? 'Saved artifacts' : 'Telemetry & health';
  const isGenerating = Boolean(socket.activeTaskId || messages.some((m) => m.role === 'assistant' && m.pending));
  const canSend = connection === 'connected' && !isGenerating && Boolean(draft.trim() || attachments.length);

  return <div className={`app-shell ${sidebarOpen ? 'sidebar-open' : 'sidebar-collapsed'}`}>
    <div className={`ambient-glow ${isGenerating ? 'active' : ''}`} />
    <aside className={`sidebar ${sessionDrawerOpen ? 'session-drawer-open' : ''}`}>
      <div className="brand">
        <div className="brand-mark" onClick={handleBrandClick} title="Makima Core (Click for status)">
          <Sparkles size={18} />
          {brandQuip && (
            <div className="brand-quip-popover">
              <Sparkles size={12} color="var(--accent)" />
              <span>{brandQuip}</span>
            </div>
          )}
        </div>
        <div><strong>MAKIMA</strong><small>v2 command deck</small></div>
        <Button className="sidebar-toggle-btn" title="Collapse sidebar" aria-label="Collapse sidebar" onClick={() => setSidebarOpen(false)} style={{ marginLeft: 'auto', padding: '6px', minWidth: 'auto', background: 'transparent', border: 0 }}><Menu size={16} /></Button>
      </div>
      <Button className="new-chat" onClick={() => void clearChat()}><Plus size={16} /> New session</Button>
      <Button className="search-sessions" onClick={() => { setSessionDrawerOpen(true); setSessionSearch(''); }}><Search size={15} /> Search chats <kbd>⌘K</kbd></Button>
      <div className="side-section"><small>WORKSPACE</small><button className={`side-item ${view === 'chat' ? 'active' : ''}`} onClick={() => setView('chat')}><MessageSquare size={15} /> Chat</button><button className={`side-item ${view === 'artifacts' ? 'active' : ''}`} onClick={() => setView('artifacts')}><Archive size={15} /> Artifacts <em>{artifacts.length}</em></button><button className={`side-item ${view === 'telemetry' ? 'active' : ''}`} onClick={() => setView('telemetry')}><Gauge size={15} /> Telemetry</button></div>
      <div className="session-list"><small>RECENT CHATS</small>{sessions.slice(0, 8).map((session) => <div className={`session-row ${session.id === currentSessionId ? 'active' : ''}`} key={session.id}><button className="session-item" onClick={() => void loadSession(session)}><span>{session.pinned ? '★ ' : ''}{session.title}</span><small>{session.message_count} messages</small></button><button type="button" className="session-delete-btn" title={`Delete "${session.title}"`} aria-label={`Delete ${session.title}`} onClick={(e) => void deleteSession(session.id, e)}><Trash2 size={12} /></button></div>)}{!sessions.length && <span className="muted session-empty">No saved chats yet.</span>}</div>
      <div className="sidebar-spacer" />
      <div className="sidebar-status"><span className={`status-dot ${connection === 'connected' ? 'good' : ''}`} /> {connectionLabel(connection)}</div>
      <Button className="settings-button" onClick={() => setSettingsOpen(true)}><Settings size={16} /> Settings</Button>
    </aside>
    <main className="main-panel">
      <header className="topbar">
        <Button className="sidebar-expand-btn" aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'} title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'} onClick={() => setSidebarOpen((open) => !open)} style={{ marginRight: '8px', padding: '6px', minWidth: 'auto' }}><Menu size={18} /></Button>
        <div className="mobile-brand"><span>Makima</span></div>
        <div className="session-heading">
          <span className={`status-dot ${connection === 'connected' ? 'good' : ''}`} />
          <input value={pageTitle} onChange={(event) => view === 'chat' && setSessionName(event.target.value)} aria-label="Session name" readOnly={view !== 'chat'} />
          {view === 'chat' && currentSessionId && (
            <button
              type="button"
              className="session-header-delete-btn"
              title="Delete this chat"
              aria-label="Delete this chat"
              onClick={() => void deleteSession(currentSessionId)}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
        <div className="top-actions"><Button className="command-button" title="Open command palette" aria-label="Open command palette" onClick={() => { setCommandOpen(true); setCommandQuery(''); }}><Command size={15} /><kbd>⌘K</kbd></Button><ModelPicker backends={backends} activeBackend={settings.active_backend} onSelect={(backendId) => void updateSettings({ active_backend: backendId })} /><Button className="topbar-label-button" title="Plugins & OpenAPI" onClick={() => setPluginsOpen(true)}><Cpu size={14} /><span>Plugins</span></Button><Button className="topbar-label-button" title="Connectors" onClick={() => { setTab('connectors'); setSettingsOpen(true); }}><Layers size={14} /><span>Connectors</span></Button><Button className="topbar-label-button" title="Voice settings" onClick={() => { setTab('voice'); setSettingsOpen(true); }}><Mic size={14} /><span>Voice</span></Button><Button className="topbar-label-button" title="Telemetry" onClick={() => setView('telemetry')}><Gauge size={14} /><span>Telemetry</span></Button><Button className="topbar-label-button" title="Settings" onClick={() => setSettingsOpen(true)}><Settings size={14} /><span>Settings</span></Button><Button title="Toggle theme" aria-label="Toggle theme" onClick={() => void updateSettings({ theme: settings.theme === 'dark' ? 'light' : 'dark' })}>{settings.theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</Button></div>
      </header>
      {connection !== 'connected' && <div className="connection-banner" role="status"><span className="status-dot" /> {connectionLabel(connection)} Your current task will not be resent automatically. <Button onClick={socket.reconnect}>Reconnect</Button></div>}
      {socket.taskStage && socket.activeTaskId && <div className="task-notice" role="status" aria-live="polite">{socket.taskStage} <span className="muted">· one foreground task</span></div>}
      {view === 'chat' && <>
        <div className="chat-scroll" ref={chatScrollRef} onScroll={handleChatScroll}>
          {messages.length === 0 ? (
            <WelcomeHeroStage
              onSurprise={handleSurprisePrompt}
              onSelectDraft={(prompt) => {
                setDraft(prompt);
                input.current?.focus();
              }}
            />
          ) : messages.map((message, index) => (

            <ChatMessage
              key={`${message.id}-${message.role}-${index}`}
              message={message}
              copied={copiedMessage === message.id}
              onCopy={handleCopy}
              onRetry={handleRetry}
              onCanvas={setCanvas}
              onFullscreen={setFullscreen}
              onSelectSuggestion={handleSelectSuggestion}
              onStop={handleStop}
            />
          ))}
        </div>
        {showScrollBottom && (
          <button type="button" className="scroll-bottom-pill" onClick={scrollToBottom} aria-label="Scroll to bottom">
            <ArrowDown size={14} /> Latest
          </button>
        )}
        <div className="composer-wrap"><div className={`composer ${dropActive ? 'drop-active' : ''}`} onDragEnter={(event) => { event.preventDefault(); setDropActive(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (event.currentTarget === event.target) setDropActive(false); }} onDrop={(event) => { event.preventDefault(); setDropActive(false); void addFiles(event.dataTransfer.files); }}><input ref={fileInput} className="file-input" type="file" multiple accept="*/*" onChange={(event) => void addFiles(event.target.files ?? [])} /><textarea ref={input} value={draft} onChange={(event) => { setDraft(event.target.value); adjustComposerHeight(event.currentTarget); }} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }} placeholder={connection === 'connected' ? 'Message Makima…' : 'Waiting for local server…'} rows={1} aria-label="Message Makima" />{attachments.length > 0 && <div className="attachment-strip" aria-label="Pending attachments">{attachments.map((attachment) => <span className="attachment-chip" key={attachment.id}><FileText size={13} /><span title={attachment.name}>{attachment.name}</span><button type="button" onClick={() => setAttachments((current) => current.filter((item) => item.id !== attachment.id))} aria-label={`Remove ${attachment.name}`}>×</button></span>)}</div>}<div className="composer-tools"><Button className="attach-button" onClick={() => fileInput.current?.click()} disabled={Boolean(isGenerating)} aria-label="Attach files" title="Attach files"><Paperclip size={14} /> <span>Attach files</span></Button><VoiceControl settings={settings} onNotice={(message) => notify(message, 'info')} /><label className={`thinking-mode-pill ${(settings.thinking_mode || 'off') !== 'off' ? 'is-active' : ''}`} title="Toggle model reasoning speed vs deep thinking"><Cpu size={13} /><select aria-label="Thinking mode" value={settings.thinking_mode || 'off'} onChange={(event) => void updateSettings({ thinking_mode: event.target.value as 'off' | 'auto' | 'on' })} disabled={Boolean(isGenerating)}><option value="off">⚡ Fast (Thinking Off)</option><option value="auto">✨ Auto Thinking</option><option value="on">🧠 Thinking On</option></select></label><span className="composer-hint"><Info size={12} /> Enter to send · Shift+Enter for newline · 5 files max · 8 MB each</span>{isGenerating ? <Button className="stop-button active-stop-btn" onClick={() => handleStop()} title="Stop response (Escape)" aria-label="Stop response"><Square size={13} fill="currentColor" /> <span>Stop response</span></Button> : <Button className="send-button" onClick={() => void send()} disabled={!canSend} title="Send message" aria-label="Send message"><Send size={15} /></Button>}</div></div><small className="disclaimer">Makima can make mistakes. Review actions before approval.</small></div></>}
      {view === 'artifacts' && <ArtifactWorkspace artifacts={artifacts} onCanvas={setCanvas} onFullscreen={setFullscreen} />}
      {view === 'telemetry' && <TelemetryWorkspace system={status?.system ?? {}} backends={backends} connectors={connectors} events={telemetry} onRefresh={refresh} />}
    </main>
    {sessionDrawerOpen && <div className="session-overlay" role="dialog" aria-modal="true" aria-label="Search chats"><div className="session-panel"><header><div><small>CHAT HISTORY</small><h2>Find a session</h2></div><Button aria-label="Close chat history" onClick={() => setSessionDrawerOpen(false)}><X size={16} /></Button></header><label className="session-search"><Search size={15} /><input autoFocus value={sessionSearch} onChange={(event) => { setSessionSearch(event.target.value); void refreshSessions(event.target.value); }} placeholder="Search chats…" /></label><div className="session-results">{sessions.map((session) => <div className="session-result" key={session.id}><button onClick={() => void loadSession(session)}><strong>{session.title}</strong><small>{session.preview || 'Empty session'} · {session.message_count} messages</small></button><div><Button title="Pin session" aria-label={`Pin ${session.title}`} onClick={() => void updateSession(session.id, { pinned: !session.pinned })}>★</Button><Button title="Archive session" aria-label={`Archive ${session.title}`} onClick={() => void updateSession(session.id, { archived: true })}><Archive size={13} /></Button><Button title="Delete session" aria-label={`Delete ${session.title}`} onClick={(e) => void deleteSession(session.id, e)} style={{ color: 'var(--danger)' }}><Trash2 size={13} /></Button></div></div>)}{!sessions.length && <div className="empty-state">No matching sessions.</div>}</div></div></div>}
    {commandOpen && <div className="command-overlay" role="dialog" aria-modal="true" aria-label="Command palette"><div className="command-panel"><div className="command-search"><Command size={15} /><input autoFocus value={commandQuery} onChange={(event) => setCommandQuery(event.target.value)} placeholder="Type a command…" /></div>{[['New session', () => void clearChat()], ['Search chats', () => setSessionDrawerOpen(true)], ['Open plugins & OpenAPI', () => setPluginsOpen(true)], ['Delete current chat', () => currentSessionId && void deleteSession(currentSessionId)], ['Open artifacts', () => setView('artifacts')], ['Open telemetry', () => setView('telemetry')], ['Open settings', () => setSettingsOpen(true)], ['Toggle theme', () => void updateSettings({ theme: settings.theme === 'dark' ? 'light' : 'dark' })], ['Export current session', () => void exportCurrentSession()]].filter(([label]) => String(label).toLowerCase().includes(commandQuery.toLowerCase())).map(([label, action]) => <button key={String(label)} onClick={() => { (action as () => void)(); setCommandOpen(false); }}><span>{label as string}</span><ChevronDown size={13} /></button>)}</div></div>}
    <CanvasPanel artifact={canvas} onClose={() => setCanvas(null)} onFullscreen={setFullscreen} onUpdateArtifact={handleUpdateArtifact} onAskMakima={handleAskMakimaInCanvas} /><FullscreenArtifact artifact={fullscreen} onClose={() => setFullscreen(null)} />
    {settingsOpen && <SettingsModal tab={tab} setTab={setTab} settings={settings} backends={backends} connectors={connectors} tools={tools} debugEvents={events} apiError={apiError} onClose={() => setSettingsOpen(false)} onRefresh={refresh} onSettingsChange={updateSettings} onConnectorChange={updateConnector} onConnectorCheck={checkConnector} onConnectorConfigure={configureConnector} onConnectorDisconnect={disconnectConnector} onToolChange={updateTool} onToolCheck={checkTool} onReset={reset} />}
    {pluginsOpen && <PluginsModal isOpen={pluginsOpen} onClose={() => setPluginsOpen(false)} onToolsUpdated={refresh} />}
    {toast && <div className={`toast ${toast.tone}`} role="status"><span>{toast.tone === 'success' ? '✓' : toast.tone === 'error' ? '!' : '·'}</span>{toast.message}<Button onClick={() => setToast(null)} aria-label="Dismiss notification"><X size={13} /></Button></div>}
  </div>;
}

export default App;
