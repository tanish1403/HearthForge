# Implementation status

Legend: **Implemented** (code + automated tests) · **Partial** · **Planned** (not built) · **Blocked**.
"Verified" means actually run in this repository's test suite or smoke test, not assumed.

## Platform verification
| Platform | Status |
|---|---|
| Linux (Ubuntu 24.04, Python 3.12) | **Verified**: 181 tests, lint, wheel build, real server + 22-step UI journey (jsdom) |
| Windows 11 | **Unverified.** Code paths exist (APPDATA, process groups, `.cmd` shim guard); CI matrix will exercise them once pushed |
| macOS | **Unverified.** Same as above; Apple Silicon memory detection is a heuristic and flagged unverified |
| Real browser rendering | **Unverified.** The UI journey (connect gateway, browse folder, chat, internet, agent approval, all views) passes in jsdom (`tests/ui/run.sh`), which checks logic and DOM, not visual layout, styling or screen readers |
| Live internet / search engines | **Unverified.** The build sandbox could not reach them; parsers and SSRF rules are tested against mocks only |
| Real local model (Ollama/llama.cpp) | **Unverified.** Adapters are tested against mock servers that follow the documented wire formats |
| Real cloud providers | **Unverified.** No credentials were used; endpoints are presets to confirm against provider docs |

## Features
| Area | Status | Notes |
|---|---|---|
| Workspace sandbox (traversal, symlink, secret-file refusal, .git protection) | Implemented | `workspace.py`, tests in `test_workspace.py` |
| Edits, validated unified-diff patches, snapshots, undo (refuses to clobber newer edits) | Implemented | |
| Command policy (argv only, allowlist, never-shells, git hardening, env scrubbing, timeout, output caps, cancel) | Implemented | No OS sandbox |
| Layered permissions allow/ask/deny with approval gates and feedback | Implemented | Backend-enforced |
| Agent loop: plan/build modes, bounded steps, fix rounds, loop guard, cancel, resume, persistence | Implemented | |
| Evidence-based completion report | Implemented | `completed_verified / unverified / failed` |
| Provider gateway: OpenAI-compatible + Ollama, streaming, error normalisation, retries | Implemented | Mock-tested |
| Privacy modes, zero-spend, budgets (need user-entered prices), usage ledger (reported vs estimated) | Implemented | |
| Model routing with explanations | Partial | Simple ranking; no task-aware scoring or health history |
| Credential storage via OS keychain; env-var fallback; no plaintext fallback | Implemented | Needs a keyring backend on the host |
| Document adapters: text, MD, CSV, PDF text, DOCX, XLSX, PPTX | Implemented | Layout/formulas/images not interpreted |
| OCR / scanned PDFs | Planned | Detected and reported, not processed |
| Image understanding | Partial | Sent only to models you declare/are reported as vision-capable |
| Knowledge index (FTS5/BM25, incremental, citations, exclude/export/delete) | Implemented | |
| Vector search / embeddings in the index / reranking | Planned | Gateway `embed()` exists and is policy-enforced |
| Project memory (scoped, secret-refusing, editable) | Implemented | |
| Obsidian | Partial | Index a vault folder as a source; no plugin API |
| Plugin system (external-command JSON manifests) | Implemented | Min `exec` permission, no shell |
| Connect-a-model wizard (URL normalisation, endpoint probing, key hand-off, consented privacy change, test message, session-key fallback) | Implemented | Mock-tested incl. an OmniRoute-style gateway |
| Folder browser (server-side directory listing, new folder, path cleanup, duplicate handling) | Implemented | |
| Web search + page fetch (DuckDuckGo/Wikipedia/SearXNG), off/ask/on, SSRF guard incl. redirects | Implemented | Live endpoints unverified; DNS-rebinding race documented |
| Chat with streaming, web sources, project excerpts | Implemented | |
| In-app Guide + generated `docs/GUIDE.md`, command palette, model picker | Implemented | |
| Research agent, scheduler/automation, MCP client | Planned | Shown as "planned" in the UI |
| Hardware detection and fit estimates | Implemented | Estimates ±40% |
| Web UI (rail with approval gates, diffs, inspector, settings) | Implemented | Not browser-verified visually |
| Native desktop packaging | Planned | Tauri shell proposed in ARCHITECTURE.md |
| Streaming task events (SSE), reconnect with backlog | Implemented | |

## Known issues / limitations
- Local-only default means a fresh install does nothing until a local model server is running.
- Context compaction is simple truncation of old tool output, not summarisation.
- The index re-reads changed files fully; very large repos will index slowly (single thread).
- Knowledge sources are not auto-refreshed; click *Re-index*.
- Native tool-calling APIs are not used (JSON protocol only).

## Next steps (suggested order)
1. Run the CI matrix on Windows/macOS and fix whatever it finds.
2. Try with real Ollama (`qwen2.5-coder`-class 7B) and record which models follow the protocol.
3. Optional embeddings + hybrid retrieval through `Gateway.embed`.
4. Tauri shell and signed installers.
5. Task-aware routing and a reviewer sub-agent.
