"""External-command plugins: a JSON manifest declares tools backed by fixed argv commands.

A plugin cannot widen permissions: its tools are always at least 'exec' level, run without a shell,
receive tool arguments as JSON on stdin, and have bounded output/time.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .commands import NEVER, exe_name

ID_RX = re.compile(r"^[a-z0-9][a-z0-9\-]{1,40}$")
NAME_RX = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class PluginError(Exception):
    pass


def validate_manifest(m: dict) -> dict:
    if not isinstance(m, dict):
        raise PluginError("Manifest must be an object")
    if not ID_RX.match(str(m.get("id", ""))):
        raise PluginError("id must be lowercase letters, digits and dashes (2-41 chars)")
    if not str(m.get("name", "")).strip():
        raise PluginError("name is required")
    tools = m.get("tools")
    if not isinstance(tools, list) or not tools or len(tools) > 20:
        raise PluginError("tools must be a list of 1-20 tool definitions")
    seen = set()
    for t in tools:
        if not NAME_RX.match(str(t.get("name", ""))):
            raise PluginError(f"Bad tool name: {t.get('name')!r}")
        if t["name"] in seen:
            raise PluginError(f"Duplicate tool name: {t['name']}")
        seen.add(t["name"])
        cmd = t.get("command")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
            raise PluginError(f"Tool {t['name']}: command must be a non-empty list of strings")
        if exe_name(cmd[0]) in NEVER or "/" in cmd[0] or "\\" in cmd[0]:
            raise PluginError(f"Tool {t['name']}: executable must be a bare command and not a shell/destructive utility")
        if not str(t.get("description", "")).strip():
            raise PluginError(f"Tool {t['name']}: description required")
        params = t.get("parameters", {"type": "object", "properties": {}})
        if params.get("type") != "object":
            raise PluginError(f"Tool {t['name']}: parameters must be an object schema")
        t["parameters"] = params
        t["level"] = t.get("level", "exec") if t.get("level", "exec") in {"exec", "network", "install"} else "exec"
    return m


class PluginManager:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                out.append(validate_manifest(json.loads(f.read_text("utf-8"))))
            except Exception:
                continue  # invalid manifests are ignored, never executed
        return out

    def get(self, pid: str) -> dict | None:
        return next((p for p in self.list() if p["id"] == pid), None)

    def has(self, pid: str) -> bool:
        return self.get(pid) is not None

    def add(self, manifest: dict) -> dict:
        m = validate_manifest(manifest)
        (self.dir / f"{m['id']}.json").write_text(json.dumps(m, indent=2), "utf-8")
        return m

    def remove(self, pid: str) -> None:
        if not ID_RX.match(pid):
            raise PluginError("bad id")
        f = self.dir / f"{pid}.json"
        if f.exists():
            f.unlink()
