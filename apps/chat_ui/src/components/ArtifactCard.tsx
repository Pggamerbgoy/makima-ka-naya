import { memo, useEffect, useMemo, useState } from 'react';
import { Activity, AudioLines, Check, Code2, Copy, Download, FileJson, FileText, Image as ImageIcon, LayoutDashboard, Maximize2, PanelRight, RefreshCw, Table2, Video } from 'lucide-react';
import type { Artifact } from '../types';
import { artifactFileName, downloadArtifact, safeArtifactUrl, sanitizeArtifactHtml } from '../artifacts';
import { Button, EmptyState } from './ui';

export function artifactText(artifact: Artifact): string {
  return artifact.content ?? (typeof artifact.data === 'string' ? artifact.data : JSON.stringify(artifact.data ?? '', null, 2));
}

const ArtifactActions = memo(function ArtifactActions({ artifact, onCanvas, onFullscreen }: { artifact: Artifact; onCanvas: (artifact: Artifact) => void; onFullscreen?: (artifact: Artifact) => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => { await navigator.clipboard?.writeText(artifactText(artifact)); setCopied(true); window.setTimeout(() => setCopied(false), 1000); };
  return <div className="artifact-actions">
    {onFullscreen && <Button title="Fullscreen preview" aria-label="Fullscreen preview" onClick={() => onFullscreen(artifact)}><Maximize2 size={14} /></Button>}
    <Button title="Open in Canvas" aria-label="Open in Canvas" onClick={() => onCanvas(artifact)}><PanelRight size={14} /></Button>
    <Button title={copied ? 'Copied' : 'Copy'} aria-label={copied ? 'Copied' : 'Copy'} onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />}</Button>
    {artifact.downloadable !== false && <Button title={`Download ${artifactFileName(artifact)}`} aria-label="Download artifact" onClick={() => downloadArtifact(artifact)}><Download size={14} /></Button>}
  </div>;
});

const CodeCard = memo(function CodeCard({ artifact, onCanvas, onFullscreen }: { artifact: Artifact; onCanvas: (artifact: Artifact) => void; onFullscreen?: (artifact: Artifact) => void }) {
  const code = artifact.content ?? '';
  return <section className="artifact-card code-card"><header><span><Code2 size={15} /> {artifact.title ?? 'Code'}</span><small>{artifact.language || 'text'}</small><ArtifactActions artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} /></header><div className="code-scroll"><pre><code>{code.split('\n').map((line, index) => <span className="code-line" key={`${index}-${line}`}><i>{index + 1}</i>{line || ' '}</span>)}</code></pre></div></section>;
});

const TableCard = memo(function TableCard({ artifact, onCanvas, onFullscreen }: { artifact: Artifact; onCanvas: (artifact: Artifact) => void; onFullscreen?: (artifact: Artifact) => void }) {
  const parsed = useMemo(() => {
    const data = artifact.data as { headers?: string[]; rows?: string[][] } | undefined;
    if (data?.headers?.length) return { headers: data.headers, rows: data.rows ?? [] };
    const lines = (artifact.content ?? '').trim().split(/\r?\n/).filter(Boolean).map((line) => line.split(',').map((value) => value.trim()));
    return { headers: lines[0] ?? [], rows: lines.slice(1) };
  }, [artifact.data, artifact.content]);
  const [sort, setSort] = useState<{ index: number; direction: 'asc' | 'desc' } | null>(null);
  const rows = useMemo(() => {
    if (!sort) return parsed.rows;
    return [...parsed.rows].sort((a, b) => {
      const result = (a[sort.index] ?? '').localeCompare(b[sort.index] ?? '', undefined, { numeric: true });
      return sort.direction === 'asc' ? result : -result;
    });
  }, [parsed.rows, sort]);
  const csv = useMemo(() => {
    return [parsed.headers, ...rows].map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\n');
  }, [parsed.headers, rows]);
  const tableArtifact = useMemo(() => ({ ...artifact, content: csv }), [artifact, csv]);
  return <section className="artifact-card"><header><span><Table2 size={15} /> {artifact.title ?? 'Table'}</span><ArtifactActions artifact={tableArtifact} onCanvas={onCanvas} onFullscreen={onFullscreen} /></header>{parsed.headers.length ? <div className="table-scroll"><table><thead><tr>{parsed.headers.map((header, index) => <th key={`${header}-${index}`}><button onClick={() => setSort((current) => current?.index === index && current.direction === 'asc' ? { index, direction: 'desc' } : { index, direction: 'asc' })}>{header} {sort?.index === index ? (sort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{parsed.headers.map((_, columnIndex) => <td key={columnIndex}>{row[columnIndex] ?? '—'}</td>)}</tr>)}</tbody></table></div> : <EmptyState text="No table data" />}</section>;
});

const ChartCard = memo(function ChartCard({ artifact, onCanvas, onFullscreen }: { artifact: Artifact; onCanvas: (artifact: Artifact) => void; onFullscreen?: (artifact: Artifact) => void }) {
  const raw = artifact.data as { labels?: string[]; values?: number[]; type?: string } | Array<{ label: string; value: number }> | undefined;
  const { points, max } = useMemo(() => {
    const pts = Array.isArray(raw) ? raw : (raw?.labels ?? []).map((label, index) => ({ label, value: Number(raw?.values?.[index] ?? 0) }));
    const m = Math.max(...pts.map((point) => point.value), 1);
    return { points: pts, max: m };
  }, [raw]);
  const width = 520; const height = 190;
  return <section className="artifact-card"><header><span><Activity size={15} /> {artifact.title ?? 'Chart'}</span><small>{Array.isArray(raw) ? 'line' : raw?.type ?? 'line'}</small><ArtifactActions artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} /></header>{points.length ? <div className="chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={artifact.title ?? 'Chart'}>{points.map((point, index) => { const x = 45 + index * (450 / Math.max(points.length - 1, 1)); const y = 150 - (point.value / max) * 115; const previous = index > 0 ? points[index - 1] : null; return <g key={`${point.label}-${index}`}><circle cx={x} cy={y} r="4" fill="var(--accent)" className="chart-dot-animated" style={{ animationDelay: `${index * 80}ms` }} /><text x={x} y="174" textAnchor="middle">{point.label.slice(0, 10)}</text>{previous && <line x1={45 + (index - 1) * (450 / Math.max(points.length - 1, 1))} y1={150 - (previous.value / max) * 115} x2={x} y2={y} stroke="var(--accent)" strokeWidth="2" className="chart-line-animated" style={{ animationDelay: `${(index - 1) * 80}ms` }} />}</g>; })}</svg></div> : <EmptyState text="No chart data" />}</section>;
});

const MermaidCard = memo(function MermaidCard({ artifact, onCanvas, onFullscreen }: { artifact: Artifact; onCanvas: (artifact: Artifact) => void; onFullscreen?: (artifact: Artifact) => void }) {
  const [svg, setSvg] = useState(''); const [error, setError] = useState(''); const [source, setSource] = useState(false); const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError('');
    setSvg('');
    import('mermaid').then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'dark' });
      try {
        const result = await mermaid.render(`makima_${artifact.id.replace(/\W/g, '')}_${attempt}`, artifact.content ?? '');
        if (active) setSvg(result.svg);
      } catch (exception) {
        if (active) setError(String(exception));
      }
    });
    return () => { active = false; };
  }, [artifact.id, artifact.content, attempt]);
  return <section className="artifact-card"><header><span><LayoutDashboard size={15} /> {artifact.title ?? 'Diagram'}</span><div className="artifact-actions"><Button onClick={() => setSource((value) => !value)}>{source ? 'Preview' : 'Source'}</Button><ArtifactActions artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} /></div></header>{source ? <pre className="source-box">{artifact.content}</pre> : error ? <div className="artifact-error"><strong>Diagram syntax error</strong><small>{error}</small><Button onClick={() => setAttempt((value) => value + 1)}><RefreshCw size={13} /> Retry</Button></div> : <div className="diagram" dangerouslySetInnerHTML={{ __html: sanitizeArtifactHtml(svg, 'svg') }} />}</section>;
});

const MediaCard = memo(function MediaCard({ artifact, onCanvas, onFullscreen }: { artifact: Artifact; onCanvas: (artifact: Artifact) => void; onFullscreen?: (artifact: Artifact) => void }) {
  const [failed, setFailed] = useState(false);
  const src = useMemo(() => safeArtifactUrl(artifact.url ?? artifact.content, artifact.kind), [artifact.url, artifact.content, artifact.kind]);
  const unavailable = !src || failed;
  return <section className="artifact-card media-card"><header><span>{artifact.kind === 'image' ? <ImageIcon size={15} /> : artifact.kind === 'video' ? <Video size={15} /> : <AudioLines size={15} />} {artifact.title ?? artifact.kind}</span><ArtifactActions artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} /></header><div className={`media-stage ${unavailable ? 'failed' : ''}`}>{unavailable ? <EmptyState text={failed ? 'Media failed to load' : 'Media URL is blocked for safety'} action={failed ? <Button onClick={() => setFailed(false)}><RefreshCw size={13} /> Retry</Button> : undefined} /> : artifact.kind === 'image' ? <img src={src} alt={String(artifact.metadata?.alt ?? artifact.title ?? 'Makima image')} onError={() => setFailed(true)} /> : artifact.kind === 'video' ? <video src={src} controls onError={() => setFailed(true)} /> : <audio src={src} controls onError={() => setFailed(true)} />}</div></section>;
});

export const ArtifactCard = memo(function ArtifactCard({ artifact, onCanvas, onFullscreen }: { artifact: Artifact; onCanvas: (artifact: Artifact) => void; onFullscreen?: (artifact: Artifact) => void }) {
  if (artifact.kind === 'code' || artifact.kind === 'diff' || artifact.kind === 'log') return <CodeCard artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} />;
  if (artifact.kind === 'table') return <TableCard artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} />;
  if (artifact.kind === 'chart') return <ChartCard artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} />;
  if (artifact.kind === 'diagram') return <MermaidCard artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} />;
  if (artifact.kind === 'image' || artifact.kind === 'video' || artifact.kind === 'audio') return <MediaCard artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} />;
  if (artifact.kind === 'html') return <section className="artifact-card"><header><span><FileText size={15} /> {artifact.title ?? 'HTML preview'}</span><ArtifactActions artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} /></header><iframe title={artifact.title ?? 'HTML preview'} sandbox="" srcDoc={sanitizeArtifactHtml(artifact.content ?? '', 'html')} /></section>;
  return <section className="artifact-card"><header><span><FileJson size={15} /> {artifact.title ?? artifact.kind}</span><ArtifactActions artifact={artifact} onCanvas={onCanvas} onFullscreen={onFullscreen} /></header><pre className="source-box">{artifactText(artifact)}</pre></section>;
});
