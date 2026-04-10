"""
UI Server for Live-Vision-Narrator.

This FastAPI app serves the UI (HTML, CSS, JavaScript) from the `ui/` directory.
It also proxies `/api/*` requests to the backend API server (reverse proxy).
This allows the UI to be served from a different host/port while seamlessly
accessing the API without CORS issues (same-origin requests from browser perspective).

Run with: python ui.py
or: uvicorn ui:app --reload --port 8001
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pathlib import Path
import uvicorn
from config import get_settings
import logging
import httpx
import re

# Load settings early so logging can be configured
settings = get_settings()
# Configure logging for UI server
log_level_val = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(level=log_level_val)
for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "httpx"):
    try:
        logging.getLogger(logger_name).setLevel(log_level_val)
    except Exception:
        pass

app = FastAPI(title="Live-Vision-Narrator UI")

# Mount static files (CSS, JS, etc.)
ui_dir = Path(__file__).parent / "ui"
app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    """Serve the main UI HTML."""
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return {"error": "index.html not found"}
    return FileResponse(index_path)


@app.get("/ui", response_class=FileResponse)
async def ui():
    """Serve the main UI HTML (alternative route)."""
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return {"error": "index.html not found"}
    return FileResponse(index_path)


@app.get("/health")
async def health():
    """Simple health check."""
    return {"ok": True, "service": "ui"}


@app.get("/api-config")
async def api_config():
    """Provide API configuration to UI.

    Returns the API base URL as /api (relative path), which will be served
    by this UI server as a reverse proxy. This avoids CORS issues.
    """
    settings = get_settings()
    return {
        "api_base_url": "/api",  # Use relative path for reverse proxied API
        "api_port": settings.api_port,
    }


# ============================================================================
# API REVERSE PROXY
# ============================================================================

# Create a persistent async HTTP client for proxying to the backend API
_api_client = None

def get_api_client() -> httpx.AsyncClient:
    """Get or create the persistent API client.

    Uses api_local_host (not host_ip) to connect to the backend API.
    host_ip is for server binding (0.0.0.0 = all interfaces).
    api_local_host is for client connections (127.0.0.1 = localhost).
    """
    global _api_client
    if _api_client is None:
        settings = get_settings()
        # Use api_local_host for connecting to backend API
        # (0.0.0.0 cannot be used as a connection target, only as a bind address)
        _api_client = httpx.AsyncClient(
            base_url=f"http://{settings.api_local_host}:{settings.api_port}",
            timeout=None  # No timeout for streaming responses
        )
    return _api_client


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_api(request: Request, path: str):
    """
    Reverse proxy for API requests.

    This endpoint catches all /api/* requests and forwards them to the backend
    API server. This allows the UI and API to be served from the same origin
    (UI perspective), eliminating CORS issues.

    Supports streaming responses (e.g., /api/generate/stream).
    """
    client = get_api_client()

    # Prepare the request to forward to the backend API
    url = f"/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Copy headers, excluding host-related ones
    headers = {
        key: value for key, value in request.headers.items()
        if key.lower() not in ("host", "connection")
    }

    try:
        # Read the request body if present
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None

        # Detect streaming endpoints by path
        is_streaming = "stream" in request.url.path

        # For streaming endpoints use httpx's stream context manager so the
        # response body is not fully loaded into memory.
        if is_streaming:
            # Create the stream context manager and enter it so we can access
            # status and headers before returning the StreamingResponse.
            stream_cm = client.stream(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
            resp = await stream_cm.__aenter__()

            async def stream_generator():
                try:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        if chunk:
                            yield chunk
                except Exception as e:
                    logging.error(f"Error streaming response: {e}")
                    # Send an error chunk so the client knows something failed
                    try:
                        yield (json.dumps({"error": str(e)}, ensure_ascii=False) + "\n").encode()
                    except Exception:
                        yield b'{"error":"stream error"}\n'
                finally:
                    # Ensure the response context is closed
                    try:
                        await stream_cm.__aexit__(None, None, None)
                    except Exception:
                        pass

            return StreamingResponse(
                stream_generator(),
                status_code=resp.status_code,
                headers=dict(resp.headers),
                media_type=resp.headers.get("content-type", "application/octet-stream"),
            )

        # Forward non-streaming requests to backend API
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )

        # For JSON responses, extract and return the data (not the raw httpx.Response)
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type or "json" in content_type:
            try:
                data = response.json()
                return JSONResponse(
                    content=data,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                )
            except Exception as e:
                logging.error(f"Failed to parse JSON response: {e}")
                # If JSON parsing fails, return as text
                return response.content.decode("utf-8", errors="replace"), response.status_code

        # For other content types, return the raw bytes
        content = response.content
        await response.aclose()
        return content, response.status_code

    except Exception as e:
        logging.error(f"Error proxying request to {url}: {e}")
        return JSONResponse({"error": f"Failed to reach API: {str(e)}"}, status_code=502)


if __name__ == "__main__":
    uvicorn.run("ui:app", host=settings.ui_ip, port=settings.ui_port, log_level=settings.log_level.lower(), reload=False)
