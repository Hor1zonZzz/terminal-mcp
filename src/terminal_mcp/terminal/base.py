"""Base classes for terminal implementations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import time
import uuid


@dataclass
class TerminalSession:
    """Terminal session data class."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    platform: str = ""
    pid: Optional[int] = None
    input_pipe: Optional[str] = None
    output_file: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    is_alive: bool = True


class BaseTerminal(ABC):
    """Abstract base class for terminal implementations."""

    @abstractmethod
    async def create_terminal(
        self, name: Optional[str] = None, working_dir: Optional[str] = None
    ) -> TerminalSession:
        """Create a new visible terminal window.

        Args:
            name: Optional name for the terminal session.
            working_dir: Optional working directory for the terminal.

        Returns:
            TerminalSession with the session details.
        """
        pass

    @abstractmethod
    async def send_input(self, session: TerminalSession, text: str) -> bool:
        """Send input to the terminal.

        Args:
            session: The terminal session to send input to.
            text: The text to send.

        Returns:
            True if successful, False otherwise.
        """
        pass

    @abstractmethod
    async def get_output(self, session: TerminalSession, lines: int = 100) -> str:
        """Get output from the terminal.

        Args:
            session: The terminal session to get output from.
            lines: Number of lines to retrieve.

        Returns:
            The terminal output as a string.
        """
        pass

    @abstractmethod
    async def is_session_alive(self, session: TerminalSession) -> bool:
        """Check if the terminal session is still alive.

        Args:
            session: The terminal session to check.

        Returns:
            True if alive, False otherwise.
        """
        pass

    @abstractmethod
    async def close_terminal(self, session: TerminalSession) -> bool:
        """Close the terminal.

        Args:
            session: The terminal session to close.

        Returns:
            True if successful, False otherwise.
        """
        pass
