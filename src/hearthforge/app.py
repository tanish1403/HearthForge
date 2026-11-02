"""Composition root: wires every service together."""
from __future__ import annotations

import secrets as pysecrets
from pathlib import Path

import httpx

from .agent import TaskManager
from .audit import AuditLog
from .capabilities import Capabilities
from .config import SettingsStore, default_home
from .db import DB
from .gateway import Gateway, PolicyEngine, Router, UsageLedger
from .knowledge import Knowledge
from .plugins import PluginManager
from .secrets_store import SecretStore
from .tools import Services
from .workspace import SnapshotStore


class App:
    def __init__(self, home: Path | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 secrets: SecretStore | None = None, token: str | None = None,
                 web_transport: httpx.AsyncBaseTransport | None = None, resolver=None):
        self.home = Path(home) if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.token = token or pysecrets.token_urlsafe(24)
        self.store = SettingsStore(self.home)
        self.secrets = secrets or SecretStore()
        self.audit = AuditLog(self.home / "audit.jsonl", lambda: self.secrets.all_values([p.id for p in self.store.settings.providers]))
        self.db = DB(self.home / "app.db")
        self.ledger = UsageLedger(self.db)
        self.policy = PolicyEngine(self.store, self.ledger)
        self.gateway = Gateway(self.store, self.secrets, self.policy, self.ledger, self.audit, transport)
        self.router = Router(self.gateway)
        self.kb = Knowledge(DB(self.home / "knowledge.db"))
        self.snapshots = SnapshotStore(self.home / "snapshots")
        self.plugins = PluginManager(self.home / "plugins")
        self.caps = Capabilities(self.store, self.plugins)
        self.web_transport, self.resolver = web_transport, resolver
        self.svc = Services(self.kb, self.snapshots, self.caps, self.plugins, self.audit, self.store, web_transport, resolver)
        self.tasks = TaskManager(self.db, self.store, self.gateway, self.svc, self.audit)

    def workspace(self, wid: str):
        for w in self.store.settings.workspaces:
            if w.id == wid:
                return w
        return None

    async def aclose(self) -> None:
        await self.gateway.aclose()
