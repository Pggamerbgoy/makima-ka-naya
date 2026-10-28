import { memo, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  AlertTriangle,
  ArrowUpRight,
  Bookmark,
  Brain,
  Check,
  ChevronDown,
  Clock,
  Code2,
  Copy,
  Download,
  FileText,
  Globe,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Terminal,
  Volume2,
  VolumeX,
  Wand2,
  Wrench,
} from 'lucide-react';
import { ArtifactCard } from './ArtifactCard';
import { Button } from './ui';
import { playSoftPop } from '../utils/soundEffects';
import type { Artifact, ExecutionStep } from '../types';

export type ChatMessageData = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  attachments?: Array<{ id: string; name: string; size: number }>;
  artifacts?: Artifact[];
  pending?: boolean;
  error?: string;
  createdAt?: number;
  suggestions?: string[];
  steps?: ExecutionStep[];
  currentStage?: string;
};

type Props = {
  message: ChatMessageData;
  copied: boolean;
  onCopy: (content: string, id?: string) => void;
  onRetry: (message: ChatMessageData) => void;
  onCanvas: (artifact: Artifact) => void;
  onFullscreen: (artifact: Artifact) => void;
  onSelectSuggestion?: (suggestion: string) => void;
  onStop?: (id: string) => void;
  onPermissionResponse?: (permissionId: string, allowed: boolean) => void;
};

const REACTION_OPTIONS = ['👍', '❤️', '💡', '🚀'];
const REMARK_PLUGINS = [remarkGfm];

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function getStepIcon(type: string, name?: string) {
  if (type === 'thought') return <Brain size={13} />;
  const n = (name || '').toLowerCase();
  if (n.includes('browser') || n.includes('navigate') || n.includes('fetch') || n.includes('url')) {
    return <Globe size={13} />;
  }
  if (n.includes('search')) {
    return <Search size={13} />;
  }
  if (n.includes('command') || n.includes('bash') || n.includes('shell') || n.includes('exec')) {
    return <Terminal size={13} />;
  }
  return <Wrench size={13} />;
}

function formatArgSummary(args: unknown): string {
  if (!args || typeof args !== 'object') return '';
  const obj = args as Record<string, unknown>;
  const parts: string[] = [];
  if (obj.action) parts.push(`action: ${String(obj.action)}`);
  if (obj.url) {
    const urlStr = String(obj.url);
    try {
      const u = new URL(urlStr);
      parts.push(`url: ${u.hostname}${u.pathname}`);
    } catch {
      parts.push(`url: ${urlStr.slice(0, 45)}`);
    }
  }
  if (obj.query) parts.push(`query: "${String(obj.query).slice(0, 40)}"`);
  if (obj.command) parts.push(`cmd: "${String(obj.command).slice(0, 40)}"`);
  if (obj.selector) parts.push(`sel: ${String(obj.selector)}`);
  if (obj.text) parts.push(`text: "${String(obj.text).slice(0, 30)}"`);
  if (obj.app_name) parts.push(`app: ${String(obj.app_name)}`);
  if (obj.path) parts.push(`path: ${String(obj.path)}`);

  if (!parts.length) {
    const keys = Object.keys(obj).slice(0, 3);
    return keys.map((k) => `${k}: ${String(obj[k]).slice(0, 25)}`).join(', ');
  }
  return parts.join(' · ');
}

function formatResultPreview(result: unknown): string {
  if (result === undefined || result === null) return '';
  if (typeof result === 'string') return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

function ExecutionStepItem({
  step,
  isLive,
  onPermissionResponse,
}: {
  step: ExecutionStep;
  isLive?: boolean;
  onPermissionResponse?: (permissionId: string, allowed: boolean) => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const isThought = step.type === 'thought';
  const isFailed = step.status === 'failed';
  const isRunning = step.status === 'running';
  const isAwaitingApproval = step.status === 'awaiting_approval';

  const duration = step.durationMs ?? step.duration_ms;
  const argSummary = useMemo(() => formatArgSummary(step.arguments), [step.arguments]);
  const resultStr = useMemo(() => formatResultPreview(step.result), [step.result]);
  const hasDetails = Boolean(step.arguments && typeof step.arguments === 'object' && Object.keys(step.arguments).length > 0) || Boolean(resultStr) || Boolean(step.error);

  return (
    <div className={`step-timeline-item ${step.status}`}>
      <div className={`step-timeline-icon ${step.status}`}>
        {isRunning ? (
          <div className="step-spinner" />
        ) : isAwaitingApproval ? (
          <AlertTriangle size={12} className="text-amber-400" />
        ) : isFailed ? (
          <AlertTriangle size={12} className="text-error" />
        ) : isThought ? (
          <Brain size={12} className="text-accent" />
        ) : (
          <Check size={12} className="text-success" />
        )}
      </div>
      <div className="step-timeline-content">
        <div
          className={`step-main-row ${hasDetails ? 'clickable' : ''}`}
          onClick={() => hasDetails && setDetailsOpen((v) => !v)}
          role={hasDetails ? 'button' : undefined}
          tabIndex={hasDetails ? 0 : undefined}
        >
          <div className="step-title-wrap">
            <span className="step-type-icon">{getStepIcon(step.type, step.name)}</span>
            <span className="step-name">{isThought ? 'Reasoning' : (step.name || 'Tool Call')}</span>
            {argSummary ? <span className="step-arg-summary">{argSummary}</span> : null}
            {isThought && step.stage ? (
              <span className="step-thought-snippet">{step.stage.slice(0, 75)}{step.stage.length > 75 ? '…' : ''}</span>
            ) : null}
          </div>
          <div className="step-meta-wrap">
            {duration ? <span className="step-duration">{duration}ms</span> : null}
            {isAwaitingApproval ? (
              <span className="step-badge border border-amber-500/40 bg-amber-500/10 text-amber-400">
                Awaiting Approval
              </span>
            ) : null}
            {isFailed ? <span className="step-badge error">Failed</span> : null}
            {isRunning ? <span className="step-badge running">Running…</span> : null}
            {hasDetails ? (
              <span className={`step-details-toggle ${detailsOpen ? 'open' : ''}`}>
                <ChevronDown size={11} />
              </span>
            ) : null}
          </div>
        </div>

        {isAwaitingApproval && (
          <div className="mt-2.5 p-3 rounded-lg border border-amber-500/50 bg-amber-500/10 text-amber-200">
            <div className="flex items-center gap-1.5 font-semibold text-amber-400 text-xs mb-1.5">
              <span aria-hidden="true">⚠️</span>
              <span>Security Permission Required</span>
            </div>
            <div className="text-xs text-amber-200/90 mb-1.5">
              Tool <strong className="font-mono text-amber-300 font-semibold">{step.name || 'Action'}</strong> requests execution:
            </div>
            {step.arguments && (
              <pre className="mb-2.5 p-2 rounded bg-black/40 text-[11px] font-mono text-amber-100 overflow-x-auto max-h-48 border border-amber-500/20 whitespace-pre-wrap">
                {typeof step.arguments === 'object' && step.arguments !== null
                  ? JSON.stringify(step.arguments, null, 2)
                  : String(step.arguments)}
              </pre>
            )}
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="px-3 py-1.5 rounded text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white transition-colors flex items-center gap-1 cursor-pointer shadow-sm border border-emerald-400/30"
                onClick={(e) => {
                  e.stopPropagation();
                  onPermissionResponse?.(step.permission_id || step.id, true);
                }}
              >
                <Check size={12} />
                <span>Allow Once</span>
              </button>
              <button
                type="button"
                className="px-3 py-1.5 rounded text-xs font-semibold bg-rose-600/90 hover:bg-rose-500 active:bg-rose-700 text-white transition-colors flex items-center gap-1 cursor-pointer shadow-sm border border-rose-400/30"
                onClick={(e) => {
                  e.stopPropagation();
                  onPermissionResponse?.(step.permission_id || step.id, false);
                }}
              >
                <span>Deny</span>
              </button>
            </div>
          </div>
        )}

        {detailsOpen && hasDetails && !isAwaitingApproval && (
          <div className="step-details-panel">
            {step.arguments && typeof step.arguments === 'object' && Object.keys(step.arguments).length > 0 && (
              <div className="step-details-section">
                <div className="step-section-label">Parameters</div>
                <pre className="step-code">{JSON.stringify(step.arguments, null, 2)}</pre>
              </div>
            )}
            {step.error && (
              <div className="step-details-section">
                <div className="step-section-label error">Error / Failure</div>
                <pre className="step-code error">{step.error}</pre>
              </div>
            )}
            {resultStr && !step.error && (
              <div className="step-details-section">
                <div className="step-section-label">Output</div>
                <pre className="step-code">{resultStr.length > 3000 ? resultStr.slice(0, 3000) + '\n…[truncated]' : resultStr}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ExecutionStepsAccordion({
  steps,
  messagePending,
  currentStage,
  onStop,
  messageId,
  hasError,
  onPermissionResponse,
  hasContent,
}: {
  steps?: ExecutionStep[];
  messagePending?: boolean;
  currentStage?: string;
  onStop?: (id: string) => void;
  messageId: string;
  hasError?: boolean;
  onPermissionResponse?: (permissionId: string, allowed: boolean) => void;
  hasContent?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(() => Boolean(hasError || steps?.some((s) => s.status === 'failed' || s.status === 'awaiting_approval')));

  if (!steps || steps.length === 0) {
    if (messagePending && !hasContent) {
      return (
        <div className="thinking-stage" aria-label="Makima is working">
          <div className="thinking-header">
            <div className="aurora-pulse">
              <Sparkles size={13} className="aurora-sparkle" />
              <span>{currentStage || 'Makima is reasoning & synthesizing...'}</span>
            </div>
            {onStop && (
              <button
                type="button"
                className="stop-response-bubble-btn"
                onClick={() => onStop(messageId)}
                title="Stop response"
                aria-label="Stop response"
              >
                <Square size={10} fill="currentColor" />
                <span>Stop response</span>
              </button>
            )}
          </div>
          <div className="typing"><i /><i /><i /></div>
        </div>
      );
    }
    return null;
  }

  const toolSteps = steps.filter((s) => s.type === 'tool');
  const failedStep = steps.find((s) => s.status === 'failed');
  const awaitingStep = steps.find((s) => s.status === 'awaiting_approval');
  const uniqueTools = Array.from(new Set(toolSteps.map((s) => s.name).filter(Boolean))) as string[];
  const totalDuration = steps.reduce((acc, s) => acc + (s.durationMs ?? s.duration_ms ?? 0), 0);

  if (messagePending) {
    return (
      <div className="execution-steps-live" aria-label="Makima execution progress">
        <div className="thinking-header">
          <div className="aurora-pulse">
            <Sparkles size={13} className="aurora-sparkle" />
            <span>{currentStage || (awaitingStep ? `Waiting for permission: ${awaitingStep.name || 'action'}…` : uniqueTools.length ? `Executing ${uniqueTools[uniqueTools.length - 1]}…` : 'Makima is reasoning…')}</span>
          </div>
          {onStop && (
            <button
              type="button"
              className="stop-response-bubble-btn"
              onClick={() => onStop(messageId)}
              title="Stop response"
              aria-label="Stop response"
            >
              <Square size={10} fill="currentColor" />
              <span>Stop response</span>
            </button>
          )}
        </div>

        <div className="execution-timeline live">
          {steps.map((step) => (
            <ExecutionStepItem key={step.id} step={step} isLive onPermissionResponse={onPermissionResponse} />
          ))}
        </div>
        {!hasContent && <div className="typing"><i /><i /><i /></div>}
      </div>
    );
  }

  const summaryTitle = awaitingStep
    ? `Permission required: ${awaitingStep.name || 'action'}`
    : failedStep
    ? `Stopped at step: ${failedStep.name || 'action'} (${failedStep.error ? failedStep.error.slice(0, 50) : 'Failed'})`
    : toolSteps.length > 0
    ? `Thought & executed ${toolSteps.length} step${toolSteps.length === 1 ? '' : 's'}`
    : `Thought process (${steps.length} steps)`;

  return (
    <div className={`execution-steps-accordion ${failedStep ? 'has-failure' : awaitingStep ? 'has-permission' : ''}`}>
      <button
        type="button"
        className="execution-steps-summary"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
      >
        <div className="summary-left">
          {awaitingStep ? (
            <AlertTriangle size={13} className="text-amber-400 summary-icon" />
          ) : failedStep ? (
            <AlertTriangle size={13} className="text-warning summary-icon" />
          ) : (
            <Brain size={13} className="summary-icon" />
          )}
          <span className="summary-title">{summaryTitle}</span>
          <div className="summary-pills">
            {uniqueTools.map((t) => (
              <span key={t} className="summary-tool-pill">{t}</span>
            ))}
            {totalDuration > 0 && (
              <span className="summary-duration-pill">
                <Clock size={10} />
                {(totalDuration / 1000).toFixed(1)}s
              </span>
            )}
          </div>
        </div>
        <div className={`summary-chevron ${isOpen ? 'open' : ''}`}>
          <ChevronDown size={14} />
        </div>
      </button>

      {isOpen && (
        <div className="execution-steps-body">
          <div className="execution-timeline">
            {steps.map((step) => (
              <ExecutionStepItem key={step.id} step={step} onPermissionResponse={onPermissionResponse} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function downloadMarkdown(content: string, id: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `makima-response-${id.slice(0, 8)}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export const ChatMessage = memo(function ChatMessage({
  message,
  copied,
  onCopy,
  onRetry,
  onCanvas,
  onFullscreen,
  onSelectSuggestion,
  onStop,
  onPermissionResponse,
}: Props) {
  const timestamp = useMemo(() => {
    return message.createdAt ? new Date(message.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  }, [message.createdAt]);
  const [reactions, setReactions] = useState<Record<string, number>>({});
  const [activeReactions, setActiveReactions] = useState<Record<string, boolean>>({});
  const [particles, setParticles] = useState<Array<{ id: number; emoji: string; driftX: number }>>([]);
  const [speaking, setSpeaking] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [bookmarked, setBookmarked] = useState(false);

  useEffect(() => {
    return () => {
      if (speaking && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, [speaking]);

  const toggleSpeech = () => {
    if (!('speechSynthesis' in window)) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    } else {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(message.content);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(utterance);
      setSpeaking(true);
    }
  };

  const handleReact = (emoji: string) => {
    playSoftPop();
    const isActive = activeReactions[emoji];
    setActiveReactions((prev) => ({ ...prev, [emoji]: !isActive }));
    setReactions((prev) => ({
      ...prev,
      [emoji]: (prev[emoji] || 0) + (isActive ? -1 : 1),
    }));

    if (!isActive) {
      const particleId = Date.now() + Math.random();
      const drift = (Math.random() - 0.5) * 36;
      setParticles((prev) => [...prev, { id: particleId, emoji, driftX: drift }]);
      window.setTimeout(() => {
        setParticles((prev) => prev.filter((p) => p.id !== particleId));
      }, 950);
    }
  };

  return <article className={`message ${message.role}`}>
    <div className="avatar">{message.role === 'assistant' ? <Sparkles size={15} /> : 'You'}</div>
    <div className="message-body">
      {message.attachments?.length ? <div className="message-attachments" aria-label="Attached files">{message.attachments.map((attachment) => <span className="message-attachment" key={attachment.id}><FileText size={13} /><span>{attachment.name}</span><small>{formatBytes(attachment.size)}</small></span>)}</div> : null}
      {message.role === 'assistant' && (
        <ExecutionStepsAccordion
          steps={message.steps}
          messagePending={message.pending}
          currentStage={message.currentStage}
          onStop={onStop}
          messageId={message.id}
          hasError={Boolean(message.error)}
          onPermissionResponse={onPermissionResponse}
          hasContent={Boolean(message.content)}
        />
      )}
      {message.role === 'assistant' && message.pending && !message.content && (!message.steps || message.steps.length === 0) ? null : showRaw ? (
        <pre className="raw-markdown-view">
          {message.content || ''}
          {message.role === 'assistant' && message.pending && Boolean(message.content) && (
            <span className="inline-block w-2 h-4 ml-1 bg-current align-middle animate-pulse" aria-hidden="true" />
          )}
        </pre>
      ) : (
        Boolean(message.content) && (
          <div className="message-content-render">
            <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>{message.content}</ReactMarkdown>
            {message.role === 'assistant' && message.pending && (
              <span className="inline-block w-2 h-4 ml-1 bg-current align-middle animate-pulse" aria-hidden="true" />
            )}
          </div>
        )
      )}
      {message.error && <div className="message-error" role="alert"><span>{message.error}</span><Button onClick={() => onRetry(message)}><RotateCcw size={13} /> Retry</Button></div>}
      {message.artifacts?.map((artifact) => <ArtifactCard artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} key={artifact.id} />)}
      {message.role === 'assistant' && !message.pending && Boolean(message.suggestions?.length) && (
        <div className="suggested-replies" aria-label="Suggested follow-ups">
          <div className="suggested-heading">
            <Sparkles size={12} />
            <span>Suggested replies</span>
          </div>
          <div className="suggested-chips">
            {message.suggestions?.map((suggestion, index) => (
              <button
                key={index}
                className="suggested-chip"
                onClick={() => onSelectSuggestion?.(suggestion)}
                type="button"
              >
                <span>{suggestion}</span>
                <ArrowUpRight size={13} />
              </button>
            ))}
          </div>
        </div>
      )}
      {!message.pending && (message.content || message.error) && (
        <div className="message-footer">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <small>{timestamp} · {message.role === 'assistant' ? 'Makima response' : 'Sent'}</small>
            {message.role === 'assistant' && (
              <div className="message-reactions" aria-label="Reactions">
                {REACTION_OPTIONS.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    className={`reaction-btn ${activeReactions[emoji] ? 'active' : ''}`}
                    onClick={() => handleReact(emoji)}
                    title={`React with ${emoji}`}
                    aria-label={`React with ${emoji}`}
                  >
                    <span>{emoji}</span>
                    {Boolean(reactions[emoji]) && <small>{reactions[emoji]}</small>}
                  </button>
                ))}
                {particles.map((p) => (
                  <span
                    key={p.id}
                    className="floating-particle"
                    style={{ '--drift-x': `${p.driftX}px` } as React.CSSProperties}
                  >
                    {p.emoji}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="message-actions">
            <Button onClick={() => onCopy(message.content, message.id)} disabled={!message.content} title="Copy message">
              {copied ? <Check size={13} /> : <Copy size={13} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </Button>
            {message.role === 'assistant' && (
              <>
                <Button onClick={toggleSpeech} title={speaking ? 'Stop reading aloud' : 'Read aloud'} className={speaking ? 'active' : ''}>
                  {speaking ? <VolumeX size={13} /> : <Volume2 size={13} />}
                  <span>{speaking ? 'Stop' : 'Listen'}</span>
                </Button>
                <Button onClick={() => setShowRaw(!showRaw)} title={showRaw ? 'Rendered view' : 'Raw markdown view'} className={showRaw ? 'active' : ''}>
                  {showRaw ? <FileText size={13} /> : <Code2 size={13} />}
                  <span>{showRaw ? 'Rendered' : 'Raw'}</span>
                </Button>
                <Button onClick={() => downloadMarkdown(message.content, message.id)} title="Download response as Markdown (.md)">
                  <Download size={13} />
                  <span>Export</span>
                </Button>
                <Button onClick={() => onSelectSuggestion?.('Can you explain and summarize this more simply?')} title="Explain simply">
                  <Sparkles size={13} />
                  <span>Simplify</span>
                </Button>
                <Button onClick={() => onSelectSuggestion?.('Can you provide more technical depth and code examples on this?')} title="Elaborate with deeper details">
                  <Wand2 size={13} />
                  <span>Deepen</span>
                </Button>
                <Button onClick={() => setBookmarked(!bookmarked)} title={bookmarked ? 'Bookmarked' : 'Bookmark this answer'} className={bookmarked ? 'active' : ''}>
                  <Bookmark size={13} fill={bookmarked ? 'currentColor' : 'none'} />
                  <span>{bookmarked ? 'Saved' : 'Save'}</span>
                </Button>
                <Button onClick={() => onRetry(message)} title="Retry this prompt">
                  <RotateCcw size={13} />
                  <span>Retry</span>
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  </article>;
});


