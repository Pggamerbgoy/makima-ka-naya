import type { Artifact } from './types';
import DOMPurify from 'dompurify';

let sequence = 0;
const id = () => `artifact_${Date.now()}_${sequence++}`;
const MAX_ARTIFACT_TEXT = 1_000_000;

export function safeArtifactUrl(value: string | undefined, kind: Artifact['kind']): string | undefined {
  if (!value || value.length > 2_000_000) return undefined;
  try {
    const base = typeof window === 'undefined' ? 'http://localhost/' : window.location.href;
    const parsed = new URL(value, base);
    const local = parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost';
    if (parsed.protocol === 'https:' || (parsed.protocol === 'http:' && local) || parsed.protocol === 'blob:') return parsed.href;
    if (parsed.protocol === 'data:' && ['image', 'audio', 'video'].includes(kind) && /^data:(image|audio|video)\//i.test(value)) return value;
  } catch { /* invalid URL is rendered as an error state */ }
  return undefined;
}

export function sanitizeArtifactHtml(value: string, kind: 'html' | 'svg'): string {
  if (typeof window === 'undefined') return value;
  return DOMPurify.sanitize(value, kind === 'svg'
    ? { USE_PROFILES: { svg: true, svgFilters: true } }
    : { USE_PROFILES: { html: true } });
}

function tableFromMarkdown(text: string): Artifact | undefined {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2 || !lines[0].includes('|') || !/^\s*\|?\s*:?-{3,}/.test(lines[1])) return undefined;
  const cells = (line: string) => line.replace(/^\||\|$/g, '').split('|').map((v) => v.trim());
  return { id: id(), kind: 'table', title: 'Table', data: { headers: cells(lines[0]), rows: lines.slice(2).map(cells) }, downloadable: true };
}

export function normalizeArtifact(value: unknown, fallbackTitle = 'Artifact'): Artifact {
  const raw = (value ?? {}) as Record<string, unknown>;
  const allowedKinds: Artifact['kind'][] = ['markdown', 'image', 'video', 'audio', 'chart', 'diagram', 'table', 'code', 'html', 'document', 'diff', 'log', 'json', 'pdf'];
  const candidateKind = String(raw.kind ?? 'markdown') as Artifact['kind'];
  const kind = allowedKinds.includes(candidateKind) ? candidateKind : 'markdown';
  const content = typeof raw.content === 'string' ? raw.content.slice(0, MAX_ARTIFACT_TEXT) : undefined;
  const url = safeArtifactUrl(typeof raw.url === 'string' ? raw.url : undefined, kind);
  const metadata = raw.metadata && typeof raw.metadata === 'object' ? raw.metadata as Record<string, unknown> : undefined;
  return {
    id: String(raw.id ?? id()).slice(0, 160), kind, title: String(raw.title ?? fallbackTitle).slice(0, 240),
    mime_type: raw.mime_type as string | undefined, content,
    url, language: typeof raw.language === 'string' ? raw.language.slice(0, 80) : undefined,
    data: raw.data, downloadable: raw.downloadable !== false, metadata,
  };
}

export function detectArtifacts(text: string): Artifact[] {
  const artifacts: Artifact[] = [];
  const fence = /```([\w+-]*)\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  while ((match = fence.exec(text))) {
    const lang = match[1].toLowerCase(); const content = match[2].trim();
    const kind: Artifact['kind'] = lang === 'mermaid' || lang === 'diagram' ? 'diagram' : lang === 'html' ? 'html' : lang === 'json' || lang === 'xml' ? 'json' : lang === 'csv' ? 'table' : lang === 'chart' ? 'chart' : lang === 'diff' ? 'diff' : lang === 'log' || lang === 'shell' ? 'log' : 'code';
    let data: unknown;
    if (kind === 'chart' || kind === 'json') { try { data = JSON.parse(content); } catch { data = undefined; } }
    artifacts.push({ id: id(), kind, title: `${lang || 'code'} artifact`, content, language: lang || 'text', data, downloadable: true });
  }
  const table = tableFromMarkdown(text);
  if (table) artifacts.push(table);

  // Automatically detect workspace document references (e.g. reports/sample.pdf, documents/summary.docx)
  const fileRegex = /(?:[\s(]|^|['"`])([a-zA-Z0-9_\-\\/]+\.(pdf|docx|xlsx|pptx|html))(?=[\s),.'"`]|$)/gi;
  let fileMatch: RegExpExecArray | null;
  const seenPaths = new Set<string>();
  while ((fileMatch = fileRegex.exec(text))) {
    const rawPath = fileMatch[1].replace(/\\/g, '/').replace(/^\.?\//, '');
    if (seenPaths.has(rawPath.toLowerCase())) continue;
    seenPaths.add(rawPath.toLowerCase());
    const ext = fileMatch[2].toLowerCase();
    const fileName = rawPath.split('/').pop() || rawPath;
    const kind: Artifact['kind'] = ext === 'pdf' ? 'pdf' : 'document';
    artifacts.push({
      id: id(),
      kind,
      title: fileName,
      url: `/api/workspace/files/${rawPath}`,
      metadata: { file_path: rawPath, file_name: fileName, extension: `.${ext}` },
      downloadable: true,
    });
  }

  return artifacts;
}

export function artifactFileName(artifact: Artifact): string {
  const safe = (artifact.title ?? artifact.kind).replace(/[^\w.-]+/g, '-').toLowerCase();
  const ext = artifact.kind === 'code' ? (artifact.language || 'txt') : artifact.kind === 'table' ? 'csv' : artifact.kind === 'html' ? 'html' : artifact.kind === 'diagram' ? 'mmd' : 'txt';
  return `${safe || 'artifact'}.${ext}`;
}

export function downloadArtifact(artifact: Artifact, content = artifact.content ?? JSON.stringify(artifact.data ?? '', null, 2)): void {
  const blob = new Blob([content], { type: artifact.mime_type ?? 'text/plain;charset=utf-8' });
  const href = URL.createObjectURL(blob); const anchor = document.createElement('a');
  anchor.href = href; anchor.download = artifactFileName(artifact); anchor.click(); URL.revokeObjectURL(href);
}
