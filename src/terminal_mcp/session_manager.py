"""Session manager for terminal sessions."""

import asyncio
import atexit
import signal
import sys
from typing import Optional

from .terminal import get_terminal_implementation
from .terminal.base import BaseTerminal, TerminalSession


class SessionManager:
    """Terminal session manager - singleton pattern."""

    _instance: Optional["SessionManager"] = None

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}
        self._terminal: BaseTerminal = get_terminal_implementation()
        self._lock = asyncio.Lock()
        self._cleanup_registered = False
        self._setup_cleanup_handlers()

    @classmethod
    def get_instance(cls) -> "SessionManager":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _setup_cleanup_handlers(self):
        """Set up cleanup handlers for graceful shutdown."""
        if self._cleanup_registered:
            return

        # Register atexit handler
        atexit.register(self._sync_cleanup)

        # Register signal handlers
        if sys.platform != "win32":
            # Unix-like systems
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    original_handler = signal.getsignal(sig)
                    signal.signal(sig, lambda s, f: self._signal_handler(s, f, original_handler))
                except (ValueError, OSError):
                    # Can't set signal handler (e.g., not main thread)
                    pass
        else:
            # Windows
            try:
                signal.signal(signal.SIGTERM, lambda s, f: self._signal_handler(s, f, None))
                signal.signal(signal.SIGINT, lambda s, f: self._signal_handler(s, f, None))
            except (ValueError, OSError):
                pass

        self._cleanup_registered = True

    def _signal_handler(self, signum, frame, original_handler):
        """Handle termination signals."""
        self._sync_cleanup()
        if callable(original_handler):
            original_handler(signum, frame)
        elif original_handler == signal.SIG_DFL:
            sys.exit(0)

    def _sync_cleanup(self):
        """Synchronous cleanup for atexit."""
        # Call the terminal's cleanup method if available
        if hasattr(self._terminal, "cleanup"):
            self._terminal.cleanup()

        # Also try async cleanup
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.cleanup_all())
            loop.close()
        except Exception:
            pass

    async def cleanup_all(self):
        """Clean up all terminal sessions."""
        async with self._lock:
            for session_id, session in list(self._sessions.items()):
                try:
                    await self._terminal.close_terminal(session)
                except Exception:
                    pass
            self._sessions.clear()

    async def create_or_get_terminal(
        self, name: Optional[str] = None, working_dir: Optional[str] = None
    ) -> TerminalSession:
        """Create a new terminal or get an existing one by name.

        Args:
            name: Optional terminal name. If specified and exists, returns existing session.
            working_dir: Optional working directory for the terminal.

        Returns:
            TerminalSession for the created or existing terminal.
        """
        async with self._lock:
            # If name specified, try to find existing session
            if name:
                for session in self._sessions.values():
                    if session.name == name:
                        if await self._terminal.is_session_alive(session):
                            return session
                        else:
                            # Clean up dead session
                            await self._terminal.close_terminal(session)
                            del self._sessions[session.id]
                            break

            # Create new terminal
            session = await self._terminal.create_terminal(name, working_dir)
            self._sessions[session.id] = session
            return session

    async def get_session(self, session_id: str) -> Optional[TerminalSession]:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            TerminalSession if found and alive, None otherwise.
        """
        session = self._sessions.get(session_id)
        if session:
            if await self._terminal.is_session_alive(session):
                return session
            else:
                # Clean up dead session
                async with self._lock:
                    await self._terminal.close_terminal(session)
                    del self._sessions[session_id]
        return None

    async def send_input(self, session_id: str, text: str) -> bool:
        """Send input to a terminal.

        Args:
            session_id: The session ID.
            text: Text to send.

        Returns:
            True if successful, False otherwise.
        """
        session = await self.get_session(session_id)
        if not session:
            return False
        return await self._terminal.send_input(session, text)

    async def get_output(self, session_id: str, lines: int = 100) -> str:
        """Get output from a terminal.

        Args:
            session_id: The session ID.
            lines: Number of lines to retrieve.

        Returns:
            Terminal output as string, or empty string if session not found.
        """
        session = await self.get_session(session_id)
        if not session:
            return ""
        return await self._terminal.get_output(session, lines)

    async def list_sessions(self) -> list[TerminalSession]:
        """List all active terminal sessions.

        Returns:
            List of active TerminalSession objects.
        """
        async with self._lock:
            active_sessions = []
            dead_sessions = []

            for session in self._sessions.values():
                if await self._terminal.is_session_alive(session):
                    active_sessions.append(session)
                else:
                    dead_sessions.append(session)

            # Clean up dead sessions
            for session in dead_sessions:
                await self._terminal.close_terminal(session)
                del self._sessions[session.id]

            return active_sessions

    async def close_session(self, session_id: str) -> bool:
        """Close a specific terminal session.

        Args:
            session_id: The session ID to close.

        Returns:
            True if successful, False if session not found.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            await self._terminal.close_terminal(session)
            del self._sessions[session_id]
            return True
