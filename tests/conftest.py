from __future__ import annotations

import json

import httpx
import pytest

from hearthforge.app import App
from hearthforge.config import WorkspaceConfig, ActiveModel
from hearthforge.secrets_store import SecretStore


class FakeKeyring:
    def __init__(self):
        self.d = {}

    def get_password(self, s, k):
        return self.d.get((s, k))

    def set_password(self, s, k, v):
        self.d[(s, k)] = v

    def delete_password(self, s, k):
        self.d.pop((s, k), None)


def sse(text: str, usage=True) -> bytes:
    half = max(1, len(text) // 2)
    chunks = [text[:half], text[half:]]
    out = "".join("data: " + json.dumps({"choices": [{"delta": {"content": c}}]}) + "\n\n" for c in chunks if c)
    out += "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}) + "\n\n"
    if usage:
        out += "data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}) + "\n\n"
    return (out + "data: [DONE]\n\n").encode()


class Scripted:
    """Mock OpenAI-compatible server. `replies` are served in order; dicts may be callables(request_body)."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []
        self.models = ["mock-model"]
        self.status_sequence: list[int] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        if path.endswith("/chat/completions"):
            body = json.loads(request.content)
            self.bodies.append(body)
            if self.status_sequence:
                code = self.status_sequence.pop(0)
                if code != 200:
                    return httpx.Response(code, json={"error": "x"}, headers={"retry-after": "0"})
            if not self.replies:
                return httpx.Response(500, json={"error": "no scripted reply left"})
            r = self.replies.pop(0)
            text = r(body) if callable(r) else r
            if isinstance(text, dict):
                text = json.dumps(text)
            return httpx.Response(200, content=sse(text), headers={"content-type": "text/event-stream"})
        if path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        return httpx.Response(404)


@pytest.fixture
def mock():
    return Scripted()


@pytest.fixture
def core(tmp_path, mock):
    c = App(home=tmp_path / "home", transport=httpx.MockTransport(mock.handler), secrets=SecretStore(FakeKeyring()), token="tok")
    return c


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    return root


@pytest.fixture
def ws(core, project):
    w = WorkspaceConfig(id="ws1", name="proj", path=str(project))
    core.store.update(lambda s: s.workspaces.append(w))
    core.store.update(lambda s: setattr(s, "active", ActiveModel(provider="llamacpp", model="mock-model")))
    return w


PUBLIC_RESOLVER = staticmethod(lambda host: ["93.184.216.34"])


@pytest.fixture
def set_web(core):
    """Install a mock web transport and a resolver that maps every hostname to a public IP."""
    def _set(handler):
        t = httpx.MockTransport(handler)
        core.web_transport = core.svc.web_transport = t
        core.resolver = core.svc.resolver = lambda host: ["93.184.216.34"]
        return t
    return _set
