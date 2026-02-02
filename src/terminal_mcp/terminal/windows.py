"""Windows terminal implementation using ConPTY via pywinpty."""

import asyncio
import collections
import uuid
from typing import Optional

from winpty import PTY

from .base import BaseTerminal, TerminalSession


class WindowsTerminal(BaseTerminal):
    """Windows terminal implementation using ConPTY (pywinpty)."""

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}
        self._ptys: dict[str, PTY] = {}
        self._buffers: dict[str, collections.deque] = {}
        self._reader_tasks: dict[str, asyncio.Task] = {}

    async def _read_pty_output(self, session_id: str) -> None:
        """Background task that continuously reads PTY output into a deque buffer."""
        pty = self._ptys.get(session_id)
        buf = self._buffers.get(session_id)
        if not pty or buf is None:
            return

        loop = asyncio.get_event_loop()
        while True:
            try:
                data = await loop.run_in_executor(
                    None, lambda: pty.read(blocking=False)
                )
            except Exception:
                break
            if data:
                text = data.replace("\r\n", "\n").replace("\r", "")
                for line in text.split("\n"):
                    buf.append(line)
            else:
                await asyncio.sleep(0.05)

    async def create_terminal(
        self, name: Optional[str] = None, working_dir: Optional[str] = None
    ) -> TerminalSession:
        """Create a new terminal using ConPTY."""
        session_id = str(uuid.uuid4())[:8]
        terminal_name = name or f"Terminal-{session_id}"

        pty = PTY(120, 30)
        cwd = working_dir or None
        pty.spawn(r"C:\Windows\System32\cmd.exe", cwd=cwd)

        buf: collections.deque[str] = collections.deque(maxlen=10000)

        self._ptys[session_id] = pty
        self._buffers[session_id] = buf

        task = asyncio.create_task(self._read_pty_output(session_id))
        self._reader_tasks[session_id] = task

        session = TerminalSession(
            id=session_id,
            name=terminal_name,
            platform="windows",
            pid=pty.pid if pty.pid else None,
        )
        self._sessions[session_id] = session
        return session

    async def send_input(self, session: TerminalSession, text: str) -> bool:
        """Send input to the PTY."""
        pty = self._ptys.get(session.id)
        if not pty:
            return False
        try:
            pty.write(text + "\r\n")
            return True
        except Exception:
            return False

    async def get_output(self, session: TerminalSession, lines: int = 100) -> str:
        """Read the last N lines from the output buffer."""
        buf = self._buffers.get(session.id)
        if buf is None:
            return ""
        snapshot = list(buf)[-lines:]
        return "\n".join(snapshot)

    async def is_session_alive(self, session: TerminalSession) -> bool:
        """Check if the PTY process is still running."""
        pty = self._ptys.get(session.id)
        if not pty:
            return False
        try:
            return pty.isalive()
        except Exception:
            return False

    async def close_terminal(self, session: TerminalSession) -> bool:
        """Close the PTY and clean up resources."""
        sid = session.id

        task = self._reader_tasks.pop(sid, None)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        pty = self._ptys.pop(sid, None)
        if pty:
            try:
                pty.write("exit\r\n")
            except Exception:
                pass
            # Let GC clean up the PTY object
            del pty

        self._buffers.pop(sid, None)
        self._sessions.pop(sid, None)
        return True

    def cleanup(self):
        """Synchronous cleanup for atexit — close all PTYs."""
        for sid, pty in list(self._ptys.items()):
            try:
                pty.write("exit\r\n")
            except Exception:
                pass
        self._ptys.clear()
        self._buffers.clear()
        self._sessions.clear()
        self._reader_tasks.clear()
