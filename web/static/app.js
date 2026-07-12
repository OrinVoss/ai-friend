let ws = null;
let sessionId = getCookie('session_id') || '';
let aiName = '星';
let isProcessing = false;
let lastMessageTime = 0;

function formatTime(ts) {
    var d = new Date(ts);
    var h = d.getHours();
    var m = d.getMinutes();
    return (h < 10 ? '0' + h : h) + ':' + (m < 10 ? '0' + m : m);
}

function insertTimeMarker(ts) {
    var container = document.getElementById('chat-messages');
    var div = document.createElement('div');
    div.className = 'time-marker';
    div.textContent = formatTime(ts);
    container.appendChild(div);
}

function maybeInsertTimeMarker() {
    var now = Date.now();
    if (now - lastMessageTime > 120000) {  // 2 min gap
        insertTimeMarker(now);
    }
    lastMessageTime = now;
}

function getCookie(name) {
    const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? match[2] : '';
}

function setCookie(name, value) {
    document.cookie = name + '=' + value + '; path=/; max-age=86400';
}

function connect() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = function() {
        ws.send(JSON.stringify({ type: 'init', session_id: sessionId }));
        setStatus('connected');
    };

    ws.onmessage = function(event) {
        try {
            var data = JSON.parse(event.data);
            switch (data.type) {
                case 'init_ok':
                    sessionId = data.session_id;
                    setCookie('session_id', sessionId);
                    showEmotion(data.emotion);
                    // FJ-007/FH-003: dynamic personality name
                    if (data.name) {
                        aiName = data.name;
                        var titleEl = document.querySelector('.chat-header .info h1');
                        if (titleEl) titleEl.textContent = aiName;
                        var avatarEl = document.querySelector('.chat-header .avatar');
                        if (avatarEl) avatarEl.textContent = aiName;
                    }
                    loadHistory();
                    break;
                case 'segment':
                    hideTyping();
                    var lastBubble = document.querySelector('.message.assistant:last-child .bubble');
                    if (lastBubble) {
                        var raw = lastBubble.getAttribute('data-raw') || '';
                        raw += data.content;
                        lastBubble.setAttribute('data-raw', raw);
                        lastBubble.textContent = raw;
                    } else {
                        createMessage('assistant', data.content);
                        var nb = document.querySelector('.message.assistant:last-child .bubble');
                        if (nb) nb.setAttribute('data-raw', data.content);
                    }
                    scrollToBottom();
                    break;
                case 'done':
                    isProcessing = false;
                    updateSendButton();
                    setStatus('connected');
                    hideTyping();
                    if (typeof marked !== 'undefined') {
                        var lastBubble = document.querySelector('.message.assistant:last-child .bubble');
                        if (lastBubble) {
                            var raw = lastBubble.getAttribute('data-raw') || lastBubble.textContent;
                            lastBubble.innerHTML = marked.parse(raw);
                            lastBubble.removeAttribute('data-raw');
                        }
                    }
                    if (data.emotion) showEmotion(data.emotion);
                    break;
                case 'error':
                case 'pong':
                    break;
            }
        } catch(e) {
            console.error('[ws] parse error:', e, event.data);
        }
    };

    var reconnectDelay = 2000;
    const maxReconnectDelay = 30000;

    ws.onclose = function() {
        setStatus('disconnected'); hideTyping();
        // #277: exponential backoff for reconnect
        setTimeout(connect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
    };

    ws.onopen = function() {
        reconnectDelay = 2000;  // reset on successful connection
        ws.send(JSON.stringify({ type: 'init', session_id: sessionId }));
        setStatus('connected');
    };

    ws.onerror = function() { setStatus('error'); };

    // Keepalive ping every 25s to prevent proxy timeout
    setInterval(function() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
        }
    }, 25000);
}

function loadHistory() {
    var sid = getCookie('session_id');
    if (!sid) return;
    // FJ-009: AbortController 15s timeout
    var controller = new AbortController();
    setTimeout(function() { controller.abort(); }, 15000);
    fetch('/api/chat/history?session_id=' + encodeURIComponent(sid), { signal: controller.signal })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var turns = data.turns || [];
            for (var i = 0; i < turns.length; i++) {
                var t = turns[i];
                createMessage(t.role === 'user' ? 'user' : 'assistant', t.content);
            }
            scrollToBottom();
        })
        .catch(function(e) { console.error('[history] load failed:', e); });
}

function setStatus(s) {
    var dot = document.getElementById('status-dot');
    var text = document.getElementById('status-text');
    if (!dot || !text) return;
    var m = {
        connected: ['#4ade80','在线'],
        disconnected: ['#f87171','已断开'],
        error: ['#fbbf24','连接异常'],
        thinking: ['#fbbf24','输入中']
    };
    var st = m[s] || m.disconnected;
    dot.style.background = st[0];
    text.textContent = st[1];
}

function showTyping() {
    var el = document.getElementById('typing-dots');
    if (el) el.style.display = 'inline-flex';
}

function hideTyping() {
    var el = document.getElementById('typing-dots');
    if (el) el.style.display = 'none';
}

function showEmotion(emotion) {
    var el = document.getElementById('emotion-text');
    if (el) el.textContent = emotion || '';
}

function scrollToBottom() {
    var c = document.getElementById('chat-messages');
    c.scrollTop = c.scrollHeight;
}

function addSystemMessage(text) {
    var c = document.getElementById('chat-messages');
    var d = document.createElement('div');
    d.style.cssText = 'text-align:center;color:#666;font-size:12px;padding:4px 0;';
    d.textContent = text;
    c.appendChild(d);
    scrollToBottom();
}

function createMessage(role, content) {
    var container = document.getElementById('chat-messages');
    maybeInsertTimeMarker();
    var div = document.createElement('div');
    div.className = 'message ' + role;
    var av = document.createElement('div');
    av.className = 'avatar';
    av.textContent = role === 'user' ? '我' : aiName;
    var bb = document.createElement('div');
    bb.className = 'bubble';
    if (role === 'assistant' && typeof marked !== 'undefined') {
        bb.innerHTML = marked.parse(content);
    } else {
        bb.textContent = content;
    }
    div.appendChild(av);
    div.appendChild(bb);
    container.appendChild(div);
    scrollToBottom();
    return div;
}

function updateSendButton() {
    var b = document.getElementById('send-btn');
    var i = document.getElementById('input');
    b.disabled = isProcessing || !i.value.trim();
}

function sendMessage() {
    var input = document.getElementById('input');
    var text = input.value.trim();
    if (!text || isProcessing) return;
    input.value = '';
    input.style.height = 'auto';
    isProcessing = true;
    updateSendButton();
    setStatus('thinking');
    showTyping();
    createMessage('user', text);

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'message', content: text }));
    } else {
        // FJ-009: AbortController 15s timeout for REST fallback
        var controller = new AbortController();
        setTimeout(function() { controller.abort(); }, 15000);
        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: sessionId }),
            signal: controller.signal,
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            hideTyping();
            var resp = data.response || '';
            createMessage('assistant', resp);
            if (data.emotion) showEmotion(data.emotion);
            isProcessing = false; updateSendButton(); setStatus('connected');
        })
        .catch(function(err) {
            console.error('[rest] chat failed:', err);
            hideTyping(); isProcessing = false; updateSendButton(); setStatus('connected');
        });
    }
}

(function() {
    document.addEventListener('DOMContentLoaded', function() {
        connect();
        var input = document.getElementById('input');
        var btn = document.getElementById('send-btn');
        input.addEventListener('input', function() {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
            updateSendButton();
        });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });
        btn.addEventListener('click', sendMessage);
        updateSendButton();
    });
})();
