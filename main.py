from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import os
import httpx

app = FastAPI(title="Ollama Proxy (FastAPI)")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_GENERATE_PATH = os.getenv("OLLAMA_GENERATE_PATH", "/api/generate")
OLLAMA_MODELS_PATH = os.getenv("OLLAMA_MODELS_PATH", "/api/models")
WARMUP_MODEL = os.getenv("WARMUP_MODEL")


class GenerateRequest(BaseModel):
    model: str
    prompt: str
    parameters: dict | None = None


client: httpx.AsyncClient | None = None


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
        html = """
        <!doctype html>
        <html>
            <head>
                <meta charset="utf-8" />
                <title>Ollama Proxy UI</title>
                <style>body{font-family:system-ui,Segoe UI,Roboto,Arial;margin:20px}label{display:block;margin-top:8px}</style>
            </head>
            <body>
                <h2>Ollama Proxy — Test UI</h2>
                <form id="form">
                    <label>Model<br/>
                        <select id="modelSelect" style="width:60%"></select>
                        <div style="margin-top:6px"><label><input id="customToggle" type="checkbox"/> カスタム指定</label></div>
                        <input id="model" placeholder="カスタムモデル名" style="width:60%;display:none;margin-top:6px"/>
                    </label>
                    <label>Prompt<br/><textarea id="prompt" rows="6" style="width:80%">こんにちは</textarea></label>
                    <label>Additional JSON parameters (optional)<br/><textarea id="params" rows="4" style="width:80%">{
}
</textarea></label>
                    <button type="submit">送信</button>
                </form>
                <h3>Response</h3>
                <pre id="out" style="background:#f6f8fa;padding:12px;border-radius:6px;max-height:400px;overflow:auto"></pre>

                <script>
                    const form = document.getElementById('form');
                    const out = document.getElementById('out');
                    form.addEventListener('submit', async (e)=>{
                        e.preventDefault();
                        out.textContent = '…sending';
                        const model = document.getElementById('model').value;
                        const prompt = document.getElementById('prompt').value;
                        let parameters = {};
                        try{ parameters = JSON.parse(document.getElementById('params').value) }catch(err){ out.textContent = 'Invalid JSON in parameters'; return }
                            const useCustom = document.getElementById('customToggle').checked;
                            const modelSelect = document.getElementById('modelSelect');
                            const modelInput = document.getElementById('model');
                            const modelName = useCustom ? modelInput.value : modelSelect.value;
                            const body = { model: modelName, prompt, parameters };
                        try{
                            const r = await fetch('/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
                            const t = await r.text();
                            try{ out.textContent = JSON.stringify(JSON.parse(t), null, 2) }catch(e){ out.textContent = t }
                        }catch(err){ out.textContent = String(err) }
                    })

                    // Populate model list on load
                    async function loadModels(){
                        try{
                            const r = await fetch('/models');
                            if(!r.ok) throw new Error('failed to fetch models');
                            const data = await r.json();
                            const select = document.getElementById('modelSelect');
                            // Expecting array or object. Try common shapes.
                            let models = [];
                            if(Array.isArray(data)) models = data;
                            else if (data.models && Array.isArray(data.models)) models = data.models;
                            else if (data.items && Array.isArray(data.items)) models = data.items;
                            else if (typeof data === 'object') models = Object.values(data);
                            models.forEach(m=>{
                                const name = (typeof m === 'string') ? m : (m.name || m.id || JSON.stringify(m));
                                const opt = document.createElement('option'); opt.value = name; opt.textContent = name; select.appendChild(opt);
                            });
                            if(select.options.length>0) select.value = select.options[0].value;
                        }catch(err){ console.warn('Could not load models', err) }
                    }
                    loadModels();

                    // Toggle custom input visibility
                    document.getElementById('customToggle').addEventListener('change', (e)=>{
                        const custom = e.target.checked;
                        document.getElementById('model').style.display = custom ? 'block' : 'none';
                        document.getElementById('modelSelect').style.display = custom ? 'none' : 'inline-block';
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

    payload: dict = {"model": req.model, "prompt": req.prompt}
    if req.parameters:
        payload.update(req.parameters)

    try:
        r = await client.post(f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}", json=payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    # Return whatever Ollama returns (assumed JSON)
    try:
        return r.json()
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

    payload: dict = {"model": req.model, "prompt": req.prompt}
    if req.parameters:
        payload.update(req.parameters)

    try:
        # Use httpx stream to proxy bytes as they arrive from Ollama
        async with client.stream("POST", f"{OLLAMA_URL}{OLLAMA_GENERATE_PATH}", json=payload, timeout=None) as res:
            if res.status_code >= 400:
                text = await res.aread()
                raise HTTPException(status_code=res.status_code, detail=text.decode('utf-8', errors='replace'))

            async def proxy():
                async for chunk in res.aiter_bytes():
                    if not chunk:
                        continue
                    yield chunk

            return StreamingResponse(proxy(), media_type="text/event-stream")
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")
def main():
    print("Hello from live-vision-narrator!")


if __name__ == "__main__":
    main()
