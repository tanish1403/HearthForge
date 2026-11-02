"""Settings model and atomic on-disk store. Secrets are NEVER stored here."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["allow", "ask", "deny"]
LEVELS = ("read", "write", "exec", "network", "install", "destructive")

DEFAULT_PERMISSIONS: dict[str, str] = {
    "read": "allow",
    "write": "ask",
    "exec": "ask",
    "network": "deny",
    "install": "ask",
    "destructive": "ask",
}


def default_home() -> Path:
    env = os.environ.get("HEARTHFORGE_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "hearthforge"


class Policy(BaseModel):
    # local_only: no remote inference/embedding/rerank at all (default)
    # free_only:  remote allowed only for providers the user declared "free_tier"
    # budgeted:   remote allowed; metered use counted against budgets
    cloud_mode: Literal["local_only", "free_only", "budgeted"] = "local_only"
    monthly_budget_usd: float | None = None
    task_budget_usd: float | None = None
    # Web access for the agent and chat (search + page fetch). Independent of model privacy mode.
    # off: blocked | ask: every call needs approval (agent) | on: allowed automatically
    internet: Literal["off", "ask", "on"] = "off"


class WebSettings(BaseModel):
    engine: Literal["duckduckgo", "searxng", "wikipedia"] = "duckduckgo"
    searxng_url: str = ""


class ProviderConfig(BaseModel):
    id: str
    name: str
    kind: Literal["ollama", "openai_compat"]
    base_url: str
    # Only meaningful for REMOTE providers. Locality is derived from base_url, never trusted from here.
    cost_class: Literal["free_tier", "metered", "unknown"] = "unknown"
    default_model: str | None = None
    enabled: bool = True
    prices: dict[str, list[float]] = Field(default_factory=dict)  # model -> [usd/1M in, usd/1M out]
    vision_models: list[str] = Field(default_factory=list)  # user-declared
    tool_models: list[str] = Field(default_factory=list)  # user-declared native tool-calling (informational)
    timeout_s: float = 120.0


class WorkspaceConfig(BaseModel):
    id: str
    name: str
    path: str
    permissions: dict[str, Mode] = Field(default_factory=lambda: dict(DEFAULT_PERMISSIONS))
    extra_allowed_commands: list[str] = Field(default_factory=list)
    auto_approve_safe_commands: bool = True
    max_steps: int = 25


class ActiveModel(BaseModel):
    provider: str
    model: str


class Settings(BaseModel):
    version: int = 1
    policy: Policy = Field(default_factory=Policy)
    web: WebSettings = Field(default_factory=WebSettings)
    providers: list[ProviderConfig] = Field(default_factory=list)
    workspaces: list[WorkspaceConfig] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    active: ActiveModel | None = None


def default_settings() -> Settings:
    return Settings(
        providers=[
            ProviderConfig(id="ollama", name="Ollama (local)", kind="ollama", base_url="http://127.0.0.1:11434"),
            ProviderConfig(
                id="llamacpp", name="llama.cpp server (local)", kind="openai_compat", base_url="http://127.0.0.1:8080/v1"
            ),
        ]
    )


# Starting points only. Verify endpoints against provider docs; nothing here is auto-enabled.
PRESETS: list[dict] = [
    {"id": "openrouter", "name": "OpenRouter", "kind": "openai_compat", "base_url": "https://openrouter.ai/api/v1"},
    {"id": "groq", "name": "Groq", "kind": "openai_compat", "base_url": "https://api.groq.com/openai/v1"},
    {
        "id": "gemini",
        "name": "Google Gemini (OpenAI-compatible)",
        "kind": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    },
    {"id": "hf", "name": "Hugging Face Inference Providers", "kind": "openai_compat", "base_url": "https://router.huggingface.co/v1"},
    {"id": "lmstudio", "name": "LM Studio (local)", "kind": "openai_compat", "base_url": "http://127.0.0.1:1234/v1"},
    {"id": "custom", "name": "Custom OpenAI-compatible", "kind": "openai_compat", "base_url": "https://"},
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class SettingsStore:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "settings.json"
        self._lock = threading.RLock()
        self.settings = self._load()

    def _load(self) -> Settings:
        if self.path.exists():
            try:
                return Settings.model_validate_json(self.path.read_text("utf-8"))
            except Exception:
                backup = self.path.with_suffix(".json.corrupt")
                self.path.replace(backup)
        s = default_settings()
        self._write(s)
        return s

    def _write(self, s: Settings) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.home, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(s.model_dump_json(indent=2))
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def save(self) -> None:
        with self._lock:
            self._write(self.settings)

    def update(self, fn) -> Settings:
        with self._lock:
            fn(self.settings)
            self._write(self.settings)
            return self.settings
