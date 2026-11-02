import json

import httpx
import pytest

from hearthforge.config import ProviderConfig
from hearthforge.gateway import PolicyError, ProviderError, host_is_local

MSG = [{"role": "user", "content": "hi"}]


def add_remote(core, **kw):
    p = ProviderConfig(id="remote", name="Remote", kind="openai_compat", base_url="https://api.example.com/v1", **kw)
    core.store.update(lambda s: s.providers.append(p))
    return p


@pytest.mark.parametrize("url,local", [
    ("http://127.0.0.1:11434", True), ("http://localhost:8080/v1", True), ("http://[::1]:8000", True),
    ("http://127.0.0.1.evil.com/v1", False), ("http://192.168.1.5:11434", False), ("https://api.groq.com/openai/v1", False),
    ("http://localhost.evil.com", False), ("http://0.0.0.0:8000", False),
])
def test_locality_is_derived_from_host(url, local):
    assert host_is_local(url) is local


async def test_streaming_chat_and_reported_usage(core, mock, ws):
    mock.replies = ['{"final":"ok"}']
    seen = []
    r = await core.gateway.chat(MSG, "llamacpp", "mock-model", on_delta=seen.append)
    assert r.text == '{"final":"ok"}' and "".join(seen) == r.text
    assert (r.prompt_tokens, r.completion_tokens, r.token_source) == (11, 7, "reported")
    assert core.ledger.summary()["rows"][0]["src"] == "reported"


async def test_usage_is_labelled_estimated_when_not_reported(core, mock):
    from tests.conftest import sse
    mock.replies = []
    def h(req):
        return httpx.Response(200, content=sse("hello world", usage=False))
    core.gateway.transport = httpx.MockTransport(h)
    r = await core.gateway.chat(MSG, "llamacpp", "m")
    assert r.token_source == "estimated"


async def test_rate_limit_retries_then_succeeds(core, mock):
    mock.status_sequence = [429, 200]
    mock.replies = ["done"]
    r = await core.gateway.chat(MSG, "llamacpp", "mock-model")
    assert r.text == "done"


async def test_rate_limit_exhausted_is_normalized(core, mock):
    mock.status_sequence = [429, 429, 429]
    with pytest.raises(ProviderError) as e:
        await core.gateway.chat(MSG, "llamacpp", "mock-model")
    assert e.value.kind == "rate_limit"


@pytest.mark.parametrize("code,kind", [(401, "auth"), (400, "bad_request"), (404, "not_found")])
async def test_error_normalization(core, mock, code, kind):
    mock.status_sequence = [code]
    with pytest.raises(ProviderError) as e:
        await core.gateway.chat(MSG, "llamacpp", "mock-model")
    assert e.value.kind == kind


async def test_unreachable_server(core):
    def boom(req):
        raise httpx.ConnectError("refused")
    core.gateway.transport = httpx.MockTransport(boom)
    with pytest.raises(ProviderError) as e:
        await core.gateway.chat(MSG, "llamacpp", "m")
    assert e.value.kind == "unreachable"
    assert (await core.gateway.health("llamacpp"))["ok"] is False


async def test_local_only_blocks_all_remote_operations(core, mock):
    add_remote(core, cost_class="free_tier")
    for op in (core.gateway.chat(MSG, "remote", "m"), core.gateway.embed(["x"], "remote", "e"),
               core.gateway.list_models("remote")):
        with pytest.raises(PolicyError):
            await op
    h = await core.gateway.health("remote")
    assert h["blocked"] and not mock.requests  # nothing was sent to the network at all


async def test_free_only_allows_only_declared_free_tier(core, mock):
    core.store.update(lambda s: setattr(s.policy, "cloud_mode", "free_only"))
    add_remote(core, cost_class="metered")
    with pytest.raises(PolicyError):
        await core.gateway.chat(MSG, "remote", "m")
    core.store.update(lambda s: setattr(s.providers[-1], "cost_class", "unknown"))
    with pytest.raises(PolicyError):
        await core.gateway.chat(MSG, "remote", "m")
    core.store.update(lambda s: setattr(s.providers[-1], "cost_class", "free_tier"))
    core.gateway.transport = httpx.MockTransport(mock.handler)
    mock.replies = ["ok"]
    assert (await core.gateway.chat(MSG, "remote", "m")).text == "ok"


async def test_free_only_also_blocks_remote_embeddings_and_still_allows_local(core, mock):
    core.store.update(lambda s: setattr(s.policy, "cloud_mode", "free_only"))
    add_remote(core, cost_class="metered")
    with pytest.raises(PolicyError):
        await core.gateway.embed(["x"], "remote", "e")
    vecs = await core.gateway.embed(["x"], "llamacpp", "e")  # local is always allowed
    assert vecs == [[0.1, 0.2]]


async def test_budget_requires_known_price_and_is_enforced(core, mock):
    core.store.update(lambda s: (setattr(s.policy, "cloud_mode", "budgeted"), setattr(s.policy, "monthly_budget_usd", 0.0001)))
    add_remote(core, cost_class="metered")
    with pytest.raises(PolicyError, match="no price"):
        await core.gateway.chat(MSG, "remote", "paid")
    core.store.update(lambda s: s.providers[-1].prices.__setitem__("paid", [1000.0, 1000.0]))
    mock.replies = ["first"]
    r = await core.gateway.chat(MSG, "remote", "paid")
    assert r.cost_usd and r.cost_usd > 0.0001
    with pytest.raises(PolicyError, match="monthly"):
        await core.gateway.chat(MSG, "remote", "paid")


async def test_api_key_is_sent_but_never_logged(core, mock):
    add_remote(core, cost_class="free_tier")
    core.store.update(lambda s: setattr(s.policy, "cloud_mode", "free_only"))
    core.secrets.set("remote", "sk-supersecretvalue1234567890")
    mock.replies = ["ok"]
    await core.gateway.chat(MSG, "remote", "m")
    assert mock.requests[-1].headers["authorization"] == "Bearer sk-supersecretvalue1234567890"
    core.audit.write("leak_test", note="key was sk-supersecretvalue1234567890")
    log = core.audit.path.read_text()
    assert "supersecretvalue" not in log
    assert "supersecretvalue" not in (core.home / "settings.json").read_text()


async def test_router_prefers_local_and_explains_rejections(core, mock):
    add_remote(core, cost_class="free_tier")
    d = await core.router.choose()
    assert d["provider"] == "llamacpp"
    assert any(r["provider"] == "remote" for r in d["rejected"])  # blocked by local-only policy
    d2 = await core.router.choose(need_vision=True)
    assert d2["provider"] is None  # no model known to support vision


async def test_router_manual_pin_still_obeys_policy(core):
    add_remote(core, cost_class="free_tier")
    d = await core.router.choose(pinned=("remote", "m"))
    assert d["provider"] != "remote"


async def test_ollama_adapter_stream_and_discovery(core):
    def h(req):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen:7b", "size": 4_000_000_000}]})
        if req.url.path == "/api/chat":
            lines = [{"message": {"content": "he"}, "done": False}, {"message": {"content": "llo"}, "done": False},
                     {"message": {"content": ""}, "done": True, "prompt_eval_count": 5, "eval_count": 2}]
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
        if req.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "vision"], "model_info": {"llama.context_length": 8192}})
        return httpx.Response(404)
    core.gateway.transport = httpx.MockTransport(h)
    ms = await core.gateway.list_models("ollama")
    assert ms[0].id == "qwen:7b"
    r = await core.gateway.chat(MSG, "ollama", "qwen:7b")
    assert r.text == "hello" and r.token_source == "reported"
    assert "vision" in await core.gateway.model_caps("ollama", "qwen:7b")
