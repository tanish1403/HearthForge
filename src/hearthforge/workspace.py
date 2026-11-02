"""Workspace sandbox: path isolation, bounded file ops, validated patches, snapshots and undo."""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MAX_WRITE_BYTES = 2_000_000
MAX_READ_BYTES = 400_000
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "target", ".idea", ".next", ".tox",
}
SECRET_FILE_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "id_ecdsa*", "*.p12", "*.pfx",
    ".npmrc", ".pypirc", ".netrc", "credentials", "*.kdbx", "secrets.json", "secrets.yaml", "secrets.yml",
)
SECRET_ALLOW = (".env.example", ".env.sample", ".env.template")


class WorkspaceError(Exception):
    pass


def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def is_within(child: str | Path, parent: str | Path) -> bool:
    try:
        c, p = _norm(child), _norm(parent)
        return os.path.commonpath([c, p]) == p
    except ValueError:
        return False


def is_secret_file(path: str | Path) -> bool:
    name = Path(path).name.lower()
    if name in SECRET_ALLOW:
        return False
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_FILE_PATTERNS)


def looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


@dataclass
class Change:
    path: str  # workspace-relative, posix
    kind: str  # create | modify | delete
    old: str | None
    new: str | None
    diff: str = ""

    def summary(self) -> dict:
        add = sum(1 for ln in self.diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        rem = sum(1 for ln in self.diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))
        return {"path": self.path, "kind": self.kind, "added": add, "removed": rem}


def make_diff(path: str, old: str | None, new: str | None) -> str:
    a = (old or "").splitlines(keepends=True)
    b = (new or "").splitlines(keepends=True)
    fa = "/dev/null" if old is None else f"a/{path}"
    fb = "/dev/null" if new is None else f"b/{path}"
    out = "".join(difflib.unified_diff(a, b, fa, fb))
    return out


class Sandbox:
    def __init__(self, root: str | Path):
        p = Path(root)
        if not p.is_dir():
            raise WorkspaceError(f"Workspace folder does not exist: {root}")
        self.root = Path(os.path.realpath(p))

    # ---- path handling -------------------------------------------------
    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        if not isinstance(rel, str) or not rel or "\x00" in rel:
            raise WorkspaceError("Invalid path")
        cand = Path(rel)
        cand = cand if cand.is_absolute() else self.root / cand
        real = Path(os.path.realpath(cand))  # follows symlinks (including in parents)
        if not is_within(real, self.root):
            raise WorkspaceError(f"Path escapes the workspace: {rel}")
        if must_exist and not real.exists():
            raise WorkspaceError(f"Path does not exist: {rel}")
        return real

    def rel(self, p: Path) -> str:
        return Path(os.path.relpath(p, self.root)).as_posix()

    def check_writable(self, p: Path) -> None:
        parts = Path(self.rel(p)).parts
        if parts and parts[0] == ".git":
            raise WorkspaceError("Writing inside .git is not allowed")

    # ---- reading -------------------------------------------------------
    def list_dir(self, rel: str = ".", depth: int = 1, limit: int = 300) -> list[str]:
        base = self.resolve(rel, must_exist=True)
        if not base.is_dir():
            raise WorkspaceError("Not a directory")
        out: list[str] = []

        def walk(d: Path, level: int):
            try:
                entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError:
                return
            for e in entries:
                if len(out) >= limit:
                    return
                if e.name in SKIP_DIRS and e.is_dir():
                    out.append(self.rel(e) + "/  (skipped)")
                    continue
                if e.is_symlink() and not is_within(os.path.realpath(e), self.root):
                    out.append(self.rel(e) + "  (symlink outside workspace, hidden)")
                    continue
                out.append(self.rel(e) + ("/" if e.is_dir() else ""))
                if e.is_dir() and level < depth:
                    walk(e, level + 1)

        walk(base, 1)
        return out

    def read_text(self, rel: str, start: int = 1, end: int | None = None, max_bytes: int = MAX_READ_BYTES) -> dict:
        p = self.resolve(rel, must_exist=True)
        if not p.is_file():
            raise WorkspaceError("Not a file")
        if is_secret_file(p):
            raise WorkspaceError(f"Refusing to read likely secret file: {self.rel(p)}")
        size = p.stat().st_size
        with p.open("rb") as f:
            data = f.read(max_bytes + 1)
        if looks_binary(data):
            raise WorkspaceError("Binary file; use the document reader for supported formats")
        truncated_bytes = len(data) > max_bytes
        text = data[:max_bytes].decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        s = max(1, int(start))
        e = min(total, int(end)) if end else total
        body = "\n".join(lines[s - 1 : e])
        return {
            "path": self.rel(p), "text": body, "start": s, "end": e, "total_lines": total,
            "size": size, "truncated": truncated_bytes or e < total,
        }

    def read_raw(self, rel: str) -> str | None:
        p = self.resolve(rel)
        if not p.exists():
            return None
        data = p.read_bytes()
        if looks_binary(data):
            raise WorkspaceError("Binary file cannot be edited as text")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError("File is not valid UTF-8; refusing to edit")

    def search(self, pattern: str, glob: str | None = None, regex: bool = False,
               ignore_case: bool = True, max_results: int = 80) -> list[dict]:
        flags = re.I if ignore_case else 0
        try:
            rx = re.compile(pattern if regex else re.escape(pattern), flags)
        except re.error as e:
            raise WorkspaceError(f"Bad regex: {e}")
        results: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                fp = Path(dirpath) / fn
                rel = self.rel(fp)
                if glob and not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(fn, glob):
                    continue
                if is_secret_file(fp) or fp.is_symlink():
                    continue
                try:
                    if fp.stat().st_size > 1_500_000:
                        continue
                    data = fp.read_bytes()
                except OSError:
                    continue
                if looks_binary(data):
                    continue
                for i, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                    if rx.search(line):
                        results.append({"path": rel, "line": i, "text": line[:300]})
                        if len(results) >= max_results:
                            return results
        return results

    # ---- planning changes (no disk writes) -----------------------------
    def plan_write(self, rel: str, content: str) -> Change:
        p = self.resolve(rel)
        self.check_writable(p)
        if is_secret_file(p):
            raise WorkspaceError("Refusing to write likely secret file")
        if p.is_dir():
            raise WorkspaceError("Path is a directory")
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise WorkspaceError("Content too large")
        old = self.read_raw(rel) if p.exists() else None
        if old == content:
            raise WorkspaceError("No change: file already has this content")
        r = self.rel(p)
        return Change(r, "create" if old is None else "modify", old, content, make_diff(r, old, content))

    def plan_edit(self, rel: str, old: str, new: str, replace_all: bool = False) -> Change:
        p = self.resolve(rel, must_exist=True)
        self.check_writable(p)
        if is_secret_file(p):
            raise WorkspaceError("Refusing to edit likely secret file")
        if old == "":
            raise WorkspaceError("'old' must not be empty")
        cur = self.read_raw(rel)
        assert cur is not None
        crlf = "\r\n" in cur
        o = old.replace("\r\n", "\n").replace("\n", "\r\n") if crlf and "\r\n" not in old else old
        n = new.replace("\r\n", "\n").replace("\n", "\r\n") if crlf and "\r\n" not in new else new
        count = cur.count(o)
        if count == 0:
            raise WorkspaceError("'old' text not found (must match exactly, including whitespace)")
        if count > 1 and not replace_all:
            raise WorkspaceError(f"'old' text matches {count} places; add context or set replace_all")
        updated = cur.replace(o, n) if replace_all else cur.replace(o, n, 1)
        r = self.rel(p)
        return Change(r, "modify", cur, updated, make_diff(r, cur, updated))

    def plan_delete(self, rel: str) -> Change:
        p = self.resolve(rel, must_exist=True)
        self.check_writable(p)
        if not p.is_file():
            raise WorkspaceError("Only single files can be deleted with this tool")
        old = self.read_raw(rel)
        r = self.rel(p)
        return Change(r, "delete", old, None, make_diff(r, old, None))

    def plan_patch(self, patch: str) -> list[Change]:
        changes: list[Change] = []
        for fp in parse_unified_diff(patch):
            target = fp["new"] if fp["new"] != "/dev/null" else fp["old"]
            target = re.sub(r"^[ab]/", "", target)
            p = self.resolve(target)
            self.check_writable(p)
            if is_secret_file(p):
                raise WorkspaceError("Refusing to patch likely secret file")
            r = self.rel(p)
            if fp["old"] == "/dev/null":
                if p.exists():
                    raise WorkspaceError(f"Patch creates {r} but it already exists")
                old, lines = None, []
            else:
                cur = self.read_raw(r)
                if cur is None:
                    raise WorkspaceError(f"Patch targets missing file {r}")
                old, lines = cur, cur.split("\n")
            new_lines = apply_hunks(lines, fp["hunks"], r)
            if fp["new"] == "/dev/null":
                changes.append(Change(r, "delete", old, None, make_diff(r, old, None)))
            else:
                new = "\n".join(new_lines)
                changes.append(Change(r, "create" if old is None else "modify", old, new, make_diff(r, old, new)))
        if not changes:
            raise WorkspaceError("Patch contains no file changes")
        return changes


# ---- unified diff ---------------------------------------------------------
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(text: str) -> list[dict]:
    files: list[dict] = []
    cur = None
    hunk = None
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            cur = {"old": ln[4:].split("\t")[0].strip(), "new": lines[i + 1][4:].split("\t")[0].strip(), "hunks": []}
            files.append(cur)
            hunk = None
            i += 2
            continue
        m = _HUNK.match(ln)
        if m and cur is not None:
            hunk = {"old_start": int(m.group(1)), "lines": []}
            cur["hunks"].append(hunk)
        elif hunk is not None:
            if ln.startswith("\\"):
                pass
            elif ln[:1] in (" ", "+", "-"):
                hunk["lines"].append((ln[0], ln[1:]))
            elif ln == "":
                hunk["lines"].append((" ", ""))
            else:
                hunk = None
        i += 1
    for f in files:
        if not f["hunks"]:
            raise WorkspaceError("Malformed patch: file header without hunks")
    return files


def apply_hunks(lines: list[str], hunks: list[dict], name: str) -> list[str]:
    out = list(lines)
    offset = 0
    for h in hunks:
        before = [t for k, t in h["lines"] if k in (" ", "-")]
        after = [t for k, t in h["lines"] if k in (" ", "+")]
        guess = max(0, h["old_start"] - 1 + offset)
        if not before:
            pos = min(guess, len(out))
        else:
            pos = _find(out, before, guess)
            if pos is None:
                raise WorkspaceError(f"Hunk does not apply to {name} (context mismatch near line {h['old_start']})")
        out[pos : pos + len(before)] = after
        offset += len(after) - len(before)
    return out


def _find(hay: list[str], needle: list[str], guess: int) -> int | None:
    n = len(needle)
    cands = [i for i in range(0, len(hay) - n + 1) if hay[i : i + n] == needle]
    if not cands:
        return None
    return min(cands, key=lambda i: abs(i - guess))


# ---- snapshots / undo ------------------------------------------------------
def _sha(b: bytes | None) -> str | None:
    return hashlib.sha256(b).hexdigest() if b is not None else None


class SnapshotStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "manifest.jsonl"

    def _rows(self) -> list[dict]:
        if not self.manifest.exists():
            return []
        return [json.loads(x) for x in self.manifest.read_text("utf-8").splitlines() if x.strip()]

    def apply(self, sb: Sandbox, change: Change, task_id: str, ws_id: str) -> dict:
        p = sb.resolve(change.path)
        sb.check_writable(p)
        before = p.read_bytes() if p.exists() else None
        sid = f"s_{int(time.time()*1000)}_{len(self._rows())}"
        backup = None
        if before is not None:
            backup = f"{sid}.bak"
            (self.dir / backup).write_bytes(before)
        after: bytes | None
        if change.kind == "delete":
            p.unlink()
            after = None
        else:
            after = (change.new or "").encode("utf-8")
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".hf_", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(after)
                if p.exists():
                    try:
                        os.chmod(tmp, p.stat().st_mode & 0o777)
                    except OSError:
                        pass
                os.replace(tmp, p)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        row = {
            "id": sid, "ws": ws_id, "task": task_id, "path": change.path, "kind": change.kind,
            "backup": backup, "after_sha": _sha(after), "ts": time.time(), "undone": False,
        }
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def list(self, task_id: str | None = None, ws_id: str | None = None) -> list[dict]:
        return [r for r in self._rows() if (not task_id or r["task"] == task_id) and (not ws_id or r["ws"] == ws_id)]

    def undo(self, sb: Sandbox, snap_id: str, force: bool = False) -> dict:
        rows = self._rows()
        row = next((r for r in rows if r["id"] == snap_id), None)
        if not row:
            raise WorkspaceError("Unknown snapshot")
        if row["undone"]:
            raise WorkspaceError("Already undone")
        p = sb.resolve(row["path"])
        cur = p.read_bytes() if p.exists() else None
        if _sha(cur) != row["after_sha"] and not force:
            raise WorkspaceError("File changed since this edit; undo would overwrite newer work (use force)")
        if row["backup"]:
            data = (self.dir / row["backup"]).read_bytes()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        elif p.exists():
            p.unlink()
        row["undone"] = True
        self.manifest.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
        return row
