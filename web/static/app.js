let ws = null;
let sessionId = getCookie('session_id') || '';
let roleId = getCookie('role_id') || '';
let aiName = '星';
let roleName = '';
let isProcessing = false;
let lastMessageTime = 0;
let logsEnabled = true;
let eventSource = null;
let currentMobileTab = 'chat';
let reconnectDelay = 2000;
const maxReconnectDelay = 30000;
let wsIntentionalClose = false;
let reconnectTimer = null;

function formatTime(ts) {
    var d = new Date(ts);
    var h = d.getHours();
    var m = d.getMinutes();
    return (h < 10 ? '0' + h : h) + ':' + (m < 10 ? '0' + m : m);
}

function formatDate(ts) {
    var d = new Date(ts);
    return (d.getMonth() + 1) + '/' + d.getDate();
}

function formatDateTime(ts) {
    var d = new Date(ts);
    var m = d.getMonth() + 1;
    var day = d.getDate();
    var h = d.getHours();
    var min = d.getMinutes();
    return (m < 10 ? '0' + m : m) + '/' + (day < 10 ? '0' + day : day) + ' ' +
           (h < 10 ? '0' + h : h) + ':' + (min < 10 ? '0' + min : min);
}

function insertTimeMarker(ts) {
    var container = document.getElementById('chat-messages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'time-marker';
    div.textContent = formatTime(ts);
    container.appendChild(div);
}

function maybeInsertTimeMarker() {
    var now = Date.now();
    if (now - lastMessageTime > 120000) {
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

function clearCookie(name) {
    document.cookie = name + '=; path=/; max-age=0';
}

function connect() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
    if (ws && ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
        return;
    }
    wsIntentionalClose = false;
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = function() {
        reconnectDelay = 2000;
        var init = { type: 'init' };
        if (sessionId) init.session_id = sessionId;
        if (roleId) init.role_id = roleId;
        ws.send(JSON.stringify(init));
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
                    if (data.name) {
                        aiName = data.name;
                        updateAIName(aiName);
                    }
                    loadHistory();
                    loadStatus();
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
                    loadStatus();
                    break;
                case 'error':
                    addSystemMessage(data.content || '出错了');
                    isProcessing = false;
                    updateSendButton();
                    hideTyping();
                    setStatus('connected');
                    break;
                case 'pong':
                    break;
            }
        } catch(e) {
            console.error('[ws] parse error:', e, event.data);
        }
    };

    ws.onclose = function() {
        setStatus('disconnected');
        hideTyping();
        if (wsIntentionalClose) return;
        reconnectTimer = setTimeout(connect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
    };

    ws.onerror = function() {
        setStatus('error');
    };

    setInterval(function() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
        }
    }, 25000);
}

function disconnectAndReconnect() {
    wsIntentionalClose = true;
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
    if (ws) {
        try { ws.close(); } catch(e) {}
    }
    reconnectDelay = 2000;
    connect();
}

function updateAIName(name) {
    var titleEl = document.querySelector('.app-header .info h1');
    if (titleEl) titleEl.textContent = name;
    var avatarEl = document.querySelector('.app-header .avatar');
    if (avatarEl) avatarEl.textContent = name;
}

function updateHeaderRole(name) {
    roleName = name || roleId;
    var titleEl = document.querySelector('.app-header .info h1');
    if (titleEl && roleName) {
        titleEl.textContent = roleName;
    }
}

function loadHistory() {
    var sid = getCookie('session_id');
    if (!sid) return;
    var controller = new AbortController();
    setTimeout(function() { controller.abort(); }, 15000);
    fetch('/api/chat/history?session_id=' + encodeURIComponent(sid), { signal: controller.signal })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var container = document.getElementById('chat-messages');
            if (!container) return;
            container.innerHTML = '';
            var turns = data.turns || [];
            for (var i = 0; i < turns.length; i++) {
                var t = turns[i];
                createMessage(t.role === 'user' ? 'user' : 'assistant', t.content, false);
            }
            if (turns.length) lastMessageTime = Date.now();
            scrollToBottom();
        })
        .catch(function(e) { console.error('[history] load failed:', e); });
}

function loadStatus() {
    var sid = getCookie('session_id') || 'default';
    var controller = new AbortController();
    setTimeout(function() { controller.abort(); }, 15000);
    fetch('/api/status?session_id=' + encodeURIComponent(sid), { signal: controller.signal })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            renderStatus(data);
        })
        .catch(function(e) { console.error('[status] load failed:', e); });
}

function renderStatus(data) {
    var turnEl = document.getElementById('status-turn');
    var emotionEl = document.getElementById('status-emotion');
    if (turnEl) turnEl.textContent = data.turn !== undefined ? data.turn : '--';
    if (emotionEl) emotionEl.textContent = data.emotion || '--';

    var rel = data.relationship || {};
    document.querySelectorAll('#relationship-grid .rel-value').forEach(function(el) {
        var key = el.getAttribute('data-key');
        var val = rel[key];
        el.textContent = val !== undefined ? val.toFixed(2) : '--';
    });

    var historyList = document.getElementById('relationship-history');
    if (historyList) {
        historyList.innerHTML = '';
        var hist = data.relationship_history || [];
        hist.slice().reverse().forEach(function(item) {
            var div = document.createElement('div');
            div.className = 'history-item';
            var dateDiv = document.createElement('div');
            dateDiv.className = 'history-date';
            dateDiv.textContent = item.timestamp ? formatDateTime(item.timestamp) : '--';
            var valsDiv = document.createElement('div');
            valsDiv.className = 'history-values';
            ['trust', 'familiarity', 'intimacy', 'fun'].forEach(function(k) {
                var span = document.createElement('span');
                span.textContent = k + ': ' + (item[k] !== undefined ? item[k].toFixed(2) : '--');
                valsDiv.appendChild(span);
            });
            div.appendChild(dateDiv);
            div.appendChild(valsDiv);
            historyList.appendChild(div);
        });
    }
}

function connectLogs() {
    if (eventSource) {
        eventSource.close();
    }
    if (!logsEnabled) return;

    var content = document.getElementById('logs-content');
    if (!content) return;

    eventSource = new EventSource('/api/logs');
    eventSource.onmessage = function(e) {
        appendLogLine(e.data);
    };
    eventSource.onerror = function(e) {
        console.error('[logs] sse error:', e);
    };
}

function appendLogLine(line) {
    var content = document.getElementById('logs-content');
    if (!content) return;
    var div = document.createElement('div');
    div.className = 'log-line';

    var levelMatch = line.match(/\[(INFO|WARNING|ERROR|CRITICAL|DEBUG)\]/);
    if (levelMatch) {
        div.classList.add('level-' + levelMatch[1]);
    }

    div.textContent = line;
    content.appendChild(div);

    // Keep last 500 lines
    while (content.children.length > 500) {
        content.removeChild(content.firstChild);
    }

    content.scrollTop = content.scrollHeight;
}

function setStatus(s) {
    var dot = document.getElementById('status-dot');
    var text = document.getElementById('status-text');
    if (!dot || !text) return;
    var m = {
        connected: '在线',
        disconnected: '已断开',
        error: '连接异常',
        thinking: '输入中'
    };
    dot.className = 'dot ' + (s || 'disconnected');
    text.textContent = m[s] || m.disconnected;
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
    if (c) c.scrollTop = c.scrollHeight;
}

function addSystemMessage(text) {
    var c = document.getElementById('chat-messages');
    if (!c) return;
    var d = document.createElement('div');
    d.className = 'system-message';
    d.textContent = text;
    c.appendChild(d);
    scrollToBottom();
}

function createMessage(role, content, autoScroll) {
    autoScroll = autoScroll !== false;
    var container = document.getElementById('chat-messages');
    if (!container) return;
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
    if (autoScroll) scrollToBottom();
    return div;
}

function updateSendButton() {
    var b = document.getElementById('send-btn');
    var i = document.getElementById('input');
    if (!b || !i) return;
    b.disabled = isProcessing || !i.value.trim();
}

function sendMessage() {
    var input = document.getElementById('input');
    if (!input) return;
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
            loadStatus();
        })
        .catch(function(err) {
            console.error('[rest] chat failed:', err);
            hideTyping(); isProcessing = false; updateSendButton(); setStatus('connected');
        });
    }
}

/* Role selection */
function showModal(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = 'flex';
}

function hideModal(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

function openRoleModal() {
    var list = document.getElementById('role-list');
    if (!list) return;
    list.innerHTML = '<div class="system-message">加载中...</div>';
    showModal('role-modal');

    fetch('/api/roles')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            list.innerHTML = '';
            var roles = data.roles || [];
            roles.forEach(function(role) {
                var card = document.createElement('div');
                card.className = 'role-card';
                card.innerHTML = '<div class="avatar">' + (role.name ? role.name[0] : 'AI') + '</div><div class="name">' + escapeHtml(role.name || role.id) + '</div>';
                card.addEventListener('click', function() {
                    selectRole(role.id, role.name);
                });
                list.appendChild(card);
            });
        })
        .catch(function(e) {
            console.error('[roles] load failed:', e);
            list.innerHTML = '<div class="system-message">加载失败</div>';
        });
}

function selectRole(id, name) {
    roleId = id;
    roleName = name || id;
    sessionId = id;  // 一个角色只有一个 session
    setCookie('role_id', roleId);
    setCookie('session_id', sessionId);
    updateHeaderRole(roleName);
    hideModal('role-modal');
    disconnectAndReconnect();
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/* UI interactions */
function togglePanel(panelName) {
    var panel = document.getElementById(panelName + '-panel');
    if (!panel) return;
    panel.classList.toggle('open');
    panel.classList.toggle('collapsed');
}

function switchMobileTab(tab) {
    currentMobileTab = tab;
    var chatSection = document.getElementById('chat-section');
    var statusPanel = document.getElementById('status-panel');
    var logsPanel = document.getElementById('logs-panel');

    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tab);
    });

    if (tab === 'chat') {
        chatSection.classList.remove('hidden-mobile');
        statusPanel.classList.remove('open');
        logsPanel.classList.remove('open');
    } else if (tab === 'status') {
        chatSection.classList.add('hidden-mobile');
        statusPanel.classList.add('open');
        logsPanel.classList.remove('open');
    } else if (tab === 'logs') {
        chatSection.classList.add('hidden-mobile');
        statusPanel.classList.remove('open');
        logsPanel.classList.add('open');
    }
}

function setupUI() {
    var switchRoleBtn = document.getElementById('switch-role-btn');
    if (switchRoleBtn) {
        switchRoleBtn.addEventListener('click', function() {
            openRoleModal();
        });
    }

    document.querySelectorAll('.panel-collapse').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var panel = btn.getAttribute('data-panel');
            togglePanel(panel);
        });
    });

    document.querySelectorAll('.panel-expand-bar').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var panel = btn.getAttribute('data-panel');
            togglePanel(panel);
        });
    });

    document.querySelectorAll('.panel-close').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var panel = btn.getAttribute('data-panel');
            if (window.innerWidth <= 600) {
                switchMobileTab('chat');
            } else {
                togglePanel(panel);
            }
        });
    });

    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            switchMobileTab(btn.getAttribute('data-tab'));
        });
    });

    var input = document.getElementById('input');
    var btn = document.getElementById('send-btn');
    if (input) {
        input.addEventListener('input', function() {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
            updateSendButton();
        });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });
    }
    if (btn) btn.addEventListener('click', sendMessage);
    updateSendButton();
}

function initApp() {
    setupUI();
    connectLogs();
    if (!roleId) {
        openRoleModal();
    } else {
        // 一个角色只有一个 session，session_id 必须与 role_id 一致
        sessionId = roleId;
        setCookie('session_id', sessionId);
        updateHeaderRole(roleName);
        connect();
    }
}

(function() {
    document.addEventListener('DOMContentLoaded', initApp);
})();
