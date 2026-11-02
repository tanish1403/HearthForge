import json

import pytest

from hearthforge.plugins import PluginError, PluginManager, validate_manifest

GOOD = {"id": "echo-plug", "name": "Echo", "tools": [
    {"name": "run", "description": "echo stdin", "command": ["python3", "plug.py"], "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}}}]}


def test_valid_manifest_and_forced_exec_level():
    m = validate_manifest(json.loads(json.dumps(GOOD)))
    assert m["tools"][0]["level"] == "exec"
    g = json.loads(json.dumps(GOOD)); g["tools"][0]["level"] = "read"
    assert validate_manifest(g)["tools"][0]["level"] == "exec"  # cannot self-declare read-level


@pytest.mark.parametrize("mut", [
    lambda m: m.update(id="Bad ID"),
    lambda m: m["tools"][0].update(command=["bash", "-c", "x"]),
    lambda m: m["tools"][0].update(command=["/bin/evil"]),
    lambda m: m["tools"][0].update(command=[]),
    lambda m: m.update(tools=[]),
    lambda m: m["tools"][0].update(name="Bad-Name"),
])
def test_invalid_manifests_rejected(mut):
    m = json.loads(json.dumps(GOOD))
    mut(m)
    with pytest.raises(PluginError):
        validate_manifest(m)


def test_add_remove_lifecycle(tmp_path):
    pm = PluginManager(tmp_path / "p")
    pm.add(json.loads(json.dumps(GOOD)))
    assert pm.has("echo-plug")
    pm.remove("echo-plug")
    assert not pm.has("echo-plug") and pm.list() == []
    with pytest.raises(PluginError):
        pm.remove("../../etc")


def test_tampered_manifest_on_disk_is_ignored(tmp_path):
    pm = PluginManager(tmp_path / "p")
    (pm.dir / "evil.json").write_text(json.dumps({"id": "evil", "name": "x", "tools": [{"name": "t", "description": "d", "command": ["bash"]}]}))
    assert pm.list() == []
