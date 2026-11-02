import asyncio
import os
import sys

import pytest

from hearthforge.commands import classify, run_command, scrubbed_env

ROOT = os.path.abspath(os.sep + "ws")


@pytest.mark.parametrize("argv,allowed,safe,level", [
    (["pytest", "-q"], True, True, "exec"),
    (["python", "-m", "pytest"], True, True, "exec"),
    (["ruff", "check", "."], True, True, "exec"),
    (["ruff", "check", ".", "--fix"], True, False, "exec"),
    (["npm", "test"], True, True, "exec"),
    (["npm", "run", "build"], True, True, "exec"),
    (["npm", "install"], True, False, "install"),
    (["pip", "install", "requests"], True, False, "install"),
    (["python", "-m", "pip", "install", "x"], True, False, "install"),
    (["cargo", "test"], True, True, "exec"),
    (["python", "script.py"], True, False, "exec"),
    (["git", "status"], True, True, "exec"),
    (["git", "push"], True, False, "network"),
    (["git", "reset", "--hard"], True, False, "destructive"),
    (["curl", "http://x"], True, False, "network"),
    (["rm", "-rf", "/"], False, False, ""),
    (["bash", "-c", "ls"], False, False, ""),
    (["powershell", "x"], False, False, ""),
    (["sh"], False, False, ""),
    (["/usr/bin/python", "x"], False, False, ""),
    (["unknown-tool"], False, False, ""),
    (["git", "-c", "core.sshCommand=evil", "fetch"], False, False, ""),
    (["git", "diff", "--ext-diff"], False, False, ""),
    ([], False, False, ""),
])
def test_classification(argv, allowed, safe, level):
    c = classify(argv, ROOT)
    assert c.allowed == allowed, c.reason
    if allowed:
        assert c.safe == safe
        assert c.level == level


def test_outside_workspace_path_is_never_safe():
    outside = os.path.abspath(os.sep + "etc" + os.sep + "passwd")
    assert not classify(["pytest", outside], ROOT).safe
    assert not classify(["pytest", "../../x"], ROOT, ROOT).safe


def test_extra_allowed_command():
    assert not classify(["mytool"], ROOT).allowed
    assert classify(["mytool"], ROOT, extra_allowed=["mytool"]).allowed
    assert not classify(["bash"], ROOT, extra_allowed=["bash"]).allowed  # shells can never be allowlisted


def test_env_scrubbing(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "x")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("HEARTHFORGE_KEY_OPENROUTER", "x")
    env = scrubbed_env()
    assert not any(k in env for k in ("MY_API_KEY", "GITHUB_TOKEN", "HEARTHFORGE_KEY_OPENROUTER"))


async def test_run_command_output_and_exit(tmp_path):
    r = await run_command([sys.executable, "-c", "print('hi'); raise SystemExit(3)"], str(tmp_path))
    assert r.exit_code == 3 and "hi" in r.output


async def test_run_command_timeout(tmp_path):
    r = await run_command([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), timeout_s=0.5)
    assert r.timed_out


async def test_run_command_output_is_bounded(tmp_path):
    r = await run_command([sys.executable, "-c", "print('x'*500000)"], str(tmp_path), max_chars=3000)
    assert r.truncated and len(r.output) < 4000


async def test_run_command_cancel(tmp_path):
    ev = asyncio.Event()
    t = asyncio.create_task(run_command([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), cancel=ev))
    await asyncio.sleep(0.3)
    ev.set()
    r = await asyncio.wait_for(t, 5)
    assert not r.timed_out
