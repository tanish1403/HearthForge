# Contributing

1. Fork, create a branch, `pip install -e ".[dev]"`.
2. `ruff check src tests` and `pytest -q` must pass. Add tests with every behaviour change; **security-relevant changes need a test that fails without the fix**.
3. Never mark a capability `implemented` in `capabilities.py` or `IMPLEMENTATION_STATUS.md` without tests. Do not claim OS/provider support you haven't run.
4. Keep the core light: new dependencies need a justification (licence, maintenance, size) in the PR.
5. UI changes: no `innerHTML`, keyboard accessible, works in light/dark and at narrow widths.
6. Sign off that you have the right to contribute under Apache-2.0.

Good first areas: Windows/macOS CI fixes, OCR adapter, vector retrieval via `Gateway.embed`, more document adapters, native tool-calling adapters.
