import { describe, expect, it } from 'vitest';
import { detectArtifacts, normalizeArtifact, safeArtifactUrl } from './artifacts';

describe('artifact normalization', () => {
  it('normalizes typed backend artifacts with safe defaults', () => {
    const artifact = normalizeArtifact({ kind: 'code', content: 'print(1)', language: 'python' });
    expect(artifact.kind).toBe('code');
    expect(artifact.downloadable).toBe(true);
    expect(artifact.id).toMatch(/^artifact_/);
  });

  it('detects code, Mermaid, and Markdown tables from plain text', () => {
    const plain = [
      '| name | value |', '| --- | --- |', '| latency | 12 |', '',
      '```python', 'print("ok")', '```', '', '```mermaid', 'graph TD; A-->B', '```',
    ].join('\n');
    const artifacts = detectArtifacts(plain);
    expect(artifacts.map((item) => item.kind)).toEqual(['code', 'diagram', 'table']);
  });

  it('allows only local or secure artifact URLs', () => {
    expect(safeArtifactUrl('https://cdn.example.test/image.png', 'image')).toBe('https://cdn.example.test/image.png');
    expect(safeArtifactUrl('http://localhost:8000/file.png', 'image')).toBe('http://localhost:8000/file.png');
    expect(safeArtifactUrl('http://evil.example.test/file.png', 'image')).toBeUndefined();
    expect(safeArtifactUrl('javascript:alert(1)', 'html')).toBeUndefined();
    expect(safeArtifactUrl('data:text/html,<script>alert(1)</script>', 'html')).toBeUndefined();
    expect(safeArtifactUrl('data:image/png;base64,AAAA', 'image')).toBe('data:image/png;base64,AAAA');
  });

  it('bounds untrusted artifact content and rejects unknown kinds', () => {
    const artifact = normalizeArtifact({ kind: 'unknown', content: 'x'.repeat(1_000_100) });
    expect(artifact.kind).toBe('markdown');
    expect(artifact.content).toHaveLength(1_000_000);
  });

  it('formats artifactText from content and structured json data', async () => {
    const { artifactText } = await import('./components/ArtifactCard');
    const codeArtifact = normalizeArtifact({ kind: 'code', content: 'console.log("hello")', language: 'typescript' });
    expect(artifactText(codeArtifact)).toBe('console.log("hello")');

    const jsonArtifact = normalizeArtifact({ kind: 'json', data: { model: 'makima', version: 2 } });
    expect(artifactText(jsonArtifact)).toContain('"model": "makima"');
  });
});
