"""Run a command inside a pseudo-terminal and stream it over asyncio.

Castle stays assistant-agnostic: it just launches a command in a real TTY and
shunts raw bytes both ways. The command's own TUI (an agent CLI, a shell, …)
renders exactly as it would in a terminal — Castle never parses its output.

The PTY master is a raw OS fd, not an asyncio stream, so we watch it with
``loop.add_reader`` (no extra thread, no busy-poll). Output is delivered to an
``on_output`` callback (a fan-out layer above can broadcast it to any number of
attached clients and buffer scrollback), so a session's lifetime is decoupled
from any one WebSocket connection. Keystroke writes are tiny, so a plain
``os.write`` is fine.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Apply a terminal window size via TIOCSWINSZ (struct winsize)."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _acquire_controlling_tty() -> None:
    """Child-side setup (preexec), run after the pty slave is dup'd to fd 0/1/2.

    ``setsid()`` starts a new session (own process group, so cleanup can
    ``killpg`` the whole tree). ``TIOCSCTTY`` then makes the slave our
    *controlling terminal* — without it the kernel has no foreground process
    group to deliver ``SIGWINCH`` to, so a later winsize change (a browser resize)
    is silently dropped and the app never reflows. This is what makes live resize
    work, not just the initial size.
    """
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


@dataclass
class PtySession:
    """A child process attached to a pty master.

    Output is pushed to ``on_output(bytes)`` as it arrives and ``on_exit()`` is
    fired once when the child closes the tty. Both run in the event-loop thread.
    """

    proc: asyncio.subprocess.Process
    master_fd: int
    on_output: Callable[[bytes], None] | None = None
    on_exit: Callable[[], None] | None = None
    cols: int = 80
    rows: int = 24
    _closed: bool = field(default=False)

    @classmethod
    async def start(
        cls,
        command: str,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        cols: int = 80,
        rows: int = 24,
        on_output: Callable[[bytes], None] | None = None,
        on_exit: Callable[[], None] | None = None,
    ) -> PtySession:
        """Spawn ``command args`` on a fresh pty, sized ``cols`` x ``rows``."""
        master_fd, slave_fd = pty.openpty()
        # Size the tty before exec so the first TUI render lays out correctly.
        _set_winsize(master_fd, rows, cols)

        proc_env = {**os.environ, "TERM": "xterm-256color"}
        if env:
            proc_env.update(env)

        proc = await asyncio.create_subprocess_exec(
            command,
            *(args or []),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(cwd) if cwd else None,
            env=proc_env,
            # setsid + TIOCSCTTY in the child: own session/group (for killpg) AND
            # the slave as controlling tty (for SIGWINCH resize delivery).
            preexec_fn=_acquire_controlling_tty,
            close_fds=True,
        )
        os.close(slave_fd)  # parent keeps only the master
        os.set_blocking(master_fd, False)

        session = cls(proc=proc, master_fd=master_fd, cols=cols, rows=rows)
        if on_output is not None:
            session.on_output = on_output
        if on_exit is not None:
            session.on_exit = on_exit
        asyncio.get_running_loop().add_reader(master_fd, session._drain_master)
        return session

    def _drain_master(self) -> None:
        """Reader callback: pull available bytes off the master and fan them out."""
        try:
            data = os.read(self.master_fd, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""  # slave closed → child gone
        if not data:
            try:
                asyncio.get_running_loop().remove_reader(self.master_fd)
            except (ValueError, OSError):
                pass
            if self.on_exit is not None:
                self.on_exit()
            return
        if self.on_output is not None:
            self.on_output(data)

    def write(self, data: bytes) -> None:
        """Forward keystroke bytes to the child's tty."""
        try:
            os.write(self.master_fd, data)
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        """Resize the tty (browser terminal changed dimensions)."""
        self.cols, self.rows = cols, rows
        try:
            _set_winsize(self.master_fd, rows, cols)
        except OSError:
            pass

    @property
    def running(self) -> bool:
        return self.proc.returncode is None

    async def close(self) -> None:
        """Kill the whole process group and release the master fd (idempotent)."""
        if self._closed:
            return
        self._closed = True
        try:
            asyncio.get_running_loop().remove_reader(self.master_fd)
        except (ValueError, OSError):
            pass
        if self.proc.returncode is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass
