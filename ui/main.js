console.log('Ollama UI script loaded');
window.addEventListener('error', (e) => { console.error('UI error', e); });

// API Base URL - LAN 内のホストを自動判別、デフォルト以外の設定は /api-config から取得
let API_BASE_URL = `${location.protocol}//${location.hostname}:8000`; // ローカルホスト型フォールバック

// Fetch API configuration from UI server
// Note: intentionally do NOT override API_BASE_URL from /api-config to avoid
// exposing the backend host to the browser (prevents accidental direct calls
// to the backend which cause CORS errors). The UI uses relative proxy paths
// (e.g. `/generate`, `/system-profiles`) so this fetch is omitted.

const form = document.getElementById('form');
const sendBtn = document.getElementById('sendBtn');
const resetSessionBtn = document.getElementById('resetSessionBtn');
const showSessionBtn = document.getElementById('showSessionBtn');
const thinkBtn = document.getElementById('thinkBtn');
const promptInput = document.getElementById('prompt');
const responses = document.getElementById('responses');
let activeController = null;
let requestId = 0;
let thinkToggle = false;

function buildWebSocketUrl() {
    const apiUrl = new URL(API_BASE_URL);
    const wsProtocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProtocol}//${apiUrl.host}/ws`;
}

function sendChatStreamViaWebSocket(body, pane, controller) {
    return new Promise((resolve, reject) => {
        const ws = new WebSocket(buildWebSocketUrl());
        let finished = false;
        let started = false;

        const cleanup = () => {
            if (controller && controller.signal) {
                controller.signal.onabort = null;
            }
            if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
                try { ws.close(1000, 'done'); } catch (_) { }
            }
        };

        const fail = (error) => {
            if (finished) return;
            finished = true;
            cleanup();
            reject(error instanceof Error ? error : new Error(String(error)));
        };

        if (controller && controller.signal) {
            controller.signal.addEventListener('abort', () => {
                fail(new DOMException('Aborted', 'AbortError'));
            }, { once: true });
        }

        ws.onopen = () => {
            started = true;
            console.log('[WS] open', buildWebSocketUrl());
            const sessionId = body.session_id || 'default';
            ws.send(JSON.stringify({
                version: 1,
                type: 'control.start_session',
                session_id: sessionId,
                client_id: 'ui',
            }));
            ws.send(JSON.stringify({
                version: 1,
                type: 'inference.request',
                session_id: sessionId,
                request_id: String(requestId),
                model: body.model,
                prompt: body.prompt,
                think: Boolean(body.think === true),
            }));
        };

        ws.onmessage = (event) => {
            try {
                const obj = JSON.parse(event.data);
                console.log('[WS] message', obj.type);
                if (obj.type === 'inference.delta' && obj.text) {
                    appendText(pane, obj.text);
                    return;
                }
                if (obj.type === 'inference.thinking' && obj.text) {
                    const card = pane.parentElement;
                    if (card) {
                        if (!card.thinkingPre) {
                            const tl = document.createElement('div');
                            tl.style.fontSize = '12px';
                            tl.style.color = '#9ca3af';
                            tl.textContent = 'Thinking';
                            tl.style.marginTop = '6px';
                            tl.style.display = 'block';
                            const tp = document.createElement('pre');
                            tp.style.background = '#fff7ed';
                            tp.style.padding = '8px';
                            tp.style.borderRadius = '6px';
                            tp.style.maxHeight = '200px';
                            tp.style.overflow = 'auto';
                            tp.style.marginTop = '6px';
                            tp.textContent = '';
                            card.appendChild(tl);
                            card.appendChild(tp);
                            card.thinkingPre = tp;
                            card.thinkingLabel = tl;
                        }
                        card.thinkingLabel.style.display = 'block';
                        card.thinkingPre.style.display = 'block';
                        card.thinkingPre.textContent += obj.text;
                    }
                    return;
                }
                if (obj.type === 'inference.done') {
                    console.log('[WS] done');
                    finished = true;
                    cleanup();
                    resolve();
                    return;
                }
                if (obj.type === 'error') {
                    console.error('[WS] server error', obj.error);
                    fail(new Error(obj.error || 'websocket error'));
                }
            } catch (err) {
                console.error('[WS] parse error', err);
                fail(err);
            }
        };

        ws.onerror = () => {
            console.error('[WS] onerror');
            if (!started) {
                fail(new Error('WebSocket connection failed'));
            }
        };

        ws.onclose = (event) => {
            console.log('[WS] close', event.code, event.reason || '(no reason)');
            if (!finished) {
                fail(new Error('WebSocket closed before completion'));
            }
        };
    });
}

function createResponsePane(id, replaceExisting) {
    if (replaceExisting) {
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

    // Thinking panel (hidden by default)
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
    card.thinkingPre = thinkingPre;
    card.thinkingLabel = thinkingLabel;

    // Token information panel
    const tokenDiv = document.createElement('div');
    tokenDiv.style.fontSize = '11px';
    tokenDiv.style.color = '#6b7280';
    tokenDiv.style.marginTop = '6px';
    tokenDiv.textContent = '';
    tokenDiv.style.display = 'none';
    card.appendChild(tokenDiv);
    card.tokenDiv = tokenDiv;

    responses.prepend(card);
    return pre;
}

function pruneFinishedCards() {
    const finished = responses.querySelectorAll('div[data-status="done"]');
    finished.forEach((node) => node.remove());
}

function appendText(target, text) {
    target.textContent += text;
    target.scrollTop = target.scrollHeight;
}

function updateTokenDisplay(tokenDiv, tokens) {
    if (!tokens || typeof tokens !== 'object') return;
    let display = 'Tokens: ';
    if (tokens.prompt_tokens !== undefined) {
        display += 'prompt=' + tokens.prompt_tokens + ' ';
    }
    if (tokens.response_tokens !== undefined) {
        display += 'response=' + tokens.response_tokens + ' ';
    } else if (tokens.completion_tokens !== undefined) {
        display += 'completion=' + tokens.completion_tokens + ' ';
    }
    if (tokens.total_tokens !== undefined) {
        display += 'total=' + tokens.total_tokens;
    }
    if (display !== 'Tokens: ') {
        tokenDiv.textContent = display;
        tokenDiv.style.display = 'block';
    }
}

if (thinkBtn) {
    thinkBtn.textContent = 'Thinking: OFF';
    thinkBtn.addEventListener('click', () => {
        thinkToggle = !thinkToggle;
        thinkBtn.textContent = thinkToggle ? 'Thinking: ON' : 'Thinking: OFF';
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

function setModeChat(enabled) {
    if (enabled) {
        document.getElementById('prompt').style.display = 'none';
        chatModeDiv.style.display = 'block';
    } else {
        document.getElementById('prompt').style.display = 'block';
        chatModeDiv.style.display = 'none';
    }
}

if (chatModeToggle) {
    chatModeToggle.addEventListener('change', (e) => {
        setModeChat(e.target.checked);
    });
}

function appendChat(role, text) {
    const wrap = document.createElement('div');
    wrap.style.margin = '6px 0';
    const bubble = document.createElement('div');
    bubble.style.display = 'inline-block';
    bubble.style.padding = '8px 12px';
    bubble.style.borderRadius = '12px';
    bubble.style.maxWidth = '86%';
    bubble.style.whiteSpace = 'pre-wrap';
    bubble.textContent = text;
    if (role === 'user') {
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

async function sendChatMessage() {
    const modelName = document.getElementById('model').value;
    const sessionId = document.getElementById('sessionId').value || 'default';
    const text = chatInput.value || '';
    if (!text.trim()) { return; }

    if (!modelName || !modelName.trim()) {
        appendChat('assistant', 'Model is required (例: live-narrator)');
        return;
    }

    appendChat('user', text);
    chatInput.value = '';
    pruneFinishedCards();

    if (activeController) {
        activeController.abort();
    }

    const controller = new AbortController();
    activeController = controller;

    const pane = createResponsePane(++requestId, true);
    const wrapper = pane.parentElement;
    const body = { model: modelName, prompt: text, session_id: sessionId, think: thinkToggle };

    pane.textContent = '';

    try {
        await sendChatStreamViaWebSocket(body, pane, controller);
    } catch (err) {
        if (err && err.name === 'AbortError') {
            appendText(pane, '\n[aborted]');
        } else {
            pane.textContent = String(err);
        }
    } finally {
        if (wrapper) {
            wrapper.dataset.status = 'done';
        }
        if (activeController === controller) {
            activeController = null;
        }
    }
}

async function sendPromptMessage() {
    const modelName = document.getElementById('model').value;
    const sessionId = document.getElementById('sessionId').value || 'default';
    const text = promptInput ? promptInput.value || '' : '';
    if (!text.trim()) { return; }

    if (!modelName || !modelName.trim()) {
        appendChat('assistant', 'Model is required (例: live-narrator)');
        return;
    }

    if (activeController) {
        activeController.abort();
    }

    const controller = new AbortController();
    activeController = controller;

    const pane = createResponsePane(++requestId, true);
    const wrapper = pane.parentElement;
    const body = { model: modelName, prompt: text, session_id: sessionId, think: thinkToggle };

    pane.textContent = '';

    try {
        await sendChatStreamViaWebSocket(body, pane, controller);
    } catch (err) {
        if (err && err.name === 'AbortError') {
            appendText(pane, '\n[aborted]');
        } else {
            pane.textContent = String(err);
        }
    } finally {
        if (wrapper) {
            wrapper.dataset.status = 'done';
        }
        if (activeController === controller) {
            activeController = null;
        }
    }
}

if (chatSendBtn) {
    chatSendBtn.addEventListener('click', () => {
        sendChatMessage();
    });
}

if (sendBtn) {
    sendBtn.addEventListener('click', () => {
        sendPromptMessage();
    });
}

chatInput.addEventListener && chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
});

if (resetSessionBtn) {
    resetSessionBtn.addEventListener('click', async () => {
        const sessionId = document.getElementById('sessionId').value || 'default';
        const pane = createResponsePane(++requestId, false);
        pane.textContent = '...resetting session';
        try {
            const r = await fetch('/session/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId }),
            });
            const t = await r.text();
            pane.textContent = t;
            if (pane.parentElement) { pane.parentElement.dataset.status = 'done'; }
            try {
                const chatMessages = document.getElementById('chatMessages');
                if (chatMessages) { chatMessages.innerHTML = ''; }
                const chatInput = document.getElementById('chatInput');
                if (chatInput) { chatInput.value = ''; }
            } catch (_) { }
        } catch (err) {
            pane.textContent = String(err);
            if (pane.parentElement) { pane.parentElement.dataset.status = 'done'; }
        }
    });
}

if (showSessionBtn) {
    showSessionBtn.addEventListener('click', async () => {
        const sessionId = document.getElementById('sessionId').value || 'default';
        const pane = createResponsePane(++requestId, false);
        pane.textContent = '...loading session memory';
        try {
            const r = await fetch('/session/get', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId }),
            });
            const t = await r.text();
            try {
                const obj = JSON.parse(t);
                pane.textContent = JSON.stringify(obj, null, 2);
            } catch (_) {
                pane.textContent = t;
            }
            if (pane.parentElement) { pane.parentElement.dataset.status = 'done'; }
        } catch (err) {
            pane.textContent = String(err);
            if (pane.parentElement) { pane.parentElement.dataset.status = 'done'; }
        }
    });
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    sendPromptMessage();
});
