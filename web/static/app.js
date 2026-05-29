let ws = null;
let sessionId = getCookie('session_id') || '';
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

function splitSegments(text) {
    // Step 1: split on sentence-ending punctuation (handles trailing quotes/brackets)
    var parts = text.split(/(?<=[。！？.!?\n])(?:[」"'')]?\s*)(?=\S)/).filter(function(s) { return s.trim(); });
    if (parts.length > 1) {
        return _mergeShort(parts);
    }

    // Step 2: split on whitespace
    var spaceParts = text.split(/\s+/).filter(function(s) { return s.trim(); });
    if (spaceParts.length > 1) {
        return _mergeShort(spaceParts);
    }

    // Step 3: split after 语气词
    if (text.length > 10) {
        var toneParts = text.split(/(?<=[啊吗呢了吧么呀哦嘛哇])/).filter(function(s) { return s.trim(); });
        if (toneParts.length > 1) {
            return _mergeShort(toneParts);
        }
    }

    // Step 4: last resort for long text — split at natural pauses
    if (text.length > 25) {
        var naturalParts = text.split(/(?<=[了过完好到])|(?<=然后|但是|不过|所以|因为|而且|或者|只是|于是|接着|还有|另外|虽然|如果|可以|应该)/).filter(function(s) { return s.trim(); });
        if (naturalParts.length > 1) {
            return _mergeShort(naturalParts);
        }
        // absolute fallback: hard-split
        var chunked = [];
        for (var i = 0; i < text.length; i += 18) {
            chunked.push(text.slice(i, i + 18));
        }
        return _mergeShort(chunked);
    }

    return [text];
}

function _mergeShort(parts) {
    var merged = [];
    for (var i = 0; i < parts.length; i++) {
        var s = parts[i];
        if (merged.length && s.length < 4) {
            merged[merged.length - 1] += s;
        } else {
            merged.push(s);
        }
    }
    return merged;
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
                    break;
                case 'segment':
                    hideTyping();
                    createMessage('assistant', data.content);
                    scrollToBottom();
                    break;
                case 'done':
                    isProcessing = false;
                    updateSendButton();
                    setStatus('connected');
                    hideTyping();
                    if (data.emotion) showEmotion(data.emotion);
                    break;
                case 'error':
                case 'pong':
                    break;
            }
        } catch(e) {}
    };

    ws.onclose = function() {
        setStatus('disconnected'); hideTyping();
        setTimeout(connect, 3000);
    };

    ws.onerror = function() { setStatus('error'); };
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
    av.textContent = role === 'user' ? '我' : '星';
    var bb = document.createElement('div');
    bb.className = 'bubble';
    bb.textContent = content;
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
        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: sessionId }),
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            hideTyping();
            var resp = data.response || '';
            var segs = splitSegments(resp);
            var delay = 0;
            for (var i = 0; i < segs.length; i++) {
                (function(seg) {
                    setTimeout(function() { createMessage('assistant', seg); }, delay);
                })(segs[i]);
                delay += 1200;
            }
            if (data.emotion) showEmotion(data.emotion);
            setTimeout(function() {
                isProcessing = false; updateSendButton(); setStatus('connected');
            }, delay);
        })
        .catch(function(err) {
            hideTyping(); isProcessing = false; updateSendButton(); setStatus('connected');
        });
    }
}

(function() {
    setInterval(function() {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
    }, 30000);
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
