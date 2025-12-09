"""Windows terminal implementation."""

import asyncio
import os
import subprocess
import uuid
from typing import Optional

from .base import BaseTerminal, TerminalSession


class WindowsTerminal(BaseTerminal):
    """Windows terminal implementation supporting Windows Terminal and cmd.exe."""

    def __init__(self):
        # Use tmp folder under the project directory for easier management
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self._temp_dir = os.path.join(project_root, "tmp")
        os.makedirs(self._temp_dir, exist_ok=True)
        self._sessions: dict[str, TerminalSession] = {}
        self._use_windows_terminal = self._check_windows_terminal()

    def _check_windows_terminal(self) -> bool:
        """Check if Windows Terminal is installed."""
        try:
            result = subprocess.run(
                ["where", "wt.exe"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    async def create_terminal(
        self, name: Optional[str] = None, working_dir: Optional[str] = None
    ) -> TerminalSession:
        """Create a new terminal window."""
        session_id = str(uuid.uuid4())[:8]
        terminal_name = name or f"Terminal-{session_id}"

        # Create communication files
        input_file = os.path.join(self._temp_dir, f"{session_id}_input.txt")
        output_file = os.path.join(self._temp_dir, f"{session_id}_output.log")
        marker_file = os.path.join(self._temp_dir, f"{session_id}_running.marker")

        # Create empty files
        open(input_file, "w").close()
        open(output_file, "w").close()
        open(marker_file, "w").close()

        # Create agent batch script
        agent_bat = os.path.join(self._temp_dir, f"{session_id}_agent.bat")
        with open(agent_bat, "w") as f:
            f.write(
                self._create_agent_bat(
                    input_file, output_file, marker_file, working_dir
                )
            )

        # Start terminal
        if self._use_windows_terminal:
            # Use Windows Terminal
            cmd = [
                "wt.exe",
                "-w",
                "0",
                "nt",
                "--title",
                terminal_name,
                "cmd.exe",
                "/k",
                agent_bat,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        else:
            # Use traditional cmd.exe with start command
            cmd = f'start "{terminal_name}" cmd.exe /k "{agent_bat}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )

        session = TerminalSession(
            id=session_id,
            name=terminal_name,
            platform="windows",
            pid=proc.pid,
            input_pipe=input_file,
            output_file=output_file,
        )
        # Store marker file path in session for cleanup
        session._marker_file = marker_file  # type: ignore
        session._agent_bat = agent_bat  # type: ignore
        self._sessions[session_id] = session
        return session

    def _create_agent_bat(
        self,
        input_file: str,
        output_file: str,
        marker_file: str,
        working_dir: Optional[str] = None,
    ) -> str:
        """Create Windows agent batch script."""
        cd_cmd = f'cd /d "{working_dir}"' if working_dir else ""

        return f"""@echo off
setlocal EnableDelayedExpansion
{cd_cmd}
echo Terminal MCP Agent Started (Session ID in filename) >> "{output_file}"
echo Working directory: %CD% >> "{output_file}"
echo.

:loop
    if not exist "{marker_file}" (
        echo Session terminated >> "{output_file}"
        exit /b 0
    )

    set "cmd="
    for /f "usebackq delims=" %%i in ("{input_file}") do set "cmd=%%i"

    if defined cmd (
        echo. > "{input_file}"
        echo ^> !cmd! >> "{output_file}"
        echo ^> !cmd!
        cmd /c "!cmd!" >> "{output_file}" 2>&1
        echo. >> "{output_file}"
    )

    timeout /t 1 /nobreak > nul
goto loop
"""

    async def send_input(self, session: TerminalSession, text: str) -> bool:
        """Send input via file."""
        if not session.input_pipe or not os.path.exists(session.input_pipe):
            return False

        try:
            with open(session.input_pipe, "w") as f:
                f.write(text)
            return True
        except (OSError, PermissionError):
            return False

    async def get_output(self, session: TerminalSession, lines: int = 100) -> str:
        """Read output from file."""
        if not session.output_file or not os.path.exists(session.output_file):
            return ""

        try:
            with open(session.output_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
        except (FileNotFoundError, PermissionError):
            return ""

    async def is_session_alive(self, session: TerminalSession) -> bool:
        """Check if session is alive by checking marker file."""
        marker_file = getattr(session, "_marker_file", None)
        if marker_file:
            return os.path.exists(marker_file)
        return False

    async def close_terminal(self, session: TerminalSession) -> bool:
        """Close terminal by removing marker file."""
        # Remove marker file to signal the batch script to exit
        marker_file = getattr(session, "_marker_file", None)
        if marker_file and os.path.exists(marker_file):
            try:
                os.remove(marker_file)
            except OSError:
                pass

        # Wait a bit for the batch script to notice and exit
        await asyncio.sleep(2)

        # Clean up temp files
        try:
            if session.input_pipe and os.path.exists(session.input_pipe):
                os.remove(session.input_pipe)
            if session.output_file and os.path.exists(session.output_file):
                os.remove(session.output_file)
            agent_bat = getattr(session, "_agent_bat", None)
            if agent_bat and os.path.exists(agent_bat):
                os.remove(agent_bat)
        except (OSError, PermissionError):
            pass

        # Remove from sessions
        if session.id in self._sessions:
            del self._sessions[session.id]

        return True

    def cleanup(self):
        """Clean up all sessions and temp files."""
        for session in list(self._sessions.values()):
            # Synchronous cleanup for atexit
            marker_file = getattr(session, "_marker_file", None)
            if marker_file and os.path.exists(marker_file):
                try:
                    os.remove(marker_file)
                except OSError:
                    pass
        # Note: We don't delete the tmp directory itself since it's a fixed location
