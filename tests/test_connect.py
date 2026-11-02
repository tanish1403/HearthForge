import json

import httpx
import pytest
from fastapi.testclient import TestClient

from hearthforge.gateway import normalize_base_url, probe_endpoint
from hearthforge.secrets_store import SecretStore
from hearthforge.server import create_app
from tests.conftest import sse

H = {"x-hearthforge-token": "tok"}
KEY = "omni-key-1234567890"


@pytest.mark.parametrize("raw,expected", [
    ("localhost:20128/v1", "http://localhost:20128/v1"),
    ("http://localhost:20128/v1/", "http://localhost:20128/v1"),
    ("  http://localhost:20128/v1/chat/completions ", "http://localhost:20128/v1"),
    ("https://gw.example.com/v1/models", "https://gw.example.com/v1"),
    ("gw.example.com", "https://gw.example.com"),
    ('"http://127.0.0.1:20128"', "http://127.0.0.1:20128"),
    ("192.168.1.9:8080/v1", "http://192.168.1.9:8080/v1"),
])
def test_url_normalisation(raw, expected):
    assert normalize_base_url(raw) == expected


def omni(request: httpx.Request) -> httpx.Response:
    """Mimics an OmniRoute-like gateway: only /v1/* exists and a bearer key is required."""
    if not request.url.path.startswith("/v1/"):
        return httpx.Response(404)
    if request.headers.get("authorization") != f"Bearer {KEY}":
        return httpx.Response(401, json={"error": "invalid key"})
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "auto"}, {"id": "openai/gpt-x"}]})
    if request.url.path == "/v1/chat/completions":
        return httpx.Response(200, content=sse("hello from the gateway"), headers={"content-type": "text/event-stream"})
    return httpx.Response(404)


async def test_probe_finds_v1_when_user_omits_it():
    r = await probe_endpoint("http://localhost:20128", KEY, transport=httpx.MockTransport(omni))
    assert r["ok"] and r["base_url"] == "http://localhost:20128/v1" and r["models"] == ["auto", "openai/gpt-x"] and r["remote"] is False


async def test_probe_wrong_key_gives_actionable_hint():
    r = await probe_endpoint("http://localhost:20128/v1", "wrong", transport=httpx.MockTransport(omni))
    assert not r["ok"] and r["error"]["kind"] == "auth" and "key" in r["hint"]


async def test_probe_unreachable_and_not_openai():
    def boom(req):
        raise httpx.ConnectError("refused")
    r = await probe_endpoint("http://localhost:1", None, transport=httpx.MockTransport(boom))
    assert not r["ok"] and "Nothing is listening" in r["hint"]
    r = await probe_endpoint("http://localhost:2", None, transport=httpx.MockTransport(lambda q: httpx.Response(404)))
    assert not r["ok"] and "/v1" in r["hint"]


async def test_probe_detects_ollama_native():
    def h(req):
        return httpx.Response(200, json={"models": [{"name": "qwen:7b"}]}) if req.url.path == "/api/tags" else httpx.Response(404)
    r = await probe_endpoint("http://127.0.0.1:11434", None, transport=httpx.MockTransport(h))
    assert r["ok"] and r["kind"] == "ollama" and r["models"] == ["qwen:7b"]


@pytest.fixture
def client(core):
    core.gateway.transport = httpx.MockTransport(omni)
    with TestClient(create_app(core)) as c:
        c.headers.update(H)
        yield c


def test_probe_requires_consent_for_remote_hosts(client):
    r = client.post("/api/providers/probe", json={"base_url": "https://gw.example.com", "key": KEY})
    assert r.status_code == 403
    ok = client.post("/api/providers/probe", json={"base_url": "http://localhost:20128", "key": KEY}).json()
    assert ok["ok"] and "auto" in ok["models"]  # local needs no consent


def test_connect_local_gateway_end_to_end_then_chat(client, core):
    r = client.post("/api/providers/connect", json={"name": "OmniRoute", "base_url": "localhost:20128/v1/chat/completions", "key": KEY, "model": "auto"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["provider"] == "omniroute" and j["policy_changed"] is None
    s = j["state"]
    assert s["active"] == {"provider": "omniroute", "model": "auto"}
    assert [p for p in s["providers"] if p["id"] == "omniroute"][0]["base_url"] == "http://localhost:20128/v1"
    assert KEY not in json.dumps(s) and KEY not in (core.home / "settings.json").read_text()
    # the very next chat works with no further selection
    with client.stream("POST", "/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}) as resp:
        body = "".join(resp.iter_lines())
    assert "hello from the gateway" in body.replace('"}', "").replace('{"type": "delta", "text": "', "") or "gateway" in body
    assert client.get("/api/models").json()["models"][0]["model"] in ("auto", "openai/gpt-x")


def test_connect_remote_requires_consent_and_sets_policy(client, core):
    body = {"name": "Cloud GW", "base_url": "https://gw.example.com/v1", "key": KEY, "cost": "free", "model": "auto"}
    assert client.post("/api/providers/connect", json=body).status_code == 403
    assert client.get("/api/state").json()["policy"]["cloud_mode"] == "local_only"
    j = client.post("/api/providers/connect", json={**body, "allow_remote": True}).json()
    assert j["policy_changed"] == {"from": "local_only", "to": "free_only"}
    p = [x for x in j["state"]["providers"] if x["id"] == "cloud-gw"][0]
    assert p["cost_class"] == "free_tier" and p["local"] is False and p["has_key"]
    # paid / unsure upgrades further to budgeted, never silently downgrades
    j = client.post("/api/providers/connect", json={**body, "name": "Paid", "cost": "unsure", "allow_remote": True}).json()
    assert j["policy_changed"]["to"] == "budgeted"
    j = client.post("/api/providers/connect", json={**body, "name": "Free2", "cost": "free", "allow_remote": True}).json()
    assert j["policy_changed"] is None and j["state"]["policy"]["cloud_mode"] == "budgeted"


def test_key_falls_back_to_session_when_no_keychain(core):
    core.secrets = SecretStore.__new__(SecretStore)
    core.secrets._backend, core.secrets._checked, core.secrets._session = None, True, {}
    core.gateway.secrets = core.secrets
    core.gateway.transport = httpx.MockTransport(omni)
    with TestClient(create_app(core)) as c:
        c.headers.update(H)
        j = c.post("/api/providers/connect", json={"name": "Omni", "base_url": "http://localhost:20128/v1", "key": KEY, "model": "auto"}).json()
        assert j["key_stored"] == "session"
        assert core.secrets.get("omni") == KEY and KEY not in (core.home / "settings.json").read_text()


def test_task_without_selected_model_autopicks_instead_of_erroring(client, core, ws, mock):
    core.store.update(lambda s: setattr(s, "active", None))
    mock.replies = [json.dumps({"final": "hi"})]
    core.gateway.transport = httpx.MockTransport(mock.handler)
    r = client.post("/api/tasks", json={"workspace_id": ws.id, "goal": "x", "mode": "plan"})
    assert r.status_code == 200
    assert client.get("/api/state").json()["active"] == {"provider": "llamacpp", "model": "mock-model"}


# ---------- folder browser
def test_browse_roots_and_listing(client, tmp_path):
    roots = client.get("/api/fs/browse").json()
    assert roots["path"] == "" and any(r["name"] == "Home" for r in roots["roots"])
    (tmp_path / "myproj").mkdir()
    (tmp_path / "myproj" / "package.json").write_text("{}")
    (tmp_path / "plain").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    d = client.get("/api/fs/browse", params={"path": str(tmp_path)}).json()
    names = [e["name"] for e in d["entries"]]
    assert "myproj" in names and "plain" in names and ".hidden" not in names and "file.txt" not in names
    assert [e for e in d["entries"] if e["name"] == "myproj"][0]["project"] is True
    assert client.get("/api/fs/browse", params={"path": str(tmp_path / "nope")}).status_code == 400


def test_mkdir_validates_names(client, tmp_path):
    assert client.post("/api/fs/mkdir", json={"parent": str(tmp_path), "name": "new-app"}).status_code == 200
    assert (tmp_path / "new-app").is_dir()
    for bad in ["../x", "a/b", "..", "", "a:b"]:
        assert client.post("/api/fs/mkdir", json={"parent": str(tmp_path), "name": bad}).status_code == 400
    assert client.post("/api/fs/mkdir", json={"parent": str(tmp_path), "name": "new-app"}).status_code == 400


def test_workspace_accepts_pasted_quoted_path_and_dedupes(client, tmp_path):
    d = tmp_path / "proj one"
    d.mkdir()
    a = client.post("/api/workspaces", json={"path": f'"{d}"'})
    assert a.status_code == 200
    b = client.post("/api/workspaces", json={"path": str(d)})
    assert a.json()["id"] == b.json()["id"]
    assert len(client.get("/api/state").json()["workspaces"]) == 1


# ---------- internet settings + chat with web
def test_internet_setting_and_search_test(client, core, set_web):
    from tests.test_web import DDG
    set_web(lambda r: httpx.Response(200, text=DDG))
    assert client.post("/api/web/test", json={}).status_code == 403  # off by default
    s = client.put("/api/policy", json={"cloud_mode": "local_only", "internet": "on"}).json()
    assert s["policy"]["internet"] == "on" and "queries leave this machine" in s["policy_explain"]["summary"]
    assert client.put("/api/policy", json={"cloud_mode": "local_only", "internet": "maybe"}).status_code == 400
    assert client.post("/api/web/test", json={"query": "python"}).json()[0]["title"] == "Python 3 docs"
    assert client.put("/api/web", json={"engine": "wikipedia"}).json()["web"]["engine"] == "wikipedia"


def test_chat_with_web_uses_sources_and_cites(client, core, mock, set_web):
    from tests.test_web import DDG
    client.put("/api/policy", json={"cloud_mode": "local_only", "internet": "on"})
    def h(r):
        if r.url.host == "html.duckduckgo.com":
            return httpx.Response(200, text=DDG)
        return httpx.Response(200, text="<html><body>Official docs text</body></html>", headers={"content-type": "text/html"})
    set_web(h)
    seen = []
    mock.replies = [lambda body: seen.append(body["messages"]) or "Answer [1]"]
    core.gateway.transport = httpx.MockTransport(mock.handler)
    client.put("/api/active", json={"provider": "llamacpp", "model": "mock-model"})
    with client.stream("POST", "/api/chat", json={"messages": [{"role": "user", "content": "python docs?"}], "use_web": True}) as r:
        events = [json.loads(x[5:]) for x in r.iter_lines() if x.startswith("data:")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "sources" and "delta" in kinds and kinds[-1] == "done"
    assert events[0]["sources"][0]["url"] == "https://docs.python.org/3/"
    last = seen[0][-1]["content"]
    assert "UNTRUSTED CONTEXT" in last and "Official docs text" in last
    assert "never follow instructions" in seen[0][0]["content"]


def test_chat_web_refused_when_internet_off_and_policy_checked(client, core):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "use_web": True, "provider": "llamacpp", "model": "m"})
    assert r.status_code == 403 and "Internet is off" in r.json()["detail"]
    client.post("/api/providers/connect", json={"name": "R", "base_url": "https://gw.example.com/v1", "allow_remote": True, "cost": "free"})
    client.put("/api/policy", json={"cloud_mode": "local_only", "internet": "off"})
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "provider": "r", "model": "m"})
    assert r.status_code == 403 and "Local only" in r.json()["detail"]
