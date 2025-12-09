"""Linux terminal emulator implementation."""

import asyncio
import os
import signal
import shutil
import uuid
from typing import Optional

from .base import BaseTerminal, TerminalSession

from .base import BaseTerminal, TerminalSession


class LinuxTerminal(BaseTerminal):
    """Linux terminal implementation supporting multiple terminal emulators."""

    # Terminal emulators in order of preference
    TERMINAL_EMULATORS = [
        ("gnome-terminal", ["gnome-terminal", "--", "bash", "-c"]),
        ("konsole", ["konsole", "-e", "bash", "-c"]),
        ("xfce4-terminal", ["xfce4-terminal", "-e"]),
        ("mate-terminal", ["mate-terminal", "-e"]),
        ("lxterminal", ["lxterminal", "-e"]),
        ("xterm", ["xterm", "-hold", "-e", "bash", "-c"]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-c"]),
    ]

    def __init__(self):
        # Use tmp folder under the project directory for easier management
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self._temp_dir = os.path.join(project_root, "tmp")
        os.makedirs(self._temp_dir, exist_ok=True)
        self._sessions: dict[str, TerminalSession] = {}
        self._terminal_cmd = self._detect_terminal()

    def _detect_terminal(self) -> list[str]:
        """Detect available terminal emulator."""
        for name, cmd in self.TERMINAL_EMULATORS:
            if shutil.which(name):
                return cmd
        raise RuntimeError(
            "No supported terminal emulator found. "
            "Please install one of: gnome-terminal, konsole, xfce4-terminal, "
            "mate-terminal, lxterminal, xterm"
        )

    async def create_terminal(
        self, name: Optional[str] = None, working_dir: Optional[str] = None
    ) -> TerminalSession:
        """Create a new terminal window."""
        session_id = str(uuid.uuid4())[:8]
        terminal_name = name or f"Terminal-{session_id}"

        # Create named pipe and output file
        input_pipe = os.path.join(self._temp_dir, f"{session_id}_input.fifo")
        output_file = os.path.join(self._temp_dir, f"{session_id}_output.log")
        pid_file = os.path.join(self._temp_dir, f"{session_id}.pid")

        os.mkfifo(input_pipe)
        open(output_file, "w").close()

        # Working directory setup
        cwd = working_dir if working_dir else os.getcwd()

        # Agent script with both FIFO monitoring and interactive input
        # Cleans up all temp files on exit (regardless of how terminal is closed)
        agent_script = f"""
cd '{cwd}'
exec > >(tee -a '{output_file}') 2>&1
echo $$ > '{pid_file}'
echo "Terminal MCP Agent Started (Session: {session_id})"
echo "Working directory: $(pwd)"
echo "You can type commands directly or they will be received via MCP."
echo ""

# Background process to read from FIFO (for MCP commands)
(
    while true; do
        if read -r cmd < '{input_pipe}'; then
            if [ -n "$cmd" ]; then
                echo "$ $cmd"
                eval "$cmd"
            fi
        fi
    done
) &
FIFO_PID=$!

# Cleanup function - removes all temp files when terminal exits
cleanup() {{
    kill $FIFO_PID 2>/dev/null
    rm -f '{input_pipe}' 2>/dev/null
    rm -f '{output_file}' 2>/dev/null
    rm -f '{pid_file}' 2>/dev/null
    exit 0
}}
trap cleanup EXIT INT TERM

# Interactive prompt for direct user input
while true; do
    read -p "> " user_cmd
    if [ -n "$user_cmd" ]; then
        echo "$ $user_cmd"
        eval "$user_cmd"
    fi
done
"""

        # Build command based on terminal emulator
        # For xfce4-terminal, the -e option takes the whole command as one arg
        if "xfce4-terminal" in self._terminal_cmd[0]:
            cmd = self._terminal_cmd + [f'bash -c "{agent_script}"']
        else:
            cmd = self._terminal_cmd + [agent_script]

        # Start the terminal process
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait a bit for the agent to start and write PID
        await asyncio.sleep(0.5)

        # Read the agent's PID
        agent_pid = None
        try:
            if os.path.exists(pid_file):
                with open(pid_file, "r") as f:
                    agent_pid = int(f.read().strip())
        except (ValueError, FileNotFoundError):
            pass

        session = TerminalSession(
            id=session_id,
            name=terminal_name,
            platform="linux",
            pid=agent_pid or proc.pid,
            input_pipe=input_pipe,
            output_file=output_file,
        )
        session._pid_file = pid_file  # type: ignore
        self._sessions[session_id] = session
        return session

    async def send_input(self, session: TerminalSession, text: str) -> bool:
        """Send input via named pipe."""
        if not session.input_pipe or not os.path.exists(session.input_pipe):
            return False

        try:
            # Open pipe in non-blocking mode
            fd = os.open(session.input_pipe, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, (text + "\n").encode())
            finally:
                os.close(fd)
            return True
        except (OSError, BrokenPipeError):
            return False

    async def get_output(self, session: TerminalSession, lines: int = 100) -> str:
        """Read output from the output file."""
        if not session.output_file or not os.path.exists(session.output_file):
            return ""

        try:
            with open(session.output_file, "r") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
        except (FileNotFoundError, PermissionError):
            return ""

    async def is_session_alive(self, session: TerminalSession) -> bool:
        """Check if the terminal process is still running."""
        if not session.pid:
            return False

        try:
            # Check if process exists
            os.kill(session.pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    async def close_terminal(self, session: TerminalSession) -> bool:
        """Close the terminal."""
        if session.pid:
            try:
                # Send SIGTERM to the process group
                os.killpg(os.getpgid(session.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

            try:
                # Also try to kill just the process
                os.kill(session.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

        # Clean up temp files
        try:
            if session.input_pipe and os.path.exists(session.input_pipe):
                os.remove(session.input_pipe)
            if session.output_file and os.path.exists(session.output_file):
                os.remove(session.output_file)
            pid_file = getattr(session, "_pid_file", None)
            if pid_file and os.path.exists(pid_file):
                os.remove(pid_file)
        except (OSError, PermissionError):
            pass

        # Remove from sessions
        if session.id in self._sessions:
            del self._sessions[session.id]

        return True

    def cleanup(self):
        """Clean up all sessions and temp files."""
        for session in list(self._sessions.values()):
            if session.pid:
                try:
                    os.killpg(os.getpgid(session.pid), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    os.kill(session.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
        # Note: We don't delete the tmp directory itself since it's a fixed location
