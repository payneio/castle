"""Tests for git working-copy status/sync (core/src/castle_core/git.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from castle_core import git as G

# Identity so commits succeed without touching the user's global git config.
_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_base_env(), **_ENV},
    )


def _base_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def _commit(cwd: Path, fname: str, text: str) -> None:
    (cwd / fname).write_text(text)
    _git(cwd, "add", fname)
    _git(cwd, "commit", "-m", f"add {fname}")


@pytest.fixture
def repos(tmp_path: Path):
    """An `upstream` repo and a `work` clone of it (tracking upstream/main)."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, "a.txt", "one")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(upstream), str(work))
    return upstream, work


def test_non_repo_is_benign(tmp_path: Path) -> None:
    assert G.is_git_repo(tmp_path / "nope") is False
    st = G.git_status(tmp_path / "nope")
    assert st.is_repo is False and st.branch is None
    ok, out = G.pull(tmp_path / "nope")
    assert ok is False and "not a git" in out


def test_status_clean_and_up_to_date(repos) -> None:
    _, work = repos
    st = G.git_status(work, fetch=True)
    assert st.is_repo and st.branch == "main"
    assert st.dirty is False
    assert st.behind == 0 and st.ahead == 0
    assert st.upstream and st.upstream.endswith("main")


def test_behind_then_pull_fast_forwards(repos) -> None:
    upstream, work = repos
    _commit(upstream, "b.txt", "two")  # advance the remote
    st = G.git_status(work, fetch=True)
    assert st.behind == 1 and st.ahead == 0

    ok, out = G.pull(work)
    assert ok is True, out
    assert (work / "b.txt").exists()

    after = G.git_status(work, fetch=True)
    assert after.behind == 0 and after.dirty is False


def test_conflicting_dirty_tree_blocks_pull(repos) -> None:
    """A pull that would overwrite a locally-modified file is refused (ff-only never
    merges), leaving the working copy untouched with git's own message."""
    upstream, work = repos
    _commit(upstream, "a.txt", "upstream change")  # remote touches a.txt...
    (work / "a.txt").write_text("local uncommitted change")  # ...so does the work tree
    assert G.git_status(work, fetch=False).dirty is True

    ok, out = G.pull(work)
    assert ok is False and out  # "local changes would be overwritten"
    assert (work / "a.txt").read_text() == "local uncommitted change"


def test_diverged_branch_blocks_ff_pull(repos) -> None:
    """Local commits the remote doesn't have → --ff-only refuses (no merge commit)."""
    upstream, work = repos
    _commit(upstream, "b.txt", "remote two")
    _commit(work, "c.txt", "local two")  # work now has a commit upstream lacks
    st = G.git_status(work, fetch=True)
    assert st.behind == 1 and st.ahead == 1

    ok, out = G.pull(work)
    assert ok is False and out


def test_detached_head_reported(repos) -> None:
    _, work = repos
    head = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        env={**_base_env(), **_ENV},
    ).stdout.strip()
    _git(work, "checkout", "-q", head)
    st = G.git_status(work, fetch=False)
    assert st.detached is True and st.branch is None
