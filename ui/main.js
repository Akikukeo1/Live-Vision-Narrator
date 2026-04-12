console.log('Ollama UI script loaded');
window.addEventListener('error', (e) => { console.error('UI error', e); });

// API Base URL - LAN 内のホストを自動判別、デフォルト以外の設定は /api-config から取得
let API_BASE_URL = `${location.protocol}//${location.hostname}:8000`; // ローカルホスト型フォールバック

// Fetch API configuration from UI server
(async () => {
    try {
        const response = await fetch('/api-config');
        if (response.ok) {
            const config = await response.json();
            API_BASE_URL = config.api_base_url || API_BASE_URL;
            console.log('API Base URL configured:', API_BASE_URL);
        }
    } catch (err) {
        console.warn('Failed to fetch API config, using default:', API_BASE_URL, err);
    }
})();

const form = document.getElementById('form');
const sendBtn = document.getElementById('sendBtn');
const resetSessionBtn = document.getElementById('resetSessionBtn');
const showSessionBtn = document.getElementById('showSessionBtn');
const thinkBtn = document.getElementById('thinkBtn');
const showCoTToggle = document.getElementById('showCoTToggle');
const showInnerToggle = document.getElementById('showInnerToggle');
const saveInnerToggle = document.getElementById('saveInnerToggle');
const innerDetailSelect = document.getElementById('innerDetailSelect');
const systemProfile = document.getElementById('systemProfile');
const systemOverride = document.getElementById('systemOverride');
const responses = document.getElementById('responses');
let activeController = null;
let requestId = 0;
let thinkToggle = false;

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

// ============================================================================
// システムプロファイル管理
// ============================================================================

async function loadSystemProfiles() {
    // 利用可能なシステムプロファイルの一覧を取得してセレクタに入れます
    try {
        const response = await fetch(API_BASE_URL + '/system-profiles');
        if (!response.ok) return;
        const data = await response.json();
        if (!data.profiles) return;

        const select = document.getElementById('systemProfile');
        if (!select) return;

        // 既存のオプションをクリア（デフォルト値は残す）
        const defaultOption = select.querySelector('option[value=""]');
        select.innerHTML = '';
        if (defaultOption) select.appendChild(defaultOption);

        // 取得したプロファイルをオプションに追加
        for (const [key, profile] of Object.entries(data.profiles)) {
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = key;
            select.appendChild(opt);
        }
    } catch (err) {
        console.warn('Failed to load system profiles:', err);
    }
}

// Initialize system profiles on page load
(async () => {
    await loadSystemProfiles();
})();

if (sendBtn) {
    sendBtn.addEventListener('click', () => {
        try { form.requestSubmit(); } catch (err) { form.dispatchEvent(new Event('submit', { cancelable: true })); }
    });
}

if (thinkBtn) {
    thinkBtn.addEventListener('click', () => {
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

function setModeChat(enabled) {
    if (enabled) {
        document.getElementById('prompt').style.display = 'none';
        document.getElementById('params').style.display = 'none';
        chatModeDiv.style.display = 'block';
    } else {
        document.getElementById('prompt').style.display = 'block';
        document.getElementById('params').style.display = 'block';
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

async function sendChatMessage(streaming) {
    const modelName = document.getElementById('model').value;
    const sessionId = document.getElementById('sessionId').value || 'default';
    const text = chatInput.value || '';
    if (!text.trim()) { return; }
    appendChat('user', text);
    chatInput.value = '';

    // Build parameters for chat request
    let chatParams = {};
    if (thinkToggle) { chatParams.think = true; }
    if (showCoTToggle && showCoTToggle.checked) { chatParams.reveal_thoughts = true; }
    if (showInnerToggle && showInnerToggle.checked) {
        chatParams.reveal_thoughts = true;
        chatParams.options = chatParams.options || {};
        chatParams.options.think = true;
    }
    if (saveInnerToggle && saveInnerToggle.checked) { chatParams.save_inner = true; }
    if (innerDetailSelect && innerDetailSelect.value) { chatParams.inner_detail = innerDetailSelect.value; }
    if (systemProfile && systemProfile.value) { chatParams.system_profile = systemProfile.value; }
    if (systemOverride && systemOverride.value && systemOverride.value.trim()) {
        chatParams.system_override = systemOverride.value.trim();
    }

    const body = { model: modelName, prompt: text, parameters: chatParams, session_id: sessionId };

    try {
        if (!streaming) {
            const r = await fetch(API_BASE_URL + '/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (!r.ok) { appendChat('assistant', 'Error: ' + r.status); return; }
            const t = await r.text();
            try {
                const obj = JSON.parse(t);
                appendChat('assistant', String(obj.response ?? t));
            }
            catch { appendChat('assistant', t); }
            return;
        }

        const r = await fetch(API_BASE_URL + '/generate/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!r.ok) { appendChat('assistant', 'Error: ' + r.status); return; }
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
        const wrapper = document.createElement('div');
        wrapper.style.margin = '6px 0';
        wrapper.appendChild(assistantNode);
        chatMessages.appendChild(wrapper);

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split(/\r?\n/);
            buffer = parts.pop();
            for (const part of parts) {
                if (!part.trim()) continue;
                try {
                    const obj = JSON.parse(part);
                    if (obj.thinking !== undefined) {
                        if (!wrapper.thinkingPre) {
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
                            wrapper.appendChild(tl);
                            wrapper.appendChild(tp);
                            wrapper.thinkingPre = tp;
                            wrapper.thinkingLabel = tl;
                        }
                        wrapper.thinkingLabel.style.display = 'block';
                        wrapper.thinkingPre.style.display = 'block';
                        wrapper.thinkingPre.textContent += obj.thinking;
                    }
                    if (obj.response !== undefined) { assistantNode.textContent += obj.response; }
                    else if (obj.choices && Array.isArray(obj.choices)) { obj.choices.forEach(c => { if (c.text) assistantNode.textContent += c.text; }); }
                } catch (_) { }
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }

        if (buffer.trim()) {
            try {
                const obj = JSON.parse(buffer);

                if (obj.response !== undefined) assistantNode.textContent += obj.response;
                if (obj.thinking !== undefined) {
                    if (!wrapper.thinkingPre) {
                        const tl = document.createElement('div');
                        tl.style.fontSize = '12px';
                        tl.style.color = '#9ca3af';
                        tl.textContent = 'Thinking';
                        tl.style.marginTop = '6px';
                        const tp = document.createElement('pre');
                        tp.style.background = '#fff7ed';
                        tp.style.padding = '8px';
                        tp.style.borderRadius = '6px';
                        tp.style.maxHeight = '200px';
                        tp.style.overflow = 'auto';
                        tp.style.marginTop = '6px';
                        wrapper.appendChild(tl);
                        wrapper.appendChild(tp);
                        wrapper.thinkingPre = tp;
                        wrapper.thinkingLabel = tl;
                    }
                    wrapper.thinkingLabel.style.display = 'block';
                    wrapper.thinkingPre.style.display = 'block';
                    wrapper.thinkingPre.textContent += obj.thinking;
                }
            } catch (_) { }
        }
        chatMessages.scrollTop = chatMessages.scrollHeight;
    } catch (err) { appendChat('assistant', String(err)); }
}

if (chatSendBtn) {
    chatSendBtn.addEventListener('click', () => {
        const streaming = document.getElementById('streamToggle').checked;
        sendChatMessage(streaming);
    });
}

chatInput.addEventListener && chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const streaming = document.getElementById('streamToggle').checked;
        sendChatMessage(streaming);
    }
});

if (resetSessionBtn) {
    resetSessionBtn.addEventListener('click', async () => {
        const sessionId = document.getElementById('sessionId').value || 'default';
        const pane = createResponsePane(++requestId, false);
        pane.textContent = '...resetting session';
        try {
            const r = await fetch(API_BASE_URL + '/session/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId }),
            });
            const t = await r.text();
            pane.textContent = t;
            if (pane.parentElement) { pane.parentElement.dataset.status = 'done'; }
            // Also clear chat UI if present
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
            const r = await fetch(API_BASE_URL + '/session/get', {
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

    const modelName = document.getElementById('model').value;
    const sessionId = document.getElementById('sessionId').value || 'default';
    const prompt = document.getElementById('prompt').value;
    const stream = document.getElementById('streamToggle').checked;
    const allowParallel = document.getElementById('parallelToggle').checked;

    if (!modelName || !modelName.trim()) {
        const pane = createResponsePane(++requestId, !allowParallel);
        pane.textContent = 'Model is required (例: live-narrator)';
        if (pane.parentElement) { pane.parentElement.dataset.status = 'done'; }
        return;
    }

    let parameters = {};
    try { parameters = JSON.parse(document.getElementById('params').value); }
    catch (err) {
        const pane = createResponsePane(++requestId, !allowParallel);
        pane.textContent = 'Invalid JSON in parameters';
        if (pane.parentElement) { pane.parentElement.dataset.status = 'done'; }
        return;
    }

    // Inject parameters
    parameters = parameters || {};
    if (thinkToggle) { parameters.think = true; }
    if (showCoTToggle && showCoTToggle.checked) { parameters.reveal_thoughts = true; }
    if (showInnerToggle && showInnerToggle.checked) {
        parameters.reveal_thoughts = true;
        parameters.options = parameters.options || {};
        parameters.options.think = true;
    }
    if (saveInnerToggle && saveInnerToggle.checked) { parameters.save_inner = true; }
    if (innerDetailSelect && innerDetailSelect.value) { parameters.inner_detail = innerDetailSelect.value; }
    if (systemProfile && systemProfile.value) { parameters.system_profile = systemProfile.value; }
    if (systemOverride && systemOverride.value && systemOverride.value.trim()) {
        parameters.system_override = systemOverride.value.trim();
        console.warn('system_override を使用します。ローカル開発環境専用です。');
    }

    console.log('Request parameters:', parameters);

    if (allowParallel) {
        pruneFinishedCards();
    }

    if (!allowParallel && activeController) {
        activeController.abort();
    }

    const controller = new AbortController();
    if (!allowParallel) {
        activeController = controller;
    }

    const pane = createResponsePane(++requestId, !allowParallel);
    const isThinkingNow = parameters && parameters.think;
    if (isThinkingNow) { pane.textContent = 'Thinking中だから待ってね〜\n'; }
    const body = { model: modelName, prompt, parameters, session_id: sessionId };

    console.log('Form submit: session=%s, model=%s, prompt_len=%d, streaming=%s, parallel=%s', sessionId, modelName, prompt.length, stream, allowParallel);

    try {
        if (!stream) {
            pane.textContent = '...sending';
            const r = await fetch(API_BASE_URL + '/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: controller.signal,
            });
            if (!r.ok) {
                const errText = await r.text();
                pane.textContent = 'Error: ' + r.status + '\n' + errText;
                return;
            }
            const t = await r.text();
            try {
                const obj = JSON.parse(t);
                if (obj && typeof obj === 'object' && obj.response !== undefined) {
                    pane.textContent = String(obj.response);
                    if (obj.thinking !== undefined) {
                        const card = pane.parentElement;
                        if (card && card.thinkingPre) {
                            card.thinkingLabel.style.display = 'block';
                            card.thinkingPre.style.display = 'block';
                            card.thinkingPre.textContent = String(obj.thinking);
                        }
                    }
                    if (obj.tokens !== undefined && pane.parentElement && pane.parentElement.tokenDiv) {
                        updateTokenDisplay(pane.parentElement.tokenDiv, obj.tokens);
                    }
                } else {
                    pane.textContent = JSON.stringify(obj, null, 2);
                }
            }
            catch (_) { pane.textContent = t; }
            return;
        }

        pane.textContent = '';
        const r = await fetch(API_BASE_URL + '/generate/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: controller.signal,
        });

        if (!r.ok) {
            const errText = await r.text();
            pane.textContent = 'Error: ' + r.status + '\n' + errText;
            return;
        }

        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split(/\r?\n/);
            buffer = parts.pop();
            for (const part of parts) {
                if (!part.trim()) continue;
                try {
                    const obj = JSON.parse(part);

                    if (obj.thinking !== undefined) {
                        const card = pane.parentElement;
                        if (card && card.thinkingPre) {
                            card.thinkingLabel.style.display = 'block';
                            card.thinkingPre.style.display = 'block';
                            card.thinkingPre.textContent += obj.thinking;
                        }
                    }
                    if (obj.response !== undefined) {
                        appendText(pane, obj.response);
                    } else if (obj.choices && Array.isArray(obj.choices)) {
                        obj.choices.forEach(c => { if (c.text) appendText(pane, c.text); });
                    }
                    if (obj.tokens !== undefined && pane.parentElement && pane.parentElement.tokenDiv) {
                        updateTokenDisplay(pane.parentElement.tokenDiv, obj.tokens);
                    }
                } catch (_) {
                    // Ignore malformed fragments
                }
            }
        }

        if (buffer.trim()) {
            try {
                const obj = JSON.parse(buffer);
                if (obj.response !== undefined) appendText(pane, obj.response);
                if (obj.thinking !== undefined) {
                    const card = pane.parentElement;
                    if (card && card.thinkingPre) {
                        card.thinkingLabel.style.display = 'block';
                        card.thinkingPre.style.display = 'block';
                        card.thinkingPre.textContent += obj.thinking;
                    }
                }
                if (obj.tokens !== undefined && pane.parentElement && pane.parentElement.tokenDiv) {
                    updateTokenDisplay(pane.parentElement.tokenDiv, obj.tokens);
                }
            } catch (_) {
                // ignore trailing partial fragment
            }
        }
    } catch (err) {
        if (err && err.name === 'AbortError') {
            appendText(pane, '\n[aborted]');
        } else {
            pane.textContent = String(err);
        }
    } finally {
        if (pane.parentElement) {
            pane.parentElement.dataset.status = 'done';
        }
        if (activeController === controller) {
            activeController = null;
        }
    }
});
