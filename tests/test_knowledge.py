import pytest

from hearthforge.db import DB
from hearthforge.knowledge import Knowledge, KnowledgeError


@pytest.fixture
def kb(tmp_path):
    return Knowledge(DB(tmp_path / "k.db"))


@pytest.fixture
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "auth.md").write_text("# Auth\nTokens are rotated every hour by the refresh service.\n")
    (d / "db.py").write_text("def connect():\n    return 'postgres connection pool'\n")
    (d / ".env").write_text("SECRET=hunter2hunter2")
    return d


def test_index_search_with_citations(kb, docs):
    s = kb.add_source("p1", str(docs))
    stats = kb.index(s["id"])
    assert stats["added"] == 2
    hits = kb.search("how are tokens rotated?", "p1")
    assert hits[0]["path"] == "auth.md" and hits[0]["loc"].startswith("L")


def test_secret_files_are_never_indexed(kb, docs):
    s = kb.add_source("p1", str(docs))
    kb.index(s["id"])
    assert kb.search("hunter2hunter2", "p1") == []
    assert ".env" not in [d["path"] for d in kb.list_docs(s["id"])]


def test_incremental_index_detects_changes(kb, docs):
    s = kb.add_source("p1", str(docs))
    kb.index(s["id"])
    assert kb.index(s["id"])["unchanged"] == 2
    (docs / "auth.md").write_text("Completely different content about kubernetes.\n")
    (docs / "db.py").unlink()
    st = kb.index(s["id"])
    assert st["updated"] == 1 and st["removed"] == 1
    assert kb.search("kubernetes", "p1") and not kb.search("postgres", "p1")


def test_scopes_are_isolated(kb, docs):
    a = kb.add_source("proj-a", str(docs))
    kb.index(a["id"])
    assert kb.search("tokens", "proj-b") == []
    assert kb.search("tokens", "proj-b", include_global=True) == []
    kb.remember("proj-a", "uses postgres 16")
    assert kb.recall("proj-b", "postgres", include_global=False) == []
    assert kb.recall("proj-a", "postgres")


def test_global_memory_visible_when_included(kb):
    kb.remember("global", "prefer pytest over unittest")
    assert kb.recall("proj-x", "pytest", include_global=True)
    assert not kb.recall("proj-x", "pytest", include_global=False)


def test_exclude_and_reindex_respects_exclusion(kb, docs):
    s = kb.add_source("p", str(docs))
    kb.index(s["id"])
    did = next(d["id"] for d in kb.list_docs(s["id"]) if d["path"] == "auth.md")
    kb.set_excluded(did, True)
    assert kb.search("tokens", "p") == []
    kb.index(s["id"], force=True)
    assert kb.search("tokens", "p") == []
    kb.set_excluded(did, False)
    kb.index(s["id"], force=True)
    assert kb.search("tokens", "p")


def test_memory_refuses_credentials(kb):
    with pytest.raises(KnowledgeError):
        kb.remember("p", "the key is sk-abcdefghijklmnopqrstuvwxyz123456")
    with pytest.raises(KnowledgeError):
        kb.remember("p", "password = hunter2hunter2")


def test_memory_crud_export_delete(kb, docs):
    m = kb.remember("p", "build with make all", tags="build")
    kb.update_memory(m["id"], "build with make everything")
    assert kb.recall("p", "everything")[0]["text"].endswith("everything")
    s = kb.add_source("p", str(docs))
    kb.index(s["id"])
    exp = kb.export("p")
    assert exp["memories"] and exp["sources"]
    kb.delete_scope("p")
    assert kb.export("p")["memories"] == [] and kb.search("tokens", "p") == []


def test_query_with_fts_syntax_does_not_crash(kb, docs):
    s = kb.add_source("p", str(docs))
    kb.index(s["id"])
    for q in ['tokens" OR "', "NEAR(", "a*b", "'; DROP TABLE k_docs;--", ""]:
        kb.search(q, "p")
    assert kb.list_docs(s["id"])
