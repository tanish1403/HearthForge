# UI journey fixture: real Hearthforge server + scripted mock model/gateway/search. Used by tests/ui/run.sh
import os, sys, json, httpx, tempfile, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT))
from tests.conftest import FakeKeyring, sse
from tests.test_web import DDG
from hearthforge.app import App
from hearthforge.secrets_store import SecretStore
from hearthforge.server import create_app
import uvicorn
tmp=pathlib.Path(tempfile.mkdtemp()); OUT=pathlib.Path(os.environ['HF_UI_TMP']); parent=tmp/'code'; proj=parent/'myapp'; proj.mkdir(parents=True)
(proj/'package.json').write_text('{}')
(proj/'calc.py').write_text("def add(a, b):\n    return a - b\n")
(proj/'test_calc.py').write_text("from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
(OUT/'parent').write_text(str(parent))
KEY="omni-key-1234567890"
Q=["I work!","Hello from the model","Answer using the source [1]",
 json.dumps({"thought":"fix the sign","tool":"edit_file","args":{"path":"calc.py","old":"a - b","new":"a + b"}}),
 json.dumps({"thought":"verify","tool":"run_command","args":{"argv":["python3","-m","pytest","-q","-p","no:cacheprovider"]}}),
 json.dumps({"final":"Fixed add()."})]
def handler(req):
    if req.url.host=="html.duckduckgo.com": return httpx.Response(200,text=DDG)
    if req.url.path.startswith("/v1/"):
        if req.headers.get("authorization")!=f"Bearer {KEY}": return httpx.Response(401,json={"error":"bad key"})
        if req.url.path=="/v1/models": return httpx.Response(200,json={"data":[{"id":"auto"},{"id":"openai/gpt-x"}]})
        if req.url.path=="/v1/chat/completions": return httpx.Response(200,content=sse(Q.pop(0) if Q else "ok"),headers={"content-type":"text/event-stream"})
    if req.url.host!="localhost" and req.url.path=="/": return httpx.Response(200,text="<html><title>Docs</title><body>Official docs text</body></html>",headers={"content-type":"text/html"})
    return httpx.Response(404)
t=httpx.MockTransport(handler)
c=App(home=tmp/'h',transport=t,secrets=SecretStore(FakeKeyring()),token='tok',web_transport=t,resolver=lambda h:["93.184.216.34"])
uvicorn.run(create_app(c),host='127.0.0.1',port=int(os.environ.get('HF_UI_PORT','8798')),log_level='warning')
