import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { detectArtifacts, normalizeArtifact, safeArtifactUrl } from './artifacts';

describe('artifact normalization', () => {
  it('normalizes typed backend artifacts with safe defaults', () => {
    const artifact = normalizeArtifact({ kind: 'code', content: 'print(1)', language: 'python' });
    assert.equal(artifact.kind, 'code');
    assert.equal(artifact.downloadable, true);
    assert.match(artifact.id, /^artifact_/);
  });

  it('detects code, Mermaid, and Markdown tables from plain text', () => {
    const plain = [
      '| name | value |', '| --- | --- |', '| latency | 12 |', '',
      '```python', 'print("ok")', '```', '', '```mermaid', 'graph TD; A-->B', '```',
    ].join('\n');
    const artifacts = detectArtifacts(plain);
    assert.deepEqual(artifacts.map((item) => item.kind), ['code', 'diagram', 'table']);
  });

  it('allows only local or secure artifact URLs', () => {
    assert.equal(safeArtifactUrl('https://cdn.example.test/image.png', 'image'), 'https://cdn.example.test/image.png');
    assert.equal(safeArtifactUrl('http://localhost:8000/file.png', 'image'), 'http://localhost:8000/file.png');
    assert.equal(safeArtifactUrl('http://evil.example.test/file.png', 'image'), undefined);
    assert.equal(safeArtifactUrl('javascript:alert(1)', 'html'), undefined);
    assert.equal(safeArtifactUrl('data:text/html,<script>alert(1)</script>', 'html'), undefined);
    assert.equal(safeArtifactUrl('data:image/png;base64,AAAA', 'image'), 'data:image/png;base64,AAAA');
  });

  it('bounds untrusted artifact content and rejects unknown kinds', () => {
    const artifact = normalizeArtifact({ kind: 'unknown', content: 'x'.repeat(1_000_100) });
    assert.equal(artifact.kind, 'markdown');
    assert.equal(artifact.content.length, 1_000_000);
  });

  it('formats artifactText from content and structured json data', async () => {
    const { artifactText } = await import('./components/ArtifactCard');
    const codeArtifact = normalizeArtifact({ kind: 'code', content: 'console.log("hello")', language: 'typescript' });
    assert.equal(artifactText(codeArtifact), 'console.log("hello")');

    const jsonArtifact = normalizeArtifact({ kind: 'json', data: { model: 'makima', version: 2 } });
    assert.ok(artifactText(jsonArtifact).includes('"model": "makima"'));
  });
});
