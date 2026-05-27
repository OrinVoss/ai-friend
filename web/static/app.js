let ws = null;
let sessionId = getCookie('session_id') || '';
let isProcessing = false;

function getCookie(name) {
    const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? match[2] : '';
}

function setCookie(name, value) {
    document.cookie = name + '=' + value + '; path=/; max-age=86400';
}

function connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'init', session_id: sessionId }));
        setStatus('connected');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

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
                isProcessing = false;
                updateSendButton();
                setStatus('connected');
                hideTyping();
                addSystemMessage('错误: ' + data.content);
                break;

            case 'pong':
                break;
        }
    };

    ws.onclose = () => {
        setStatus('disconnected');
        hideTyping();
        setTimeout(connect, 3000);
    };

    ws.onerror = () => {
        setStatus('error');
    };
}

function setStatus(status) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (!dot || !text) return;
    switch (status) {
        case 'connected':
            dot.style.background = '#4ade80';
            text.textContent = '在线';
            break;
        case 'disconnected':
            dot.style.background = '#f87171';
            text.textContent = '已断开';
            break;
        case 'error':
            dot.style.background = '#fbbf24';
            text.textContent = '连接异常';
            break;
        case 'thinking':
            dot.style.background = '#fbbf24';
            text.textContent = '输入中';
            break;
    }
}

function showTyping() {
    const el = document.getElementById('typing-dots');
    if (el) el.style.display = 'inline-flex';
}

function hideTyping() {
    const el = document.getElementById('typing-dots');
    if (el) el.style.display = 'none';
}

function showEmotion(emotion) {
    const el = document.getElementById('emotion-text');
    if (el) el.textContent = emotion || '';
}

function scrollToBottom() {
    const container = document.getElementById('chat-messages');
    container.scrollTop = container.scrollHeight;
}

function addSystemMessage(text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.style.cssText = 'text-align:center;color:#666;font-size:12px;padding:4px 0;';
    div.textContent = text;
    container.appendChild(div);
    scrollToBottom();
}

function createMessage(role, content) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message ' + role;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? '我' : '星';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = content;

    div.appendChild(avatar);
    div.appendChild(bubble);
    container.appendChild(div);
    scrollToBottom();
    return div;
}

function updateSendButton() {
    const btn = document.getElementById('send-btn');
    const input = document.getElementById('input');
    btn.disabled = isProcessing || !input.value.trim();
}

function sendMessage() {
    const input = document.getElementById('input');
    const text = input.value.trim();
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
        .then(r => r.json())
        .then(data => {
            hideTyping();
            createMessage('assistant', data.response);
            if (data.emotion) showEmotion(data.emotion);
            isProcessing = false;
            updateSendButton();
            setStatus('connected');
        })
        .catch(err => {
            hideTyping();
            addSystemMessage('请求失败: ' + err.message);
            isProcessing = false;
            updateSendButton();
            setStatus('connected');
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    connect();
    const input = document.getElementById('input');
    const btn = document.getElementById('send-btn');

    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        updateSendButton();
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    btn.addEventListener('click', sendMessage);
    updateSendButton();
});
