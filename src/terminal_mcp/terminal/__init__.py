"""Terminal implementations for different platforms."""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseTerminal


def is_wsl() -> bool:
    """Check if running inside WSL."""
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except (FileNotFoundError, PermissionError):
        return False


def get_terminal_implementation() -> "BaseTerminal":
    """Get the appropriate terminal implementation for the current platform.

    Returns:
        BaseTerminal implementation for the current platform.

    Raises:
        RuntimeError: If the platform is not supported.
    """
    if sys.platform == "darwin":
        from .macos import MacOSTerminal

        return MacOSTerminal()
    elif sys.platform == "win32":
        from .windows import WindowsTerminal

        return WindowsTerminal()
    elif sys.platform.startswith("linux"):
        if is_wsl():
            from .wsl import WSLTerminal

            return WSLTerminal()
        else:
            from .linux import LinuxTerminal

            return LinuxTerminal()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
