from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hearthforge", description="Local-first AI development workstation")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sv = sub.add_parser("serve", help="start the local server and UI")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--home", type=Path, default=None, help="data directory (default: per-user app data)")
    sv.add_argument("--no-browser", action="store_true")
    sub.add_parser("doctor", help="print environment diagnostics")
    args = ap.parse_args(argv)

    if args.cmd == "doctor":
        from . import hardware
        from .secrets_store import SecretStore
        import json, shutil
        print(json.dumps({
            "version": __version__, "python": sys.version.split()[0], "git": bool(shutil.which("git")),
            "ollama_cli": bool(shutil.which("ollama")), "secure_secret_store": SecretStore().secure_backend_available,
            "hardware": hardware.detect(),
        }, indent=2))
        return 0

    import uvicorn
    from .app import App
    from .server import create_app

    core = App(home=args.home)
    url = f"http://127.0.0.1:{args.port}/auth?token={core.token}"
    print(f"Hearthforge {__version__}\nData directory: {core.home}\nOpen: {url}\n(The token is regenerated every launch. Keep this URL private.)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(core), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
