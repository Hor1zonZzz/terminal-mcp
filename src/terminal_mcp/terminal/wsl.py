"""WSL terminal implementation - opens terminals on Windows side."""

import asyncio
import os
import subprocess
import tempfile
import uuid
from typing import Optional

from .base import BaseTerminal, TerminalSession


class WSLTerminal(BaseTerminal):
    """WSL terminal implementation that opens Windows terminals from WSL."""

    def __init__(self):
        # Try to use tmp folder under the project directory for easier management
        # Fall back to Windows temp if project is not accessible from Windows
        self._temp_dir = self._get_temp_dir()
        self._sessions: dict[str, TerminalSession] = {}
        self._use_windows_terminal = self._check_windows_terminal()

    def _get_temp_dir(self) -> str:
        """Get a temp directory accessible from both WSL and Windows."""
        # First, try to use project's tmp directory
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        project_tmp = os.path.join(project_root, "tmp")
        
        # Check if project is on a Windows-accessible path (e.g., /mnt/c/...)
        if project_root.startswith("/mnt/"):
            os.makedirs(project_tmp, exist_ok=True)
            return project_tmp
        
        # Otherwise, use Windows TEMP directory
        try:
            result = subprocess.run(
                ["cmd.exe", "/c", "echo %TEMP%"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            win_temp = result.stdout.strip()
            if win_temp and "%" not in win_temp:
                # Convert Windows path to WSL path
                wsl_path = self._windows_to_wsl_path(win_temp)
                temp_dir = os.path.join(wsl_path, f"terminal_mcp_{uuid.uuid4().hex[:8]}")
                os.makedirs(temp_dir, exist_ok=True)
                return temp_dir
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Fallback to /mnt/c/temp
        temp_dir = f"/mnt/c/temp/terminal_mcp_{uuid.uuid4().hex[:8]}"
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir

    def _windows_to_wsl_path(self, win_path: str) -> str:
        """Convert Windows path to WSL path."""
        try:
            result = subprocess.run(
                ["wslpath", "-u", win_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Manual conversion fallback
            path = win_path.replace("\\", "/")
            if len(path) >= 2 and path[1] == ":":
                drive = path[0].lower()
                return f"/mnt/{drive}{path[2:]}"
            return path

    def _wsl_to_windows_path(self, wsl_path: str) -> str:
        """Convert WSL path to Windows path."""
        try:
            result = subprocess.run(
                ["wslpath", "-w", wsl_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Manual conversion fallback
            if wsl_path.startswith("/mnt/"):
                parts = wsl_path[5:].split("/", 1)
                drive = parts[0].upper()
                rest = parts[1] if len(parts) > 1 else ""
                return f"{drive}:\\{rest.replace('/', '\\')}"
            return wsl_path

    def _check_windows_terminal(self) -> bool:
        """Check if Windows Terminal is installed."""
        try:
            result = subprocess.run(
                ["cmd.exe", "/c", "where wt.exe"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    async def create_terminal(
        self, name: Optional[str] = None, working_dir: Optional[str] = None
    ) -> TerminalSession:
        """Create a new Windows terminal from WSL."""
        session_id = str(uuid.uuid4())[:8]
        terminal_name = name or f"Terminal-{session_id}"

        # Create communication files (in WSL-accessible Windows temp)
        input_file = os.path.join(self._temp_dir, f"{session_id}_input.txt")
        output_file = os.path.join(self._temp_dir, f"{session_id}_output.log")
        marker_file = os.path.join(self._temp_dir, f"{session_id}_running.marker")

        # Create empty files
        open(input_file, "w").close()
        open(output_file, "w").close()
        open(marker_file, "w").close()

        # Convert paths to Windows format for the batch script
        win_input_file = self._wsl_to_windows_path(input_file)
        win_output_file = self._wsl_to_windows_path(output_file)
        win_marker_file = self._wsl_to_windows_path(marker_file)

        # Handle working directory
        win_working_dir = None
        if working_dir:
            win_working_dir = self._wsl_to_windows_path(working_dir)

        # Create agent batch script
        agent_bat = os.path.join(self._temp_dir, f"{session_id}_agent.bat")
        with open(agent_bat, "w") as f:
            f.write(
                self._create_agent_bat(
                    win_input_file, win_output_file, win_marker_file, win_working_dir
                )
            )

        win_agent_bat = self._wsl_to_windows_path(agent_bat)

        # Start terminal using cmd.exe /c
        if self._use_windows_terminal:
            cmd = [
                "cmd.exe",
                "/c",
                "wt.exe",
                "-w",
                "0",
                "nt",
                "--title",
                terminal_name,
                "cmd.exe",
                "/k",
                win_agent_bat,
            ]
        else:
            cmd = [
                "cmd.exe",
                "/c",
                "start",
                terminal_name,
                "cmd.exe",
                "/k",
                win_agent_bat,
            ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        session = TerminalSession(
            id=session_id,
            name=terminal_name,
            platform="wsl",
            pid=proc.pid,
            input_pipe=input_file,
            output_file=output_file,
        )
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
echo Terminal MCP Agent Started (WSL Session) >> "{output_file}"
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
        """Check if session is alive."""
        marker_file = getattr(session, "_marker_file", None)
        if marker_file:
            return os.path.exists(marker_file)
        return False

    async def close_terminal(self, session: TerminalSession) -> bool:
        """Close terminal by removing marker file."""
        marker_file = getattr(session, "_marker_file", None)
        if marker_file and os.path.exists(marker_file):
            try:
                os.remove(marker_file)
            except OSError:
                pass

        # Wait for batch script to notice
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

        if session.id in self._sessions:
            del self._sessions[session.id]

        return True

    def cleanup(self):
        """Clean up all sessions and temp files."""
        import shutil

        for session in list(self._sessions.values()):
            marker_file = getattr(session, "_marker_file", None)
            if marker_file and os.path.exists(marker_file):
                try:
                    os.remove(marker_file)
                except OSError:
                    pass

        # Only delete the temp directory if it's not the project's tmp folder
        # (i.e., if it's a randomly generated Windows temp directory)
        if "terminal_mcp_" in os.path.basename(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass
        # Otherwise, leave the project tmp directory intact
