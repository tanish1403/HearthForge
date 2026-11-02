"""Redaction and append-only JSONL audit log."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)(\s*[:=]\s*)(['\"]?)[^\s'\"]{6,}"),
]


def has_secret(text: str) -> bool:
    return any(p.search(text) for p in _PATTERNS)


def redact(text: str, extra_secrets: list[str] | None = None) -> str:
    if not text:
        return text
    for s in extra_secrets or []:
        if s and len(s) >= 6:
            text = text.replace(s, "[REDACTED]")
    for p in _PATTERNS[:-1]:
        text = p.sub("[REDACTED]", text)
    text = _PATTERNS[-1].sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[REDACTED]", text)
    return text


class AuditLog:
    def __init__(self, path: Path, secrets_provider=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._secrets = secrets_provider or (lambda: [])

    def write(self, kind: str, **data) -> None:
        rec = {"ts": time.time(), "kind": kind, **data}
        line = redact(json.dumps(rec, default=str), self._secrets())
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def tail(self, n: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text("utf-8").splitlines()[-n:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
        return out
