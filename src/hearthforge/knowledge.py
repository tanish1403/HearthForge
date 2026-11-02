"""Local knowledge: incremental FTS5/BM25 document index with citations, plus scoped long-term memory.

RAG (retrieval pipeline) and memory (curated persistent notes) are deliberately separate stores.
Everything is scoped: a workspace id or 'global'. Searches never cross scopes unless asked.
Retrieved text is untrusted data.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from pathlib import Path

from .audit import has_secret
from .db import DB
from .documents import extract
from .workspace import SKIP_DIRS, Sandbox, is_secret_file, looks_binary

DOC_EXT = {".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".tsv"}
MAX_INDEX_BYTES = 3_000_000
LINES_PER_CHUNK, LINE_OVERLAP, MAX_CHUNK_CHARS = 48, 8, 1800


class KnowledgeError(Exception):
    pass


def _tokens(q: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[A-Za-z0-9_]{2,}", q)))[:24]


def chunk_lines(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        j, size = i, 0
        while j < len(lines) and j - i < LINES_PER_CHUNK and size + len(lines[j]) < MAX_CHUNK_CHARS:
            size += len(lines[j]) + 1
            j += 1
        j = max(j, i + 1)
        body = "\n".join(lines[i:j]).strip()
        if body:
            out.append((body[:MAX_CHUNK_CHARS], f"L{i+1}-L{j}"))
        if j >= len(lines):
            break
        i = max(j - LINE_OVERLAP, i + 1)
    return out


def chunk_chars(text: str, locations: list[dict], size: int = 1500, overlap: int = 200) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(text):
        body = text[i : i + size].strip()
        if body:
            label = next((x["label"] for x in locations if x["start"] <= i < x["end"]), "")
            out.append((body, label or f"chars {i}-{i+size}"))
        i += size - overlap
    return out


class Knowledge:
    def __init__(self, db: DB):
        self.db = db
        db.script("""
        CREATE TABLE IF NOT EXISTS k_sources(id TEXT PRIMARY KEY, scope TEXT, name TEXT, root TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS k_docs(id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, path TEXT, sha TEXT,
            excluded INTEGER DEFAULT 0, chunks INTEGER DEFAULT 0, UNIQUE(source_id, path));
        CREATE VIRTUAL TABLE IF NOT EXISTS k_chunks USING fts5(content, path UNINDEXED, loc UNINDEXED,
            source_id UNINDEXED, doc_id UNINDEXED, scope UNINDEXED, tokenize='porter unicode61');
        CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, scope TEXT, text TEXT, tags TEXT, pinned INTEGER DEFAULT 0,
            created REAL, task_id TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(text, tags, mem_id UNINDEXED, scope UNINDEXED, tokenize='porter unicode61');
        """)

    # ---------------------------------------------------------- sources
    def add_source(self, scope: str, root: str, name: str | None = None) -> dict:
        Sandbox(root)  # validates directory exists
        sid = "src_" + uuid.uuid4().hex[:8]
        self.db.execute("INSERT INTO k_sources VALUES(?,?,?,?,?)", (sid, scope, name or Path(root).name, str(Path(root).resolve()), time.time()))
        return {"id": sid, "scope": scope, "name": name or Path(root).name, "root": root}

    def list_sources(self, scope: str | None = None) -> list[dict]:
        rows = self.db.query("SELECT * FROM k_sources" + (" WHERE scope=?" if scope else ""), (scope,) if scope else ())
        out = []
        for r in rows:
            d = dict(r)
            c = self.db.query("SELECT COUNT(*) n, COALESCE(SUM(chunks),0) c FROM k_docs WHERE source_id=? AND excluded=0", (r["id"],))[0]
            d["documents"], d["chunks"] = c["n"], c["c"]
            out.append(d)
        return out

    def remove_source(self, sid: str) -> None:
        self.db.execute("DELETE FROM k_chunks WHERE source_id=?", (sid,))
        self.db.execute("DELETE FROM k_docs WHERE source_id=?", (sid,))
        self.db.execute("DELETE FROM k_sources WHERE id=?", (sid,))

    def _source(self, sid: str):
        rows = self.db.query("SELECT * FROM k_sources WHERE id=?", (sid,))
        if not rows:
            raise KnowledgeError("Unknown knowledge source")
        return rows[0]

    # ---------------------------------------------------------- indexing
    def index(self, sid: str, force: bool = False) -> dict:
        src = self._source(sid)
        sb = Sandbox(src["root"])
        stats = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0, "skipped": 0, "errors": []}
        seen: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(sb.root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                fp = Path(dirpath) / fn
                rel = sb.rel(fp)
                try:
                    if fp.is_symlink() or is_secret_file(fp) or fp.stat().st_size > MAX_INDEX_BYTES:
                        stats["skipped"] += 1
                        continue
                    data = fp.read_bytes()
                    is_doc = fp.suffix.lower() in DOC_EXT
                    if not is_doc and looks_binary(data):
                        stats["skipped"] += 1
                        continue
                    sha = hashlib.sha256(data).hexdigest()
                    seen.add(rel)
                    row = self.db.query("SELECT id, sha, excluded FROM k_docs WHERE source_id=? AND path=?", (sid, rel))
                    if row and row[0]["excluded"]:
                        continue
                    if row and row[0]["sha"] == sha and not force:
                        stats["unchanged"] += 1
                        continue
                    if is_doc:
                        ex = extract(fp, 400_000, rel)
                        if not ex.text:
                            stats["skipped"] += 1
                            continue
                        chunks = chunk_chars(ex.text, ex.locations)
                    else:
                        chunks = chunk_lines(data.decode("utf-8", "replace"))
                    if row:
                        doc_id = row[0]["id"]
                        self.db.execute("DELETE FROM k_chunks WHERE doc_id=?", (doc_id,))
                        self.db.execute("UPDATE k_docs SET sha=?, chunks=? WHERE id=?", (sha, len(chunks), doc_id))
                        stats["updated"] += 1
                    else:
                        cur = self.db.execute("INSERT INTO k_docs(source_id,path,sha,chunks) VALUES(?,?,?,?)", (sid, rel, sha, len(chunks)))
                        doc_id = cur.lastrowid
                        stats["added"] += 1
                    for body, loc in chunks:
                        self.db.execute("INSERT INTO k_chunks(content,path,loc,source_id,doc_id,scope) VALUES(?,?,?,?,?,?)",
                                        (body, rel, loc, sid, doc_id, src["scope"]))
                except Exception as e:
                    stats["errors"].append(f"{rel}: {type(e).__name__}")
        for r in self.db.query("SELECT id, path FROM k_docs WHERE source_id=?", (sid,)):
            if r["path"] not in seen:
                self.db.execute("DELETE FROM k_chunks WHERE doc_id=?", (r["id"],))
                self.db.execute("DELETE FROM k_docs WHERE id=?", (r["id"],))
                stats["removed"] += 1
        return stats

    def list_docs(self, sid: str) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT id, path, chunks, excluded FROM k_docs WHERE source_id=? ORDER BY path", (sid,))]

    def set_excluded(self, doc_id: int, excluded: bool) -> None:
        self.db.execute("UPDATE k_docs SET excluded=? WHERE id=?", (1 if excluded else 0, doc_id))
        if excluded:
            self.db.execute("DELETE FROM k_chunks WHERE doc_id=?", (doc_id,))
            self.db.execute("UPDATE k_docs SET chunks=0, sha='' WHERE id=?", (doc_id,))

    # ---------------------------------------------------------- search
    def search(self, query: str, scope: str, limit: int = 6, include_global: bool = False) -> list[dict]:
        toks = _tokens(query)
        if not toks:
            return []
        q = " OR ".join(f'"{t}"' for t in toks)
        scopes = [scope] + (["global"] if include_global and scope != "global" else [])
        ph = ",".join("?" * len(scopes))
        rows = self.db.query(
            f"""SELECT content, path, loc, source_id, doc_id, bm25(k_chunks) AS score FROM k_chunks
                WHERE k_chunks MATCH ? AND scope IN ({ph}) ORDER BY score LIMIT ?""", [q, *scopes, limit])
        return [{"path": r["path"], "loc": r["loc"], "source_id": r["source_id"], "score": round(-r["score"], 3),
                 "text": r["content"][:1200]} for r in rows]

    # ---------------------------------------------------------- memory
    def remember(self, scope: str, text: str, tags: str = "", task_id: str | None = None, pinned: bool = False) -> dict:
        text = text.strip()
        if not text:
            raise KnowledgeError("Empty memory")
        if len(text) > 2000:
            raise KnowledgeError("Memory too long (max 2000 chars); store a summary")
        if has_secret(text) or has_secret(tags):
            raise KnowledgeError("Refusing to store text that looks like a credential")
        mid = "mem_" + uuid.uuid4().hex[:8]
        self.db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?)", (mid, scope, text, tags, int(pinned), time.time(), task_id))
        self.db.execute("INSERT INTO mem_fts(text,tags,mem_id,scope) VALUES(?,?,?,?)", (text, tags, mid, scope))
        return {"id": mid, "scope": scope, "text": text, "tags": tags}

    def recall(self, scope: str, query: str, limit: int = 5, include_global: bool = True) -> list[dict]:
        toks = _tokens(query)
        scopes = [scope] + (["global"] if include_global and scope != "global" else [])
        ph = ",".join("?" * len(scopes))
        if not toks:
            rows = self.db.query(f"SELECT * FROM memories WHERE scope IN ({ph}) ORDER BY pinned DESC, created DESC LIMIT ?", [*scopes, limit])
            return [dict(r) for r in rows]
        q = " OR ".join(f'"{t}"' for t in toks)
        rows = self.db.query(
            f"""SELECT m.* FROM mem_fts f JOIN memories m ON m.id=f.mem_id WHERE mem_fts MATCH ? AND f.scope IN ({ph})
                ORDER BY bm25(mem_fts) LIMIT ?""", [q, *scopes, limit])
        return [dict(r) for r in rows]

    def list_memories(self, scope: str) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM memories WHERE scope=? ORDER BY created DESC", (scope,))]

    def forget(self, mem_id: str) -> None:
        self.db.execute("DELETE FROM memories WHERE id=?", (mem_id,))
        self.db.execute("DELETE FROM mem_fts WHERE mem_id=?", (mem_id,))

    def update_memory(self, mem_id: str, text: str) -> None:
        if has_secret(text):
            raise KnowledgeError("Refusing to store text that looks like a credential")
        self.db.execute("UPDATE memories SET text=? WHERE id=?", (text, mem_id))
        self.db.execute("UPDATE mem_fts SET text=? WHERE mem_id=?", (text, mem_id))

    def export(self, scope: str) -> dict:
        return {
            "scope": scope,
            "sources": [s for s in self.list_sources(scope)],
            "documents": {s["id"]: self.list_docs(s["id"]) for s in self.list_sources(scope)},
            "memories": self.list_memories(scope),
        }

    def delete_scope(self, scope: str) -> None:
        for s in self.list_sources(scope):
            self.remove_source(s["id"])
        for m in self.list_memories(scope):
            self.forget(m["id"])
