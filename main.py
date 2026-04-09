from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import os
import json
import httpx

app = FastAPI(title="Ollama Proxy (FastAPI)")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_GENERATE_PATH = os.getenv("OLLAMA_GENERATE_PATH", "/api/generate")
OLLAMA_MODELS_PATH = os.getenv("OLLAMA_MODELS_PATH", "/api/models")
WARMUP_MODEL = os.getenv("WARMUP_MODEL")
DEFAULT_THINK = os.getenv("OLLAMA_DEFAULT_THINK", "false").lower() in {"1", "true", "yes", "on"}


class GenerateRequest(BaseModel):
    model: str
    prompt: str
    parameters: dict | None = None
    session_id: str | None = None


class SessionResetRequest(BaseModel):
    session_id: str


def build_payload(req: GenerateRequest) -> dict:
    payload: dict = {"model": req.model, "prompt": req.prompt}
    if req.parameters:
        payload.update(req.parameters)
    if req.session_id and "context" not in payload:
        ctx = SESSION_CONTEXTS.get(req.session_id)
        if ctx is not None:
            payload["context"] = ctx
    # Respect explicit request parameter, otherwise enforce configured default.
    payload.setdefault("think", DEFAULT_THINK)
    return payload


def update_session_context(session_id: str | None, data: dict) -> None:
    if not session_id:
        return
    ctx = data.get("context")
    if ctx is not None:
        SESSION_CONTEXTS[session_id] = ctx


client: httpx.AsyncClient | None = None
SESSION_CONTEXTS: dict[str, list[int]] = {}


@app.on_event("startup")
async def startup_event():
    global client
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    # Optional warmup: trigger a tiny request to load model into memory
    if WARMUP_MODEL and client:
        try:
            await client.post(
                f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}",
                json={"model": WARMUP_MODEL, "prompt": ""},
                timeout=5.0,
            )
        except Exception:
            # Non-fatal; warmup best-effort only
            pass


@app.on_event("shutdown")
async def shutdown_event():
    global client
    if client is not None:
        await client.aclose()


@app.get("/health")
async def health():
    # Check minimal connectivity to Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(OLLAMA_URL)
            return {"ok": True, "ollama_status_code": r.status_code}
    except Exception:
        return {"ok": False, "ollama_url": OLLAMA_URL}


@app.get("/")
async def root():
    return {"ok": True, "endpoints": ["/health", "/generate"]}


@app.get("/ui", response_class=HTMLResponse)
async def ui():
    html = r"""
    <!doctype html>
    <html>
        <head>
            <meta charset="utf-8" />
            <title>Ollama Proxy UI</title>
            <style>
                body{font-family:system-ui,Segoe UI,Roboto,Arial;margin:20px}
                label{display:block;margin-top:8px}
                input, select, textarea{font-family:inherit}
                #out{background:#f6f8fa;padding:12px;border-radius:6px;max-height:400px;overflow:auto}
            </style>
        </head>
        <body>
            <h2>Ollama Proxy — Test UI</h2>
            <form id="form">
                <label for="sessionId">Session ID</label>
                <div style="display:flex;gap:8px;align-items:center;max-width:95%;margin-top:6px">
                    <input id="sessionId" name="sessionId" placeholder="default" value="default" style="flex:1"/>
                    <button id="resetSessionBtn" type="button">記憶リセット</button>
                </div>

                <label for="model">Model</label>
                <input id="model" name="model" placeholder="モデル名を入力（例: live-narrator）" style="width:60%;margin-top:6px"/>

                <label for="prompt">Prompt</label>
                <textarea id="prompt" name="prompt" rows="6" style="width:95%;margin-top:6px">こんにちは</textarea>

                <label for="params">Additional JSON parameters (optional)</label>
                <textarea id="params" name="params" rows="4" style="width:95%;margin-top:6px">{
                }</textarea>

                <div style="margin-top:8px">
                    <label><input id="streamToggle" type="checkbox" checked/> ストリーミング表示</label>
                    <label><input id="parallelToggle" type="checkbox"/> 並列許可（ONで複数同時実行）</label>
                </div>

                <button id="sendBtn" type="button">送信</button>
            </form>

            <h3>Response</h3>
            <div id="responses"></div>

            <script>
                console.log('Ollama UI script loaded');
                window.addEventListener('error', (e)=>{ console.error('UI error', e); });

                const form = document.getElementById('form');
                const sendBtn = document.getElementById('sendBtn');
                const resetSessionBtn = document.getElementById('resetSessionBtn');
                const responses = document.getElementById('responses');
                let activeController = null;
                let requestId = 0;

                function createResponsePane(id, replaceExisting){
                    if(replaceExisting){
                        responses.innerHTML = '';
                    }
                    const card = document.createElement('div');
                    card.dataset.status = 'running';
                    card.dataset.requestId = String(id);
                    card.style.border = '1px solid #e5e7eb';
                    card.style.borderRadius = '8px';
                    card.style.padding = '8px';
                    card.style.marginBottom = '8px';

                    const title = document.createElement('div');
                    title.style.fontSize = '12px';
                    title.style.color = '#6b7280';
                    title.textContent = 'Request #' + id;

                    const pre = document.createElement('pre');
                    pre.style.background = '#f6f8fa';
                    pre.style.padding = '12px';
                    pre.style.borderRadius = '6px';
                    pre.style.maxHeight = '320px';
                    pre.style.overflow = 'auto';
                    pre.style.marginTop = '6px';
                    pre.textContent = '';

                    card.appendChild(title);
                    card.appendChild(pre);
                    responses.prepend(card);
                    return pre;
                }

                function pruneFinishedCards(){
                    const finished = responses.querySelectorAll('div[data-status="done"]');
                    finished.forEach((node)=>node.remove());
                }

                function appendText(target, text){
                    target.textContent += text;
                    target.scrollTop = target.scrollHeight;
                }

                if(sendBtn){
                    sendBtn.addEventListener('click', ()=>{
                        try{ form.requestSubmit(); }catch(err){ form.dispatchEvent(new Event('submit', {cancelable:true})); }
                    });
                }

                if(resetSessionBtn){
                    resetSessionBtn.addEventListener('click', async ()=>{
                        const sessionId = document.getElementById('sessionId').value || 'default';
                        const pane = createResponsePane(++requestId, false);
                        pane.textContent = '...resetting session';
                        try{
                            const r = await fetch('/session/reset', {
                                method:'POST',
                                headers:{'Content-Type':'application/json'},
                                body: JSON.stringify({session_id: sessionId}),
                            });
                            const t = await r.text();
                            pane.textContent = t;
                            if(pane.parentElement){ pane.parentElement.dataset.status = 'done'; }
                        }catch(err){
                            pane.textContent = String(err);
                            if(pane.parentElement){ pane.parentElement.dataset.status = 'done'; }
                        }
                    });
                }

                form.addEventListener('submit', async (e)=>{
                    e.preventDefault();

                    const modelName = document.getElementById('model').value;
                    const sessionId = document.getElementById('sessionId').value || 'default';
                    const prompt = document.getElementById('prompt').value;
                    const stream = document.getElementById('streamToggle').checked;
                    const allowParallel = document.getElementById('parallelToggle').checked;

                    let parameters = {};
                    try{ parameters = JSON.parse(document.getElementById('params').value); }
                    catch(err){
                        const pane = createResponsePane(++requestId, !allowParallel);
                        pane.textContent = 'Invalid JSON in parameters';
                        if(pane.parentElement){ pane.parentElement.dataset.status = 'done'; }
                        return;
                    }

                    if(allowParallel){
                        // On new parallel request, remove already-finished old requests.
                        pruneFinishedCards();
                    }

                    if(!allowParallel && activeController){
                        activeController.abort();
                    }

                    const controller = new AbortController();
                    if(!allowParallel){
                        activeController = controller;
                    }

                    const pane = createResponsePane(++requestId, !allowParallel);
                    const body = { model: modelName, prompt, parameters, session_id: sessionId };

                    console.log('Form submit: session=%s, model=%s, prompt_len=%d, streaming=%s, parallel=%s', sessionId, modelName, prompt.length, stream, allowParallel);

                    try{
                        if(!stream){
                            pane.textContent = '...sending';
                            const r = await fetch('/generate', {
                                method:'POST',
                                headers:{'Content-Type':'application/json'},
                                body:JSON.stringify(body),
                                signal: controller.signal,
                            });
                            const t = await r.text();
                            try{
                                const obj = JSON.parse(t);
                                if(obj && typeof obj === 'object' && obj.response !== undefined){
                                    pane.textContent = String(obj.response);
                                } else {
                                    pane.textContent = JSON.stringify(obj, null, 2);
                                }
                            }
                            catch(_){ pane.textContent = t; }
                            return;
                        }

                        pane.textContent = '';
                        const r = await fetch('/generate/stream', {
                            method:'POST',
                            headers:{'Content-Type':'application/json'},
                            body:JSON.stringify(body),
                            signal: controller.signal,
                        });

                        if(!r.ok){
                            pane.textContent = 'Error: ' + r.status;
                            return;
                        }

                        const reader = r.body.getReader();
                        const decoder = new TextDecoder();
                        let buffer = '';

                        while(true){
                            const { done, value } = await reader.read();
                            if(done) break;
                            buffer += decoder.decode(value, { stream: true });
                            const parts = buffer.split(/\r?\n/);
                            buffer = parts.pop();
                            for(const part of parts){
                                if(!part.trim()) continue;
                                try{
                                    const obj = JSON.parse(part);
                                    if(obj.response !== undefined){
                                        appendText(pane, obj.response);
                                    } else if(obj.choices && Array.isArray(obj.choices)){
                                        obj.choices.forEach(c=>{ if(c.text) appendText(pane, c.text); });
                                    }
                                }catch(_){
                                    // Ignore malformed fragments to avoid leaking raw payloads.
                                }
                            }
                        }

                        if(buffer.trim()){
                            try{
                                const obj = JSON.parse(buffer);
                                if(obj.response !== undefined) appendText(pane, obj.response);
                            }catch(_){
                                // ignore trailing partial fragment
                            }
                        }
                    }catch(err){
                        if(err && err.name === 'AbortError'){
                            appendText(pane, '\n[aborted]');
                        } else {
                            pane.textContent = String(err);
                        }
                    } finally {
                        if(pane.parentElement){
                            pane.parentElement.dataset.status = 'done';
                        }
                        if(activeController === controller){
                            activeController = null;
                        }
                    }
                });
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/generate")
async def generate(req: GenerateRequest):
    global client
    if client is None:
        raise HTTPException(status_code=503, detail="Service not started")

    payload = build_payload(req)

    try:
        r = await client.post(f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}", json=payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    # Return whatever Ollama returns (assumed JSON)
    try:
        data = r.json()
        update_session_context(req.session_id, data)
        return data
    except Exception:
        return {"raw": r.text}


@app.post("/generate/stream")
async def generate_stream(req: GenerateRequest):
    """Stream response from Ollama through to the client.

    This keeps streaming logic separate from the UI and non-streaming endpoint.
    """
    global client
    if client is None:
        raise HTTPException(status_code=503, detail="Service not started")

    payload = build_payload(req)

    try:
        # Keep upstream stream open for as long as StreamingResponse is iterating.
        request = client.build_request("POST", f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}", json=payload)
        res = await client.send(request, stream=True)

        if res.status_code >= 400:
            text = await res.aread()
            await res.aclose()
            raise HTTPException(status_code=res.status_code, detail=text.decode("utf-8", errors="replace"))

        async def proxy():
            latest_ctx = None
            line_buffer = b""
            try:
                async for chunk in res.aiter_bytes():
                    if chunk:
                        line_buffer += chunk
                        parts = line_buffer.split(b"\n")
                        line_buffer = parts.pop()
                        for part in parts:
                            line = part.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line.decode("utf-8", errors="replace"))
                                if "context" in obj:
                                    latest_ctx = obj["context"]
                            except Exception:
                                pass
                        yield chunk
            except httpx.StreamClosed:
                return
            except Exception:
                return
            finally:
                if line_buffer.strip():
                    try:
                        obj = json.loads(line_buffer.decode("utf-8", errors="replace"))
                        if "context" in obj:
                            latest_ctx = obj["context"]
                    except Exception:
                        pass
                if latest_ctx is not None:
                    update_session_context(req.session_id, {"context": latest_ctx})
                await res.aclose()

        # Ollama returns newline-delimited JSON chunks.
        return StreamingResponse(proxy(), media_type="application/x-ndjson")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models")
async def models_list():
    """Return the list of available models from the Ollama instance."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{OLLAMA_URL}{OLLAMA_MODELS_PATH}")
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
    return {"ok": True, "session_id": req.session_id, "reset": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")
