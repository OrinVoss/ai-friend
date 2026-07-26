let ws = null;
let sessionId = getCookie('session_id') || '';
let roleId = getCookie('role_id') || '';
let aiName = 'AI'; // L-06: 窗口期默认值，init_ok 后由 data.name 覆盖
let roleName = '';
let isProcessing = false;
let lastMessageTime = 0;
let logsEnabled = true;
let stickToBottom = true;
let newMsgCount = 0;

// A1: 可选 token 鉴权（web_access_token）——token 存 localStorage，
// 401 时提示输入并重载
function getToken() { return localStorage.getItem('ai_friend_token') || ''; }
function withToken(url) {
    var t = getToken();
    return t ? url + (url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(t) : url;
}
function authFetch(url, opts) {
    opts = opts || {};
    if (getToken()) {
        opts.headers = Object.assign({}, opts.headers, { 'Authorization': 'Bearer ' + getToken() });
    }
    return fetch(url, opts).then(function(resp) {
        if (resp.status === 401) {
            var t = prompt('需要访问令牌（web_access_token）：');
            if (t) { localStorage.setItem('ai_friend_token', t); location.reload(); }
        }
        return resp;
    });
}
let eventSource = null;
let currentMobileTab = 'chat';
let reconnectDelay = 2000;
const maxReconnectDelay = 30000;
let wsIntentionalClose = false;
let reconnectTimer = null;

/* ---------- 主题（浅色/深色，localStorage 持久化，缺省跟随系统） ---------- */
var THEME_ICONS = {
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>',
    moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>'
};

function isDarkTheme() {
    var t = document.documentElement.getAttribute('data-theme');
    if (t) return t === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function updateThemeIcon() {
    var btn = document.getElementById('theme-toggle-btn');
    if (!btn) return;
    // 深色下显示太阳（切回浅色），浅色下显示月亮
    btn.innerHTML = isDarkTheme() ? THEME_ICONS.sun : THEME_ICONS.moon;
}

function toggleTheme() {
    var next = isDarkTheme() ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('ai_friend_theme', next); } catch (e) {}
    updateThemeIcon();
}

function initTheme() {
    var saved = '';
    try { saved = localStorage.getItem('ai_friend_theme') || ''; } catch (e) {}
    if (saved === 'light' || saved === 'dark') {
        document.documentElement.setAttribute('data-theme', saved);
    }
    updateThemeIcon();
    if (window.matchMedia) {
        var mq = window.matchMedia('(prefers-color-scheme: dark)');
        var onChange = function() {
            var manual = '';
            try { manual = localStorage.getItem('ai_friend_theme') || ''; } catch (e) {}
            if (!manual) updateThemeIcon();
        };
        if (mq.addEventListener) mq.addEventListener('change', onChange);
        else if (mq.addListener) mq.addListener(onChange);
    }
}

/* ---------- 时间 ---------- */
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
    // SameSite=Lax: 防止跨站请求附带此 cookie。
    // 不加 HttpOnly: session_id 需要被 JS 读取后放进 WebSocket init 消息。
    // 不加 Secure: 本地开发使用 http，Secure 会导致 cookie 无法写入。
    document.cookie = name + '=' + value + '; path=/; max-age=86400; SameSite=Lax';
}

function clearCookie(name) {
    document.cookie = name + '=; path=/; max-age=0; SameSite=Lax';
}

/* ---------- Markdown 渲染（流式与终态共用，失败回退纯文本） ---------- */
function renderMarkdownInto(bubble, raw) {
    if (typeof marked !== 'undefined') {
        try {
            bubble.innerHTML = marked.parse(raw);
            return;
        } catch (e) { /* fall through to plain text */ }
    }
    bubble.textContent = raw;
}

/* ---------- 智能滚动：贴底才跟随，上翻时显示"回到底部"按钮 ---------- */
function isNearBottom() {
    var c = document.getElementById('chat-messages');
    if (!c) return true;
    return c.scrollHeight - c.scrollTop - c.clientHeight < 60;
}

// countAsNew: 未贴底时是否把这次内容计入"新消息"角标
function maybeScroll(countAsNew) {
    var c = document.getElementById('chat-messages');
    if (!c) return;
    if (stickToBottom) {
        c.scrollTo({ top: c.scrollHeight, behavior: 'auto' });
    } else if (countAsNew !== false) {
        newMsgCount++;
        updateScrollBottomBtn();
    }
}

function scrollToBottom() {
    var c = document.getElementById('chat-messages');
    if (c) c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' });
    stickToBottom = true;
    newMsgCount = 0;
    updateScrollBottomBtn();
}

function updateScrollBottomBtn() {
    var btn = document.getElementById('scroll-bottom-btn');
    var cnt = document.getElementById('new-count');
    if (!btn) return;
    if (stickToBottom) {
        btn.style.display = 'none';
        return;
    }
    btn.style.display = 'flex';
    if (cnt) {
        if (newMsgCount > 0) {
            cnt.style.display = 'inline';
            cnt.textContent = newMsgCount > 99 ? '99+' : String(newMsgCount);
        } else {
            cnt.style.display = 'none';
        }
    }
}

/* ---------- 断线横幅 ---------- */
function showOfflineBanner(show) {
    var el = document.getElementById('offline-banner');
    if (el) el.style.display = show ? 'flex' : 'none';
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
        if (getToken()) init.token = getToken();
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
                    showOfflineBanner(false);
                    showEmotion(data.emotion);
                    if (data.name) {
                        aiName = data.name;
                        updateAIName(aiName);
                    }
                    loadHistory();
                    loadStatus();
                    break;
                case 'segment': {
                    hideTyping();
                    // 只向"仍在流式中"（带 data-raw）的气泡追加；否则新开气泡
                    var streaming = document.querySelectorAll('.message.assistant .bubble[data-raw]');
                    var sb = streaming.length ? streaming[streaming.length - 1] : null;
                    if (!sb) {
                        var m = createMessage('assistant', '', false, Date.now());
                        sb = m ? m.querySelector('.bubble') : null;
                        if (sb) sb.setAttribute('data-raw', '');
                    }
                    if (sb) {
                        var raw = (sb.getAttribute('data-raw') || '') + data.content;
                        sb.setAttribute('data-raw', raw);
                        sb.classList.add('streaming');
                        renderMarkdownInto(sb, raw);
                    }
                    maybeScroll();
                    break;
                }
                case 'done': {
                    isProcessing = false;
                    updateSendButton();
                    setStatus('connected');
                    hideTyping();
                    var doneBubbles = document.querySelectorAll('.message.assistant .bubble[data-raw]');
                    var lastBubble = doneBubbles.length
                        ? doneBubbles[doneBubbles.length - 1]
                        : document.querySelector('.message.assistant:last-child .bubble');
                    if (lastBubble) {
                        var finalRaw = lastBubble.getAttribute('data-raw') || lastBubble.textContent;
                        renderMarkdownInto(lastBubble, finalRaw);
                        lastBubble.removeAttribute('data-raw');
                        lastBubble.classList.remove('streaming');
                    }
                    maybeScroll(false);
                    if (data.emotion) showEmotion(data.emotion);
                    loadStatus();
                    break;
                }
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
        showOfflineBanner(true);
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

/* ---------- 空态与历史骨架屏 ---------- */
function showEmptyState() {
    var container = document.getElementById('chat-messages');
    if (!container) return;
    hideEmptyState();
    var div = document.createElement('div');
    div.className = 'empty-state';
    div.id = 'empty-state';
    var av = document.createElement('div');
    av.className = 'avatar';
    av.textContent = roleName || aiName;
    var title = document.createElement('div');
    title.className = 'empty-title';
    title.textContent = '开始和 ' + (roleName || aiName) + ' 聊天吧';
    var hint = document.createElement('div');
    hint.className = 'empty-hint';
    hint.textContent = '在下方输入消息，按 Enter 发送，Shift + Enter 换行。';
    div.appendChild(av);
    div.appendChild(title);
    div.appendChild(hint);
    container.appendChild(div);
}

function hideEmptyState() {
    var el = document.getElementById('empty-state');
    if (el) el.remove();
}

function showSkeleton() {
    var container = document.getElementById('chat-messages');
    if (!container || container.children.length) return;
    var widths = [180, 240, 140, 200];
    for (var i = 0; i < widths.length; i++) {
        var msg = document.createElement('div');
        msg.className = 'skeleton-msg' + (i % 2 ? ' user' : '');
        msg.setAttribute('data-skeleton', '1');
        var bub = document.createElement('div');
        bub.className = 'skeleton-bubble';
        bub.style.width = widths[i] + 'px';
        bub.style.height = '38px';
        msg.appendChild(bub);
        container.appendChild(msg);
    }
}

function clearSkeleton() {
    document.querySelectorAll('[data-skeleton]').forEach(function(el) { el.remove(); });
}

function loadHistory() {
    var sid = getCookie('session_id');
    if (!sid) return;
    showSkeleton();
    var controller = new AbortController();
    setTimeout(function() { controller.abort(); }, 15000);
    authFetch('/api/chat/history?session_id=' + encodeURIComponent(sid), { signal: controller.signal })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var container = document.getElementById('chat-messages');
            if (!container) return;
            container.innerHTML = '';
            var turns = data.turns || [];
            if (!turns.length) {
                showEmptyState();
                return;
            }
            for (var i = 0; i < turns.length; i++) {
                var t = turns[i];
                // 历史消息无时间戳数据，不显示时间，仅提供复制操作
                createMessage(t.role === 'user' ? 'user' : 'assistant', t.content, false);
            }
            lastMessageTime = Date.now();
            stickToBottom = true;
            newMsgCount = 0;
            scrollToBottom();
        })
        .catch(function(e) {
            console.error('[history] load failed:', e);
            clearSkeleton();
        });
}

function loadStatus() {
    var sid = getCookie('session_id') || 'default';
    var controller = new AbortController();
    setTimeout(function() { controller.abort(); }, 15000);
    authFetch('/api/status?session_id=' + encodeURIComponent(sid), { signal: controller.signal })
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

    eventSource = new EventSource(withToken('/api/logs'));
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

function addSystemMessage(text) {
    var c = document.getElementById('chat-messages');
    if (!c) return;
    hideEmptyState();
    var d = document.createElement('div');
    d.className = 'system-message';
    d.textContent = text;
    c.appendChild(d);
    maybeScroll();
}

/* ---------- 消息操作条（时间戳 + 复制） ---------- */
function createMsgActions(bubble, ts) {
    var actions = document.createElement('div');
    actions.className = 'msg-actions';
    if (ts) {
        var time = document.createElement('span');
        time.className = 'msg-time';
        time.textContent = formatTime(ts);
        actions.appendChild(time);
    }
    var btn = document.createElement('button');
    btn.className = 'msg-action-btn';
    btn.type = 'button';
    btn.textContent = '复制';
    btn.addEventListener('click', function() { copyBubbleText(bubble, btn); });
    actions.appendChild(btn);
    return actions;
}

function copyBubbleText(bubble, btn) {
    var text = bubble.getAttribute('data-raw') || bubble.textContent;
    function done() {
        btn.classList.add('copied');
        btn.textContent = '已复制';
        setTimeout(function() {
            btn.classList.remove('copied');
            btn.textContent = '复制';
        }, 1200);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function() { fallbackCopy(text); done(); });
    } else {
        fallbackCopy(text);
        done();
    }
}

function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
}

function createMessage(role, content, autoScroll, ts) {
    autoScroll = autoScroll !== false;
    var container = document.getElementById('chat-messages');
    if (!container) return;
    hideEmptyState();
    maybeInsertTimeMarker();
    var div = document.createElement('div');
    div.className = 'message ' + role;
    var av = document.createElement('div');
    av.className = 'avatar';
    av.textContent = role === 'user' ? '我' : aiName;
    var col = document.createElement('div');
    col.className = 'bubble-col';
    var bb = document.createElement('div');
    bb.className = 'bubble';
    if (role === 'assistant' && content) {
        renderMarkdownInto(bb, content);
    } else {
        bb.textContent = content;
    }
    col.appendChild(bb);
    col.appendChild(createMsgActions(bb, ts));
    div.appendChild(av);
    div.appendChild(col);
    container.appendChild(div);
    if (autoScroll) maybeScroll();
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
    createMessage('user', text, true, Date.now());

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'message', content: text }));
    } else {
        var controller = new AbortController();
        setTimeout(function() { controller.abort(); }, 15000);
        authFetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: sessionId }),
            signal: controller.signal,
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            hideTyping();
            var resp = data.response || '';
            createMessage('assistant', resp, true, Date.now());
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

    authFetch('/api/roles')
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
    var themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
        themeBtn.addEventListener('click', toggleTheme);
    }

    var switchRoleBtn = document.getElementById('switch-role-btn');
    if (switchRoleBtn) {
        switchRoleBtn.addEventListener('click', function() {
            openRoleModal();
        });
    }

    var chatEl = document.getElementById('chat-messages');
    if (chatEl) {
        chatEl.addEventListener('scroll', function() {
            stickToBottom = isNearBottom();
            if (stickToBottom) newMsgCount = 0;
            updateScrollBottomBtn();
        });
    }

    var scrollBtn = document.getElementById('scroll-bottom-btn');
    if (scrollBtn) {
        scrollBtn.addEventListener('click', function() {
            scrollToBottom();
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
    initTheme();
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
