/* WorkBuddy 技能管家 · 前端逻辑 */
'use strict';

const state = {
  data: null,
  scenes: [],        // 场景列表
  cat: 'all',        // 'all' | 分类 id | 'on' | 'off'
  query: '',
  hideOff: false,
  expanded: false,
  current: null,     // 当前详情技能
};

const $ = id => document.getElementById(id);
const grid = $('grid');

function api(path, opts) {
  return fetch(path, opts).then(r => r.json());
}
function post(path, body) {
  return api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
}

function toast(msg, type) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast' + (type ? ' ' + type : '');
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 2400);
}

function setSync(status, text) {
  const b = $('syncBadge');
  b.className = 'sync-badge' + (status ? ' ' + status : '');
  $('syncText').textContent = text;
}

function catColor(id) {
  const c = (state.data.categories || []).find(x => x.id === id);
  return c ? c.color : '#888';
}
function catName(id) {
  const c = (state.data.categories || []).find(x => x.id === id);
  return c ? c.name : '其他';
}
function catIcon(id) {
  // 分类完全由使用者自己的 AI 定义，图标从 meta 的 icon 字段读取
  const c = (state.data && state.data.categories || []).find(x => x.id === id);
  return (c && c.icon) || '□';
}

/* 渲染场景模式 */
function renderScenes() {
  const nav = $('sceneNav');
  if (!nav) return;
  nav.innerHTML = '';
  const active = state.data && state.data.activeScene;
  state.scenes.forEach(sc => {
    const b = document.createElement('button');
    b.className = 'scene-item' + (active === sc.id ? ' active' : '');
    b.title = sc.desc || '';
    b.innerHTML = `<span class="scene-ico">${esc(sc.icon || '◆')}</span>` +
                  `<span class="scene-name">${esc(sc.name)}</span>`;
    b.onclick = () => applyScene(sc);
    nav.appendChild(b);
  });
}

async function applyScene(sc) {
  const keepNames = (sc.keep || []).map(id => catName(id)).join('、');
  if (!confirm(`切换到「${sc.name}」模式？\n\n保留：${keepNames}\n其余分类的技能会全部关闭。\n随时可以点「全部启用」或「恢复原状」还原。\n\n${sc.desc || ''}`)) return;
  setSync('busy', '切换场景中…');
  try {
    const r = await post('/api/scene-apply', {scene: sc.id});
    if (!r.ok) throw new Error(r.error || '切换失败');
    toast(`已切换「${r.name}」：保留 ${r.kept} 个，关闭 ${r.closed} 个`, 'ok');
    await load();
  } catch (e) { setSync('err', '切换失败'); toast('切换失败：' + e.message, 'err'); }
}

/* 渲染左侧分类 */
function renderNav() {
  const d = state.data;
  const counts = {};
  d.skills.forEach(s => { counts[s.category] = (counts[s.category] || 0) + 1; });
  const on = d.skills.filter(s => !s.disabled).length;
  $('cntOn').textContent = on;
  $('cntOff').textContent = d.skills.length - on;

  const nav = $('catNav');
  nav.innerHTML = '';
  const mk = (id, name, count, color) => {
    // 用 div 而非 button：分类项内要嵌两个一键小按钮，button 套 button 会被浏览器拆散 DOM
    const b = document.createElement('div');
    b.className = 'cat-item' + (state.cat === id ? ' active' : '');
    b.dataset.cat = id;
    b.setAttribute('role', 'button');
    b.tabIndex = 0;
    b.innerHTML = `<span class="cat-ico" style="--c:${color}">${catIcon(id)}</span>` +
                  `<span class="cat-name" title="${esc(name)}">${esc(name)}</span>` +
                  `<span class="cat-actions">` +
                    `<button class="cat-mini m-on" data-cat-id="${escAttr(id)}" data-cat-bulk="1" title="一键启用「${escAttr(name)}」下全部技能">✓</button>` +
                    `<button class="cat-mini m-off" data-cat-id="${escAttr(id)}" data-cat-bulk="0" title="一键关闭「${escAttr(name)}」下全部技能">⊘</button>` +
                  `</span>` +
                  `<span class="cat-count">${count}</span>`;
    b.onclick = () => selectCat(id);
    b.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectCat(id); } };
    b.querySelectorAll('[data-cat-bulk]').forEach(m => {
      m.onclick = ev => {
        ev.stopPropagation();
        bulkScope('category', +m.dataset.catBulk === 1, {category: m.dataset.catId});
      };
    });
    nav.appendChild(b);
  };
  mk('all', '全部技能', d.skills.length, '#3b5bdb');
  d.categories.forEach(c => mk(c.id, c.name, counts[c.id] || 0, c.color));

  document.querySelectorAll('[data-quick]').forEach(b => {
    b.classList.toggle('active', state.cat === b.dataset.quick);
    b.onclick = () => selectCat(b.dataset.quick);
  });
}

function selectCat(id) {
  state.cat = id;
  renderNav();
  renderHead();
  renderGrid();
}

function renderHead() {
  const d = state.data;
  let title = '全部技能', desc = `共 ${d.skills.length} 个技能，按用途分类整理`, showBulk = true;
  if (state.cat === 'on') {
    title = '已启用技能'; desc = '这些技能当前对 WorkBuddy 可见并可用'; showBulk = false;
  } else if (state.cat === 'off') {
    title = '已关闭技能'; desc = '这些技能已被关闭，WorkBuddy 不会加载'; showBulk = false;
  } else if (state.cat !== 'all') {
    const c = d.categories.find(x => x.id === state.cat);
    title = c ? c.name : state.cat;
    desc = c ? c.desc : '';
  }
  $('catTitle').textContent = title;
  $('catDesc').textContent = desc;
  $('bulkBar').hidden = !showBulk || state.cat === 'all';
}

function filtered() {
  let list = state.data.skills.slice();
  if (state.cat === 'on') list = list.filter(s => !s.disabled);
  else if (state.cat === 'off') list = list.filter(s => !!s.disabled);
  else if (state.cat !== 'all') list = list.filter(s => s.category === state.cat);

  if (state.hideOff) list = list.filter(s => !s.disabled);

  const q = state.query.trim().toLowerCase();
  if (q) {
    list = list.filter(s =>
      (s.name || '').toLowerCase().includes(q) ||
      (s.summary || '').toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q) ||
      (s.path || '').toLowerCase().includes(q));
  }
  return list;
}

function renderGrid() {
  const list = filtered();
  grid.innerHTML = '';
  $('empty').hidden = list.length > 0;
  const frag = document.createDocumentFragment();
  list.forEach(s => frag.appendChild(makeCard(s)));
  grid.appendChild(frag);
  if (state.expanded) grid.querySelectorAll('.card-summary').forEach(e => {
    e.style.webkitLineClamp = 'unset';
  });
}

function makeCard(s) {
  const card = document.createElement('div');
  card.className = 'card' + (s.disabled ? ' off' : '');
  card.style.setProperty('--c', catColor(s.category));
  const src = (s.path || '').split('\\').slice(-2, -1)[0] || '';
  card.innerHTML = `
    <div class="card-top">
      <div class="card-mark"></div>
      <div class="card-title-wrap">
        <div class="card-name" title="${esc(s.name)}">${esc(s.name)}</div>
        <div class="card-cat">${esc(catName(s.category))}${s.user_invocable === 0 ? ' · 仅AI调用' : ''}</div>
      </div>
    </div>
    <div class="card-summary">${esc(s.summary || s.description || '暂无说明')}</div>
    <div class="card-bottom">
      <span class="card-tag src" title="${esc(s.path)}">${esc(src)}${s.body ? '' : ' · 无正文'}</span>
      <div class="card-toggle" onclick="event.stopPropagation()">
        <span>${s.disabled ? '已关闭' : '已启用'}</span>
        <label class="switch"><input type="checkbox" ${s.disabled ? '' : 'checked'} data-path="${escAttr(s.path)}"><span class="slider"></span></label>
      </div>
    </div>`;
  card.onclick = () => openDetail(s.path);
  const cb = card.querySelector('input[type=checkbox]');
  cb.onchange = async () => {
    await doToggle(s.path, 'disabled', cb.checked ? 0 : 1, cb);
    const lab = cb.parentElement.parentElement.querySelector('span');
    lab.textContent = cb.checked ? '已启用' : '已关闭';
    card.classList.toggle('off', !cb.checked);
  };
  return card;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function escAttr(s) { return esc(s); }

async function doToggle(path, field, value, inputEl) {
  setSync('busy', '同步中…');
  try {
    const r = await post('/api/toggle', {path, field, value});
    if (!r.ok) throw new Error(r.error || '切换失败');
    const s = state.data.skills.find(x => x.path === path);
    if (s) {
      if (field === 'disabled') s.disabled = value;
      if (field === 'disable_model_invocation') s.disable_model_invocation = value;
      if (field === 'user_invocable') s.user_invocable = value;
    }
    setSync('', '已同步');
    toast('已写入 WorkBuddy，开关状态已同步', 'ok');
    renderNav();
    // “已启用/已关闭”视图下单条切换会让卡片不符合当前筛选，需要重绘
    if (state.cat === 'on' || state.cat === 'off') renderGrid();
  } catch (e) {
    setSync('err', '同步失败');
    toast('同步失败：' + e.message, 'err');
    if (inputEl) inputEl.checked = !inputEl.checked;
  }
}

/* 一键批量：all 全库 / category 单分类 / paths 指定列表
   enable 为“启用/关闭”语义，写入时转成 disabled 字段值（0=启用，1=关闭） */
async function bulkScope(scope, enable, opts) {
  opts = opts || {};
  const label = enable ? '启用' : '关闭';
  const value = enable ? 0 : 1;
  let noun, count;
  if (scope === 'all') {
    noun = '全部技能';
    count = state.data.skills.length;
  } else if (scope === 'category') {
    noun = `「${catName(opts.category)}」分类`;
    count = state.data.skills.filter(s => s.category === opts.category).length;
  } else {
    noun = '当前筛选结果';
    count = (opts.paths || []).length;
  }
  if (!count) { toast('没有可操作的技能', 'err'); return; }
  const extra = scope === 'all' && !enable ? '\n\n关闭后 WorkBuddy 将不加载任何技能；随时点「一键全开」即可恢复。' : '';
  if (!confirm(`一键${label}${noun}（${count} 个）？${extra}`)) return;

  // 关闭时让用户选择关闭强度：匹配 WorkBuddy 界面的「关闭」与「彻底禁用」
  let mode = 'normal';
  if (!enable) {
    mode = confirm('关闭方式：\n\n【确定】= 彻底禁用（AI 和手动都不能调用）\n【取消】= 普通关闭（保留手动调用，AI 不能自动用）') ? 'full' : 'normal';
  }

  setSync('busy', '批量同步中…');
  try {
    const r = await post('/api/toggle-batch', {
      scope, field: 'disabled', value, mode,
      category: opts.category || null,
      paths: opts.paths || [],
    });
    if (!r.ok) throw new Error(r.error || '批量同步失败');
    toast(`已${label} ${r.count} 个技能，WorkBuddy 状态已同步`, 'ok');
    await load();
  } catch (e) {
    setSync('err', '同步失败');
    toast('批量同步失败：' + e.message, 'err');
  }
}

/* 详情抽屉 */
async function openDetail(path) {
  const s = state.data.skills.find(x => x.path === path);
  if (!s) return;
  state.current = s;
  const color = catColor(s.category);
  $('dCat').textContent = catName(s.category);
  $('dCat').style.setProperty('--c', color);
  $('dName').textContent = s.name;
  $('dSummary').textContent = s.summary || s.description || '暂无中文说明';
  $('dWhen').textContent = s.when_to_use || '未提供“使用时机”字段，可参考下方原始描述与技能正文。';
  $('dDesc').textContent = s.description || '—';
  $('dBody').textContent = '加载中…';
  // 正文按需加载，避免列表接口传输 2MB+ 数据拖慢首屏
  api('/api/skill?path=' + encodeURIComponent(path)).then(full => {
    if (state.current && state.current.path === path) {
      $('dBody').textContent = full.body || '（该技能没有 SKILL.md 正文）';
    }
  }).catch(() => {
    if (state.current && state.current.path === path) $('dBody').textContent = '正文加载失败';
  });
  $('dMeta').innerHTML =
    `源文件：<code>${esc(s.path)}</code><br>` +
    `来源：<code>${esc(s.source || 'userSettings')}</code>　` +
    `许可：<code>${esc(s.license || '未标注')}</code><br>` +
    `总开关状态：<code>${s.switch_state === 2 ? '彻底禁用' : (s.disabled ? '关闭（仅手动）' : '启用')}</code>　` +
    `AI 自动调用：<code>${s.disable_model_invocation ? '禁止' : '允许'}</code>　` +
    `用户手动调用：<code>${s.user_invocable ? '允许' : '禁止'}</code><br>` +
    `覆盖键(override_key)：<code>${esc(s.override_key || '—')}</code>`;

  const d1 = $('dDisabled'), d2 = $('dModelInvoke'), d3 = $('dUserInvoke');
  d1.checked = !s.disabled;
  d2.checked = !s.disable_model_invocation;
  d3.checked = !!s.user_invocable;
  $('overlay').hidden = false;
  $('drawer').hidden = false;
}
function closeDetail() {
  $('overlay').hidden = true;
  $('drawer').hidden = true;
  state.current = null;
}

/* 事件绑定 */
function bind() {
  $('search').oninput = e => { state.query = e.target.value; $('clearSearch').hidden = !state.query; renderGrid(); };
  $('clearSearch').onclick = () => { $('search').value = ''; state.query = ''; $('clearSearch').hidden = true; renderGrid(); };
  $('hideOff').onchange = e => { state.hideOff = e.target.checked; renderGrid(); };
  $('expandAll').onclick = () => {
    state.expanded = !state.expanded;
    $('expandAll').textContent = state.expanded ? '收起说明' : '展开全部说明';
    renderGrid();
  };
  $('closeDrawer').onclick = closeDetail;
  $('overlay').onclick = closeDetail;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

  ['dDisabled','dModelInvoke','dUserInvoke'].forEach(id => {
    const map = {dDisabled:'disabled', dModelInvoke:'disable_model_invocation', dUserInvoke:'user_invocable'};
    $(id).onchange = async e => {
      const field = map[id];
      let value;
      if (field === 'disabled') value = e.target.checked ? 0 : 1;
      else if (field === 'disable_model_invocation') value = e.target.checked ? 0 : 1;
      else value = e.target.checked ? 1 : 0;
      await doToggle(state.current.path, field, value, e.target);
      // 同步 Detail 里的技术信息文字
      openDetail(state.current.path);
    };
  });

  $('btnReload').onclick = load;
  $('btnAllScenes').onclick = async () => {
    if (!confirm('全部启用？将清空所有开关覆盖，AI 可以使用全部技能（技能越多越费 token）。')) return;
    setSync('busy', '切换中…');
    try {
      const r = await post('/api/scene-apply', {scene: 'all'});
      if (!r.ok) throw new Error(r.error || '失败');
      toast('已全部启用', 'ok');
      await load();
    } catch (e) { toast(e.message, 'err'); }
  };
  $('btnBaseline').onclick = async () => {
    if (!confirm('恢复原状？回到你原来手动设置的开关状态（含原本关闭的那些技能）。')) return;
    setSync('busy', '恢复中…');
    try {
      const r = await post('/api/scene-baseline', {});
      if (!r.ok) throw new Error(r.error || '失败');
      toast(`已恢复原有 ${r.count} 条开关设置`, 'ok');
      await load();
    } catch (e) { toast(e.message, 'err'); }
  };
  $('btnBackup').onclick = async () => {
    setSync('busy', '备份中…');
    try {
      const r = await api('/api/backup');
      if (!r.ok) throw new Error(r.error || '备份失败');
      toast('已备份：' + (r.file || 'workbuddy.db'), 'ok');
      setSync('', '已同步');
    } catch (e) { setSync('err', '备份失败'); toast(e.message, 'err'); }
  };
  $('btnRefreshMeta').onclick = async () => {
    if (!confirm('重新扫描所有 SKILL.md 并重建分类？\n\n注意：你手工修改过的分类/中文说明会被覆盖。\n开关状态不受影响。')) return;
    setSync('busy', '扫描中…');
    try {
      const r = await post('/api/refresh-meta', {});
      if (!r.ok) throw new Error(r.error || '扫描失败');
      toast('扫描完成，正在重载', 'ok');
      await load();
    } catch (e) { setSync('err', '扫描失败'); toast(e.message, 'err'); }
  };

  $('btnAllOn').onclick = () => bulkScope('all', true);
  $('btnAllOff').onclick = () => bulkScope('all', false);

  // 分类标题右侧的批量按钮（当前分类或当前筛选结果）
  document.querySelectorAll('[data-bulk]').forEach(b => {
    b.onclick = () => {
      const enable = +b.dataset.bulk === 1;
      const list = filtered().filter(s => s.category === state.cat);
      bulkScope('paths', enable, {paths: list.map(s => s.path)});
    };
  });
}

async function load() {
  setSync('busy', '读取中…');
  try {
    state.data = await api('/api/skills');
    if (!state.scenes.length) {
      try { state.scenes = (await api('/api/scenes')).scenes || []; }
      catch (e) { state.scenes = []; }
    }
    $('dbPath').textContent = state.data.settingsPath || state.data.dbPath;
    renderScenes(); renderNav(); renderHead(); renderGrid();
    setSync('', '已同步');
  } catch (e) {
    setSync('err', '连接失败');
    grid.innerHTML = `<div class="empty">无法读取数据：${esc(e.message)}<br>请确认后端服务正在运行</div>`;
  }
}

bind();
load();
