#!/usr/bin/env python3
"""Pre-publish scan: looks for credential-like strings and private paths in files git would commit.

Usage: python scripts/check_secrets.py          (scans `git ls-files` + untracked, non-ignored files)
Not a replacement for a dedicated scanner (gitleaks/trufflehog), but catches the common mistakes.
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "AWS key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "Groq/HF key": re.compile(r"\b(gsk|hf)_[A-Za-z0-9]{30,}"),
    "assigned secret": re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
    "personal home path": re.compile(r"(?i)(C:\\Users\\[A-Za-z0-9_.-]+|/home/[a-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/)"),
}
SKIP_SUFFIX = {".png", ".jpg", ".ico", ".whl", ".gz", ".db"}
ALLOW = ("sk-abcdefghijklmnopqrstuvwxyz", "sk-abcdefghijklmnopqrstuvwx1234", "sk-supersecretvalue", "gsk_")


def files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], capture_output=True, text=True, check=True).stdout
        return [Path(p) for p in out.splitlines()]
    except Exception:
        print("Not a git repo (or git missing); scanning working tree instead.")
        return [p for p in Path(".").rglob("*") if p.is_file() and not ({".venv", ".git", "node_modules"} & set(p.parts))]


def main() -> int:
    bad = 0
    for p in files():
        if p.suffix in SKIP_SUFFIX or not p.is_file() or p.name == "check_secrets.py":
            continue
        try:
            text = p.read_text("utf-8")
        except Exception:
            continue
        for name, rx in PATTERNS.items():
            for m in rx.finditer(text):
                if any(a in m.group(0) for a in ALLOW) and p.parts[0] == "tests":
                    continue
                line = text.count("\n", 0, m.start()) + 1
                print(f"{p}:{line}: possible {name}")
                bad += 1
    print("No findings." if not bad else f"{bad} finding(s). Review before committing.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
