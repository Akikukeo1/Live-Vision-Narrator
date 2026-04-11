from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path
import os
import json
import re
import time
import logging
import httpx
import sys

from config import get_settings, Settings

# ============================================================================
# APPLICATION & CONFIGURATION SETUP
# ============================================================================

app = FastAPI(title="Ollama Proxy (FastAPI)")

# Configure CORS for UI served from different port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load and attach settings to app state
settings = get_settings()
app.state.settings = settings

# Configure logging based on settings
log_level_val = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(level=log_level_val)
# Ensure uvicorn/fastapi loggers follow configured level as well
for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "httpx"):
    try:
        logging.getLogger(logger_name).setLevel(log_level_val)
    except Exception:
        pass

# ============================================================================
# SYSTEM PROFILE MANAGEMENT
# ============================================================================

# Placeholder SYSTEM variable (can be overridden by loading profiles)
SYSTEM = ""

# Cache for local system profiles: name -> system prompt text
SYSTEM_PROFILES: dict[str, str] = {}

def load_system_profile(name: str) -> str | None:
    """Load and cache a named local system profile (e.g. Modelfile.detailed).

    Only allowed profile names should be loaded. Returns profile text or None.
    """
    if not name:
        return None
    if name in SYSTEM_PROFILES:
        return SYSTEM_PROFILES[name]

    s = app.state.settings
    allowed = {
        "default": Path(s.system_default_file),
        "detailed": Path(s.system_detailed_file),
    }
    path = allowed.get(name)
    if not path or not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        SYSTEM_PROFILES[name] = text
        return text
    except Exception:
        return None


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class GenerateRequest(BaseModel):
    model: str = Field(min_length=1)
    prompt: str
    parameters: dict | None = None
    session_id: str | None = None


class SessionResetRequest(BaseModel):
    session_id: str


class SessionGetRequest(BaseModel):
    session_id: str


# ============================================================================
# PAYLOAD BUILDING & PROCESSING HELPERS
# ============================================================================

def build_payload(req: GenerateRequest) -> dict:
    payload: dict = {"model": req.model, "prompt": req.prompt}
    # Server-only parameter keys that should NOT be forwarded to the model
    server_keys = {"reveal_thoughts", "save_inner", "inner_detail", "system_profile", "system_override"}

    if req.parameters and isinstance(req.parameters, dict):
        # If client requested reveal_thoughts, inform model via prompt prefix
        if bool(req.parameters.get("reveal_thoughts")):
            # Tell the model to include inner-voice and mark the prompt —
            # also set think=true so the model actually emits thinking content.
            payload["prompt"] = "[REVEAL_INNER_VOICE]\n" + payload["prompt"]
            payload.setdefault("options", {})
            payload["options"]["think"] = True
        # Forward client parameters except server-only controls
        params_to_forward = {k: v for k, v in req.parameters.items() if k not in server_keys}
        if params_to_forward:
            payload.update(params_to_forward)
            # Promote options.think to top-level 'think' so Ollama sees it
            opts = payload.get("options")
            if isinstance(opts, dict) and "think" in opts:
                payload["think"] = opts.get("think")

        # If a system profile was requested, try to load it and use it as the system override
        profile = req.parameters.get("system_profile")
        if isinstance(profile, str) and profile.strip():
            profile_text = load_system_profile(profile.strip())
            if profile_text:
                # Only attach the system override if the client explicitly asked for it.
                # We do NOT log the content of the profile.
                payload["system"] = profile_text

    if req.session_id and "context" not in payload:
        ctx = SESSION_CONTEXTS.get(req.session_id)
        if ctx is not None:
            payload["context"] = ctx

    # Respect explicit request parameter, otherwise enforce configured default.
    s = app.state.settings
    payload.setdefault("think", s.default_think)
    options = payload.get("options")
    if isinstance(options, dict):
        options.setdefault("think", s.default_think)
    elif options is None:
        payload["options"] = {"think": s.default_think}
    return payload


def update_session_context(session_id: str | None, data: dict) -> None:
    if not session_id:
        return
    ctx = data.get("context")
    if ctx is not None:
        SESSION_CONTEXTS[session_id] = ctx


def sanitize_response_text(text: str) -> str:
    # Remove common think tags if present in model output.
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned


def should_reveal_thoughts(req: GenerateRequest | None) -> bool:
    """Return True when the client requested to reveal internal thinking/CoT.

    We treat `parameters.reveal_thoughts` truthy as the signal. Accepts None.
    """
    if not req or not req.parameters or not isinstance(req.parameters, dict):
        return False
    return bool(req.parameters.get("reveal_thoughts"))


def append_session_history(session_id: str | None, user_text: str, assistant_text: str) -> None:
    if not session_id:
        return
    history = SESSION_HISTORY.setdefault(session_id, [])
    history.append({"role": "user", "text": user_text})
    history.append({"role": "assistant", "text": assistant_text})
    # Keep only recent history to avoid unbounded memory growth.
    max_items = 40
    if len(history) > max_items:
        SESSION_HISTORY[session_id] = history[-max_items:]


# ============================================================================
# GLOBAL STATE & CLIENT
# ============================================================================

client: httpx.AsyncClient | None = None
SESSION_CONTEXTS: dict[str, list[int]] = {}
SESSION_HISTORY: dict[str, list[dict[str, str]]] = {}
# Per-model usage tracking to detect "first loading" (model not used recently)
MODEL_STATE: dict[str, float] = {}
# Counter for concurrent /generate/stream requests
GENERATE_STREAM_ACTIVE: int = 0


# ============================================================================
# FASTAPI LIFECYCLE EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    global client
    s = app.state.settings
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    logging.info("Application startup complete. MODEL_STATE will be populated on first request per model.")


@app.on_event("shutdown")
async def shutdown_event():
    global client
    if client is not None:
        await client.aclose()


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/health")
async def health():
    # Check minimal connectivity to Ollama
    s = app.state.settings
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(s.ollama_url)
            return {"ok": True, "ollama_status_code": r.status_code}
    except Exception:
        return {"ok": False, "ollama_url": s.ollama_url}


@app.get("/")
async def root():
    return {"ok": True, "endpoints": ["/health", "/generate"]}


@app.post("/generate")
async def generate(req: GenerateRequest):
    global client
    if client is None:
        raise HTTPException(status_code=503, detail="Service not started")

    s = app.state.settings
    payload = build_payload(req)
    # Log whether the request will think / reveal thoughts
    reveal = should_reveal_thoughts(req)
    logging.info("/generate requested think=%s reveal=%s session=%s model=%s", payload.get("think"), reveal, req.session_id, req.model)
    start = time.perf_counter()
    try:
        r = await client.post(f"{s.ollama_url}{s.ollama_generate_path}", json=payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logging.info("/generate session=%s model=%s elapsed_ms=%.1f", req.session_id, req.model, elapsed_ms)
        # PROFILE: mark time immediately after receiving Ollama response
        try:
            checkpoint_recv_generate = time.perf_counter()
        except Exception:
            checkpoint_recv_generate = None
    except Exception as e:
        logging.exception("Error during /generate request")
        raise HTTPException(status_code=500, detail=str(e))

    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    # Return whatever Ollama returns (assumed JSON)
    try:
        data = r.json()
        # Optionally reveal "thinking"/CoT to the client when requested via parameters
        if not reveal:
            data.pop("thinking", None)

        if isinstance(data.get("response"), str):
            if not reveal:
                cleaned = sanitize_response_text(data["response"]) or ""
                # If sanitizing removes all visible text, try to fall back to 'choices' if present
                if not cleaned.strip():
                    choices = data.get("choices")
                    if isinstance(choices, list):
                        parts = [c.get("text") for c in choices if isinstance(c, dict) and c.get("text")]
                        joined = "".join(parts).strip()
                        if joined:
                            data["response"] = joined
                        else:
                            data["response"] = cleaned
                    else:
                        data["response"] = cleaned
                else:
                    data["response"] = cleaned
            else:
                # keep response intact when revealing thoughts
                data["response"] = data["response"]

        # Persist session context and main assistant response
        update_session_context(req.session_id, data)
        if isinstance(data.get("response"), str):
            append_session_history(req.session_id, req.prompt, data["response"])

        # If client requested saving inner thoughts, extract and store them
        save_inner = bool(req.parameters and isinstance(req.parameters, dict) and req.parameters.get("save_inner"))
        if reveal and save_inner:
            thinking_text = None
            # Prefer explicit 'thinking' field
            if isinstance(data.get("thinking"), str):
                thinking_text = data.get("thinking")
            else:
                # Fallback: extract <inner_voice>...</inner_voice> from response
                resp = data.get("response")
                if isinstance(resp, str):
                    m = re.search(r"<inner_voice>([\s\S]*?)</inner_voice>", resp, flags=re.IGNORECASE)
                    if m:
                        thinking_text = m.group(1).strip()
            if thinking_text:
                hist = SESSION_HISTORY.setdefault(req.session_id, [])
                hist.append({"role": "assistant.inner", "text": thinking_text})

        # Surface elapsed time to API clients
        try:
            data["elapsed_ms"] = round(elapsed_ms, 1)
        except Exception:
            pass

        # Profiling: measure time between Ollama response receive and token calculation
        try:
            checkpoint_before_token_generate = time.perf_counter()
            try:
                logging.info("/profile /generate A_ollama_ms=%.2f B_recv_to_preToken_ms=%.2f",
                             elapsed_ms,
                             (checkpoint_before_token_generate - checkpoint_recv_generate) * 1000.0)
            except Exception:
                pass
        except Exception:
            pass

        # Calculate and surface token information
        try:
            token_info = {}
            # Priority 1: Use Ollama's usage if available
            usage = data.get("usage")
            if isinstance(usage, dict):
                token_info["prompt_tokens"] = usage.get("prompt_tokens")
                token_info["completion_tokens"] = usage.get("completion_tokens")
                total = usage.get("total_tokens")
                if total is None and token_info["prompt_tokens"] is not None and token_info["completion_tokens"] is not None:
                    token_info["total_tokens"] = token_info["prompt_tokens"] + token_info["completion_tokens"]
                else:
                    token_info["total_tokens"] = total
                data["tokens"] = token_info
                logging.info("/generate session=%s model=%s tokens_prompt=%s tokens_completion=%s tokens_total=%s",
                req.session_id, req.model, token_info.get("prompt_tokens"), token_info.get("completion_tokens"), token_info.get("total_tokens"))
            else:
                # Priority 2: Calculate locally using tiktoken
                try:
                    import tiktoken
                    enc = None
                    try:
                        enc = tiktoken.encoding_for_model(req.model)
                    except Exception:
                        enc = tiktoken.get_encoding("cl100k_base")

                    prompt_text = req.prompt or ""
                    resp_text = data.get("response") or ""
                    prompt_tokens = len(enc.encode(prompt_text)) if prompt_text else 0
                    response_tokens = len(enc.encode(resp_text)) if resp_text else 0
                    total_tokens = prompt_tokens + response_tokens

                    token_info["prompt_tokens"] = prompt_tokens
                    token_info["response_tokens"] = response_tokens
                    token_info["total_tokens"] = total_tokens
                    data["tokens"] = token_info

                    logging.info("/generate session=%s model=%s tokens_prompt=%s tokens_response=%s tokens_total=%s",
                    req.session_id, req.model, prompt_tokens, response_tokens, total_tokens)
                except ImportError:
                    logging.warning("/generate session=%s model=%s tiktoken not available, skipping token calculation", req.session_id, req.model)
                except Exception as e:
                    logging.warning("/generate session=%s model=%s token calculation failed: %s", req.session_id, req.model, str(e))
        except Exception:
            pass

        return data
    except Exception:
        return {"raw": r.text}


@app.post("/generate/stream")
async def generate_stream(req: GenerateRequest):
    """Stream response from Ollama through to the client.

    This keeps streaming logic separate from the UI and non-streaming endpoint.
    """
    global client, GENERATE_STREAM_ACTIVE
    if client is None:
        raise HTTPException(status_code=503, detail="Service not started")

    GENERATE_STREAM_ACTIVE += 1
    try:
        logging.info("/generate/stream START active_count=%d session=%s model=%s", GENERATE_STREAM_ACTIVE, req.session_id, req.model)

        s = app.state.settings
        payload = build_payload(req)

        try:
            # Keep upstream stream open for as long as StreamingResponse is iterating.
            start = time.perf_counter()
            request = client.build_request("POST", f"{s.ollama_url}{s.ollama_generate_path}", json=payload)
            res = await client.send(request, stream=True)
            # PROFILE: mark time immediately after receiving the upstream stream
            try:
                checkpoint_recv_stream = time.perf_counter()
            except Exception:
                checkpoint_recv_stream = None
            send_ms = (time.perf_counter() - start) * 1000
            logging.info("/generate/stream session=%s model=%s send_ms=%.1f", req.session_id, req.model, send_ms)

            if res.status_code >= 400:
                text = await res.aread()
                await res.aclose()
                raise HTTPException(status_code=res.status_code, detail=text.decode("utf-8", errors="replace"))

            # Log think/reveal for streaming requests too
            reveal = should_reveal_thoughts(req)
            logging.info("/generate/stream requested think=%s reveal=%s session=%s model=%s", payload.get("think"), reveal, req.session_id, req.model)

            async def proxy():
                latest_ctx = None
                assistant_parts: list[str] = []
                thinking_parts: list[str] = []
                first_ms = None
                last_chunk = None
                try:
                    # Surface elapsed time from POST to response start
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    header = {"elapsed_ms": round(elapsed_ms, 1)}
                    logging.info("/generate/stream session=%s model=%s header_elapsed_ms=%.1f", req.session_id, req.model, elapsed_ms)
                    yield (json.dumps(header, ensure_ascii=False) + "\n").encode("utf-8")
                    async for line in res.aiter_lines():
                        if not line:
                            continue
                        # Record time-to-first-chunk
                        if first_ms is None:
                            first_ms = (time.perf_counter() - start) * 1000
                            logging.info("/generate/stream session=%s model=%s first_chunk_ms=%.1f send_ms=%.1f", req.session_id, req.model, first_ms, send_ms)
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue

                        if "context" in obj:
                            latest_ctx = obj["context"]

                        if isinstance(obj.get("response"), str):
                            if not reveal:
                                cleaned = sanitize_response_text(obj["response"]) or ""
                                if cleaned.strip():
                                    obj["response"] = cleaned
                                    assistant_parts.append(cleaned)
                                else:
                                    # try to fallback to choices if sanitization removed visible text
                                    choices = obj.get("choices")
                                    if isinstance(choices, list):
                                        parts = [c.get("text") for c in choices if isinstance(c, dict) and c.get("text")]
                                        joined = "".join(parts).strip()
                                        if joined:
                                            obj["response"] = joined
                                            assistant_parts.append(joined)
                                        else:
                                            obj["response"] = cleaned
                                    else:
                                        obj["response"] = cleaned
                            else:
                                # keep original response (including possible <think> sections)
                                assistant_parts.append(obj["response"])

                        # Collect thinking parts when present and reveal requested
                        if obj.get("thinking") is not None:
                            if reveal:
                                thinking_parts.append(obj.get("thinking"))
                        # By default, remove any 'thinking' field unless the client requested it
                        if not reveal:
                            obj.pop("thinking", None)

                        # Store the last chunk to augment with token info later
                        if obj.get("done"):
                            last_chunk = obj

                        out_line = json.dumps(obj, ensure_ascii=False) + "\n"
                        yield out_line.encode("utf-8")
                except httpx.StreamClosed:
                    return
                except Exception:
                    logging.exception("Error while proxying stream")
                    return
                finally:
                    total_ms = (time.perf_counter() - start) * 1000
                    logging.info("/generate/stream session=%s model=%s total_ms=%.1f first_chunk_ms=%s", req.session_id, req.model, total_ms, f"{first_ms:.1f}" if first_ms is not None else "None")

                    # Profiling: measure time from stream-receive to just before token calculation
                    try:
                        checkpoint_before_token_stream = time.perf_counter()
                        try:
                            logging.info("/profile /generate/stream A_recv_ms=%.2f B_recv_to_preToken_ms=%.2f",
                                         (checkpoint_recv_stream - start) * 1000.0 if checkpoint_recv_stream else -1.0,
                                         (checkpoint_before_token_stream - checkpoint_recv_stream) * 1000.0 if checkpoint_recv_stream else -1.0)
                        except Exception:
                            pass
                    except Exception:
                        pass

                    # Calculate token information for streaming response and send to client
                    try:
                        token_info = {}
                        try:
                            import tiktoken
                            enc = None
                            try:
                                enc = tiktoken.encoding_for_model(req.model)
                            except Exception:
                                enc = tiktoken.get_encoding("cl100k_base")

                            prompt_text = req.prompt or ""
                            resp_text = "".join(assistant_parts) if assistant_parts else ""
                            prompt_tokens = len(enc.encode(prompt_text)) if prompt_text else 0
                            response_tokens = len(enc.encode(resp_text)) if resp_text else 0
                            total_tokens = prompt_tokens + response_tokens

                            token_info["prompt_tokens"] = prompt_tokens
                            token_info["response_tokens"] = response_tokens
                            token_info["total_tokens"] = total_tokens

                            logging.info("/generate/stream session=%s model=%s tokens_prompt=%s tokens_response=%s tokens_total=%s",
                            req.session_id, req.model, prompt_tokens, response_tokens, total_tokens)

                            # Send token info to client if we have a last chunk
                            if last_chunk is not None:
                                last_chunk["tokens"] = token_info
                                # Resend the final chunk with token info
                                yield (json.dumps(last_chunk, ensure_ascii=False) + "\n").encode("utf-8")
                            else:
                                # If no last chunk captured, send token info as standalone chunk
                                token_chunk = {"done": True, "tokens": token_info}
                                yield (json.dumps(token_chunk, ensure_ascii=False) + "\n").encode("utf-8")
                        except ImportError:
                            logging.warning("/generate/stream session=%s model=%s tiktoken not available, skipping token calculation", req.session_id, req.model)
                        except Exception as e:
                            logging.warning("/generate/stream session=%s model=%s token calculation failed: %s", req.session_id, req.model, str(e))
                    except Exception:
                        pass

                    if latest_ctx is not None:
                        update_session_context(req.session_id, {"context": latest_ctx})
                    if assistant_parts:
                        append_session_history(req.session_id, req.prompt, "".join(assistant_parts))
                        # Persist thinking parts if requested to save
                        save_inner = bool(req.parameters and isinstance(req.parameters, dict) and req.parameters.get("save_inner"))
                        if reveal and save_inner and thinking_parts:
                            hist = SESSION_HISTORY.setdefault(req.session_id, [])
                            hist.append({"role": "assistant.inner", "text": "\n".join(thinking_parts)})
                    await res.aclose()

            # Ollama returns newline-delimited JSON chunks.
            return StreamingResponse(proxy(), media_type="application/x-ndjson")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        GENERATE_STREAM_ACTIVE -= 1
        logging.info("/generate/stream END active_count=%d session=%s model=%s", GENERATE_STREAM_ACTIVE, req.session_id, req.model)


@app.get("/models")
async def models_list():
    """Return the list of available models from the Ollama instance."""
    s = app.state.settings
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{s.ollama_url}{s.ollama_models_path}")
            # Backward/forward compatibility across Ollama API variants.
            if r.status_code == 404:
                fallback = "/api/models" if s.ollama_models_path != "/api/models" else "/api/tags"
                r = await c.get(f"{s.ollama_url}{fallback}")
            if r.status_code >= 400:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            try:
                return r.json()
            except Exception:
                return {"raw": r.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/session/reset")
async def reset_session(req: SessionResetRequest):
    SESSION_CONTEXTS.pop(req.session_id, None)
    SESSION_HISTORY.pop(req.session_id, None)
    return {"ok": True, "session_id": req.session_id, "reset": True}


@app.post("/session/get")
async def get_session(req: SessionGetRequest):
    ctx = SESSION_CONTEXTS.get(req.session_id)
    history = SESSION_HISTORY.get(req.session_id, [])
    return {
        "ok": True,
        "session_id": req.session_id,
        "has_context": ctx is not None,
        "context_length": len(ctx) if isinstance(ctx, list) else 0,
        "history_length": len(history),
        "history": history,
        "context": ctx,
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    # Use configured log level for uvicorn
    uvicorn.run("main:app", host=settings.host_ip, port=settings.api_port, log_level=settings.log_level.lower(), reload=False)
