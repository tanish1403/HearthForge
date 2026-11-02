# Releasing and packaging

**Python package (works today):** `pip install build && python -m build` creates `dist/*.whl` and `.tar.gz`. The `release.yml` workflow builds them on a `v*` tag and attaches them to a GitHub release.

**Native installers (planned, not built):** wrap `hearthforge serve --no-browser` in a Tauri (or PyInstaller) shell per OS, sign it, and verify on each OS separately before
claiming support. Until then, install via pip.

Release checklist: update version in `pyproject.toml` and `src/hearthforge/__init__.py`, update CHANGELOG, run the full test matrix, run `scripts/check_secrets.py`, tag `vX.Y.Z`.
