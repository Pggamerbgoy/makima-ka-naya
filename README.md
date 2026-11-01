# Makima v2 - Autonomous Desktop & Swarm OS

A modern, high-performance React application rewriting and porting Makima v2 into a unified web workspace.

## Key Features

- **12 Autonomous AI Agents**: Specialized agents for Code, Research, Terminal, Documents, Memory, Data Analysis, and Desktop Automation.
- **Dynamic Pareto Router**: Automatically routes prompts across frontier AI models (Claude 3.5 Sonnet, GPT-4o, Gemini 1.5 Pro, Llama 3.3, DeepSeek R1) optimizing for latency, reasoning depth, and cost.
- **Live Canvas Studio**: Dedicated side drawer and workspace for inspecting, editing, split-viewing, and refining interactive artifacts (code, diagrams, tables, charts, and simulations) with one-click AI refactoring.
- **Interactive Multi-Modal Artifacts**:
  - Code syntax highlighting with line gutters and copy/download
  - Mermaid and SVG architecture flowcharts & sequence diagrams
  - Sortable tables with CSV export
  - Real-time SVG telemetry charts
  - Sandboxed HTML canvas simulations
- **System Telemetry & Health**: Real-time CPU, RAM, KV-cache hit rate metrics, 12-agent status cards, and live gateway event logs.
- **Ecosystem & Integrations**: Model Context Protocol (MCP) and OpenAPI plugin manager with instant discovery.
- **Voice & Gemini Live**: Web Speech and Gemini Live voice synthesis and wake word activation.

## Tech Stack

- **Framework**: React 18 with TypeScript and Vite
- **Styling**: Tailwind CSS with custom Dark/Light Black Ledger theme
- **Icons & Visuals**: Lucide React, Canvas Confetti
- **Audio**: Web Audio API synth effects & Web Speech API

## Development

```bash
npm install
npm run dev
```

Build for production:

```bash
npm run build
```
