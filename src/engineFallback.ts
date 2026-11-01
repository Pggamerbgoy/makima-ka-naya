import type { Artifact, ExecutionStep } from './types';
import { normalizeArtifact } from './artifacts';

export interface SimulatedTurnResult {
  content: string;
  steps: ExecutionStep[];
  artifacts: Artifact[];
  suggestions: string[];
}

export async function runSimulatedAgentTurn(
  prompt: string,
  onStep: (step: ExecutionStep) => void,
  onStage: (stage: string) => void,
  onChunk: (chunk: string) => void
): Promise<SimulatedTurnResult> {
  const lower = prompt.toLowerCase();
  const steps: ExecutionStep[] = [];

  const addStep = (name: string, stage: string, args?: Record<string, unknown>): ExecutionStep => {
    const step: ExecutionStep = {
      id: `step_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`,
      type: 'tool',
      name,
      stage,
      status: 'running',
      arguments: args,
      timestamp: Date.now(),
    };
    steps.push(step);
    onStep({ ...step });
    onStage(stage);
    return step;
  };

  const completeStep = (step: ExecutionStep, result?: unknown) => {
    step.status = 'completed';
    step.result = result;
    step.durationMs = Math.max(40, Math.floor(Date.now() - (step.timestamp || Date.now())));
    step.duration_ms = step.durationMs;
    onStep({ ...step });
  };

  // Step 1: Dynamic Pareto Router
  const pStep = addStep('Pareto Router', 'Evaluating prompt across frontier cascades for optimal latency and cost');
  await new Promise((r) => setTimeout(r, 240));
  completeStep(pStep, {
    selected_model: lower.includes('reason') || lower.includes('why') ? 'deepseek-r1' : 'gemini-2.5-flash',
    task_tier: lower.includes('code') ? 'code_synthesis' : 'fast_chat',
    ewma_latency_ms: 18,
    cache_hit: true,
    token_savings_pct: 82.4,
  });

  // Step 2: Dual-Tier Memory & Knowledge Graph Scan
  const mStep = addStep('Memory Agent', 'Scanning vector store and persistent USER.md profile');
  await new Promise((r) => setTimeout(r, 260));
  completeStep(mStep, {
    vector_matches: 2,
    top_relevance_score: 0.942,
    state_injection: 'Applied preferences: conciseness, BLUF response, high-contrast UI',
  });

  const artifacts: Artifact[] = [];
  let content = '';
  let suggestions: string[] = [];

  if (lower.includes('diagram') || lower.includes('architecture') || lower.includes('flow') || lower.includes('sequence')) {
    const dStep = addStep('Architecture Agent', 'Synthesizing distributed event topology in Mermaid specification');
    await new Promise((r) => setTimeout(r, 380));
    completeStep(dStep, { nodes: 7, protocol: 'Raft consensus + WebSocket gateway' });

    content = `I have architected the **Distributed Autonomous Agent Swarm & Gateway Topology**.\n\n### System Protocol Highlights\n- **Client Gateway:** WebSocket TLS termination with bidirectional streaming.\n- **Pareto Frontier:** Sub-20ms task classification and model routing cascade.\n- **Dual-Tier Memory:** SQLite WAL episodic persistence coupled with on-device vector embeddings.\n- **SAGA Filesystem:** Atomic snapshots taken prior to every mutating disk operation.`;

    const diagramArt: Artifact = normalizeArtifact({
      id: `art_diag_${Date.now()}`,
      kind: 'diagram',
      title: 'Makima v2 Distributed Swarm Architecture',
      content: `flowchart TD
  Client[Web & Desktop Clients] -->|WebSocket /ws| GW[Makima Gateway]
  GW --> PR{Pareto Router}
  PR -->|Code Tasks| CA[Code Agent]
  PR -->|Research| RA[Research Agent]
  PR -->|System & UIA| OA[OS / Desktop Sentinel]
  CA --> Canvas[Canvas Studio]
  RA --> VectorDB[(Vector & Episodic Store)]
  OA --> SAGA[SAGA Safe IO]`,
    });
    artifacts.push(diagramArt);

    suggestions = [
      'Render sequence diagram for Raft leader election',
      'Export architecture diagram as SVG',
      'Open in Canvas Studio to edit',
    ];
  } else if (lower.includes('calc') || lower.includes('math') || lower.includes('stat') || lower.includes('metric') || lower.includes('speed')) {
    const cStep = addStep('Data Analyst Agent', 'Executing calculation and generating comparative telemetry chart');
    await new Promise((r) => setTimeout(r, 340));
    completeStep(cStep, { formula: 'P95 latency benchmark across 5 frontier models', status: 'verified' });

    content = `### Performance & Latency Analytics\n- **Inference Profile:** Pareto evaluated under low-cost floating-point tier.\n- **TTFT (Time To First Token):** **18ms** via prefix KV-cache.\n- **Total RTT:** **183ms** round-trip latency.`;

    const chartArt: Artifact = normalizeArtifact({
      id: `art_chart_${Date.now()}`,
      kind: 'chart',
      title: 'Frontier AI Inference Latency (ms)',
      data: {
        type: 'bar',
        labels: ['Pareto Router', 'Gemini Flash', 'Llama 3.3', 'GPT-4o', 'Claude 3.5'],
        values: [18, 42, 28, 110, 125],
      },
    });
    artifacts.push(chartArt);

    suggestions = [
      'Export latency benchmarks as CSV',
      'Simulate 10,000 Monte Carlo requests',
      'Open in Canvas Studio',
    ];
  } else if (lower.includes('git') || lower.includes('diff') || lower.includes('repo') || lower.includes('commit') || lower.includes('status')) {
    const gStep = addStep('Git Engine Agent', 'Scanning local git status and recent commit tree');
    await new Promise((r) => setTimeout(r, 320));
    completeStep(gStep, { branch: 'main', dirty_files: 0, head_commit: '5c0e88c feat: enhance overlay and automation capabilities' });

    content = `### Git Repository Status\n- **Current Branch:** \`main\`\n- **Latest Commit:** \`5c0e88c\` — *feat: enhance overlay and automation capabilities*\n- **Working Tree:** Clean (all upstream syncs integrated)\n- **Verification:** Unit tests and build pass cleanly with zero regressions.`;

    const tableArt: Artifact = normalizeArtifact({
      id: `art_table_${Date.now()}`,
      kind: 'table',
      title: 'Recent Git History & Audits',
      data: {
        headers: ['Commit', 'Author', 'Message', 'Status'],
        rows: [
          ['5c0e88c', 'Pggamerbgoy', 'feat: enhance overlay and automation capabilities', 'Synced'],
          ['2e81ba4', 'Makima Swarm', 'audit: prompt caching & token budget history', 'Verified'],
          ['9f17042', 'Makima Core', 'feat: Gemini 3.8 Live browser voice bridge', 'Passing'],
        ],
      },
    });
    artifacts.push(tableArt);

    suggestions = [
      'Inspect full git diff for commit 5c0e88c',
      'Run complete test suite verification',
      'Show active git branch graph',
    ];
  } else if (lower.includes('city') || lower.includes('simulator') || lower.includes('cyberpunk') || lower.includes('matrix')) {
    const sStep = addStep('Creative Code Agent', 'Compiling interactive HTML5 Canvas metropolis sandbox');
    await new Promise((r) => setTimeout(r, 400));
    completeStep(sStep, { fps: 60, particles: 40, canvas: '2D hardware-accelerated' });

    content = `I have generated the **Cyberpunk Neon Matrix Simulator**.\n\n### Simulation Specs\n- **Render Target:** 60 FPS requestAnimationFrame canvas\n- **Data Streams:** Dynamic oscillating neon particle beams\n- **Interactive Controls:** Open in Canvas Studio to edit simulation variables live.`;

    const htmlArt: Artifact = normalizeArtifact({
      id: `art_city_${Date.now()}`,
      kind: 'html',
      title: 'Cyberpunk Neon Metropolis Simulation',
      content: `<!DOCTYPE html>
<html>
<head>
  <style>
    body { margin: 0; background: #0c0a14; color: #a5b4fc; font-family: monospace; overflow: hidden; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; }
    canvas { border: 1px solid #818cf8; box-shadow: 0 0 30px rgba(129, 140, 248, 0.35); border-radius: 8px; }
    .hud { position: absolute; top: 14px; left: 18px; font-size: 11px; line-height: 1.6; }
    .badge { color: #34d399; font-weight: bold; }
  </style>
</head>
<body>
  <div class="hud">
    <div>MAKIMA CANVA // <span class="badge">ACTIVE</span></div>
    <div>BUFFER: 60 FPS</div>
    <div>PARETO ROUTE: 18ms</div>
  </div>
  <canvas id="c" width="500" height="280"></canvas>
  <script>
    const c = document.getElementById('c');
    const ctx = c.getContext('2d');
    let t = 0;
    function draw() {
      ctx.fillStyle = 'rgba(12, 10, 20, 0.22)';
      ctx.fillRect(0, 0, c.width, c.height);
      t += 0.04;
      for (let i = 0; i < 40; i++) {
        const x = (Math.sin(t + i * 0.4) * 0.45 + 0.5) * c.width;
        const y = ((i * 14 + t * 50) % c.height);
        ctx.fillStyle = i % 2 === 0 ? '#818cf8' : '#34d399';
        ctx.fillRect(x, y, 4, 16);
      }
      requestAnimationFrame(draw);
    }
    draw();
  </script>
</body>
</html>`,
    });
    artifacts.push(htmlArt);

    suggestions = [
      'Add gravity well around cursor',
      'Modify neon colors to amber/emerald',
      'Open in Canvas Studio to edit',
    ];
  } else {
    // Default high-grade technical code response
    const codeStep = addStep('Code Agent', 'Synthesizing defensive, typed implementation with test suite');
    await new Promise((r) => setTimeout(r, 420));
    completeStep(codeStep, { runtime: 'TypeScript 5.6', safety: '100% typed' });

    content = `I have architected the solution for **"${prompt}"** with production resilience and safety invariants.\n\n### Architectural Highlights\n- **Asynchronous Execution:** Non-blocking event queues with task lifecycle events.\n- **Defensive Typing:** Strict generic boundaries preventing runtime exceptions.\n- **SAGA Rollback Guarantee:** All state modifications are snapshot-protected.`;

    const codeArt: Artifact = normalizeArtifact({
      id: `art_code_${Date.now()}`,
      kind: 'code',
      title: 'High-Performance Worker Pool',
      language: 'typescript',
      content: `import { EventEmitter } from 'events';

export interface Task<TInput, TOutput> {
  id: string;
  data: TInput;
  execute: (input: TInput) => Promise<TOutput>;
}

export class WorkerPool<TInput, TOutput> extends EventEmitter {
  private concurrency: number;
  private running = 0;
  private queue: Task<TInput, TOutput>[] = [];

  constructor(concurrency = 4) {
    super();
    this.concurrency = concurrency;
  }

  public submit(task: Task<TInput, TOutput>): Promise<TOutput> {
    return new Promise((resolve, reject) => {
      const wrappedTask: Task<TInput, TOutput> = {
        ...task,
        execute: async (input) => {
          try {
            const result = await task.execute(input);
            resolve(result);
            return result;
          } catch (err) {
            reject(err);
            throw err;
          }
        },
      };

      this.queue.push(wrappedTask);
      this.dispatch();
    });
  }

  private async dispatch() {
    if (this.running >= this.concurrency || this.queue.length === 0) return;

    const task = this.queue.shift();
    if (!task) return;

    this.running++;
    this.emit('task:start', task.id);

    try {
      await task.execute(task.data);
      this.emit('task:success', task.id);
    } catch (error) {
      this.emit('task:error', { id: task.id, error });
    } finally {
      this.running--;
      this.dispatch();
    }
  }
}

// Example usage:
const pool = new WorkerPool<number, number>(2);
pool.submit({
  id: 'calc-1',
  data: 42,
  execute: async (n) => n * 2,
}).then(res => console.log('Task completed with result:', res));
`,
    });
    artifacts.push(codeArt);

    suggestions = [
      'Open this code in Canvas Studio',
      'Add exponential backoff retry mechanism',
      'Generate Vitest unit tests',
    ];
  }

  // Stream text output progressively
  for (const part of content.split(' ')) {
    onChunk(part + ' ');
    await new Promise((r) => setTimeout(r, 12));
  }

  return { content, steps, artifacts, suggestions };
}
