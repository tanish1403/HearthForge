"""Provider-independent model gateway with policy enforcement at the single egress point."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from .audit import AuditLog
from .config import ProviderConfig, SettingsStore
from .db import DB
from .secrets_store import SecretStore


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, retry_after: float | None = None, status: int | None = None):
        super().__init__(message)
        self.kind, self.message, self.retry_after, self.status = kind, message, retry_after, status

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "retry_after": self.retry_after, "status": self.status}


class PolicyError(Exception):
    pass


def host_is_local(url: str) -> bool:
    """True only for loopback. LAN addresses and lookalike hostnames (127.0.0.1.evil.com) are remote."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_base_url(url: str) -> str:
    """Forgive common paste mistakes: missing scheme, trailing slash, /chat/completions, /models."""
    u = (url or "").strip().strip("\"'")
    if not u:
        return u
    if "://" not in u:
        u = ("http://" if re.match(r"^(localhost|127\.|\[::1\]|\d+\.\d+\.\d+\.\d+)", u) else "https://") + u
    u = u.split("?")[0].rstrip("/")
    for suf in ("/chat/completions", "/completions", "/models", "/embeddings"):
        if u.endswith(suf):
            u = u[: -len(suf)]
    return u.rstrip("/")


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _flat(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")


# ------------------------------------------------------------------ usage ledger
class UsageLedger:
    def __init__(self, db: DB):
        self.db = db
        db.script("""CREATE TABLE IF NOT EXISTS usage(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, provider TEXT, model TEXT, op TEXT,
            prompt_tokens INTEGER, completion_tokens INTEGER, token_source TEXT,
            cost_usd REAL, cost_source TEXT, task_id TEXT, remote INTEGER);""")

    def record(self, **r) -> None:
        self.db.execute(
            "INSERT INTO usage(ts,provider,model,op,prompt_tokens,completion_tokens,token_source,cost_usd,cost_source,task_id,remote)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), r["provider"], r["model"], r["op"], r["prompt_tokens"], r["completion_tokens"], r["token_source"],
             r.get("cost_usd"), r.get("cost_source", "unknown"), r.get("task_id"), 1 if r["remote"] else 0))

    def month_cost(self) -> float:
        start = time.time() - 30 * 86400
        row = self.db.query("SELECT COALESCE(SUM(cost_usd),0) c FROM usage WHERE ts>? AND remote=1", (start,))[0]
        return float(row["c"])

    def task_cost(self, task_id: str) -> float:
        return float(self.db.query("SELECT COALESCE(SUM(cost_usd),0) c FROM usage WHERE task_id=? AND remote=1", (task_id,))[0]["c"])

    def summary(self) -> dict:
        rows = self.db.query("""SELECT provider, model, remote, COUNT(*) calls, SUM(prompt_tokens) pt, SUM(completion_tokens) ct,
            SUM(cost_usd) cost, GROUP_CONCAT(DISTINCT token_source) src FROM usage GROUP BY provider, model, remote""")
        return {"rows": [dict(r) for r in rows], "month_cost_usd": self.month_cost()}


# ------------------------------------------------------------------ policy
class PolicyEngine:
    def __init__(self, store: SettingsStore, ledger: UsageLedger):
        self.store, self.ledger = store, ledger

    def is_local(self, p: ProviderConfig) -> bool:
        return host_is_local(p.base_url)

    def check(self, p: ProviderConfig, op: str = "inference", model: str | None = None, task_id: str | None = None) -> None:
        if not p.enabled:
            raise PolicyError(f"Provider '{p.name}' is disabled")
        if self.is_local(p):
            return
        pol = self.store.settings.policy
        if pol.cloud_mode == "local_only":
            raise PolicyError(f"Blocked ({op}): cloud mode is 'Local only' and '{p.name}' is a remote service.")
        if pol.cloud_mode == "free_only" and p.cost_class != "free_tier":
            raise PolicyError(
                f"Blocked ({op}): zero-spend mode allows only providers you marked free-tier; '{p.name}' is '{p.cost_class}'.")
        if pol.cloud_mode == "budgeted" and p.cost_class != "free_tier":
            has_budget = pol.monthly_budget_usd is not None or pol.task_budget_usd is not None
            priced = bool(model and model in p.prices)
            if has_budget and not priced:
                raise PolicyError(
                    f"Blocked ({op}): a budget is set but no price is configured for '{model}' on '{p.name}', so spend cannot be enforced.")
            if pol.monthly_budget_usd is not None and self.ledger.month_cost() >= pol.monthly_budget_usd:
                raise PolicyError("Blocked: monthly cloud budget reached.")
            if pol.task_budget_usd is not None and task_id and self.ledger.task_cost(task_id) >= pol.task_budget_usd:
                raise PolicyError("Blocked: this task's cloud budget was reached.")

    def explain(self) -> dict:
        s = self.store.settings
        mode = s.policy.cloud_mode
        text = {
            "local_only": "Nothing leaves this machine. Remote providers, remote embeddings and reranking are blocked.",
            "free_only": "Prompts and file excerpts may be sent ONLY to remote providers you marked free-tier. Metered/unknown providers are blocked.",
            "budgeted": "Prompts and file excerpts may be sent to any enabled remote provider. Metered use counts against your budgets.",
        }[mode]
        net = s.policy.internet
        text += {"off": " Internet access for search/fetch is OFF.",
                 "ask": " Web searches/page fetches send queries to a search engine and need your approval each time.",
                 "on": " Web searches/page fetches are ON: queries leave this machine automatically."}[net]
        remote = [p.name for p in s.providers if p.enabled and not self.is_local(p)]
        return {"mode": mode, "internet": net, "summary": text, "enabled_remote_providers": remote}


# ------------------------------------------------------------------ adapters
@dataclass
class ModelInfo:
    id: str
    provider: str
    context: int | None = None
    capabilities: list[str] = field(default_factory=list)
    cap_source: str = "unknown"  # reported | declared | unknown
    size_bytes: int | None = None


@dataclass
class ChatChunk:
    delta: str = ""
    finish: str | None = None
    usage: dict | None = None


def _normalize_http(resp: httpx.Response) -> ProviderError:
    body = ""
    try:
        body = resp.text[:300]
    except Exception:
        pass
    ra = None
    if "retry-after" in resp.headers:
        try:
            ra = float(resp.headers["retry-after"])
        except ValueError:
            ra = None
    s = resp.status_code
    if s in (401, 403):
        return ProviderError("auth", f"Authentication failed (HTTP {s}). Check the API key.", status=s)
    if s == 429:
        return ProviderError("rate_limit", "Rate limit or quota reached.", retry_after=ra, status=s)
    if s == 404:
        return ProviderError("not_found", f"Endpoint or model not found. {body}", status=s)
    if s in (400, 422):
        return ProviderError("bad_request", f"Request rejected: {body}", status=s)
    if s >= 500:
        return ProviderError("server", f"Provider error (HTTP {s}).", retry_after=ra, status=s)
    return ProviderError("unknown", f"HTTP {s}: {body}", status=s)


class Adapter:
    kind = "base"

    def __init__(self, cfg: ProviderConfig, api_key: str | None, client: httpx.AsyncClient):
        self.cfg, self.key, self.client = cfg, api_key, client
        self.base = cfg.base_url.rstrip("/")

    def headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = await self.client.request(method, url, headers=self.headers(), **kw)
        except httpx.ConnectError:
            raise ProviderError("unreachable", f"Cannot connect to {self.base}. Is the server running?")
        except httpx.TimeoutException:
            raise ProviderError("timeout", f"Timed out talking to {self.base}.")
        except httpx.HTTPError as e:
            raise ProviderError("unreachable", f"Network error: {type(e).__name__}")
        if r.status_code >= 400:
            raise _normalize_http(r)
        return r

    async def health(self) -> dict:
        t0 = time.monotonic()
        try:
            models = await self.list_models()
            return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000), "models": len(models)}
        except ProviderError as e:
            return {"ok": False, "error": e.as_dict()}

    async def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    def stream_chat(self, messages, model, temperature, max_tokens) -> AsyncIterator[ChatChunk]:
        raise NotImplementedError

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise ProviderError("unsupported", "Embeddings not supported by this adapter")

    def declared_caps(self, model: str) -> list[str]:
        caps = []
        if model in self.cfg.vision_models:
            caps.append("vision")
        if model in self.cfg.tool_models:
            caps.append("tools")
        return caps


class OpenAICompatAdapter(Adapter):
    kind = "openai_compat"

    async def list_models(self) -> list[ModelInfo]:
        r = await self._request("GET", f"{self.base}/models")
        data = r.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        out = []
        for m in items or []:
            mid = m.get("id") or m.get("name")
            if mid:
                mid = mid.removeprefix("models/")
                ctx = m.get("context_length") or m.get("context_window")
                out.append(ModelInfo(mid, self.cfg.id, ctx, self.declared_caps(mid), "declared" if self.declared_caps(mid) else "unknown"))
        return out

    async def stream_chat(self, messages, model, temperature=0.2, max_tokens=None):
        body = {"model": model, "messages": messages, "stream": True, "temperature": temperature,
                "stream_options": {"include_usage": True}}
        if max_tokens:
            body["max_tokens"] = max_tokens
        for attempt in range(2):
            try:
                async with self.client.stream("POST", f"{self.base}/chat/completions", headers=self.headers(), json=body) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        if r.status_code == 400 and "stream_options" in r.text and attempt == 0:
                            body.pop("stream_options")
                            continue
                        raise _normalize_http(r)
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            return
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("error"):
                            raise ProviderError("server", str(obj["error"])[:300])
                        usage = obj.get("usage")
                        ch = (obj.get("choices") or [{}])[0]
                        delta = (ch.get("delta") or {}).get("content") or ""
                        if delta or ch.get("finish_reason") or usage:
                            yield ChatChunk(delta, ch.get("finish_reason"), usage)
                    return
            except httpx.ConnectError:
                raise ProviderError("unreachable", f"Cannot connect to {self.base}. Is the server running?")
            except httpx.TimeoutException:
                raise ProviderError("timeout", f"Timed out talking to {self.base}.")
            except (httpx.RemoteProtocolError, httpx.ReadError):
                raise ProviderError("unreachable", "Connection dropped mid-response.")

    async def embed(self, texts, model):
        r = await self._request("POST", f"{self.base}/embeddings", json={"model": model, "input": texts})
        return [d["embedding"] for d in r.json()["data"]]


class OllamaAdapter(Adapter):
    kind = "ollama"

    async def list_models(self) -> list[ModelInfo]:
        r = await self._request("GET", f"{self.base}/api/tags")
        return [ModelInfo(m["name"], self.cfg.id, None, self.declared_caps(m["name"]),
                          "declared" if self.declared_caps(m["name"]) else "unknown", m.get("size"))
                for m in r.json().get("models", [])]

    async def describe(self, model: str) -> ModelInfo:
        r = await self._request("POST", f"{self.base}/api/show", json={"model": model})
        j = r.json()
        caps = list(j.get("capabilities") or [])
        ctx = next((v for k, v in (j.get("model_info") or {}).items() if k.endswith(".context_length")), None)
        caps = sorted(set(caps) | set(self.declared_caps(model)))
        return ModelInfo(model, self.cfg.id, ctx, caps, "reported" if j.get("capabilities") else "unknown")

    @staticmethod
    def _convert(messages):
        out = []
        for m in messages:
            c = m["content"]
            if isinstance(c, list):
                text = _flat(c)
                imgs = [p["image_url"]["url"].split(",", 1)[-1] for p in c if p.get("type") == "image_url"]
                msg = {"role": m["role"], "content": text}
                if imgs:
                    msg["images"] = imgs
                out.append(msg)
            else:
                out.append({"role": m["role"], "content": c})
        return out

    async def stream_chat(self, messages, model, temperature=0.2, max_tokens=None):
        opts = {"temperature": temperature}
        if max_tokens:
            opts["num_predict"] = max_tokens
        body = {"model": model, "messages": self._convert(messages), "stream": True, "options": opts}
        try:
            async with self.client.stream("POST", f"{self.base}/api/chat", headers=self.headers(), json=body) as r:
                if r.status_code >= 400:
                    await r.aread()
                    raise _normalize_http(r)
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if obj.get("error"):
                        raise ProviderError("server", str(obj["error"])[:300])
                    usage = None
                    if obj.get("done"):
                        usage = {"prompt_tokens": obj.get("prompt_eval_count"), "completion_tokens": obj.get("eval_count")}
                    yield ChatChunk((obj.get("message") or {}).get("content", ""), "stop" if obj.get("done") else None, usage)
        except httpx.ConnectError:
            raise ProviderError("unreachable", f"Cannot connect to {self.base}. Is Ollama running?")
        except httpx.TimeoutException:
            raise ProviderError("timeout", f"Timed out talking to {self.base}.")

    async def embed(self, texts, model):
        r = await self._request("POST", f"{self.base}/api/embed", json={"model": model, "input": texts})
        return r.json()["embeddings"]


ADAPTERS = {"ollama": OllamaAdapter, "openai_compat": OpenAICompatAdapter}


# ------------------------------------------------------------------ gateway
@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    token_source: str
    cost_usd: float | None


class Gateway:
    def __init__(self, store: SettingsStore, secrets: SecretStore, policy: PolicyEngine, ledger: UsageLedger,
                 audit: AuditLog, transport: httpx.AsyncBaseTransport | None = None):
        self.store, self.secrets, self.policy, self.ledger, self.audit = store, secrets, policy, ledger, audit
        self.transport = transport
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._model_cache: dict[str, tuple[float, list[ModelInfo]]] = {}

    def provider(self, pid: str) -> ProviderConfig:
        for p in self.store.settings.providers:
            if p.id == pid:
                return p
        raise ProviderError("not_found", f"Unknown provider '{pid}'")

    def adapter(self, pid: str) -> Adapter:
        cfg = self.provider(pid)
        key = f"{pid}:{cfg.base_url}:{cfg.timeout_s}"
        if key not in self._clients:
            self._clients[key] = httpx.AsyncClient(
                transport=self.transport, timeout=httpx.Timeout(cfg.timeout_s, connect=10.0), follow_redirects=False)
        return ADAPTERS[cfg.kind](cfg, self.secrets.get(pid), self._clients[key])

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.aclose()

    # -- discovery / health (these also leave the machine for remote providers, so they are policy-checked)
    async def list_models(self, pid: str, refresh: bool = False) -> list[ModelInfo]:
        cfg = self.provider(pid)
        self._guard(cfg, "discovery")
        hit = self._model_cache.get(pid)
        if hit and not refresh and time.time() - hit[0] < 60:
            return hit[1]
        models = await self.adapter(pid).list_models()
        self._model_cache[pid] = (time.time(), models)
        return models

    async def health(self, pid: str) -> dict:
        cfg = self.provider(pid)
        try:
            self._guard(cfg, "health check")
        except PolicyError as e:
            return {"ok": False, "blocked": True, "error": {"kind": "policy", "message": str(e)}}
        return await self.adapter(pid).health()

    def _guard(self, cfg: ProviderConfig, op: str, model: str | None = None, task_id: str | None = None):
        try:
            self.policy.check(cfg, op, model, task_id)
        except PolicyError as e:
            self.audit.write("policy_block", provider=cfg.id, op=op, reason=str(e))
            raise

    async def model_caps(self, pid: str, model: str) -> list[str]:
        cfg = self.provider(pid)
        ad = self.adapter(pid)
        caps = set(ad.declared_caps(model))
        if isinstance(ad, OllamaAdapter):
            try:
                self._guard(cfg, "discovery")
                caps |= set((await ad.describe(model)).capabilities)
            except (ProviderError, PolicyError):
                pass
        return sorted(caps)

    async def chat(self, messages: list[dict], provider_id: str, model: str, *, task_id: str | None = None,
                   on_delta: Callable[[str], Awaitable[None] | None] | None = None, temperature: float = 0.2,
                   max_tokens: int | None = None, max_retries: int = 2) -> ChatResult:
        cfg = self.provider(provider_id)
        self._guard(cfg, "inference", model, task_id)
        remote = not self.policy.is_local(cfg)
        attempt = 0
        while True:
            parts: list[str] = []
            usage: dict | None = None
            try:
                ad = self.adapter(provider_id)
                self.audit.write("model_call", provider=provider_id, model=model, remote=remote, task=task_id,
                                 messages=len(messages))
                async for ch in ad.stream_chat(messages, model, temperature, max_tokens):
                    if ch.delta:
                        parts.append(ch.delta)
                        if on_delta:
                            r = on_delta(ch.delta)
                            if asyncio.iscoroutine(r):
                                await r
                    if ch.usage:
                        usage = ch.usage
                break
            except ProviderError as e:
                if e.kind in ("rate_limit", "server") and attempt < max_retries and not parts:
                    attempt += 1
                    await asyncio.sleep(min(e.retry_after if e.retry_after is not None else 2 ** attempt, 10))
                    continue
                raise
        text = "".join(parts)
        reported = usage and usage.get("prompt_tokens") is not None and usage.get("completion_tokens") is not None
        pt = int(usage["prompt_tokens"]) if reported else sum(est_tokens(_flat(m["content"])) for m in messages)
        ct = int(usage["completion_tokens"]) if reported else est_tokens(text)
        cost = None
        if remote and model in cfg.prices:
            pin, pout = cfg.prices[model][0], cfg.prices[model][1]
            cost = pt / 1e6 * pin + ct / 1e6 * pout
        self.ledger.record(provider=provider_id, model=model, op="inference", prompt_tokens=pt, completion_tokens=ct,
                           token_source="reported" if reported else "estimated", cost_usd=cost,
                           cost_source="user_configured_price" if cost is not None else "unknown",
                           task_id=task_id, remote=remote)
        return ChatResult(text, provider_id, model, pt, ct, "reported" if reported else "estimated", cost)

    async def embed(self, texts: list[str], provider_id: str, model: str, task_id: str | None = None) -> list[list[float]]:
        cfg = self.provider(provider_id)
        self._guard(cfg, "embedding", model, task_id)
        vecs = await self.adapter(provider_id).embed(texts, model)
        self.ledger.record(provider=provider_id, model=model, op="embedding", prompt_tokens=sum(est_tokens(t) for t in texts),
                           completion_tokens=0, token_source="estimated", task_id=task_id,
                           remote=not self.policy.is_local(cfg))
        return vecs


# ------------------------------------------------------------------ connection probe
async def probe_endpoint(url: str, key: str | None, kind_hint: str = "auto", transport=None) -> dict:
    """Try to reach an endpoint and list its models. Tries OpenAI-style (with and without /v1), then Ollama native."""
    base = normalize_base_url(url)
    if not base:
        return {"ok": False, "error": {"kind": "bad_request", "message": "Enter a URL"}}
    cands: list[tuple[str, str]] = []
    if kind_hint in ("auto", "openai_compat"):
        cands.append(("openai_compat", base))
        if not base.endswith("/v1"):
            cands.append(("openai_compat", base + "/v1"))
    if kind_hint in ("auto", "ollama"):
        cands.append(("ollama", base[:-3] if base.endswith("/v1") else base))
    last: dict = {"kind": "unreachable", "message": f"Could not connect to {base}"}
    async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=False) as client:
        for kind, b in cands:
            cfg = ProviderConfig(id="probe", name="probe", kind=kind, base_url=b)
            try:
                models = await ADAPTERS[kind](cfg, key, client).list_models()
                return {"ok": True, "kind": kind, "base_url": b, "models": [m.id for m in models],
                        "models_detail": [m.__dict__ for m in models], "remote": not host_is_local(b)}
            except ProviderError as e:
                if e.kind == "auth":
                    return {"ok": False, "error": e.as_dict(), "base_url": b,
                            "hint": "The server answered but rejected the key. Re-copy it (no spaces) or create a new key in the service's dashboard."}
                last = e.as_dict()
    hint = {"unreachable": "Nothing is listening there. Start the service (is it running? is the port right?) or check the URL.",
            "not_found": "The server is up but doesn't look OpenAI-compatible at that path. The base URL usually ends in /v1.",
            "timeout": "The server did not answer in time."}.get(last["kind"], "")
    return {"ok": False, "error": last, "hint": hint, "base_url": base}


# ------------------------------------------------------------------ routing
class Router:
    RANK = {"local": 0, "free_tier": 1, "metered": 2, "unknown": 3}

    def __init__(self, gw: Gateway):
        self.gw = gw

    async def choose(self, *, need_vision: bool = False, min_context: int | None = None,
                     pinned: tuple[str, str] | None = None) -> dict:
        s = self.gw.store.settings
        rejected: list[dict] = []
        if pinned:
            cfg = self.gw.provider(pinned[0])
            try:
                self.gw.policy.check(cfg, "inference", pinned[1])
                return {"provider": pinned[0], "model": pinned[1], "reasons": ["manually selected"], "rejected": []}
            except PolicyError as e:
                rejected.append({"provider": pinned[0], "why": str(e)})
        cands = []
        for p in s.providers:
            try:
                self.gw.policy.check(p, "inference", p.default_model)
            except PolicyError as e:
                rejected.append({"provider": p.id, "why": str(e)})
                continue
            h = await self.gw.health(p.id)
            if not h.get("ok"):
                rejected.append({"provider": p.id, "why": "unhealthy: " + (h.get("error") or {}).get("message", "?")})
                continue
            try:
                models = await self.gw.list_models(p.id)
            except (ProviderError, PolicyError):
                continue
            for m in models:
                caps = set(m.capabilities)
                if p.default_model and m.id != p.default_model and len(models) > 1:
                    continue
                if need_vision and "vision" not in caps:
                    rejected.append({"provider": p.id, "model": m.id, "why": "no vision capability known"})
                    continue
                if min_context and m.context and m.context < min_context:
                    rejected.append({"provider": p.id, "model": m.id, "why": "context too small"})
                    continue
                cls = "local" if self.gw.policy.is_local(p) else p.cost_class
                cands.append((self.RANK[cls], p.id, m.id, cls))
        if not cands:
            return {"provider": None, "model": None, "reasons": [], "rejected": rejected}
        cands.sort()
        _, pid, mid, cls = cands[0]
        return {"provider": pid, "model": mid, "reasons": [f"best available ({cls}); policy and health checks passed"], "rejected": rejected}
