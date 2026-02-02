"""Web server for xterm.js terminal UI via WebSocket."""

import asyncio
import logging
import queue as thread_queue
import threading

from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket
import uvicorn

logger = logging.getLogger(__name__)

WEB_PORT = 8765

TERMINAL_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Terminal – {session_id}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css"/>
  <style>
    html, body {{ margin: 0; padding: 0; height: 100%; background: #000; overflow: hidden; }}
    #terminal {{ height: 100%; }}
  </style>
</head>
<body>
  <div id="terminal"></div>
  <script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js"></script>
  <script>
    const term = new window.Terminal({{ cursorBlink: true, fontSize: 14 }});
    const fitAddon = new window.FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal'));
    fitAddon.fit();
    window.addEventListener('resize', () => fitAddon.fit());

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(proto + '//' + location.host + '/ws/{session_id}');
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {{
      // Send initial resize
      const dims = {{ type: 'resize', cols: term.cols, rows: term.rows }};
      ws.send(JSON.stringify(dims));
    }};

    ws.onmessage = (ev) => {{
      if (typeof ev.data === 'string') {{
        term.write(ev.data);
      }} else {{
        term.write(new Uint8Array(ev.data));
      }}
    }};

    ws.onclose = () => {{
      term.write('\\r\\n[Connection closed]\\r\\n');
    }};

    term.onData((data) => {{
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    }});

    term.onResize(({{ cols, rows }}) => {{
      if (ws.readyState === WebSocket.OPEN) {{
        const dims = {{ type: 'resize', cols, rows }};
        ws.send(JSON.stringify(dims));
      }}
    }});
  </script>
</body>
</html>"""


async def terminal_page(request):
    """Serve the xterm.js HTML page for a terminal session."""
    session_id = request.path_params["session_id"]
    html = TERMINAL_HTML.format(session_id=session_id)
    return HTMLResponse(html)


async def terminal_ws(websocket: WebSocket):
    """WebSocket handler bridging xterm.js to the PTY."""
    session_id = websocket.path_params["session_id"]
    await websocket.accept()

    from .session_manager import SessionManager

    manager = SessionManager.get_instance()
    session = await manager.get_session(session_id)
    if not session:
        await websocket.close(code=1008, reason="Session not found")
        return

    queue = await manager.subscribe_output(session_id)
    if not queue:
        await websocket.close(code=1008, reason="Failed to subscribe")
        return

    async def pty_to_ws():
        """Forward PTY output to WebSocket."""
        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    data = await loop.run_in_executor(
                        None, lambda: queue.get(timeout=0.5)
                    )
                except thread_queue.Empty:
                    continue
                await websocket.send_text(data)
        except Exception:
            pass

    reader_task = asyncio.create_task(pty_to_ws())

    try:
        while True:
            data = await websocket.receive_text()
            # Check if it's a resize message
            if data.startswith("{"):
                try:
                    import json

                    msg = json.loads(data)
                    if msg.get("type") == "resize":
                        # Resize the PTY if supported
                        terminal = manager.get_terminal()
                        pty = terminal._ptys.get(session_id)
                        if pty and hasattr(pty, "set_size"):
                            pty.set_size(msg["cols"], msg["rows"])
                        continue
                except (ValueError, KeyError):
                    pass
            await manager.write_raw(session_id, data)
    except Exception:
        pass
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass
        await manager.unsubscribe_output(session_id, queue)


routes = [
    Route("/terminal/{session_id}", terminal_page),
    WebSocketRoute("/ws/{session_id}", terminal_ws),
]

app = Starlette(routes=routes)


def start_web_server(port: int = WEB_PORT) -> None:
    """Start the web server in a background thread."""

    def _run():
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        server.run()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info(f"Web terminal server started on http://127.0.0.1:{port}")


def get_web_url(session_id: str, port: int = WEB_PORT) -> str:
    """Get the web URL for a terminal session."""
    return f"http://127.0.0.1:{port}/terminal/{session_id}"
