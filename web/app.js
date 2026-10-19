const $ = (s) => document.querySelector(s);
const SAMPLE = `客户名称：东莞XX精密制造有限公司
产品名称：多片离合器钢片
产品尺寸：需兼容 Φ40 / Φ27mm 的产品
检测要求：
1. 检测表面划痕、凹坑、锈斑等缺陷
2. 自动判定 OK/NG 并输出剔除信号
3. 检测精度 0.05mm，速度 120 件/分钟
设备要求：光源、镜头、工业相机、控制器、工控机，PLC 输出剔除。

光路布局描述：
右上方竖直安装 CST 工业相机，配套镜头垂直向下，竖直虚线为成像光路，指向下方蓝色检测物；
相机镜头端面到下方蓝色检测物所在基准平面的垂直距离为 49mm。
画面中部：白色条形光源，呈正视图摆放，条形光源安装角度支持 15°~45° 可调；
条形光源底部距离底层基准平台高度为 20mm。`;

async function loadStats() {
  try {
    const r = await fetch('/kb/stats');
    const d = await r.json();
    const c = d.collections || {};
    $('#kb-status').textContent =
      `知识库：范文 ${c.proposals ?? 0} / 规范 ${c.legends ?? 0} / 参数 ${c.devices ?? 0} · 工位图 ${d.stations ?? 0}（${d.station_projects ?? 0} 项目） · Embedding ${d.embedding_provider} · LLM ${d.llm_provider}`;
    const lc = $('#lib-count');
    if (lc) lc.textContent = d.stations ?? 0;
  } catch (e) {
    $('#kb-status').textContent = '知识库状态加载失败';
  }
}

function setStatus(t) { $('#status').textContent = t; }

async function generate() {
  const text = $('#req').value.trim();
  if (!text) { alert('请先输入需求文本'); return; }
  const llm = $('#llm').value;
  const btn = $('#btn-generate');
  btn.disabled = true;
  btn.textContent = '生成中…';
  setStatus(llm === 'deepseek' ? '生成中…（DeepSeek 约 30~60 秒）' : '生成中…');
  $('#empty').classList.add('hidden');
  $('#result').classList.add('hidden');
  try {
    const r = await fetch('/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, llm }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status + '：' + (await r.text()).slice(0, 200));
    const d = await r.json();
    render(d);
    setStatus(d.verification_passed ? '✅ 校验通过' : '⚠️ 校验未通过');
  } catch (e) {
    setStatus('生成失败：' + (e.message || e));
  } finally {
    btn.disabled = false;
    btn.textContent = '生成 PPT 方案书';
  }
}

function stationImageUrl(sh) {
  if (!sh) return '';
  return sh.image_url || ('/station-lib/' + encodeURIComponent(sh.id) + '.png');
}

function render(d) {
  $('#result').classList.remove('hidden');
  const matched = d.matched_cases || [];
  const lr = d.layout_reasoning || {};
  const sh = lr.station_hit || null;

  // 参考来源：文本案例 + 历史工位图 + 布局方式
  const caseHtml = matched.length
    ? '<ul class="source-list">' + matched.map(m =>
        '<li><b>' + esc((m.source || '').replace(/^proposals\//, '').replace(/\.md$/, '')) +
        '</b> · 相似度 ' + m.score + '</li>').join('') + '</ul>'
    : '<div class="muted">未命中历史方案文本，按需求动态撰写</div>';

  const shUrl = stationImageUrl(sh);
  const stationHtml = sh
    ? '<a href="' + esc(shUrl) + '" target="_blank"><img class="source-thumb" src="' + esc(shUrl) +
      '" alt="历史工位图" loading="lazy"></a><div class="source-meta"><b>' +
      esc(sh.project || sh.id) + '</b><br>' + esc(sh.drawing_type || '历史工位图') +
      ' · 相似度 ' + sh.score + '</div>'
    : '<div class="muted">未命中历史工位图，本次由 LLM 自主推理布局</div>';

  let layoutText = '—';
  if (lr.status === 'success') {
    layoutText = sh ? '✅ 历史工位图参考 + LLM 细化' : '✅ LLM 自主推理（未命中历史工位图）';
  } else if (lr.status === 'mock') {
    layoutText = '⚠️ ' + esc(lr.reason || 'Mock 模式未调用布局推理');
  } else if (lr.status === 'failed') {
    layoutText = '❌ ' + esc(lr.reason || '布局推理失败');
  }

  $('#sources').innerHTML =
    '<div class="source-card"><div class="source-title">📄 历史方案文本（正文参考）</div>' + caseHtml + '</div>' +
    '<div class="source-card"><div class="source-title">📐 历史工位图（布局参考）</div>' + stationHtml + '</div>' +
    '<div class="source-card"><div class="source-title">🧠 布局生成方式</div><div class="source-meta">' + layoutText + '</div></div>';

  // 校验问题
  const issues = d.issues || [];
  const issuesHtml = issues.length
    ? issues.map(i => '<div class="issue ' + esc(i.severity) + '">[' + esc(i.severity) + '] ' +
        esc(i.code) + '：' + esc(i.message) + '</div>').join('')
    : '<div class="issue ok">无问题</div>';
  $('#issues').innerHTML = issuesHtml;
  const runId = d.run_id;

  // 全部自动生成图纸
  const diagrams = d.diagrams || [];
  $('#diagram').innerHTML = diagrams.map(dg => {
    const src = typeof dg === 'string' ? dg : dg.png;
    const title = typeof dg === 'object' ? dg.title : '';
    return `<figure class="fig"><img src="/output/${encodeURIComponent(runId)}/${esc(src)}" alt="${esc(title)}" loading="lazy"><figcaption>${esc(title)}</figcaption></figure>`;
  }).join('') || '（无图纸）';

  // PPT 下载（主按钮）
  $('#ppt-download').innerHTML = d.exports && d.exports.pptx
    ? `<a class="btn-ppt" href="/output/${runId}/${d.exports.pptx}" target="_blank">⬇ 下载 PPT 方案书</a>`
    : '<span class="muted">PPT 未生成</span>';

  // PPT 8 页大纲预览
  const slides = d.ppt_slides || [];
  $('#ppt-outline').innerHTML = slides.map(s => `
    <div class="slide-card ${s.has_image ? 'has-img' : ''}">
      <div class="slide-num">第 ${s.index} 页</div>
      <div class="slide-title">${esc(s.title)}</div>
      <div class="slide-text">${esc((s.text || '').slice(0, 80))}</div>
    </div>`).join('');

  // 其它格式
  const names = { docx: 'Word', pdf: 'PDF', html: '网页', markdown: 'Markdown' };
  $('#downloads').innerHTML = Object.entries(names).map(([k, label]) =>
    d.exports && d.exports[k] ? `<a href="/output/${runId}/${d.exports[k]}" target="_blank">${label}</a>` : ''
  ).join('');

  // 网页版正文（折叠区）
  $('#preview').src = `/output/${runId}/proposal.html`;
}

function libCard(it) {
  const url = it.image_url || ('/station-lib/' + encodeURIComponent(it.id) + '.png');
  const score = it.score != null ? '<br>相似度 ' + it.score : '';
  return '<figure class="lib-card"><a href="' + esc(url) + '" target="_blank">' +
    '<img src="' + esc(url) + '" loading="lazy" alt="' + esc(it.project || it.id) + '"></a>' +
    '<figcaption><b>' + esc(it.project || it.id) + '</b><br>' +
    esc(it.drawing_type || '') + score + '</figcaption></figure>';
}

async function loadLibrary() {
  const grid = $('#lib-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="lib-empty">加载中…</div>';
  try {
    const r = await fetch('/station-library/list?limit=200');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const items = d.items || [];
    if ($('#lib-count')) $('#lib-count').textContent = d.total ?? items.length;
    grid.innerHTML = items.length ? items.map(libCard).join('') : '<div class="lib-empty">图库为空</div>';
  } catch (e) {
    grid.innerHTML = '<div class="lib-empty">工位图库加载失败：' + esc(e.message || e) + '</div>';
  }
}

async function searchLibrary() {
  const q = $('#lib-query').value.trim();
  if (!q) { loadLibrary(); return; }
  const grid = $('#lib-grid');
  grid.innerHTML = '<div class="lib-empty">检索中…</div>';
  try {
    const r = await fetch('/station-library/search', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q, top_k: 24 }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const items = (d.items || []).filter(it => it.score == null || it.score >= 0.35);
    grid.innerHTML = items.length ? items.map(libCard).join('') : '<div class="lib-empty">未找到匹配的工位图（相似度 ≥ 0.35）</div>';
  } catch (e) {
    grid.innerHTML = '<div class="lib-empty">检索失败：' + esc(e.message || e) + '</div>';
  }
}

async function opticOnly() {
  const text = $('#req').value.trim();
  if (!text) { alert('请先输入需求文本'); return; }
  setStatus('生成工位架构图（大模型推理布局）…');
  try {
    const r = await fetch('/optic', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    $('#result').classList.remove('hidden');
    // 能力自检
    const lr = d.layout_reasoning || {};
    let lrHtml = '';
    if (lr.status === 'retrieved') {
      lrHtml = `<div class="issue ok">✅ 命中历史工位图：${d.matched || ''}（相似度 ${d.score ?? ''}），已重画</div>`;
    } else if (lr.status === 'success') {
      lrHtml = `<div class="issue ok">✅ 大模型推理布局成功：相机 ${d.camera_count} 台，光源 ${(d.lights || []).length} 个</div>`;
    } else if (lr.status === 'mock') {
      lrHtml = `<div class="issue">⚠️ ${lr.reason || '未调用大模型'}（显示旧光路图兜底）</div>`;
    } else {
      lrHtml = `<div class="issue error">❌ 布局推理失败：${lr.reason || ''}</div>`;
    }
    $('#sources').innerHTML = '<div class="source-card"><div class="source-title">📐 工位图生成</div>' +
      (lrHtml || '<div class="issue ok">已生成</div>') + '</div>';
    $('#issues').innerHTML = '';
    // 用返回的图片路径
    const src = d.png ? d.png.replace(/\\/g, '/').replace(/^.*\/output\//, '/output/') : '/output/optic/station.png';
    $('#diagram').innerHTML = `<img src="${src}?t=${Date.now()}" alt="工位架构图">`;
    $('#ppt-download').innerHTML = '';
    $('#ppt-outline').innerHTML = '';
    $('#downloads').innerHTML = '';
    $('#preview').src = 'about:blank';
    setStatus('工位架构图已生成');
  } catch (e) {
    setStatus('失败：' + e);
  }
}

$('#btn-generate').addEventListener('click', generate);
$('#btn-optic').addEventListener('click', opticOnly);
$('#btn-sample').addEventListener('click', () => { $('#req').value = SAMPLE; });
$('#btn-lib-search').addEventListener('click', searchLibrary);
$('#lib-query').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchLibrary(); });
$('#btn-lib-all').addEventListener('click', () => { $('#lib-query').value = ''; loadLibrary(); });
loadStats();
loadLibrary();

// ===== 售前选型顾问对话 =====
const chatHistory = [];   // {role, content}

function esc(t) {
  return String(t == null ? '' : t)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function appendBubble(role, text) {
  const log = $('#chat-log');
  const hint = log.querySelector('.chat-hint');
  if (hint) hint.remove();
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.innerHTML = '<pre class="msg-text">' + esc(text) + '</pre>';
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function appendDebug(d) {
  if (!d) return;
  const panel = $('#debug-log');
  if (panel.textContent === '暂无记录') panel.textContent = '';
  const el = document.createElement('div');
  el.className = 'debug-entry';
  let html = '<div class="debug-title"><b>' + esc(d.selected_source) + '</b> · 已提供：' +
    esc((d.provided_fields || []).join('、') || '—') + '<br>缺失：' + esc((d.missing_fields || []).join('、') || '无') + '</div>';
  if (d.matched && d.matched.length) {
    html += '<ul class="debug-list">' + d.matched.map(m =>
      '<li>' + esc(m.source) + ' · 相似度 ' + m.score + '</li>').join('') + '</ul>';
  }
  if (d.compat && d.compat.length) {
    html += '<div class="debug-compat">' + d.compat.map(esc).join('<br>') + '</div>';
  }
  el.innerHTML = html;
  panel.prepend(el);
}

async function sendChat() {
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text) return;
  appendBubble('user', text);
  input.value = '';
  const loading = appendBubble('assistant', '正在分析…');
  try {
    const r = await fetch('/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ history: chatHistory, text, llm: $('#chat-llm').value }),
    });
    const d = await r.json();
    loading.remove();
    const reply = d.reply || '（无返回）';
    appendBubble('assistant', reply);
    if (d.sufficient && d.requirement) {
      $('#req').value = d.requirement;
      setStatus('✅ 顾问已给出需求结论，已填入「输入项目需求」，可点击「生成 PPT 方案书」');
    }
    chatHistory.push({ role: 'user', content: text });
    chatHistory.push({ role: 'assistant', content: reply });
    appendDebug(d.debug);
  } catch (e) {
    loading.remove();
    appendBubble('assistant', '请求失败：' + e);
  }
}

$('#btn-chat').addEventListener('click', sendChat);
$('#chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });
