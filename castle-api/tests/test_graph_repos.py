"""Tests for the /graph diagnostic and /repos (repo-scoped sync) endpoints."""

import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True, env={**os.environ, **_ENV})


def _commit(cwd: Path, fname: str) -> None:
    (cwd / fname).write_text(fname)
    _git(cwd, "add", fname)
    _git(cwd, "commit", "-m", f"add {fname}")


def _setup(work: Path) -> None:
    upstream = work.parent / f"{work.name}-upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, "a.txt")
    _git(work.parent, "clone", "-q", str(upstream), str(work))


class TestGraph:
    def test_graph_shape(self, client: TestClient) -> None:
        resp = client.get("/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert {"repos", "nodes", "edges"} <= body.keys()
        # every node carries the derived predicates
        assert all("functional" in n for n in body["nodes"])


class TestRepos:
    def test_list_and_sync(self, client: TestClient, castle_root: Path) -> None:
        _setup(castle_root / "wired-in")  # program `wired-in` source → <root>/wired-in
        _commit(castle_root / "wired-in-upstream", "b.txt")  # advance remote

        repos = {r["key"]: r for r in client.get("/repos").json()}
        assert "wired-in" in repos
        assert "wired-in" in repos["wired-in"]["programs"]

        gitinfo = client.get("/repos/wired-in/git").json()
        assert gitinfo["is_repo"] is True and gitinfo["behind"] == 1

        synced = client.post("/repos/wired-in/sync").json()
        assert synced["pulled"] is True and "wired-in" in synced["deployments"]
        assert (castle_root / "wired-in" / "b.txt").exists()

    def test_unknown_repo_404(self, client: TestClient) -> None:
        assert client.get("/repos/nope/git").status_code == 404
        assert client.post("/repos/nope/sync").status_code == 404
