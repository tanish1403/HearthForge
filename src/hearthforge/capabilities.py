"""Capability catalogue: honest status, enable/disable state, and health."""
from __future__ import annotations

import importlib.util
import shutil

from .config import SettingsStore

# status: implemented | partial | planned. Never list something as implemented unless tests cover it.
CATALOG = [
    {"id": "workspace.files", "name": "Workspace files", "group": "Core", "status": "implemented", "default": True,
     "tools": ["list_dir", "read_file", "search", "write_file", "edit_file", "apply_patch", "delete_file"],
     "desc": "Sandboxed read/write/search/patch with snapshots and undo."},
    {"id": "workspace.git", "name": "Git inspection", "group": "Core", "status": "implemented", "default": True,
     "tools": ["git_status", "git_diff"], "desc": "Read-only git status and diffs (hardened against repo config)."},
    {"id": "workspace.exec", "name": "Run commands", "group": "Core", "status": "implemented", "default": True,
     "tools": ["run_command"], "desc": "Allowlisted, argv-only, bounded commands: tests, builds, linters."},
    {"id": "docs.reader", "name": "Document reader", "group": "Knowledge", "status": "implemented", "default": True,
     "tools": ["read_document"], "desc": "Text, Markdown, CSV, PDF (pypdf), DOCX, XLSX, PPTX; images need a vision model."},
    {"id": "knowledge.rag", "name": "Local search index (RAG)", "group": "Knowledge", "status": "partial", "default": True,
     "tools": ["knowledge_search"], "desc": "Incremental keyword/BM25 index with citations. Vector search is not implemented yet."},
    {"id": "memory.project", "name": "Project memory", "group": "Knowledge", "status": "implemented", "default": True,
     "tools": ["remember", "recall"], "desc": "Scoped long-term notes you can inspect, edit, export and delete."},
    {"id": "obsidian.vault", "name": "Obsidian vault (as folder)", "group": "Knowledge", "status": "partial", "default": False,
     "tools": [], "desc": "Index a vault folder as a knowledge source. No Obsidian plugin/API integration."},
    {"id": "embeddings.vector", "name": "Vector embeddings", "group": "Knowledge", "status": "partial", "default": False,
     "tools": [], "desc": "Gateway embedding calls are policy-enforced; the index does not use them yet."},
    {"id": "rerank", "name": "Reranking", "group": "Knowledge", "status": "planned", "default": False, "tools": [], "desc": "Not implemented."},
    {"id": "web.access", "name": "Internet (search and fetch pages)", "group": "Research", "status": "implemented", "default": True,
     "tools": ["web_search", "web_fetch"], "desc": "Search (DuckDuckGo, SearXNG or Wikipedia) and read public pages. Blocked until you turn Internet on; local/private addresses are always refused."},
    {"id": "research.agent", "name": "Research agent", "group": "Research", "status": "planned", "default": False, "tools": [], "desc": "Not implemented."},
    {"id": "automation.schedule", "name": "Scheduled tasks", "group": "Automation", "status": "planned", "default": False, "tools": [], "desc": "Not implemented."},
    {"id": "mcp.client", "name": "MCP client", "group": "Integrations", "status": "planned", "default": False, "tools": [], "desc": "Not implemented."},
]
BY_ID = {c["id"]: c for c in CATALOG}


class Capabilities:
    def __init__(self, store: SettingsStore, plugins=None):
        self.store, self.plugins = store, plugins

    def enabled(self, cid: str | None) -> bool:
        if cid is None:
            return True
        if cid.startswith("plugin."):
            return self.store.settings.capabilities.get(cid, True) and bool(self.plugins and self.plugins.has(cid[7:]))
        c = BY_ID.get(cid)
        if not c or c["status"] == "planned":
            return False
        return self.store.settings.capabilities.get(cid, c["default"])

    def set(self, cid: str, on: bool) -> None:
        if cid.startswith("plugin."):
            pass
        elif cid not in BY_ID:
            raise KeyError(cid)
        elif BY_ID[cid]["status"] == "planned" and on:
            raise ValueError("This capability is not implemented yet")
        self.store.update(lambda s: s.capabilities.__setitem__(cid, on))

    def health(self, cid: str) -> dict:
        if cid == "docs.reader":
            ok = importlib.util.find_spec("pypdf") is not None
            return {"ok": True, "detail": "PDF support installed" if ok else "PDF support missing: pip install 'hearthforge[docs]'"}
        if cid == "web.access":
            m = self.store.settings.policy.internet
            return {"ok": m != "off", "detail": {"off": "Internet is OFF (turn it on in the Internet panel)", "ask": "Internet: approve each request", "on": "Internet: on"}[m]}
        if cid in ("workspace.git", "workspace.exec"):
            ok = shutil.which("git") is not None
            return {"ok": ok or cid == "workspace.exec", "detail": "git found" if ok else "git not found on PATH"}
        return {"ok": True, "detail": ""}

    def list(self) -> list[dict]:
        out = []
        for c in CATALOG:
            d = dict(c)
            d["enabled"] = self.enabled(c["id"])
            d["health"] = self.health(c["id"]) if c["status"] != "planned" else {"ok": False, "detail": "not implemented"}
            out.append(d)
        if self.plugins:
            for p in self.plugins.list():
                cid = "plugin." + p["id"]
                out.append({"id": cid, "name": p["name"], "group": "Plugins", "status": "implemented", "default": True,
                            "tools": [f"plugin.{p['id']}.{t['name']}" for t in p["tools"]], "desc": p.get("description", ""),
                            "enabled": self.enabled(cid), "removable": True,
                            "health": {"ok": True, "detail": "external command plugin; always asks before running unless exec is allowed"}})
        return out
