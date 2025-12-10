# Terminal MCP

Cross-platform MCP server for managing visible terminal sessions.

## Features

- **Cross-platform**: Supports macOS, Windows, Linux, and WSL
- **Visible terminals**: Opens real terminal windows that users can see and interact with
- **Multiple sessions**: Manage multiple terminal sessions simultaneously
- **Auto-cleanup**: Automatically closes terminals when MCP server stops

## Installation

Since this package is not published on PyPI, install it directly from the repository:

### Option 1: Install from GitHub (recommended)

```bash
uv pip install "git+https://github.com/Hor1zonZzz/terminal-mcp.git"
```

### Option 2: Install from a local clone

```bash
git clone https://github.com/Hor1zonZzz/terminal-mcp.git
cd terminal-mcp
uv pip install -e .
```

## Usage

### Claude Desktop Configuration

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "terminal": {
      "command": "uv",
      "args": ["run", "terminal-mcp"]
    }
  }
}
```

Or if installed globally:

```json
{
  "mcpServers": {
    "terminal": {
      "command": "terminal-mcp"
    }
  }
}
```

## Available Tools

### terminal_create_or_get

Create a new visible terminal window or get an existing one by name.

**Parameters:**
- `name` (optional): Name for the terminal session
- `working_dir` (optional): Working directory for the terminal

**Returns:** Session ID, name, platform, and status message

### terminal_send_input

Send input (command or text) to a terminal.

**Parameters:**
- `session_id`: The terminal session ID
- `text`: The command/text to send

### terminal_get_output

Get the output from a terminal.

**Parameters:**
- `session_id`: The terminal session ID
- `lines` (optional): Number of lines to retrieve (default: 100, max: 1000)

### terminal_list

List all active terminal sessions.

### terminal_close

Close a terminal session.

**Parameters:**
- `session_id`: The terminal session ID to close

## Platform Support

| Platform | Terminal Used |
|----------|---------------|
| macOS | Terminal.app (via AppleScript) |
| Windows | Windows Terminal (wt.exe) or cmd.exe |
| Linux | gnome-terminal, konsole, xfce4-terminal, xterm, etc. |
| WSL | Windows Terminal from WSL |

## How It Works

1. **Terminal Creation**: Opens a real terminal window using platform-specific methods
2. **Communication**: Uses named pipes (Unix) or file polling (Windows) for bidirectional communication
3. **Output Capture**: Logs terminal output to temporary files for retrieval
4. **Cleanup**: Automatically closes all terminals when the MCP server stops (via atexit and signal handlers)

## License

MIT
