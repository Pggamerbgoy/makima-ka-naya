import { memo, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowUpRight, Bookmark, Check, Code2, Copy, Download, FileText, RotateCcw, Sparkles, Square, Volume2, VolumeX, Wand2 } from 'lucide-react';
import { ArtifactCard } from './ArtifactCard';
import { Button } from './ui';
import { playSoftPop } from '../utils/soundEffects';
import type { Artifact } from '../types';

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
};

const REACTION_OPTIONS = ['👍', '❤️', '💡', '🚀'];
const REMARK_PLUGINS = [remarkGfm];

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
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

export const ChatMessage = memo(function ChatMessage({ message, copied, onCopy, onRetry, onCanvas, onFullscreen, onSelectSuggestion, onStop }: Props) {
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
      {message.role === 'assistant' && message.pending ? (
        <div className="thinking-stage" aria-label="Makima is working">
          <div className="thinking-header">
            <div className="aurora-pulse">
              <Sparkles size={13} className="aurora-sparkle" />
              <span>Makima is reasoning & synthesizing...</span>
            </div>
            {onStop && (
              <button
                type="button"
                className="stop-response-bubble-btn"
                onClick={() => onStop(message.id)}
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
      ) : showRaw ? (
        <pre className="raw-markdown-view">{message.content || ''}</pre>
      ) : (
        <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>{message.content || ''}</ReactMarkdown>
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


