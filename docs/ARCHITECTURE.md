# Architecture

```
 Browser UI (vanilla JS, no build step)  ──HTTP/SSE──▶  FastAPI server (127.0.0.1, token + Host/Origin checks)
                                                          │
          ┌───────────────┬──────────────┬───────────────┼───────────────┬──────────────┐
          ▼               ▼              ▼               ▼               ▼              ▼
     TaskManager      Tool Registry   Gateway        Knowledge      Capabilities    Settings/Secrets
     (agent loop,     (schemas,       (adapters,     (FTS5 index,   (catalogue,     (JSON file; OS
      approvals,       permissions,    PolicyEngine,  memory)        plugins)        keychain)
      persistence)     approvals)      usage ledger)
          │               │
          └──── Sandbox / SnapshotStore / command runner (workspace.py, commands.py)
```

## Key decisions and alternatives

| Decision | Chosen | Alternatives considered | Why |
|---|---|---|---|
| Backend language | Python 3.10+ / FastAPI | Rust, Node | Fastest path to a real, testable agent; best ecosystem for document parsing; small deps |
| Frontend | Dependency-free JS served by the backend | React/Vite, Electron | No build chain to break, tiny attack surface, strict CSP, no `innerHTML`. Trade-off: hand-written DOM code |
| Desktop packaging | Planned Tauri shell spawning the backend | Electron, PyInstaller-only | Small footprint; **not built or verified yet** |
| Agent↔model protocol | JSON action in plain text | Native function calling | Works with any local model; native tool calls can be added per adapter later |
| Storage | SQLite (WAL) + JSON settings | Postgres, files | Zero-setup, local-first. FTS5 gives BM25 without extra services |
| Retrieval | FTS5/BM25 now, embeddings later | Vector DB (Chroma/Qdrant) now | Keeps the core lightweight and offline; gateway `embed()` is ready and policy-gated |
| Sandboxing | Policy + allowlist + argv only | Docker/WSL per task | Cross-platform and light; **weaker** than a container. Documented limitation |
| Plugins | External-command JSON manifests | In-process Python plugins, MCP | Cannot run in-process code from untrusted manifests; MCP client is planned |
| Locality detection | Derived from base URL (loopback only) | User-set "local" flag | A flag can be wrong; LAN hosts and lookalike hostnames count as remote |

## Request path for a task
1. `POST /api/tasks` checks policy *before* creating anything.
2. `TaskManager` builds context (tree, repo notes, memories, all marked untrusted), then loops: model → one JSON action → registry.
3. Registry: schema validation → capability enabled? → plan-mode read-only? → handler → `ctx.require(level)` → approval gate or auto-allow.
4. File changes are planned (no disk write), shown as diffs, applied through `SnapshotStore` (backup first, atomic replace).
5. `run_command` is classified (`commands.classify`): never-list, network, install, destructive, verification-safe.
6. When the model says *final*, the manager checks evidence: edits without a later passing check are pushed back once, then reported as `completed_unverified` or `failed`.
7. Events persist to SQLite and stream over SSE; approvals/answers come back via REST.

## Modules
`config` settings · `secrets_store` keychain · `audit` redaction + JSONL log · `workspace` sandbox/patch/snapshots · `commands` classification and execution ·
`documents` adapters · `gateway` providers/policy/ledger/router · `tools` registry · `agent` orchestration · `knowledge` index+memory ·
`capabilities`/`plugins` · `hardware` · `server` API · `cli`.

## Extending
- **Provider**: subclass `Adapter` (list_models, stream_chat), register in `ADAPTERS`, add tests against `httpx.MockTransport`.
- **Tool**: add a `ToolSpec` in `tools.py` with a capability id, a permission level, and tests.
- **Document type**: add a function in `documents.py`; it must be bounded and never raise.
- **Capability**: add to `capabilities.CATALOG` with an honest status.
