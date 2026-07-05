"""Git working-copy status and sync for programs whose source is a git repo.

Programs that declare a ``repo:`` URL are cloned once (``castle program clone``);
this module lets a running castle *see how far behind* a working copy is and pull
later updates. It is intentionally pull-only — it touches files on disk and never
builds, applies, or restarts anything. Making the running artifact reflect the new
code (rebuild a frontend, restart a service) stays an explicit, separate step via
``castle apply`` / ``castle restart``.

Plain ``git`` via subprocess (matching ``castle program clone``); no GitPython.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Bound network calls (fetch/pull) so an unreachable remote can't hang a request.
_FETCH_TIMEOUT = 20.0
_PULL_TIMEOUT = 60.0


@dataclass
class GitStatus:
    """A program working copy's git state. ``ahead``/``behind`` are relative to the
    upstream tracking branch and reflect the *last fetch* (``git_status(fetch=True)``
    refreshes them). ``None`` counts mean "no upstream to compare against"."""

    is_repo: bool
    branch: str | None = None
    upstream: str | None = None
    dirty: bool = False
    ahead: int | None = None
    behind: int | None = None
    detached: bool = False
    error: str | None = None


def _git(
    source: Path, *args: str, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C <source> <args>`` capturing text output."""
    return subprocess.run(
        ["git", "-C", str(source), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def is_git_repo(source: Path | None) -> bool:
    """True when ``source`` is inside a git working tree."""
    if not source or not Path(source).is_dir():
        return False
    try:
        r = _git(
            Path(source), "rev-parse", "--is-inside-work-tree", timeout=_FETCH_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def toplevel(source: Path | None) -> str | None:
    """The absolute path of the git working copy ``source`` lives in, or None.

    The natural identity of a *repo*: several programs whose sources share a
    toplevel are the same working copy (a monorepo). Adopted single-program repos
    are their own toplevel — the N=1 case."""
    if not source or not Path(source).is_dir():
        return None
    try:
        r = _git(Path(source), "rev-parse", "--show-toplevel", timeout=_FETCH_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def remote_url(source: Path | None) -> str | None:
    """The ``origin`` remote URL of the working copy, or None (no remote)."""
    if not is_git_repo(source):
        return None
    r = _git(Path(source), "remote", "get-url", "origin")  # type: ignore[arg-type]
    return r.stdout.strip() or None if r.returncode == 0 else None


def git_status(source: Path | None, fetch: bool = True) -> GitStatus:
    """The working copy's branch/dirty/ahead/behind state.

    ``fetch=True`` runs ``git fetch`` first (bounded, tolerant of an offline remote)
    so ``behind`` reflects the real remote; on fetch failure the counts fall back to
    the last-known values and ``error`` carries the reason. Never raises — a
    non-repo returns ``GitStatus(is_repo=False)`` so callers can just hide the UI.
    """
    if not is_git_repo(source):
        return GitStatus(is_repo=False)
    src = Path(source)  # type: ignore[arg-type]
    st = GitStatus(is_repo=True)

    # Branch (or detached HEAD).
    branch = _git(src, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch == "HEAD":
        st.detached = True
    else:
        st.branch = branch

    # Dirty working tree (staged, unstaged, or untracked).
    st.dirty = bool(_git(src, "status", "--porcelain").stdout.strip())

    # Best-effort refresh from the remote; failure is non-fatal (offline, no remote).
    if fetch:
        try:
            fr = _git(src, "fetch", "--quiet", timeout=_FETCH_TIMEOUT)
            if fr.returncode != 0:
                st.error = (fr.stderr or fr.stdout).strip() or "git fetch failed"
        except subprocess.TimeoutExpired:
            st.error = "git fetch timed out"
        except (OSError, subprocess.SubprocessError) as e:
            st.error = str(e)

    # Upstream tracking branch, then the ahead/behind split against it.
    up = _git(src, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up.returncode == 0 and up.stdout.strip():
        st.upstream = up.stdout.strip()
        counts = _git(src, "rev-list", "--left-right", "--count", "@{u}...HEAD")
        if counts.returncode == 0:
            parts = counts.stdout.split()
            if len(parts) == 2:
                st.behind, st.ahead = int(parts[0]), int(parts[1])
    return st


def head(source: Path | None) -> str | None:
    """The working copy's current commit sha, or None if unavailable. Lets a caller
    tell whether a ``pull`` actually advanced the tree (before != after)."""
    if not is_git_repo(source):
        return None
    r = _git(Path(source), "rev-parse", "HEAD")  # type: ignore[arg-type]
    return r.stdout.strip() or None if r.returncode == 0 else None


def pull(source: Path | None) -> tuple[bool, str]:
    """Fast-forward the working copy to its upstream (``git pull --ff-only``).

    ``--ff-only`` is deliberate: it refuses to merge, so a dirty or diverged tree
    fails cleanly with git's own message instead of creating a merge commit. Returns
    ``(ok, combined_output)``.
    """
    if not is_git_repo(source):
        return False, "not a git repository"
    try:
        r = _git(Path(source), "pull", "--ff-only", timeout=_PULL_TIMEOUT)  # type: ignore[arg-type]
    except subprocess.TimeoutExpired:
        return False, "git pull timed out"
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out
