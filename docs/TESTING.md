# Testing

```bash
pip install -e ".[dev]"
ruff check src tests
pytest -q
python -m build   # needs: pip install build
```
Tests use mock providers (`httpx.MockTransport`), temp dirs and a fake keyring: no network, no paid APIs, no GPU.

| Area | File |
|---|---|
| Sandbox, patches, snapshots, undo | `tests/test_workspace.py` |
| Command classification and execution | `tests/test_commands.py` |
| Adapters, errors, retries, privacy modes, budgets, routing | `tests/test_gateway.py` |
| Agent loop, permissions, cancellation, verification honesty, injection | `tests/test_agent.py` |
| Retrieval, memory, isolation | `tests/test_knowledge.py` |
| Documents | `tests/test_documents.py` |
| Hardware | `tests/test_hardware.py` |
| Plugins | `tests/test_plugins.py` |
| API, auth, SSE, end-to-end | `tests/test_server.py` |
| Connect wizard backend, folder browser, internet settings, chat | `tests/test_connect.py` |
| Web fetch/search, SSRF, agent web tools | `tests/test_web.py` |

UI journey (needs Node 18+): `tests/ui/run.sh` starts a real server with a scripted OmniRoute-style gateway and drives the UI in jsdom: connect, folder browser, chat, internet, agent approval, knowledge, all views.

Not covered by automated tests: visual UI layout/accessibility audits, real providers, Windows/macOS (CI matrix covers them once pushed).
Manual UI check: `hearthforge serve`, then walk through each section with keyboard only.
