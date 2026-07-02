"""Live agent/terminal session registry.

A session is a running terminal (an agent CLI or a shell) whose lifetime is
decoupled from any WebSocket connection — closing a tab detaches, it does not
kill the process. Sessions can be listed, re-attached (resumed) by id, and
explicitly terminated.

Two backends behind one interface, chosen at startup:

- **tmux** (default when `tmux` is on PATH): each session is a tmux session, so
  it **survives a castle-api restart** and is rediscoverable. The tmux server is
  started inside its own systemd scope so it isn't in castle-api's cgroup (which
  systemd would kill on restart); tmux's own systemd integration puts each pane
  in its own scope too. Each WebSocket is a `tmux attach` client, so multi-client
  and repaint-on-attach come for free.
- **memory** (fallback when tmux is absent, or `CASTLE_API_AGENT_BACKEND=memory`):
  castle-api owns the pty directly and fans output out to subscribers with a
  scrollback buffer. Simpler, but sessions die on restart.

The WebSocket handler is backend-agnostic: it calls `manager.create/get_info/
list/close`, then `manager.attach(id)` and drives the returned `Attachment`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from typing import Protocol

from castle_core.config import CASTLE_HOME

from castle_api.pty_session import PtySession

logger = logging.getLogger(__name__)

_SCROLLBACK_BYTES = 256 * 1024  # memory backend replay cap
_EXITED_TTL = 3600  # memory backend: reap exited sessions after this


class Attachment(Protocol):
    """One WebSocket's live view of a session."""

    def reader(self) -> AsyncIterator[bytes]: ...
    def write(self, data: bytes) -> None: ...
    def resize(self, cols: int, rows: int) -> None: ...
    async def aclose(self) -> None: ...


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class _MemSession:
    def __init__(self, sid: str, agent: str, command: str, cwd: str) -> None:
        self.id = sid
        self.agent = agent
        self.command = command
        self.cwd = cwd
        self.created_at = time.time()
        self.pty: PtySession | None = None
        self.scrollback = bytearray()
        self.subscribers: set[asyncio.Queue[bytes | None]] = set()
        self.exited = False
        self.exit_code: int | None = None
        self.exited_at: float | None = None

    def _on_output(self, data: bytes) -> None:
        self.scrollback.extend(data)
        if len(self.scrollback) > _SCROLLBACK_BYTES:
            del self.scrollback[: len(self.scrollback) - _SCROLLBACK_BYTES]
        for q in list(self.subscribers):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                self.subscribers.discard(q)

    def _on_exit(self) -> None:
        self.exited = True
        self.exit_code = self.pty.proc.returncode if self.pty else None
        self.exited_at = time.time()
        for q in list(self.subscribers):
            q.put_nowait(None)

    @property
    def running(self) -> bool:
        return not self.exited and self.pty is not None and self.pty.running

    def info(self) -> dict:
        return {
            "id": self.id,
            "agent": self.agent,
            "command": self.command,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "running": self.running,
            "exited": self.exited,
            "exit_code": self.exit_code,
            "cols": self.pty.cols if self.pty else None,
            "rows": self.pty.rows if self.pty else None,
            "clients": len(self.subscribers),
        }


class _MemAttachment:
    def __init__(
        self, session: _MemSession, q: asyncio.Queue[bytes | None], snap: bytes
    ):
        self._s = session
        self._q = q
        self._snap = snap

    async def reader(self) -> AsyncIterator[bytes]:
        if self._snap:
            yield self._snap
        while (chunk := await self._q.get()) is not None:
            yield chunk

    def write(self, data: bytes) -> None:
        if self._s.pty:
            self._s.pty.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self._s.pty:
            self._s.pty.resize(cols, rows)

    async def aclose(self) -> None:
        self._s.subscribers.discard(self._q)


class MemoryManager:
    backend = "memory"

    def __init__(self) -> None:
        self._sessions: dict[str, _MemSession] = {}

    def _reap(self) -> None:
        now = time.time()
        for sid in [
            s.id
            for s in self._sessions.values()
            if s.exited and s.exited_at and now - s.exited_at > _EXITED_TTL
        ]:
            self._sessions.pop(sid, None)

    async def create(
        self,
        agent: str,
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        cols: int,
        rows: int,
    ) -> str:
        self._reap()
        sid = uuid.uuid4().hex[:12]
        s = _MemSession(sid, agent, shlex.join(argv), cwd)
        s.pty = await PtySession.start(
            argv[0],
            args=argv[1:],
            cwd=cwd or None,
            env=env,
            cols=cols,
            rows=rows,
            on_output=s._on_output,
            on_exit=s._on_exit,
        )
        self._sessions[sid] = s
        return sid

    async def get_info(self, sid: str) -> dict | None:
        s = self._sessions.get(sid)
        return s.info() if s else None

    async def list(self) -> list[dict]:
        self._reap()
        return [
            s.info()
            for s in sorted(
                self._sessions.values(), key=lambda s: s.created_at, reverse=True
            )
        ]

    async def attach(self, sid: str, cols: int, rows: int) -> Attachment | None:
        s = self._sessions.get(sid)
        if s is None or not s.running or s.pty is None:
            return None
        # Subscribe + snapshot atomically (no await between → the output callback,
        # in this same loop, can't interleave), so replay has no gap/dup.
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        s.subscribers.add(q)
        snap = bytes(s.scrollback)
        s.pty.resize(cols, rows)
        return _MemAttachment(s, q, snap)

    async def close(self, sid: str) -> bool:
        s = self._sessions.pop(sid, None)
        if s is None:
            return False
        if s.pty:
            await s.pty.close()
        for q in list(s.subscribers):
            q.put_nowait(None)
        return True

    async def close_all(self) -> None:
        for sid in list(self._sessions):
            await self.close(sid)


# ---------------------------------------------------------------------------
# tmux backend
# ---------------------------------------------------------------------------

_TMUX_SOCK = CASTLE_HOME / "run" / "agents.sock"
_PREFIX = "castle-"
_KEEPALIVE = "__keepalive__"  # hidden session that keeps the isolated server alive


class _TmuxAttachment:
    def __init__(self, pty: PtySession, q: asyncio.Queue[bytes | None]):
        self._pty = pty
        self._q = q

    @classmethod
    async def start(
        cls, tmux_bin: str, sock: str, name: str, cols: int, rows: int
    ) -> _TmuxAttachment:
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        pty = await PtySession.start(
            tmux_bin,
            args=["-S", sock, "attach-session", "-t", name],
            cols=cols,
            rows=rows,
            on_output=lambda d: q.put_nowait(d),
            on_exit=lambda: q.put_nowait(None),
        )
        return cls(pty, q)

    async def reader(self) -> AsyncIterator[bytes]:
        while (chunk := await self._q.get()) is not None:
            yield chunk

    def write(self, data: bytes) -> None:
        self._pty.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._pty.resize(cols, rows)

    async def aclose(self) -> None:
        await self._pty.close()  # kills the attach client → detaches; session lives


class TmuxManager:
    backend = "tmux"

    def __init__(self, tmux_bin: str) -> None:
        self._bin = tmux_bin
        self._sock = str(_TMUX_SOCK)
        self._ready = False
        self._lock = asyncio.Lock()

    async def _raw(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self._bin,
            "-S",
            self._sock,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return (
            proc.returncode or 0,
            out.decode(errors="replace"),
            err.decode(errors="replace"),
        )

    async def _server_running(self) -> bool:
        _, out, err = await self._raw("list-sessions")
        text = (out + err).lower()
        return not any(
            m in text for m in ("no server", "error connecting", "no such file")
        )

    async def _ensure(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            _TMUX_SOCK.parent.mkdir(parents=True, exist_ok=True)
            if not await self._server_running():
                # Start the server inside its OWN systemd scope so it is NOT in
                # castle-api's cgroup (which a restart kills). It must be born with
                # a keepalive session: an empty server races its own empty-exit
                # check against `exit-empty off` and dies, after which a plain
                # `new-session` would restart it inside castle-api's cgroup. The
                # keepalive (a detached `sleep infinity`, name-filtered from
                # listings) guarantees the isolated server persists.
                proc = await asyncio.create_subprocess_exec(
                    "systemd-run",
                    "--user",
                    "--scope",
                    "--quiet",
                    "--collect",
                    self._bin,
                    "-S",
                    self._sock,
                    "new-session",
                    "-d",
                    "-s",
                    _KEEPALIVE,
                    "sleep infinity",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, err = await proc.communicate()
                if proc.returncode != 0 or not await self._server_running():
                    logger.warning(
                        "agent tmux server not isolated (systemd-run: %s); sessions "
                        "will still work but won't survive a castle-api restart",
                        err.decode(errors="replace").strip() or "unknown error",
                    )
            # Clean, terminal-like defaults (idempotent).
            for opt in (
                ("set", "-g", "status", "off"),  # no tmux status bar
                ("set", "-g", "window-size", "latest"),  # newest client's size wins
                ("set", "-g", "escape-time", "0"),
                ("set", "-g", "destroy-unattached", "off"),
                ("set", "-s", "exit-empty", "off"),
            ):
                await self._raw(*opt)
            self._ready = True

    async def create(
        self,
        agent: str,
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        cols: int,
        rows: int,
    ) -> str:
        await self._ensure()
        sid = uuid.uuid4().hex[:12]
        name = f"{_PREFIX}{sid}"
        cmd = shlex.join(argv)  # tmux runs this as the pane's shell-command
        args = [
            "new-session",
            "-d",
            "-s",
            name,
            "-x",
            str(cols),
            "-y",
            str(rows),
        ]
        if cwd:
            args += ["-c", cwd]
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        args += [cmd]
        rc, _, err = await self._raw(*args)
        if rc != 0:
            raise RuntimeError(f"tmux new-session failed: {err.strip()}")
        await self._raw("set-option", "-t", name, "@agent", agent)
        return sid

    async def _list_raw(self) -> list[dict]:
        fmt = "#{session_name}\t#{session_created}\t#{@agent}\t#{session_attached}\t#{window_width}\t#{window_height}"
        rc, out, _ = await self._raw("list-sessions", "-F", fmt)
        if rc != 0:
            return []
        rows: list[dict] = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 6 or not parts[0].startswith(_PREFIX):
                continue
            name, created, agent, attached, w, h = parts[:6]
            rows.append(
                {
                    "id": name[len(_PREFIX) :],
                    "agent": agent or name[len(_PREFIX) :],
                    "command": "",
                    "cwd": "",
                    "created_at": float(created) if created.isdigit() else None,
                    "running": True,
                    "exited": False,
                    "exit_code": None,
                    "cols": int(w) if w.isdigit() else None,
                    "rows": int(h) if h.isdigit() else None,
                    "clients": int(attached) if attached.isdigit() else 0,
                }
            )
        return rows

    async def get_info(self, sid: str) -> dict | None:
        for row in await self._list_raw():
            if row["id"] == sid:
                return row
        return None

    async def list(self) -> list[dict]:
        rows = await self._list_raw()
        rows.sort(key=lambda r: r["created_at"] or 0, reverse=True)
        return rows

    async def attach(self, sid: str, cols: int, rows: int) -> Attachment | None:
        if await self.get_info(sid) is None:
            return None
        return await _TmuxAttachment.start(
            self._bin, self._sock, f"{_PREFIX}{sid}", cols, rows
        )

    async def close(self, sid: str) -> bool:
        rc, _, _ = await self._raw("kill-session", "-t", f"{_PREFIX}{sid}")
        return rc == 0

    async def close_all(self) -> None:
        # No-op: tmux sessions are meant to SURVIVE a castle-api shutdown.
        return None


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def _make_manager() -> MemoryManager | TmuxManager:
    choice = os.environ.get("CASTLE_API_AGENT_BACKEND", "auto").lower()
    tmux_bin = shutil.which("tmux")
    if choice == "memory":
        return MemoryManager()
    if choice == "tmux" and not tmux_bin:
        raise RuntimeError("CASTLE_API_AGENT_BACKEND=tmux but tmux is not on PATH")
    if tmux_bin and choice in ("auto", "tmux"):
        return TmuxManager(tmux_bin)
    return MemoryManager()


manager: MemoryManager | TmuxManager = _make_manager()
