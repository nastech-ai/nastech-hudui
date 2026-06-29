"""NasTech HUD Web UI — FastAPI backend."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Suppress macOS MallocStackLogging warnings triggered by frequent subprocess spawning
if sys.platform == "darwin":
    os.environ.setdefault("MallocStackLogging", "0")
    os.environ.setdefault("MallocLogFile", "/dev/null")

# Ensure dirs that commonly hold the nastech CLI are on PATH even when the
# server is launched with a minimal environment (systemd, cron, launchd).
# Appended, so an existing PATH ordering is never overridden.
_path_parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
_extra_dirs = [
    d for d in (os.path.expanduser("~/.local/bin"), "/usr/local/bin")
    if d not in _path_parts
]
os.environ["PATH"] = os.pathsep.join(_path_parts + _extra_dirs)

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from .api import (
    state,
    memory,
    sessions,
    skills,
    cron,
    projects,
    health,
    profiles,
    patterns,
    corrections,
    agents,
    timeline,
    snapshots,
    dashboard,
    token_costs,
    cache,
    chat,
    sudo,
    providers,
    gateway,
    model_info,
    plugins,
    replay,
)
from .file_watcher import start_watcher, stop_watcher
from .websocket_manager import ws_manager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan: start/stop file watcher."""
    # Startup
    nastech_dir = os.environ.get("NASTECH_HOME") or os.path.expanduser("~/.nastech")
    await start_watcher(nastech_dir)
    logger.info(f"NasTech HUD started, watching {nastech_dir}")

    yield

    # Shutdown
    await stop_watcher()
    logger.info("NasTech HUD stopped")


app = FastAPI(
    title="NasTech HUD",
    version="0.9.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _static_http_only(scope, receive, send):
    """ASGI wrapper: forward only HTTP scopes to StaticFiles.

    StaticFiles asserts scope["type"] == "http" and crashes on WebSocket
    scopes that leak to the catch-all mount on client disconnect.
    """
    if scope["type"] != "http":
        return
    await _static_app(scope, receive, send)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WebSocket error", exc_info=True)
    finally:
        await ws_manager.disconnect(websocket)


# API routes
app.include_router(state.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(cron.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(patterns.router, prefix="/api")
app.include_router(corrections.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(timeline.router, prefix="/api")
app.include_router(snapshots.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(token_costs.router, prefix="/api")
app.include_router(cache.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(sudo.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(gateway.router, prefix="/api")
app.include_router(model_info.router, prefix="/api")
app.include_router(plugins.router, prefix="/api")
app.include_router(replay.router, prefix="/api")

# Serve frontend static files (after API routes so /api takes priority)
if STATIC_DIR.exists():
    _static_app = StaticFiles(directory=str(STATIC_DIR), html=True)
    app.mount("/", _static_http_only, name="static")


def cli():
    """CLI entry point: nastech-hudui"""
    parser = argparse.ArgumentParser(description="NasTech HUD Web UI")
    parser.add_argument("--port", type=int, default=3001, help="Port (default: 3001)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument(
        "--dev", action="store_true", help="Development mode (auto-reload)"
    )
    parser.add_argument(
        "--nastech-dir", default=None, help="NasTech data directory (default: ~/.nastech)"
    )
    args = parser.parse_args()

    if args.nastech_dir:
        os.environ["NASTECH_HOME"] = args.nastech_dir

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.dev,
    )


if __name__ == "__main__":
    cli()
