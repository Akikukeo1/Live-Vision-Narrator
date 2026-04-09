from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
import os
import json
import re
import time
import logging
import httpx

app = FastAPI(title="Ollama Proxy (FastAPI)")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_GENERATE_PATH = os.getenv("OLLAMA_GENERATE_PATH", "/api/generate")
OLLAMA_MODELS_PATH = os.getenv("OLLAMA_MODELS_PATH", "/api/models")
WARMUP_MODEL = os.getenv("WARMUP_MODEL")
DEFAULT_THINK = os.getenv("OLLAMA_DEFAULT_THINK", "false").lower() in {"1", "true", "yes", "on"}
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))


class GenerateRequest(BaseModel):
    model: str = Field(min_length=1)
    prompt: str
    parameters: dict | None = None
    session_id: str | None = None


class SessionResetRequest(BaseModel):
    session_id: str


class SessionGetRequest(BaseModel):
    session_id: str


def build_payload(req: GenerateRequest) -> dict:
    payload: dict = {"model": req.model, "prompt": req.prompt}
    # Forward parameters to Ollama, but strip server-only flags like 'reveal_thoughts'
    if req.parameters:
        params_to_forward = {k: v for k, v in req.parameters.items() if k != "reveal_thoughts"}
        if params_to_forward:
            payload.update(params_to_forward)
            # Promote options.think to top-level 'think' so Ollama sees it
            opts = payload.get("options")
            if isinstance(opts, dict) and "think" in opts:
                payload["think"] = opts.get("think")
    if req.session_id and "context" not in payload:
        ctx = SESSION_CONTEXTS.get(req.session_id)
        if ctx is not None:
            payload["context"] = ctx
    # Respect explicit request parameter, otherwise enforce configured default.
    payload.setdefault("think", DEFAULT_THINK)
    options = payload.get("options")
    if isinstance(options, dict):
        options.setdefault("think", DEFAULT_THINK)
    elif options is None:
        payload["options"] = {"think": DEFAULT_THINK}
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


client: httpx.AsyncClient | None = None
SESSION_CONTEXTS: dict[str, list[int]] = {}
SESSION_HISTORY: dict[str, list[dict[str, str]]] = {}


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
            <meta name="viewport" content="width=device-width,initial-scale=1" />
            <title>Ollama Proxy UI</title>
            <style>
                :root{--gap:12px;--btn-font:1rem;--btn-padding:10px 14px;--max-width:780px}
                *,*::before,*::after{box-sizing:border-box}
                body{font-family:system-ui,Segoe UI,Roboto,Arial;margin:12px;background:#fafafa}
                .container{max-width:var(--max-width);margin:0 auto;padding:0 12px}
                label{display:block;margin-top:8px}
                .toggles label{display:inline-flex;align-items:center;gap:8px;margin-right:12px;margin-top:0}
                .toggles input[type="checkbox"]{margin:0 6px 0 0}
                input[type="text"], input[type="search"], input[type="url"], input[type="tel"], input[type="email"], input[type="number"], input[type="password"], select, textarea{font-family:inherit;width:100%}
                label > input[type="checkbox"]{width:auto;margin-right:8px;vertical-align:middle}
                #out{background:#f6f8fa;padding:12px;border-radius:6px;max-height:400px;overflow:auto}
                .button-row{display:flex;gap:var(--gap);align-items:center;margin-top:10px;flex-wrap:wrap}
                .big-btn{font-size:var(--btn-font);padding:var(--btn-padding);border-radius:8px;background:#f6f8fa;border:1px solid #d1d5db;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}
                .big-btn-container{display:flex;gap:var(--gap);margin-top:8px;flex-wrap:wrap}
                #responses > div{word-break:break-word}
                #chatMessages{background:#ffffff}
                @media (min-width:900px){
                    .big-btn{font-size:2.4rem;padding:10px 18px}
                }
                @media (max-width:420px){
                    body{margin:8px}
                    :root{--btn-font:0.95rem;--btn-padding:8px 10px}
                    .big-btn{min-width:64px}
                    .big-btn-container{gap:8px}
                }
            </style>
        </head>
        <body>
            <div class="container">
            <h2>Ollama Proxy — Test UI</h2>
            <form id="form">
                <label for="sessionId">Session ID</label>
                <div style="display:flex;gap:8px;align-items:center;max-width:95%;margin-top:6px">
                    <input id="sessionId" name="sessionId" placeholder="default" value="default" style="flex:1"/>
                </div>

                <div class="button-row big-btn-container">
                    <button id="resetSessionBtn" type="button" class="big-btn">記憶リセット</button>
                    <button id="showSessionBtn" type="button" class="big-btn">記憶表示</button>
                    <button id="thinkBtn" type="button" class="big-btn">Thinking発動</button>
                </div>

                <label for="model">Model</label>
                <input id="model" name="model" value="live-narrator" placeholder="モデル名を入力（例: live-narrator）" style="width:60%;margin-top:6px"/>

                <label for="prompt">Prompt</label>
                <textarea id="prompt" name="prompt" rows="6" style="width:95%;margin-top:6px">こんにちは</textarea>

                <label for="params">Additional JSON parameters (optional)</label>
                <textarea id="params" name="params" rows="4" style="width:95%;margin-top:6px">{
                }</textarea>

                <div class="toggles" style="margin-top:8px">
                    <label><input id="streamToggle" type="checkbox" checked/> ストリーミング表示</label>
                    <label><input id="parallelToggle" type="checkbox"/> 並列許可（ONで複数同時実行）</label>
                    <label><input id="chatModeToggle" type="checkbox"/> チャットモード</label>
                    <label><input id="showCoTToggle" type="checkbox"/> CoT表示（オプション）</label>
                </div>

                <button id="sendBtn" type="button" class="big-btn">送信</button>
            </form>

            <div id="chatMode" style="display:none;margin-top:14px;max-width:95%">
                <h3>チャット</h3>
                <div id="chatMessages" style="border:1px solid #e5e7eb;border-radius:8px;padding:8px;max-height:360px;overflow:auto;background:#fff"></div>
                <div style="display:flex;gap:8px;margin-top:8px">
                    <input id="chatInput" placeholder="メッセージを入力..." style="flex:1;padding:8px;border-radius:6px;border:1px solid #d1d5db" />
                    <button id="chatSendBtn" class="big-btn" type="button">送信</button>
                </div>
            </div>

            <h3>Response</h3>
            <div id="responses"></div>

            <script>
                console.log('Ollama UI script loaded');
                window.addEventListener('error', (e)=>{ console.error('UI error', e); });

                const form = document.getElementById('form');
                const sendBtn = document.getElementById('sendBtn');
                const resetSessionBtn = document.getElementById('resetSessionBtn');
                const showSessionBtn = document.getElementById('showSessionBtn');
                const thinkBtn = document.getElementById('thinkBtn');
                const showCoTToggle = document.getElementById('showCoTToggle');
                const responses = document.getElementById('responses');
                let activeController = null;
                let requestId = 0;
                let thinkToggle = false;

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
                    // Thinking panel (hidden by default). We'll attach to the card for easy access.
                    const thinkingLabel = document.createElement('div');
                    thinkingLabel.style.fontSize = '12px';
                    thinkingLabel.style.color = '#9ca3af';
                    thinkingLabel.style.marginTop = '6px';
                    thinkingLabel.textContent = 'Thinking';
                    thinkingLabel.style.display = 'none';

                    const thinkingPre = document.createElement('pre');
                    thinkingPre.style.background = '#fff7ed';
                    thinkingPre.style.padding = '8px';
                    thinkingPre.style.borderRadius = '6px';
                    thinkingPre.style.maxHeight = '200px';
                    thinkingPre.style.overflow = 'auto';
                    thinkingPre.style.marginTop = '6px';
                    thinkingPre.style.display = 'none';
                    thinkingPre.textContent = '';

                    card.appendChild(thinkingLabel);
                    card.appendChild(thinkingPre);
                    // Expose for callers: pane.parentElement.thinkingPre
                    card.thinkingPre = thinkingPre;
                    card.thinkingLabel = thinkingLabel;
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

                if(thinkBtn){
                    thinkBtn.addEventListener('click', ()=>{
                        thinkToggle = !thinkToggle;
                        thinkBtn.textContent = thinkToggle ? 'Thinking: ON' : 'Thinking発動';
                        thinkBtn.classList.toggle('active', thinkToggle);
                        console.log('Thinking toggle ->', thinkToggle);
                    });
                }

                // Chat mode toggle handling
                const chatModeToggle = document.getElementById('chatModeToggle');
                const chatModeDiv = document.getElementById('chatMode');
                const chatMessages = document.getElementById('chatMessages');
                const chatInput = document.getElementById('chatInput');
                const chatSendBtn = document.getElementById('chatSendBtn');

                function setModeChat(enabled){
                    if(enabled){
                        document.getElementById('prompt').style.display = 'none';
                        document.getElementById('params').style.display = 'none';
                        chatModeDiv.style.display = 'block';
                    } else {
                        document.getElementById('prompt').style.display = 'block';
                        document.getElementById('params').style.display = 'block';
                        chatModeDiv.style.display = 'none';
                    }
                }

                if(chatModeToggle){
                    chatModeToggle.addEventListener('change', (e)=>{
                        setModeChat(e.target.checked);
                    });
                }

                function appendChat(role, text){
                    const wrap = document.createElement('div');
                    wrap.style.margin = '6px 0';
                    const bubble = document.createElement('div');
                    bubble.style.display = 'inline-block';
                    bubble.style.padding = '8px 12px';
                    bubble.style.borderRadius = '12px';
                    bubble.style.maxWidth = '86%';
                    bubble.style.whiteSpace = 'pre-wrap';
                    bubble.textContent = text;
                    if(role === 'user'){
                        bubble.style.background = '#e6f0ff';
                        bubble.style.alignSelf = 'flex-end';
                        wrap.style.textAlign = 'right';
                    } else {
                        bubble.style.background = '#f1f5f9';
                        bubble.style.textAlign = 'left';
                    }
                    wrap.appendChild(bubble);
                    chatMessages.appendChild(wrap);
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }

                async function sendChatMessage(streaming){
                    const modelName = document.getElementById('model').value;
                    const sessionId = document.getElementById('sessionId').value || 'default';
                    const text = chatInput.value || '';
                    if(!text.trim()){ return; }
                    appendChat('user', text);
                    chatInput.value = '';

                    // Build parameters for chat request; include think (top-level) and optional reveal_thoughts
                    let chatParams = {};
                    if(thinkToggle){ chatParams.think = true; }
                    if(showCoTToggle && showCoTToggle.checked){ chatParams.reveal_thoughts = true; }

                    const body = { model: modelName, prompt: text, parameters: chatParams, session_id: sessionId };

                    try{
                        if(!streaming){
                            const r = await fetch('/generate', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
                            if(!r.ok){ appendChat('assistant', 'Error: ' + r.status); return; }
                            const t = await r.text();
                            try{ const obj = JSON.parse(t); appendChat('assistant', String(obj.response ?? t)); }
                            catch{ appendChat('assistant', t); }
                            return;
                        }

                        const r = await fetch('/generate/stream', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
                        if(!r.ok){ appendChat('assistant', 'Error: ' + r.status); return; }
                        const reader = r.body.getReader();
                        const decoder = new TextDecoder();
                        let buffer = '';
                        let assistantNode = document.createElement('div');
                        assistantNode.style.display = 'inline-block';
                        assistantNode.style.padding = '8px 12px';
                        assistantNode.style.borderRadius = '12px';
                        assistantNode.style.maxWidth = '86%';
                        assistantNode.style.whiteSpace = 'pre-wrap';
                        assistantNode.style.background = '#f1f5f9';
                        const wrapper = document.createElement('div'); wrapper.style.margin='6px 0'; wrapper.appendChild(assistantNode);
                        chatMessages.appendChild(wrapper);

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
                                    if(obj.thinking !== undefined){
                                        // show thinking in a smaller area
                                        if(!wrapper.thinkingPre){
                                            const tl = document.createElement('div'); tl.style.fontSize='12px'; tl.style.color='#9ca3af'; tl.textContent='Thinking'; tl.style.marginTop='6px'; tl.style.display='block';
                                            const tp = document.createElement('pre'); tp.style.background='#fff7ed'; tp.style.padding='8px'; tp.style.borderRadius='6px'; tp.style.maxHeight='200px'; tp.style.overflow='auto'; tp.style.marginTop='6px'; tp.textContent='';
                                            wrapper.appendChild(tl); wrapper.appendChild(tp); wrapper.thinkingPre = tp; wrapper.thinkingLabel = tl;
                                        }
                                        wrapper.thinkingLabel.style.display = 'block'; wrapper.thinkingPre.style.display = 'block';
                                        wrapper.thinkingPre.textContent += obj.thinking;
                                    }
                                    if(obj.response !== undefined){ assistantNode.textContent += obj.response; }
                                    else if(obj.choices && Array.isArray(obj.choices)){ obj.choices.forEach(c=>{ if(c.text) assistantNode.textContent += c.text; }); }
                                }catch(_){ }
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            }
                        }

                        if(buffer.trim()){
                            try{
                                const obj = JSON.parse(buffer);
                                if(obj.response !== undefined) assistantNode.textContent += obj.response;
                                if(obj.thinking !== undefined){
                                    if(!wrapper.thinkingPre){
                                        const tl=document.createElement('div'); tl.style.fontSize='12px'; tl.style.color='#9ca3af'; tl.textContent='Thinking'; tl.style.marginTop='6px';
                                        const tp=document.createElement('pre'); tp.style.background='#fff7ed'; tp.style.padding='8px'; tp.style.borderRadius='6px'; tp.style.maxHeight='200px'; tp.style.overflow='auto'; tp.style.marginTop='6px';
                                        wrapper.appendChild(tl); wrapper.appendChild(tp); wrapper.thinkingPre = tp; wrapper.thinkingLabel = tl;
                                    }
                                    wrapper.thinkingLabel.style.display='block'; wrapper.thinkingPre.style.display='block'; wrapper.thinkingPre.textContent += obj.thinking;
                                }
                            }catch(_){ }
                        }
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    }catch(err){ appendChat('assistant', String(err)); }
                }

                if(chatSendBtn){
                    chatSendBtn.addEventListener('click', ()=>{
                        const streaming = document.getElementById('streamToggle').checked;
                        sendChatMessage(streaming);
                    });
                }

                chatInput.addEventListener && chatInput.addEventListener('keydown', (e)=>{
                    if(e.key === 'Enter' && !e.shiftKey){
                        e.preventDefault();
                        const streaming = document.getElementById('streamToggle').checked;
                        sendChatMessage(streaming);
                    }
                });

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
                            // Also clear chat UI if present so visual state matches server reset
                            try{
                                const chatMessages = document.getElementById('chatMessages');
                                if(chatMessages){ chatMessages.innerHTML = ''; }
                                const chatInput = document.getElementById('chatInput');
                                if(chatInput){ chatInput.value = ''; }
                            }catch(_){ }
                        }catch(err){
                            pane.textContent = String(err);
                            if(pane.parentElement){ pane.parentElement.dataset.status = 'done'; }
                        }
                    });
                }

                if(showSessionBtn){
                    showSessionBtn.addEventListener('click', async ()=>{
                        const sessionId = document.getElementById('sessionId').value || 'default';
                        const pane = createResponsePane(++requestId, false);
                        pane.textContent = '...loading session memory';
                        try{
                            const r = await fetch('/session/get', {
                                method:'POST',
                                headers:{'Content-Type':'application/json'},
                                body: JSON.stringify({session_id: sessionId}),
                            });
                            const t = await r.text();
                            try{
                                const obj = JSON.parse(t);
                                pane.textContent = JSON.stringify(obj, null, 2);
                            }catch(_){
                                pane.textContent = t;
                            }
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

                    if(!modelName || !modelName.trim()){
                        const pane = createResponsePane(++requestId, !allowParallel);
                        pane.textContent = 'Model is required (例: live-narrator)';
                        if(pane.parentElement){ pane.parentElement.dataset.status = 'done'; }
                        return;
                    }

                    let parameters = {};
                    try{ parameters = JSON.parse(document.getElementById('params').value); }
                    catch(err){
                        const pane = createResponsePane(++requestId, !allowParallel);
                        pane.textContent = 'Invalid JSON in parameters';
                        if(pane.parentElement){ pane.parentElement.dataset.status = 'done'; }
                        return;
                    }

                    // Inject Thinking toggle or reveal flags into parameters (server strips reveal_thoughts before forwarding)
                    parameters = parameters || {};
                    if(thinkToggle){ parameters.think = true; }
                    if(showCoTToggle && showCoTToggle.checked){ parameters.reveal_thoughts = true; }

                    console.log('Request parameters:', parameters);

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
                    // If this request will engage Thinking, surface a friendly waiting message
                    const isThinkingNow = parameters && parameters.think;
                    if(isThinkingNow){ pane.textContent = 'Thinking中だから待ってね〜\n'; }
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
                            if(!r.ok){
                                const errText = await r.text();
                                pane.textContent = 'Error: ' + r.status + '\n' + errText;
                                return;
                            }
                            const t = await r.text();
                            try{
                                const obj = JSON.parse(t);
                                if(obj && typeof obj === 'object' && obj.response !== undefined){
                                    pane.textContent = String(obj.response);
                                    if(obj.thinking !== undefined){
                                        const card = pane.parentElement;
                                        if(card && card.thinkingPre){
                                            card.thinkingLabel.style.display = 'block';
                                            card.thinkingPre.style.display = 'block';
                                            card.thinkingPre.textContent = String(obj.thinking);
                                        }
                                    }
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
                            const errText = await r.text();
                            pane.textContent = 'Error: ' + r.status + '\n' + errText;
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
                                    if(obj.thinking !== undefined){
                                        const card = pane.parentElement;
                                        if(card && card.thinkingPre){
                                            card.thinkingLabel.style.display = 'block';
                                            card.thinkingPre.style.display = 'block';
                                            card.thinkingPre.textContent += obj.thinking;
                                        }
                                    }
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
                                if(obj.thinking !== undefined){ const card=pane.parentElement; if(card && card.thinkingPre){ card.thinkingLabel.style.display='block'; card.thinkingPre.style.display='block'; card.thinkingPre.textContent += obj.thinking; } }
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
            </div>
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
    # Log whether the request will think / reveal thoughts
    reveal = should_reveal_thoughts(req)
    logging.info("/generate requested think=%s reveal=%s session=%s model=%s", payload.get("think"), reveal, req.session_id, req.model)
    start = time.perf_counter()
    try:
        r = await client.post(f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}", json=payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logging.info("/generate session=%s model=%s elapsed_ms=%.1f", req.session_id, req.model, elapsed_ms)
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
                data["response"] = sanitize_response_text(data["response"])
            else:
                # keep response intact when revealing thoughts
                data["response"] = data["response"]
        update_session_context(req.session_id, data)
        if isinstance(data.get("response"), str):
            append_session_history(req.session_id, req.prompt, data["response"])
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
        start = time.perf_counter()
        request = client.build_request("POST", f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}", json=payload)
        res = await client.send(request, stream=True)
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
            first_ms = None
            try:
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
                            cleaned = sanitize_response_text(obj["response"])
                            obj["response"] = cleaned
                            if cleaned:
                                assistant_parts.append(cleaned)
                        else:
                            # keep original response (including possible <think> sections)
                            assistant_parts.append(obj["response"])

                    # By default, remove any 'thinking' field unless the client requested it
                    if not reveal:
                        obj.pop("thinking", None)

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
                if latest_ctx is not None:
                    update_session_context(req.session_id, {"context": latest_ctx})
                if assistant_parts:
                    append_session_history(req.session_id, req.prompt, "".join(assistant_parts))
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

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
