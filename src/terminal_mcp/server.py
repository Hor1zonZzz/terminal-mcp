"""Terminal MCP Server - Cross-platform terminal management."""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .session_manager import SessionManager

# Initialize the MCP server
mcp = FastMCP("terminal_mcp")


@mcp.tool(
    name="terminal_create_or_get",
    annotations={
        "title": "Create or Get Terminal",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def terminal_create_or_get(
    name: Optional[str] = None, working_dir: Optional[str] = None
) -> dict:
    """Create a new visible terminal window or get an existing one by name.

    The terminal opens in a visible window that the user can interact with directly.
    Commands sent to this terminal will be executed in that visible window.

    Args:
        name: Optional name for the terminal. If a terminal with this name
              already exists and is still alive, it will be returned instead
              of creating a new one.
        working_dir: Optional working directory for the terminal.
                     If not specified, uses the current working directory.

    Returns:
        dict: Contains session_id, name, platform, and a status message.
              Use the session_id for subsequent operations.

    Examples:
        - Create unnamed terminal: terminal_create_or_get()
        - Create named terminal: terminal_create_or_get(name="dev-server")
        - Get existing terminal: terminal_create_or_get(name="dev-server")
    """
    manager = SessionManager.get_instance()
    session = await manager.create_or_get_terminal(name, working_dir)
    return {
        "session_id": session.id,
        "name": session.name,
        "platform": session.platform,
        "message": f"Terminal '{session.name}' is ready (session: {session.id})",
    }


@mcp.tool(
    name="terminal_send_input",
    annotations={
        "title": "Send Input to Terminal",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def terminal_send_input(session_id: str, text: str) -> dict:
    """Send input (command or text) to a terminal.

    The input is sent to the visible terminal window and executed there.
    The user can see the command being executed in real-time.

    Args:
        session_id: The terminal session ID returned by terminal_create_or_get.
        text: The text/command to send. This will be executed as a shell command.

    Returns:
        dict: Contains success status, session_id, and the sent text.

    Examples:
        - Run a command: terminal_send_input(session_id="abc123", text="ls -la")
        - Start a server: terminal_send_input(session_id="abc123", text="npm start")
        - Run Python: terminal_send_input(session_id="abc123", text="python script.py")

    Note:
        The command is executed asynchronously. Use terminal_get_output to
        retrieve the results after the command completes.
    """
    manager = SessionManager.get_instance()
    session = await manager.get_session(session_id)

    if not session:
        return {
            "success": False,
            "error": f"Session '{session_id}' not found. It may have been closed or never existed.",
            "suggestion": "Use terminal_create_or_get to create a new terminal.",
        }

    success = await manager.send_input(session_id, text)
    if success:
        return {
            "success": True,
            "session_id": session_id,
            "sent_text": text,
            "message": f"Command sent to terminal '{session.name}'",
        }
    else:
        return {
            "success": False,
            "session_id": session_id,
            "error": "Failed to send input. The terminal may have been closed.",
        }


@mcp.tool(
    name="terminal_get_output",
    annotations={
        "title": "Get Terminal Output",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def terminal_get_output(session_id: str, lines: int = 100) -> dict:
    """Get the output from a terminal.

    Retrieves the recent output from the terminal's history. This includes
    both command inputs and their outputs.

    Args:
        session_id: The terminal session ID returned by terminal_create_or_get.
        lines: Number of lines to retrieve from the end (default: 100, max: 1000).

    Returns:
        dict: Contains success status, session_id, and the output text.

    Examples:
        - Get last 100 lines: terminal_get_output(session_id="abc123")
        - Get last 50 lines: terminal_get_output(session_id="abc123", lines=50)

    Note:
        Output may have a slight delay as it's captured asynchronously from
        the terminal process.
    """
    manager = SessionManager.get_instance()
    session = await manager.get_session(session_id)

    if not session:
        return {
            "success": False,
            "error": f"Session '{session_id}' not found. It may have been closed or never existed.",
            "suggestion": "Use terminal_create_or_get to create a new terminal.",
        }

    # Clamp lines to reasonable range
    lines = max(1, min(lines, 1000))

    output = await manager.get_output(session_id, lines)
    return {
        "success": True,
        "session_id": session_id,
        "terminal_name": session.name,
        "output": output,
        "lines_requested": lines,
    }


@mcp.tool(
    name="terminal_list",
    annotations={
        "title": "List Terminals",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def terminal_list() -> dict:
    """List all active terminal sessions.

    Returns information about all terminal sessions that are currently
    open and active.

    Returns:
        dict: Contains a list of terminal sessions with their details.
    """
    manager = SessionManager.get_instance()
    sessions = await manager.list_sessions()

    return {
        "count": len(sessions),
        "terminals": [
            {
                "session_id": s.id,
                "name": s.name,
                "platform": s.platform,
            }
            for s in sessions
        ],
    }


@mcp.tool(
    name="terminal_close",
    annotations={
        "title": "Close Terminal",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def terminal_close(session_id: str) -> dict:
    """Close a terminal session.

    Closes the terminal window and cleans up associated resources.

    Args:
        session_id: The terminal session ID to close.

    Returns:
        dict: Contains success status and message.
    """
    manager = SessionManager.get_instance()
    success = await manager.close_session(session_id)

    if success:
        return {
            "success": True,
            "message": f"Terminal session '{session_id}' has been closed.",
        }
    else:
        return {
            "success": False,
            "error": f"Session '{session_id}' not found or already closed.",
        }


def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
