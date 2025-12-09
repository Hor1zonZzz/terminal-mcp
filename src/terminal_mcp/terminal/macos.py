"""macOS Terminal.app implementation."""

import asyncio
import os
import uuid
from typing import Optional

from .base import BaseTerminal, TerminalSession


class MacOSTerminal(BaseTerminal):
    """macOS Terminal.app implementation using AppleScript."""

    def __init__(self):
        # Use tmp folder under the project directory for easier management
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self._temp_dir = os.path.join(project_root, "tmp")
        os.makedirs(self._temp_dir, exist_ok=True)
        self._sessions: dict[str, TerminalSession] = {}

    async def create_terminal(
        self, name: Optional[str] = None, working_dir: Optional[str] = None
    ) -> TerminalSession:
        """Create a new Terminal.app window."""
        session_id = str(uuid.uuid4())[:8]
        terminal_name = name or f"Terminal-{session_id}"

        # Create output file, input FIFO, and agent script file
        output_file = os.path.join(self._temp_dir, f"{session_id}_output.log")
        input_pipe = os.path.join(self._temp_dir, f"{session_id}_input.fifo")
        script_file = os.path.join(self._temp_dir, f"{session_id}_agent.sh")

        # Create named pipe
        os.mkfifo(input_pipe)

        # Create empty output file
        open(output_file, "w").close()

        # Build the agent script that will run in the terminal
        working_dir_cmd = ""
        if working_dir:
            working_dir_cmd = f'cd "{working_dir}"\n'

        # The agent script:
        # 1. Redirects all output to the log file (via tee)
        # 2. Starts a background process to read commands from FIFO
        # 3. Provides an interactive prompt for direct user input
        # 4. Cleans up all temp files on exit (regardless of how terminal is closed)
        agent_script = f"""#!/bin/bash
{working_dir_cmd}exec > >(tee -a '{output_file}') 2>&1
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
    rm -f '{script_file}' 2>/dev/null
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
        # Write agent script to a file
        with open(script_file, "w") as f:
            f.write(agent_script)
        os.chmod(script_file, 0o755)

        # AppleScript to open terminal and run the script file
        applescript = f'''
tell application "Terminal"
    activate
    do script "{script_file}"
    set custom title of front window to "{terminal_name}"
end tell
'''

        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            applescript,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

        session = TerminalSession(
            id=session_id,
            name=terminal_name,
            platform="macos",
            input_pipe=input_pipe,
            output_file=output_file,
        )
        self._sessions[session_id] = session
        return session

    async def send_input(self, session: TerminalSession, text: str) -> bool:
        """Send input to the terminal via named pipe."""
        if not session.input_pipe or not os.path.exists(session.input_pipe):
            return False

        try:
            # Write to pipe in a separate thread to avoid blocking the event loop
            def write_to_pipe():
                try:
                    with open(session.input_pipe, 'w') as pipe:
                        pipe.write(text + "\n")
                        pipe.flush()
                    return True
                except (OSError, BrokenPipeError, IOError):
                    return False

            # Run the blocking operation in a thread pool
            result = await asyncio.to_thread(write_to_pipe)
            return result
        except Exception:
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
        """Check if the terminal window is still open."""
        # Check if the named pipe still exists
        if not session.input_pipe or not os.path.exists(session.input_pipe):
            return False

        # Try to check if Terminal.app has the window
        applescript = f'''
tell application "Terminal"
    set windowCount to count of (every window whose custom title is "{session.name}")
    return windowCount
end tell
'''
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                applescript,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            count = int(stdout.decode().strip())
            return count > 0
        except (ValueError, Exception):
            return os.path.exists(session.input_pipe)

    async def close_terminal(self, session: TerminalSession) -> bool:
        """Close the terminal window."""
        # Close the Terminal.app window
        applescript = f'''
tell application "Terminal"
    close (every window whose custom title is "{session.name}")
end tell
'''
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                applescript,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
        except Exception:
            pass

        # Clean up temp files
        try:
            if session.input_pipe and os.path.exists(session.input_pipe):
                os.remove(session.input_pipe)
            if session.output_file and os.path.exists(session.output_file):
                os.remove(session.output_file)
            # Also clean up the agent script
            script_file = session.input_pipe.replace("_input.fifo", "_agent.sh") if session.input_pipe else None
            if script_file and os.path.exists(script_file):
                os.remove(script_file)
        except (OSError, PermissionError):
            pass

        # Remove from sessions
        if session.id in self._sessions:
            del self._sessions[session.id]

        return True

    def cleanup(self):
        """Clean up all sessions and temp files."""
        # Use a new event loop since this may be called from atexit
        # where the main event loop may no longer exist
        for session in list(self._sessions.values()):
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.close_terminal(session))
                loop.close()
            except Exception:
                pass
        # Note: We don't delete the tmp directory itself since it's a fixed location
        # The close_terminal method already cleans up individual session files
