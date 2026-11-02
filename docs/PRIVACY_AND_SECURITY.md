# Privacy and security

## What can leave your machine?
| Mode | Meaning |
|---|---|
| **Local only** (default) | Nothing. Any non-loopback provider is blocked for chat, embeddings, model discovery and health checks. |
| **Free tier only** | Prompts and file excerpts may go to remote providers *you marked free-tier*. You assert free-tier status; Hearthforge cannot verify it. Metered/unknown providers are blocked. |
| **Budgeted cloud** | Any enabled remote provider. Metered use counts against budgets, but only for models with a price you entered; otherwise a budgeted call is blocked because spend can't be enforced. |

**Internet** (web search/page fetch) is a separate switch: Off (default), Ask, or On. Search words go to the chosen search engine; page requests go to the sites visited.

Locality comes from the provider URL (loopback only). `192.168.x.x` and `127.0.0.1.evil.com` count as **remote**.
The UI always shows the current mode and which remote providers are enabled.

## Threat model and controls
| Threat | Control |
|---|---|
| Path traversal / symlink escape | Every path is `realpath`-resolved and must remain inside the workspace root (reads, writes, patches, search, indexing) |
| Secret exposure | Files like `.env`, `*.pem`, `id_rsa*` are refused for read/write/search/index; credentials live in the OS keychain; logs, events and the audit file are redacted; memory refuses credential-like text; child processes get a scrubbed environment |
| Prompt injection (files, docs, command output, notes) | All tool output is wrapped as untrusted data; a heuristic flags instruction-like text; the model cannot widen permissions because enforcement is in the backend |
| Arbitrary shell | No shell is ever used. `run_command` takes an argv array; shells and destructive utilities are never allowed even if allowlisted; unknown executables are denied; git config/exec override flags are denied; `.cmd` shims reject metacharacters |
| Accidental data loss | Snapshots before every change/delete; undo refuses to overwrite newer user edits; `.git` is write-protected |
| Runaway agent | Step limit, fix-round limit, repeat-call loop guard, timeouts, output caps, cancel kills the process tree |
| Malicious web page talking to the local server | Per-launch random token (HttpOnly SameSite=Strict cookie), Host allowlist (DNS-rebinding), Origin check, CSP, loopback-only bind |
| Agent/page tricked into reaching internal services (SSRF) | `web_fetch` only connects to public addresses; loopback, private, link-local, reserved and metadata IPs are refused, also for every redirect hop and when a hostname resolves to any such address; no credentials-in-URL; only http(s); text/JSON/XML only; size/time limits |
| Malicious plugin manifest | Fixed argv, bare executable, shells rejected, ≥ `exec` permission, invalid files ignored |

## Residual risks (read these)
- Allowed commands (tests, builds, `python script.py`) execute **project code with your user rights**. No container is used.
  A hostile repository can run hostile code when you approve (or auto-approve) a test run. Keep exec on `ask` for unfamiliar code.
- Auto-approval of recognised verification commands is a convenience trade-off, configurable per workspace.
- Remote providers see whatever the agent sends them (file excerpts, command output). Use Local only for sensitive code.
- Web fetch checks the resolved address before connecting, but DNS could change between the check and the connection (DNS rebinding). Keep Internet off or on *Ask* for untrusted tasks.
- The injection heuristic is a speed bump, not a guarantee.
- If no OS keychain exists, the connect wizard keeps a key in memory only (lost on quit) and says so.
- Without an OS keychain, keys must come from environment variables; Hearthforge refuses to write them to disk.
- Audit logs may contain file paths and task text; keep `HEARTHFORGE_HOME` private.

Report vulnerabilities per [SECURITY.md](../SECURITY.md).
