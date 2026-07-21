let autoRefresh = false;
let refreshTimer = null;
let currentData = [];

// A1: 可选 token 鉴权（web_access_token），与 app.js 同一约定
function getToken() { return localStorage.getItem('ai_friend_token') || ''; }
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

function makeCardKey(rec, index) {
  return `${rec.timestamp}|${rec.source || ''}|${rec.model}|${index}`;
}

function renderCard(rec, index) {
  const durCls = clsDuration(rec.duration_ms);
  const key = makeCardKey(rec, index);

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
    <div class="card" data-key="${esc(key)}">
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

function getOpenKeys() {
  const keys = new Set();
  document.querySelectorAll('.card-body.open').forEach(body => {
    const card = body.closest('.card');
    if (card) keys.add(card.dataset.key);
  });
  return keys;
}

function restoreOpenKeys(keys) {
  if (!keys || keys.size === 0) return;
  document.querySelectorAll('.card').forEach(card => {
    if (keys.has(card.dataset.key)) {
      const body = card.querySelector('.card-body');
      const arrow = card.querySelector('.arrow');
      if (body) body.classList.add('open');
      if (arrow) arrow.classList.add('open');
    }
  });
}

function fetchData() {
  document.getElementById('status').textContent = '加载中...';
  const openKeys = getOpenKeys();
  authFetch('/api/monitor?limit=0')
    .then(r => r.json())
    .then(data => {
      currentData = data || [];
      const list = document.getElementById('list');
      if (!data || data.length === 0) {
        list.innerHTML = '<div class="no-records">暂无记录</div>';
      } else {
        list.innerHTML = data.map(renderCard).join('');
        bindCardHeaders();
        restoreOpenKeys(openKeys);
      }
      document.getElementById('count').textContent = (data?.length || 0) + ' 条记录';
      document.getElementById('status').textContent = '就绪';
    })
    .catch(e => {
      currentData = [];
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
  authFetch('/api/monitor/clear').then(() => fetchData());
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

function downloadBlob(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function formatTimestamp() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function exportJson() {
  if (!currentData || currentData.length === 0) {
    alert('当前没有可导出的记录');
    return;
  }
  const payload = {
    exported_at: new Date().toISOString(),
    count: currentData.length,
    records: currentData,
  };
  downloadBlob(JSON.stringify(payload, null, 2), `llm_monitor_${formatTimestamp()}.json`, 'application/json');
  document.getElementById('status').textContent = 'JSON 导出完成';
}

function escapeMd(text) {
  if (text === null || text === undefined) return '';
  return String(text).replace(/([\\`*_{}[\]()#+\-.!|])/g, '\\$1');
}

function exportMarkdown() {
  if (!currentData || currentData.length === 0) {
    alert('当前没有可导出的记录');
    return;
  }
  const lines = [];
  lines.push('# LLM 调用监控导出');
  lines.push('');
  lines.push(`- 导出时间：${new Date().toLocaleString('zh-CN')}`);
  lines.push(`- 记录条数：${currentData.length}`);
  lines.push('');

  currentData.forEach((rec, idx) => {
    lines.push(`## 记录 ${idx + 1} / ${currentData.length}`);
    lines.push('');
    lines.push(`- **时间**：${rec.timestamp || '-'}`);
    lines.push(`- **来源**：${rec.source || '?'}`);
    lines.push(`- **模型**：${rec.model || '-'}`);
    lines.push(`- **耗时**：${fmtDuration(rec.duration_ms || 0)}`);
    lines.push(`- **温度**：${rec.temperature ?? '-'}`);
    lines.push(`- **max_tokens**：${rec.max_tokens ?? '-'}`);
    if (rec.response_format) {
      lines.push(`- **response_format**：\`\`\`json\n${escapeMd(JSON.stringify(rec.response_format, null, 2))}\n\`\`\``);
    }
    lines.push('');
    lines.push('### 请求消息');
    lines.push('');
    if (rec.messages && rec.messages.length > 0) {
      rec.messages.forEach(m => {
        lines.push(`**role**：${m.role || '?'}`);
        lines.push('');
        lines.push('```');
        lines.push(m.content || '(空)');
        lines.push('```');
        lines.push('');
      });
    } else {
      lines.push('（无消息记录）');
      lines.push('');
    }
    lines.push('### 响应');
    lines.push('');
    lines.push('```');
    lines.push(rec.response || '(空响应)');
    lines.push('```');
    lines.push('');
    lines.push('---');
    lines.push('');
  });

  downloadBlob(lines.join('\n'), `llm_monitor_${formatTimestamp()}.md`, 'text/markdown');
  document.getElementById('status').textContent = 'Markdown 导出完成';
}

function initMonitor() {
  document.getElementById('refresh-btn')?.addEventListener('click', fetchData);
  document.getElementById('auto-btn')?.addEventListener('click', toggleAuto);
  document.getElementById('clear-btn')?.addEventListener('click', clearData);
  document.getElementById('export-json-btn')?.addEventListener('click', exportJson);
  document.getElementById('export-md-btn')?.addEventListener('click', exportMarkdown);
  fetchData();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMonitor);
} else {
  initMonitor();
}
