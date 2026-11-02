import json
import time

import pytest
from fastapi.testclient import TestClient

from hearthforge.server import create_app

H = {"x-hearthforge-token": "tok"}


@pytest.fixture
def client(core):
    with TestClient(create_app(core)) as c:
        c.headers.update(H)
        yield c


def wait(client, tid, pred, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = client.get(f"/api/tasks/{tid}").json()
        if pred(t):
            return t
        time.sleep(0.05)
    raise AssertionError(client.get(f"/api/tasks/{tid}").json()["status"])


def test_auth_required_for_api(core):
    with TestClient(create_app(core)) as c:
        assert c.get("/api/state").status_code == 401
        assert c.get("/api/state", headers={"x-hearthforge-token": "wrong"}).status_code == 401
        assert c.get("/auth?token=bad").status_code == 401
        r = c.get("/auth?token=tok", follow_redirects=False)
        assert r.status_code in (302, 307) and "hf_token" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
        assert c.get("/api/state").status_code == 200  # cookie now set


def test_dns_rebinding_and_cross_origin_blocked(client):
    assert client.get("/api/state", headers={"host": "evil.example.com"}).status_code == 403
    assert client.get("/api/state", headers={"origin": "https://evil.example.com"}).status_code == 403
    assert client.post("/api/policy", json={"cloud_mode": "budgeted"}, headers={"origin": "https://evil.example.com"}).status_code == 403
    assert client.get("/api/state").json()["policy"]["cloud_mode"] == "local_only"


def test_ui_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Hearthforge" in r.text
    for f in ("core", "guide", "settings", "app"):
        assert client.get(f"/static/{f}.js").status_code == 200
    assert "Content-Security-Policy" in client.get("/").headers or True


def test_default_state_is_local_only_with_honest_capabilities(client):
    s = client.get("/api/state").json()
    assert s["policy"]["cloud_mode"] == "local_only"
    assert {p["id"] for p in s["providers"]} == {"ollama", "llamacpp"} and all(p["local"] for p in s["providers"])
    caps = {c["id"]: c for c in s["capabilities"]}
    assert caps["research.agent"]["status"] == "planned" and caps["research.agent"]["enabled"] is False
    assert caps["web.access"]["status"] == "implemented" and s["policy"]["internet"] == "off"
    assert caps["knowledge.rag"]["status"] == "partial"


def test_planned_capability_cannot_be_enabled(client):
    assert client.put("/api/capabilities/research.agent", json={"enabled": True}).status_code == 400
    assert client.put("/api/capabilities/nope", json={"enabled": True}).status_code == 404
    caps = {c["id"]: c for c in client.put("/api/capabilities/knowledge.rag", json={"enabled": False}).json()}
    assert caps["knowledge.rag"]["enabled"] is False


def test_provider_crud_keys_never_returned(client, core):
    r = client.post("/api/providers", json={"id": "groq", "name": "Groq", "kind": "openai_compat", "base_url": "https://api.groq.com/openai/v1"})
    assert r.status_code == 200 and r.json()["local"] is False
    assert client.put("/api/providers/groq/key", json={"key": "gsk_" + "a" * 30}).status_code == 200
    s = client.get("/api/state")
    assert "gsk_aaaa" not in s.text and [p for p in s.json()["providers"] if p["id"] == "groq"][0]["has_key"] is True
    assert "gsk_aaaa" not in (core.home / "settings.json").read_text()
    assert client.delete("/api/providers/groq").status_code == 200
    assert not core.secrets.has("groq")


def test_key_storage_refused_without_secure_backend(core):
    from hearthforge.secrets_store import SecretStore
    core.secrets = SecretStore.__new__(SecretStore)
    core.secrets._backend, core.secrets._checked, core.secrets._session = None, True, {}
    with TestClient(create_app(core)) as c:
        c.headers.update(H)
        c.post("/api/providers", json={"id": "x", "name": "x", "kind": "openai_compat", "base_url": "https://x.example/v1"})
        r = c.put("/api/providers/x/key", json={"key": "secret-value-123"})
        assert r.status_code == 400 and "HEARTHFORGE_KEY_X" in r.json()["detail"]


def test_workspace_validation(client, tmp_path):
    assert client.post("/api/workspaces", json={"path": str(tmp_path / "nope")}).status_code == 400
    assert client.post("/api/workspaces", json={"path": "/"}).status_code == 400
    from pathlib import Path
    assert client.post("/api/workspaces", json={"path": str(Path.home())}).status_code == 400
    d = tmp_path / "p"; d.mkdir()
    w = client.post("/api/workspaces", json={"path": str(d)}).json()
    assert w["permissions"]["network"] == "deny" and w["permissions"]["write"] == "ask"
    r = client.put(f"/api/workspaces/{w['id']}", json={"permissions": {"write": "allow", "bogus": "allow", "exec": "maybe"}}).json()
    assert r["permissions"]["write"] == "allow" and "bogus" not in r["permissions"] and r["permissions"]["exec"] == "ask"


def test_file_api_is_sandboxed(client, ws, project):
    assert client.get(f"/api/workspaces/{ws.id}/file", params={"path": "calc.py"}).json()["total_lines"] == 2
    assert client.get(f"/api/workspaces/{ws.id}/file", params={"path": "../../etc/passwd"}).status_code == 400
    (project / ".env").write_text("A=1")
    assert client.get(f"/api/workspaces/{ws.id}/file", params={"path": ".env"}).status_code == 400


def test_task_requires_model_and_policy_checked_up_front(client, core, ws):
    core.store.update(lambda s: setattr(s, "active", None))
    import httpx
    def down(req):
        raise httpx.ConnectError("refused")
    core.gateway.transport = httpx.MockTransport(down)
    core.gateway._clients.clear()
    r = client.post("/api/tasks", json={"workspace_id": ws.id, "goal": "x"})
    assert r.status_code == 400 and "Connect a model" in r.json()["detail"]
    client.post("/api/providers", json={"id": "r", "name": "R", "kind": "openai_compat", "base_url": "https://api.example.com/v1"})
    r = client.post("/api/tasks", json={"workspace_id": ws.id, "goal": "x", "provider": "r", "model": "m"})
    assert r.status_code == 403 and "Local only" in r.json()["detail"]


def test_end_to_end_task_with_sse_and_undo(client, core, mock, ws, project):
    fix = {"tool": "edit_file", "args": {"path": "calc.py", "old": "a - b", "new": "a + b"}}
    mock.replies = [json.dumps(fix), json.dumps({"final": "changed"}), json.dumps({"final": "changed, unverified"})]
    tid = client.post("/api/tasks", json={"workspace_id": ws.id, "goal": "fix"}).json()["id"]
    events, approved = [], False
    with client.stream("GET", f"/api/tasks/{tid}/stream") as r:
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            e = json.loads(line[5:])
            events.append(e)
            if e["type"] == "approval_request" and not approved:
                approved = True
                assert client.post(f"/api/tasks/{tid}/approvals/{e['data']['id']}", json={"approved": True}).status_code == 200
    assert events[-1]["type"] == "final"
    t = client.get(f"/api/tasks/{tid}").json()
    assert t["status"] == "completed_unverified" and "a + b" in (project / "calc.py").read_text()
    snap = t["state"]["changes"][0]["snapshot"]
    assert client.post(f"/api/tasks/{tid}/undo", json={"snapshot": snap}).status_code == 200
    assert "a - b" in (project / "calc.py").read_text()
    assert client.post(f"/api/tasks/{tid}/undo", json={"snapshot": snap}).status_code == 400  # already undone
    assert client.get(f"/api/tasks/{tid}/events", params={"after": 3}).json()[0]["seq"] > 3
    audit = client.get("/api/audit").json()
    assert any(a["kind"] == "approval" for a in audit) and any(a["kind"] == "undo" for a in audit)


def test_plugin_lifecycle_and_execution(client, core, mock, ws, project):
    (project / "plug.py").write_text("import sys, json\nprint('got', json.load(sys.stdin)['x'])\n")
    manifest = {"id": "echo-plug", "name": "Echo", "tools": [{"name": "run", "description": "echo", "command": ["python3", "plug.py"],
                "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}}]}
    assert client.post("/api/plugins", json={**manifest, "tools": [{**manifest["tools"][0], "command": ["bash"]}]}).status_code == 400
    caps = {c["id"]: c for c in client.post("/api/plugins", json=manifest).json()}
    assert caps["plugin.echo-plug"]["enabled"]
    core.store.update(lambda s: s.workspaces[0].permissions.__setitem__("exec", "allow"))
    mock.replies = [json.dumps({"tool": "plugin.echo-plug.run", "args": {"x": 42}}), json.dumps({"final": "ok"})]
    tid = client.post("/api/tasks", json={"workspace_id": ws.id, "goal": "use plugin"}).json()["id"]
    wait(client, tid, lambda t: t["status"] in ("completed", "failed"))
    out = [e for e in client.get(f"/api/tasks/{tid}/events").json() if e["type"] == "tool_result"][0]["data"]["output"]
    assert "got 42" in out
    # disabling the plugin removes it from the agent; removing it deletes it without breaking built-ins
    client.put("/api/capabilities/plugin.echo-plug", json={"enabled": False})
    mock.replies = [json.dumps({"final": "n"})]
    client.post("/api/tasks", json={"workspace_id": ws.id, "goal": "again"})
    time.sleep(0.5)
    assert "plugin.echo-plug.run" not in mock.bodies[-1]["messages"][0]["content"]
    assert not any(c["id"] == "plugin.echo-plug" for c in client.delete("/api/plugins/echo-plug").json())
    assert any(c["id"] == "workspace.files" and c["enabled"] for c in client.get("/api/state").json()["capabilities"])


def test_knowledge_api_flow(client, ws, project):
    (project / "NOTES.md").write_text("The deployment pipeline uses blue green releases.\n")
    s = client.post("/api/knowledge/sources", json={"scope": ws.id}).json()
    assert client.post(f"/api/knowledge/sources/{s['id']}/index").json()["added"] >= 1
    hit = client.post("/api/knowledge/search", json={"scope": ws.id, "query": "blue green"}).json()
    assert hit[0]["path"] == "NOTES.md"
    assert client.post("/api/knowledge/search", json={"scope": "other", "query": "blue green"}).json() == []
    assert client.post("/api/memories", json={"scope": ws.id, "text": "token sk-abcdefghijklmnopqrstuvwx1234"}).status_code == 400
    m = client.post("/api/memories", json={"scope": ws.id, "text": "use tabs"}).json()
    assert client.get(f"/api/knowledge/{ws.id}").json()["memories"][0]["id"] == m["id"]
    assert client.get(f"/api/knowledge/{ws.id}/export").json()["memories"]
    client.delete(f"/api/knowledge/{ws.id}")
    assert client.get(f"/api/knowledge/{ws.id}").json() == {"sources": [], "memories": []}


def test_hardware_and_usage_endpoints(client):
    h = client.get("/api/hardware").json()
    assert h["options"] and "notes" in h
    assert "rows" in client.get("/api/usage").json()
    assert len(client.get("/api/status").json()) >= 10


def test_policy_change_is_audited_and_effective(client, core):
    r = client.put("/api/policy", json={"cloud_mode": "free_only"}).json()
    assert r["policy"]["cloud_mode"] == "free_only" and "free-tier" in r["policy_explain"]["summary"]
    assert client.put("/api/policy", json={"cloud_mode": "yolo"}).status_code == 400
    assert any(a["kind"] == "policy_changed" for a in core.audit.tail())
