"""Tests for the program git-status / sync endpoints."""

import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

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
        env={**os.environ, **_ENV},
    )


def _commit(cwd: Path, fname: str) -> None:
    (cwd / fname).write_text(fname)
    _git(cwd, "add", fname)
    _git(cwd, "commit", "-m", f"add {fname}")


def _setup_git_program(work: Path) -> None:
    """Make `work` a git clone tracking an `-upstream` repo with one commit."""
    upstream = work.parent / f"{work.name}-upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, "a.txt")
    _git(work.parent, "clone", "-q", str(upstream), str(work))


class TestProgramGit:
    def test_non_git_source_is_benign(self, client: TestClient) -> None:
        """A program whose source isn't a git repo returns is_repo:false, not 500."""
        resp = client.get("/programs/test-tool/git")
        assert resp.status_code == 200
        assert resp.json()["is_repo"] is False

    def test_status_behind_then_sync_pulls(
        self, client: TestClient, castle_root: Path
    ) -> None:
        work = castle_root / "wired-in"  # source: "wired-in" → <root>/wired-in
        _setup_git_program(work)
        _commit(work.parent / "wired-in-upstream", "b.txt")  # advance the remote

        status = client.get("/programs/wired-in/git")
        assert status.status_code == 200
        body = status.json()
        assert body["is_repo"] is True and body["branch"] == "main"
        assert body["behind"] == 1 and body["ahead"] == 0

        synced = client.post("/programs/wired-in/sync")
        assert synced.status_code == 200
        s = synced.json()
        assert s["status"] == "ok" and s["pulled"] is True
        assert "wired-in" in s["deployments"]  # affected deployment surfaced
        assert (work / "b.txt").exists()

        # A second sync is a no-op: nothing pulled, no affected deployments.
        again = client.post("/programs/wired-in/sync").json()
        assert again["pulled"] is False and again["deployments"] == []

    def test_sync_unknown_program_404(self, client: TestClient) -> None:
        assert client.post("/programs/nope/sync").status_code == 404

    def test_sync_non_git_source_400(self, client: TestClient) -> None:
        assert client.post("/programs/test-tool/sync").status_code == 400
