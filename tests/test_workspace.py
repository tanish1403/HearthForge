import os
import sys

import pytest

from hearthforge.workspace import Sandbox, SnapshotStore, WorkspaceError, is_secret_file


@pytest.fixture
def sb(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    (root / "a.txt").write_text("hello\nworld\n")
    (root / "sub").mkdir()
    (root / "sub" / "b.py").write_text("x = 1\n")
    return Sandbox(root)


def test_rejects_traversal(sb):
    for bad in ["../x", "sub/../../x", "/etc/passwd", "..\\..\\x" if sys.platform == "win32" else "../../etc/passwd"]:
        with pytest.raises(WorkspaceError):
            sb.resolve(bad)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows CI")
def test_symlink_escape_blocked(sb, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope")
    os.symlink(outside, sb.root / "link")
    with pytest.raises(WorkspaceError):
        sb.read_text("link/secret.txt")
    with pytest.raises(WorkspaceError):
        sb.plan_write("link/new.txt", "x")  # writing through a symlinked dir must also fail


def test_secret_files_not_readable_or_writable(sb):
    (sb.root / ".env").write_text("API_KEY=abc123456")
    with pytest.raises(WorkspaceError):
        sb.read_text(".env")
    with pytest.raises(WorkspaceError):
        sb.plan_write(".env", "x")
    assert not any(".env" in r["path"] for r in sb.search("abc123456"))
    assert not is_secret_file(".env.example")


def test_git_dir_is_write_protected(sb):
    (sb.root / ".git").mkdir()
    with pytest.raises(WorkspaceError):
        sb.plan_write(".git/config", "x")


def test_edit_requires_unique_match(sb):
    (sb.root / "d.txt").write_text("a\na\n")
    with pytest.raises(WorkspaceError):
        sb.plan_edit("d.txt", "a", "b")
    ch = sb.plan_edit("d.txt", "a", "b", replace_all=True)
    assert ch.new == "b\nb\n"
    with pytest.raises(WorkspaceError):
        sb.plan_edit("d.txt", "zzz", "b")


def test_edit_preserves_crlf(sb):
    (sb.root / "c.txt").write_bytes(b"one\r\ntwo\r\n")
    ch = sb.plan_edit("c.txt", "one\ntwo", "uno\ntwo")
    assert ch.new == "uno\r\ntwo\r\n"


PATCH = """--- a/a.txt
+++ b/a.txt
@@ -1,2 +1,2 @@
 hello
-world
+there
"""


def test_patch_applies_and_validates_context(sb):
    ch = sb.plan_patch(PATCH)[0]
    assert ch.new.startswith("hello\nthere")
    bad = PATCH.replace(" hello", " goodbye")
    with pytest.raises(WorkspaceError):
        sb.plan_patch(bad)


def test_patch_cannot_escape(sb):
    p = "--- a/../evil.txt\n+++ b/../evil.txt\n@@ -0,0 +1 @@\n+x\n"
    with pytest.raises(WorkspaceError):
        sb.plan_patch(p)


def test_snapshot_apply_and_undo(sb, tmp_path):
    snaps = SnapshotStore(tmp_path / "snaps")
    ch = sb.plan_write("a.txt", "changed\n")
    row = snaps.apply(sb, ch, "t1", "w1")
    assert (sb.root / "a.txt").read_text() == "changed\n"
    snaps.undo(sb, row["id"])
    assert (sb.root / "a.txt").read_text() == "hello\nworld\n"
    # undo of a created file removes it
    c2 = snaps.apply(sb, sb.plan_write("new.txt", "n"), "t1", "w1")
    snaps.undo(sb, c2["id"])
    assert not (sb.root / "new.txt").exists()


def test_undo_refuses_to_clobber_newer_work(sb, tmp_path):
    snaps = SnapshotStore(tmp_path / "snaps")
    row = snaps.apply(sb, sb.plan_write("a.txt", "agent\n"), "t", "w")
    (sb.root / "a.txt").write_text("user edit\n")
    with pytest.raises(WorkspaceError):
        snaps.undo(sb, row["id"])
    snaps.undo(sb, row["id"], force=True)


def test_delete_is_recoverable(sb, tmp_path):
    snaps = SnapshotStore(tmp_path / "snaps")
    row = snaps.apply(sb, sb.plan_delete("a.txt"), "t", "w")
    assert not (sb.root / "a.txt").exists()
    snaps.undo(sb, row["id"])
    assert (sb.root / "a.txt").read_text() == "hello\nworld\n"


def test_binary_files_refused_for_text_read(sb):
    (sb.root / "bin.dat").write_bytes(b"\x00\x01\x02")
    with pytest.raises(WorkspaceError):
        sb.read_text("bin.dat")
