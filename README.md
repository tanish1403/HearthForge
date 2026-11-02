# Hearthforge

A **local-first, modular AI workstation for software development**. Point it at a project folder, pick a model
(a local one works with no account), and let a coding agent inspect, plan, edit, test and report, with every
risky step visible and under your control.

> **Status: early alpha (v0.1.0).** The core is real and tested; several capabilities are honestly marked
> *planned*. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) before relying on anything.

## What it does

- **Coding agent loop**: understand, inspect, search, read, plan, edit, run tests, read failures, fix (bounded), report.
  Success is computed from recorded evidence (applied changes and exit codes of checks run *after* the last edit),
  never from the model saying "done".
- **Review gates**: file changes appear as diffs you approve or reject (with feedback the agent sees). Every change is
  snapshotted and can be undone.
- **Layered permissions per workspace**: read / write / exec / network / install / destructive, each `allow | ask | deny`,
  enforced in the backend.
- **Any model, connected in one step**: a *Connect a model* wizard takes a URL and key, auto-detects the right endpoint
  (fixes a missing `/v1`), lists models (or lets you type one), applies the privacy settings it needs, and sends a test
  message. Works with Ollama, llama.cpp, LM Studio, gateways such as OmniRoute, OpenRouter, Groq, Gemini's OpenAI-compatible
  API, Hugging Face's router, or any OpenAI-compatible endpoint.
- **Chat and Agent**: a streaming chat (optional web search with cited sources, optional answers from your indexed project)
  plus the full agent workflow below.
- **Internet access** (off by default): web search (DuckDuckGo, Wikipedia or your SearXNG) and page reading, with SSRF
  protection and an approval mode. See the Internet panel.
- **Folder browser**: attach a project by clicking through folders; no typing paths.
- **In-app Guide** and `Ctrl+K` command palette.
- **Privacy modes**: `Local only` (default), `Free tier only` (zero spend) and `Budgeted cloud`. Enforced at a single
  egress point for chat, embeddings and discovery.
- **Knowledge**: incremental local keyword/BM25 index with citations, plus scoped project memory you can inspect, edit,
  export and delete. Reads text, Markdown, CSV, PDF (text layer), DOCX, XLSX, PPTX.
- **Extensible**: switch capabilities on or off in the UI; add external-command plugins by pasting a JSON manifest.
- **Hardware-aware**: detects RAM/VRAM/disk and estimates which local model sizes fit (with stated uncertainty).

## Quick start

Requirements: Python 3.10+. Git is recommended. For local inference install [Ollama](https://ollama.com) or run a
llama.cpp server yourself (Hearthforge never downloads models or installs software for you).

```bash
git clone <this repository>
cd hearthforge
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
hearthforge serve
```

Open the URL printed in the terminal (it contains a one-time token). Then:

1. **Models and privacy**: *Test connection* on Ollama/llama.cpp, *List models*, *Use* one.
2. **Workspace and permissions**: add your project folder.
3. Start a task in **Plan** mode first; switch to **Build** when you like the plan.

Helper scripts: `scripts/setup.sh`, `scripts/setup.ps1`, `scripts/run.sh`, `scripts/run.ps1`.

## Models and honesty about capability

The agent speaks a simple JSON action protocol, so it works with models that lack native tool calling. Small local
models (≈3B) often fail to follow it reliably; 7B+ coder-tuned models do much better. If a model cannot produce valid
actions the task stops with a clear message instead of pretending.

## Documentation

[**Guide: connect each model, use each feature**](docs/GUIDE.md) · [Architecture](docs/ARCHITECTURE.md) · [Providers](docs/PROVIDERS.md) · [Privacy & security](docs/PRIVACY_AND_SECURITY.md) ·
[Hardware](docs/HARDWARE.md) · [Testing](docs/TESTING.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) ·
[Releasing](docs/RELEASING.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)

## Limits you should know

- Commands run with **your user rights**; there is no OS sandbox or container. Permissions and allowlists reduce
  risk, they do not eliminate it. Only work on projects you trust, and keep `exec` on `ask` for unfamiliar code.
- Scanned PDFs and images need OCR or a vision model; OCR is not bundled.
- Research agent, scheduling, MCP, vector search and reranking are **not implemented**. Web search is implemented but its live endpoints (DuckDuckGo page format etc.) were **not verified against the real internet**; it can break if a provider changes.
- Tested on Linux only so far. Windows/macOS are supported by design but **unverified**, see status file.
- No native installer yet (planned: Tauri shell around this backend).

## License

Apache-2.0. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
