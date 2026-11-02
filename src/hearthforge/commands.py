"""Command classification and bounded execution. No shell is ever used; argv only."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import sys
import time
from dataclasses import dataclass

from .workspace import is_within

NEVER = {  # shells and destructive/system utilities: never runnable, even if user-allowlisted
    "bash", "sh", "zsh", "fish", "dash", "csh", "ksh", "cmd", "powershell", "pwsh", "wsl",
    "rm", "rmdir", "del", "erase", "rd", "format", "mkfs", "dd", "sudo", "su", "doas", "chmod", "chown",
    "shutdown", "reboot", "reg", "sc", "taskkill", "kill", "killall", "eval", "xargs", "env", "sed", "awk",
}
NETWORK_EXES = {"curl", "wget", "ssh", "scp", "sftp", "ftp", "nc", "ncat", "telnet", "rsync"}
DEV_EXES = {
    "python", "python3", "py", "node", "deno", "bun", "npx", "make", "cmake", "ctest", "cargo", "rustc", "go",
    "dotnet", "java", "javac", "mvn", "gradle", "tsc", "eslint", "prettier", "ruff", "mypy", "pytest", "black",
    "flake8", "pylint", "pip", "pip3", "uv", "npm", "pnpm", "yarn", "git", "gcc", "g++", "clang", "php", "ruby",
    "bundle", "rake", "tox", "nox",
}
GIT_SAFE = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files", "blame", "describe"}
GIT_NETWORK = {"clone", "fetch", "pull", "push", "ls-remote", "submodule", "remote"}
GIT_DESTRUCTIVE = {"reset", "clean", "rm", "checkout", "restore", "rebase", "filter-branch", "gc", "prune"}
GIT_BAD_FLAGS = ("-c", "--config", "--exec-path", "--upload-pack", "--receive-pack", "--ext-diff", "--textconv")
PKG_INSTALL = {"install", "i", "add", "ci", "update", "upgrade", "remove", "uninstall", "sync"}
SAFE_SUBCOMMANDS = {
    "cargo": {"test", "check", "build", "clippy"},
    "go": {"test", "build", "vet"},
    "dotnet": {"test", "build"},
    "mvn": {"test", "verify", "compile"},
    "gradle": {"test", "build", "check"},
    "make": {"test", "check", "lint"},
    "npm": {"test", "t"},
    "pnpm": {"test", "t"},
    "yarn": {"test"},
}
SAFE_NPM_RUN = {"test", "build", "lint", "typecheck", "check"}
_SENSITIVE_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|SESSION)", re.I)
_CMD_BAD = re.compile(r'[&|<>^%"\r\n]')


@dataclass
class Classification:
    allowed: bool
    level: str = "exec"  # exec | install | network | destructive
    safe: bool = False  # true = verification-style command eligible for auto-approval
    verification: bool = False
    reason: str = ""
    exe: str = ""


def exe_name(argv0: str) -> str:
    n = os.path.basename(argv0).lower()
    return re.sub(r"\.(exe|cmd|bat|com)$", "", n)


def classify(argv: list[str], root: str, cwd: str | None = None, extra_allowed: list[str] | None = None) -> Classification:
    if not argv or not all(isinstance(a, str) for a in argv):
        return Classification(False, reason="argv must be a non-empty list of strings")
    if any("\x00" in a for a in argv):
        return Classification(False, reason="NUL byte in argument")
    exe = exe_name(argv[0])
    args = argv[1:]
    if os.path.sep in argv[0] or "/" in argv[0] or "\\" in argv[0]:
        return Classification(False, reason="Executable must be a bare command name, not a path", exe=exe)
    if exe in NEVER:
        return Classification(False, reason=f"'{exe}' is never allowed (shell or destructive utility)", exe=exe)
    extra = {exe_name(x) for x in (extra_allowed or [])}
    if exe in NETWORK_EXES:
        return Classification(True, level="network", reason=f"'{exe}' accesses the network", exe=exe)
    if exe not in DEV_EXES and exe not in extra:
        return Classification(False, reason=f"'{exe}' is not on the allowlist (add it in workspace settings)", exe=exe)

    c = Classification(True, level="exec", exe=exe)
    sub = next((a for a in args if not a.startswith("-")), "")
    flags = [a for a in args if a.startswith("-")]

    # outside-workspace path arguments are never auto-approved
    outside = False
    for a in args:
        if a.startswith("-") and "=" in a:
            a = a.split("=", 1)[1]
        if a.startswith("-"):
            continue
        if os.path.isabs(a) and not is_within(a, root):
            outside = True
        elif ".." in re.split(r"[\\/]", a):
            base = cwd or root
            if not is_within(os.path.join(base, a), root):
                outside = True
    if outside:
        c.reason = "argument points outside the workspace"
        return c

    if exe == "git":
        if any(f == b or f.startswith(b + "=") or (b == "-c" and f.startswith("-c")) for f in flags for b in GIT_BAD_FLAGS):
            return Classification(False, reason="git config/exec override flags are not allowed", exe=exe)
        if sub in GIT_SAFE:
            c.safe = True
        elif sub in GIT_NETWORK:
            c.level = "network"
        elif sub in GIT_DESTRUCTIVE:
            c.level = "destructive"
        return c

    py_m = exe in {"python", "python3", "py"} and "-m" in args
    mod = args[args.index("-m") + 1] if py_m and args.index("-m") + 1 < len(args) else ""
    if exe in {"pip", "pip3"} or (py_m and mod == "pip"):
        c.level = "install" if (sub in PKG_INSTALL or mod == "pip" and any(a in PKG_INSTALL for a in args)) else "exec"
        return c
    if exe == "uv" and sub in {"pip", "add", "sync", "install", "remove", "tool"}:
        c.level = "install"
        return c
    if exe in {"npm", "pnpm", "yarn"} and sub in PKG_INSTALL:
        c.level = "install"
        return c
    if exe == "cargo" and sub in {"install", "add", "update", "remove"}:
        c.level = "install"
        return c

    # verification-style commands
    if exe == "pytest" or (py_m and mod in {"pytest", "unittest"}):
        c.safe = c.verification = True
    elif exe == "ruff" and sub == "check" and "--fix" not in flags:
        c.safe = c.verification = True
    elif exe == "mypy" or (py_m and mod == "mypy"):
        c.safe = c.verification = True
    elif exe == "tsc" and "--noEmit" in flags:
        c.safe = c.verification = True
    elif exe in SAFE_SUBCOMMANDS and sub in SAFE_SUBCOMMANDS[exe]:
        c.safe = c.verification = True
    elif exe in {"npm", "pnpm", "yarn"} and sub == "run" and len(args) >= 2 and args[args.index("run") + 1] in SAFE_NPM_RUN:
        c.safe = c.verification = True
    return c


def scrubbed_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _SENSITIVE_ENV.search(k)}
    env.update({"CI": "1", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0"})
    return env


@dataclass
class CommandResult:
    exit_code: int | None
    output: str
    timed_out: bool
    duration_s: float
    truncated: bool
    error: str = ""


async def run_command(argv: list[str], cwd: str, timeout_s: float = 120, max_chars: int = 20000,
                      cancel: asyncio.Event | None = None, stdin_data: bytes | None = None) -> CommandResult:
    exe = shutil.which(argv[0], path=scrubbed_env().get("PATH"))
    if not exe:
        return CommandResult(None, "", False, 0.0, False, error=f"Executable not found: {argv[0]}")
    if exe.lower().endswith((".cmd", ".bat")) and any(_CMD_BAD.search(a) for a in argv[1:]):
        return CommandResult(None, "", False, 0.0, False, error="Argument contains characters unsafe for .cmd shims")
    kwargs: dict = {}
    if sys.platform == "win32":
        import subprocess
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            exe, *argv[1:], cwd=cwd, env=scrubbed_env(),
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **kwargs,
        )
    except OSError as e:
        return CommandResult(None, "", False, 0.0, False, error=str(e))

    if stdin_data is not None and proc.stdin:
        try:
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass
    head, tail, total = bytearray(), bytearray(), 0
    head_cap, tail_cap = max_chars // 3, max_chars * 2 // 3

    async def pump():
        nonlocal total
        assert proc.stdout
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            total += len(chunk)
            if len(head) < head_cap:
                take = head_cap - len(head)
                head.extend(chunk[:take])
                chunk = chunk[take:]
            if chunk:
                tail.extend(chunk)
                if len(tail) > tail_cap:
                    del tail[: len(tail) - tail_cap]

    def kill():
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    timed_out = False
    pump_task = asyncio.create_task(pump())
    wait_task = asyncio.create_task(proc.wait())
    cancel_task = asyncio.create_task(cancel.wait()) if cancel else None
    waiters = {wait_task} | ({cancel_task} if cancel_task else set())
    try:
        done, _ = await asyncio.wait(waiters, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
        if wait_task not in done:
            timed_out = not (cancel_task and cancel_task in done)
            kill()
            await proc.wait()
        await asyncio.wait_for(pump_task, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        kill()
        pump_task.cancel()
        raise
    finally:
        if cancel_task:
            cancel_task.cancel()
    truncated = total > len(head) + len(tail)
    text = head.decode("utf-8", "replace")
    if truncated:
        text += f"\n...[{total - len(head) - len(tail)} bytes omitted]...\n"
    text += tail.decode("utf-8", "replace")
    return CommandResult(proc.returncode, text, timed_out, time.monotonic() - t0, truncated)


GIT_PREFIX = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.pager=cat"]


async def git(sb_root: str, *args: str, timeout_s: float = 30) -> CommandResult:
    """Read-only git helper (hardened against repo-config command execution)."""
    extra = ["--no-ext-diff", "--no-textconv"] if args and args[0] in {"diff", "show", "log"} else []
    argv = GIT_PREFIX + [args[0], *extra, *args[1:]]
    return await run_command(argv, sb_root, timeout_s=timeout_s)
