let autoRefresh = false;
let refreshTimer = null;

function fmtDuration(ms) {
  if (ms < 1000) return ms + 'ms';
  return (ms / 1000).toFixed(1) + 's';
}

function clsDuration(ms) {
  if (ms < 2000) return 'fast';
  if (ms < 6000) return 'medium';
  return 'slow';
}

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function roleIcon(role) {
  if (role === 'system') return '⚙️';
  if (role === 'user') return '👤';
  if (role === 'assistant') return '🤖';
  return '❓';
}

function formatContent(content) {
  if (!content) return '<span class="placeholder">(空)</span>';
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content);
      return esc(JSON.stringify(parsed, null, 2));
    } catch(e) {
      return esc(content);
    }
  }
  return esc(JSON.stringify(content, null, 2));
}

function renderCard(rec) {
  const durCls = clsDuration(rec.duration_ms);

  let msgsHtml = '';
  if (rec.messages && rec.messages.length > 0) {
    rec.messages.forEach(m => {
      const role = m.role || '?';
      const content = m.content || '';
      msgsHtml += `
        <div class="msg">
          <div class="msg-header ${esc(role)}">${roleIcon(role)} ${esc(role)}</div>
          <div class="msg-content">${formatContent(content)}</div>
        </div>
      `;
    });
  } else {
    msgsHtml = '<div class="placeholder">(无消息记录)</div>';
  }

  let respHtml = '';
  if (rec.response) {
    respHtml = formatContent(rec.response);
  } else {
    respHtml = '<span class="placeholder">(空响应)</span>';
  }

  return `
    <div class="card">
      <div class="card-header">
        <span class="arrow">▶</span>
        <span class="time">${esc(rec.timestamp)}</span>
        <span class="source">${esc(rec.source || '?')}</span>
        <span class="model">${esc(rec.model)}</span>
        <span class="duration ${durCls}">${fmtDuration(rec.duration_ms)}</span>
        <span class="meta-info">${rec.messages?.length || 0} 条消息</span>
      </div>
      <div class="card-body">
        <div class="meta">
          <dt>温度</dt><dd>${rec.temperature}</dd>
          <dt>max_tokens</dt><dd>${rec.max_tokens}</dd>
          <dt>response_format</dt><dd>${rec.response_format ? esc(JSON.stringify(rec.response_format)) : '(无)'}</dd>
        </div>
        <h3 style="font-size:12px;color:#8b949e;margin:6px 0 4px;">📥 请求消息 (${rec.messages?.length || 0} 条)</h3>
        ${msgsHtml}
        <h3 style="font-size:12px;color:#8b949e;margin:8px 0 4px;">📤 响应 (${rec.response?.length || 0} 字符)</h3>
        <div class="resp">${respHtml}</div>
      </div>
    </div>
  `;
}

function fetchData() {
  document.getElementById('status').textContent = '加载中...';
  fetch('/api/monitor?limit=0')
    .then(r => r.json())
    .then(data => {
      const list = document.getElementById('list');
      if (!data || data.length === 0) {
        list.innerHTML = '<div class="no-records">暂无记录</div>';
      } else {
        list.innerHTML = data.map(renderCard).join('');
        bindCardHeaders();
      }
      document.getElementById('count').textContent = (data?.length || 0) + ' 条记录';
      document.getElementById('status').textContent = '就绪';
    })
    .catch(e => {
      document.getElementById('list').innerHTML = '<div class="no-records">加载失败: ' + esc(e.message) + '</div>';
      document.getElementById('status').textContent = '错误: ' + e.message;
    });
}

function bindCardHeaders() {
  document.querySelectorAll('.card-header').forEach(header => {
    header.addEventListener('click', () => {
      header.nextElementSibling.classList.toggle('open');
      header.querySelector('.arrow').classList.toggle('open');
    });
  });
}

function clearData() {
  fetch('/api/monitor/clear').then(() => fetchData());
  document.getElementById('status').textContent = '已清空';
}

function toggleAuto() {
  autoRefresh = !autoRefresh;
  const btn = document.getElementById('auto-btn');
  if (autoRefresh) {
    refreshTimer = setInterval(fetchData, 3000);
    document.getElementById('auto-status').textContent = '自动刷新：每 3s';
    if (btn) btn.textContent = '⏹ 停止自动';
  } else {
    clearInterval(refreshTimer);
    refreshTimer = null;
    document.getElementById('auto-status').textContent = '';
    if (btn) btn.textContent = '▶ 自动刷新';
  }
}

function initMonitor() {
  document.getElementById('refresh-btn')?.addEventListener('click', fetchData);
  document.getElementById('auto-btn')?.addEventListener('click', toggleAuto);
  document.getElementById('clear-btn')?.addEventListener('click', clearData);
  fetchData();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMonitor);
} else {
  initMonitor();
}
