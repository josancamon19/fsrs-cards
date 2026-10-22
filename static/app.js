'use strict';
/* FSRS Cards — single-file SPA. No framework: hash router + string templates. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = $('#view');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const RATINGS = [
  { n: 1, key: 'again', label: 'Again', cls: 'r-again' },
  { n: 2, key: 'hard', label: 'Hard', cls: 'r-hard' },
  { n: 3, key: 'good', label: 'Good', cls: 'r-good' },
  { n: 4, key: 'easy', label: 'Easy', cls: 'r-easy' },
];
const STATES = ['new', 'learning', 'review', 'relearning'];
const STATE_LABEL = { new: 'New', learning: 'Learning', review: 'Review', relearning: 'Relearning' };
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) { o.method = o.method || 'POST'; o.headers = { 'Content-Type': 'application/json' }; o.body = JSON.stringify(o.json); delete o.json; }
  const r = await fetch(path, o);
  if (r.status === 401 && path !== '/api/login') { loginView(); throw new Error('Login required'); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(m); }
  return r.json();
}

/* ---------------------------------------------------------------- formatting */
function fmtIvl(secs) {
  if (secs == null) return '—';
  const s = Math.max(0, secs);
  if (s < 60) return '<1m';
  if (s < 3600) return Math.round(s / 60) + 'm';
  if (s < 86400) return Math.round(s / 3600) + 'h';
  const d = s / 86400;
  if (d < 30) return Math.round(d) + 'd';
  if (d < 365) return (d / 30.4).toFixed(d < 304 ? 1 : 0).replace(/\.0$/, '') + 'mo';
  return (d / 365).toFixed(1).replace(/\.0$/, '') + 'y';
}
const fmtDays = d => d == null ? '—' : d < 1 ? (d * 24).toFixed(1) + 'h' : d < 100 ? d.toFixed(1) + 'd' : fmtIvl(d * 86400);
const pct = (x, digits = 0) => x == null ? '—' : (x * 100).toFixed(digits) + '%';
const fmtDur = ms => { const m = Math.round(ms / 60000); return m < 60 ? m + 'm' : Math.floor(m / 60) + 'h ' + (m % 60) + 'm'; };
const fmtDate = ts => new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const fmtDateTime = ms => new Date(ms).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const rel = ts => { const d = ts - Date.now() / 1000; return d <= 0 ? 'now' : 'in ' + fmtIvl(d); };
const stateChip = st => `<span class="chip" style="--c:var(--st-${st})">${STATE_LABEL[st]}</span>`;
const ratingChip = n => { const r = RATINGS[n - 1]; return `<span class="chip" style="--c:var(--${r.key})">${r.label}</span>`; };

/* ---------------------------------------------------------------- toast & tooltip */
const toastEl = $('#toast'); let toastT;
function toast(html, ms = 2200) { toastEl.innerHTML = html; toastEl.classList.add('show'); clearTimeout(toastT); toastT = setTimeout(() => toastEl.classList.remove('show'), ms); }
const tipEl = $('#tip');
function showTip(html, x, y) {
  tipEl.innerHTML = html; tipEl.classList.add('show');
  const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  let left = x + 14, top = y - h - 10;
  if (left + w > innerWidth - 8) left = x - w - 14;
  if (top < 8) top = y + 16;
  tipEl.style.left = left + 'px'; tipEl.style.top = top + 'px';
}
const hideTip = () => tipEl.classList.remove('show');
addEventListener('pointerdown', e => { if (!e.target.closest('.chart')) hideTip(); }, { passive: true });
addEventListener('scroll', hideTip, { passive: true });
const tipRow = (label, val, color) => `<div class="r"><span>${color ? `<i style="background:${color}"></i>` : ''}${label}</span><b>${val}</b></div>`;

/* ---------------------------------------------------------------- theme */
$('#theme-btn').onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('theme', root.dataset.theme); } catch (e) {}
  rerender();
};
const isDark = () => { const t = document.documentElement.dataset.theme; return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; };

/* ---------------------------------------------------------------- charts (hand-rolled SVG) */
function niceStep(max, ticks = 4) {
  const raw = max / ticks, mag = 10 ** Math.floor(Math.log10(raw || 1)), n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
}
function attachTips(el, fn) {
  const show = e => { const t = e.target.closest('[data-i]'); if (!t) return hideTip(); showTip(fn(+t.dataset.i), e.clientX, e.clientY); };
  el.onpointermove = show; el.onpointerdown = show;
  el.onpointerleave = e => { if (e.pointerType === 'mouse') hideTip(); };
}
function roundTopRect(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  if (h <= 0) return '';
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
/* stacked/simple bar chart */
function barChart(el, { data, keys, colors, xLabel, tip, height = 190, yFmt = v => v, labelEvery }) {
  const W = Math.max(280, el.clientWidth), H = height, m = { t: 10, r: 6, b: 22, l: 36 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const totals = data.map(d => keys.reduce((s, k) => s + (d[k] || 0), 0));
  const step = niceStep(Math.max(1, ...totals)), max = Math.max(step, Math.ceil(Math.max(1, ...totals) / step) * step);
  const y = v => m.t + ih - (v / max) * ih;
  const bw = iw / data.length, barW = Math.max(1, Math.min(28, bw - Math.max(1, bw * .22)));
  let s = `<svg width="${W}" height="${H}">`;
  for (let v = 0; v <= max + 1e-9; v += step) s += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${yFmt(v)}</text>`;
  const every = labelEvery || Math.ceil(data.length / Math.max(1, Math.floor(iw / 46)));
  data.forEach((d, i) => {
    const cx = m.l + bw * i + bw / 2, x0 = cx - barW / 2;
    let acc = 0;
    const segs = keys.map((k, j) => ({ k, v: d[k] || 0, c: colors[j] })).filter(q => q.v > 0);
    segs.forEach((q, j) => {
      const yTop = y(acc + q.v), yBot = y(acc); acc += q.v;
      const h = Math.max(0, yBot - yTop - (j > 0 ? 2 : 0)); // 2px surface gap between stacked segments
      if (j === segs.length - 1) s += `<path d="${roundTopRect(x0, yTop, barW, h, 3)}" fill="${q.c}"/>`;
      else s += `<rect x="${x0}" y="${yTop}" width="${barW}" height="${h}" fill="${q.c}"/>`;
    });
    if (i % every === 0) s += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${xLabel(d, i)}</text>`;
    s += `<rect class="hit" data-i="${i}" x="${m.l + bw * i}" y="${m.t}" width="${bw}" height="${ih}"/>`;
  });
  s += `<line class="base" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/></svg>`;
  el.innerHTML = s;
  if (tip) attachTips(el, i => tip(data[i], i));
}
/* line chart: series = [{values:[y|null], color, label}], x positions are indices */
function lineChart(el, { series, xs, xLabel, yMin = 0, yMax = 1, yFmt = v => v, tip, refs = [], height = 190, xNumeric = false, markers = [] }) {
  const W = Math.max(280, el.clientWidth), H = height, m = { t: 10, r: 10, b: 22, l: 40 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b, n = xs.length;
  const xMin = xNumeric ? xs[0] : 0, xMax = xNumeric ? xs[n - 1] : n - 1;
  const x = v => m.l + (xMax === xMin ? iw / 2 : (v - xMin) / (xMax - xMin) * iw);
  const xi = i => x(xNumeric ? xs[i] : i);
  const y = v => m.t + ih - (v - yMin) / (yMax - yMin) * ih;
  let s = `<svg width="${W}" height="${H}">`;
  const st = niceStep(yMax - yMin);
  for (let v = Math.ceil(yMin / st) * st; v <= yMax + 1e-9; v += st) s += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${yFmt(v)}</text>`;
  refs.forEach(r => { s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(r.y)}" y2="${y(r.y)}" stroke="${r.color || 'var(--ink-2)'}" stroke-dasharray="4 4" stroke-width="1"/><text x="${W - m.r}" y="${y(r.y) - 5}" text-anchor="end">${esc(r.label)}</text>`; });
  markers.forEach((mk, k) => { s += `<line x1="${x(mk.x)}" x2="${x(mk.x)}" y1="${m.t}" y2="${m.t + ih}" stroke="var(--axis)" stroke-dasharray="3 3"/><text x="${x(mk.x) + 4}" y="${m.t + ih - 6 - k * 14}" text-anchor="start">${esc(mk.label)}</text>`; });
  const every = Math.ceil(n / Math.max(1, Math.floor(iw / 56)));
  xs.forEach((_, i) => { if (i % every === 0) s += `<text x="${xi(i)}" y="${H - 6}" text-anchor="middle">${xLabel(xs[i], i)}</text>`; });
  series.forEach(se => {
    let d = '', pen = false;
    se.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + xi(i).toFixed(1) + ',' + y(v).toFixed(1); pen = true; });
    s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    if (se.dots) se.values.forEach((v, i) => { if (v != null) s += `<circle cx="${xi(i)}" cy="${y(v)}" r="3.5" fill="${se.color}" stroke="var(--surface)" stroke-width="2"/>`; });
  });
  s += `<line class="base" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/>`;
  if (tip) {
    const cw = iw / Math.max(1, n - 1);
    xs.forEach((_, i) => s += `<rect class="hit" data-i="${i}" x="${xi(i) - cw / 2}" y="${m.t}" width="${cw}" height="${ih}"/>`);
  }
  s += '</svg>';
  el.innerHTML = s;
  if (tip) attachTips(el, i => tip(i));
}
/* scatter for calibration */
function calibChart(el, pts, height = 230) {
  const W = Math.max(280, el.clientWidth), H = height, m = { t: 10, r: 10, b: 28, l: 40 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const lo = Math.min(.5, ...pts.map(p => Math.min(p.pred, p.actual))) - .02, lo2 = Math.floor(lo * 10) / 10;
  const x = v => m.l + (v - lo2) / (1 - lo2) * iw, y = v => m.t + ih - (v - lo2) / (1 - lo2) * ih;
  let s = `<svg width="${W}" height="${H}">`;
  for (let v = lo2; v <= 1.0001; v += .1) s += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${pct(v)}</text><text x="${x(v)}" y="${H - 12}" text-anchor="middle">${pct(v)}</text>`;
  s += `<line x1="${x(lo2)}" y1="${y(lo2)}" x2="${x(1)}" y2="${y(1)}" stroke="var(--axis)" stroke-dasharray="4 4"/>`;
  s += `<text x="${m.l + iw / 2}" y="${H}" text-anchor="middle">predicted recall (R at review)</text>`;
  const maxN = Math.max(...pts.map(p => p.n));
  pts.forEach((p, i) => { const r = 4 + 6 * Math.sqrt(p.n / maxN); s += `<circle data-i="${i}" cx="${x(p.pred)}" cy="${y(p.actual)}" r="${r}" fill="var(--seq)" fill-opacity=".85" stroke="var(--surface)" stroke-width="2"/>`; });
  s += '</svg>';
  el.innerHTML = s;
  attachTips(el, i => { const p = pts[i]; return `<div class="t">R ${pct(p.pred)} bin</div>${tipRow('Predicted', pct(p.pred, 1))}${tipRow('Actual', pct(p.actual, 1))}${tipRow('Reviews', p.n)}`; });
}
function segBar(parts) { // [{v,color,label}]
  const tot = parts.reduce((s, p) => s + p.v, 0) || 1;
  return `<div class="seg-bar">${parts.filter(p => p.v > 0).map(p => `<div title="${esc(p.label)}: ${p.v} (${pct(p.v / tot)})" style="flex:${p.v};background:${p.color}"></div>`).join('') || '<div style="flex:1;background:var(--surface-3)"></div>'}</div>`;
}
function tableToggle(btnHost, rows, cols) {
  const b = document.createElement('button'); b.className = 'toggle-table'; b.textContent = 'Show as table';
  const t = document.createElement('div'); t.className = 'hidden'; t.style.maxHeight = '260px'; t.style.overflow = 'auto'; t.style.marginTop = '8px';
  t.innerHTML = `<table class="data"><thead><tr>${cols.map(c => `<th class="${c.num ? 'num' : ''}">${c.h}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${cols.map(c => `<td class="${c.num ? 'num' : ''}">${c.f(r)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  b.onclick = () => { t.classList.toggle('hidden'); b.textContent = t.classList.contains('hidden') ? 'Show as table' : 'Hide table'; };
  btnHost.append(b, t);
}

/* ---------------------------------------------------------------- login */
function loginView() {
  if ($('#login-form')) return;
  if (cleanup) { cleanup(); cleanup = null; }
  closeModal();
  view.innerHTML = `<div style="max-width:340px;margin:12vh auto 0;text-align:center">
    <div class="brand-mark" style="width:44px;height:44px;border-radius:12px;margin:0 auto 14px"></div>
    <h1>FSRS Cards</h1><p class="sub">Enter your password to continue</p>
    <form id="login-form" style="display:grid;gap:10px;margin-top:16px">
      <input type="text" name="username" autocomplete="username" value="me" hidden>
      <input class="input" type="password" id="pw" autocomplete="current-password" placeholder="Password" autofocus style="padding:11px 12px">
      <button class="btn primary" style="padding:11px">Sign in</button>
      <div class="sub" id="login-msg" style="min-height:1.4em"></div>
    </form></div>`;
  $('#login-form').onsubmit = async e => {
    e.preventDefault();
    try { await api('/api/login', { json: { password: $('#pw').value } }); _settings = null; route(); }
    catch (er) { $('#login-msg').textContent = er.message; $('#pw').select(); }
  };
}

/* ---------------------------------------------------------------- router */
let current = null, cleanup = null;
const routes = { '': decksView, study: studyView, stats: statsView, browse: browseView, answers: answersView, settings: settingsView };
function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  closeModal();
  const [name, ...rest] = location.hash.replace(/^#\/?/, '').split('/');
  const arg = rest.length ? decodeURIComponent(rest.join('/')) : null;
  $$('[data-nav]').forEach(a => a.classList.toggle('on', (a.dataset.nav === 'decks' && (name === '' || name === 'study')) || a.dataset.nav === name));
  current = { name, arg };
  scrollTo(0, 0);
  Promise.resolve((routes[name] || decksView)(arg)).catch(e => { if (e.message !== 'Login required') view.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}
function rerender() { if (current && current.name !== 'study') route(); else if (current) studyRestyle(); }
addEventListener('hashchange', route);
// keep the deck list live: learning cards come due by the minute, and the PWA may sit in the background for hours
const refreshDecks = () => { if (current && current.name === '' && !document.hidden) decksView().catch(() => {}); };
document.addEventListener('visibilitychange', refreshDecks);
setInterval(refreshDecks, 60000);
let resizeT; addEventListener('resize', () => { clearTimeout(resizeT); resizeT = setTimeout(() => { if (current && ['stats'].includes(current.name)) route(); }, 150); });

/* ---------------------------------------------------------------- decks */
let collapsed = new Set(); try { collapsed = new Set(JSON.parse(localStorage.getItem('collapsed') || '[]')); } catch (e) {}
async function decksView() {
  view.innerHTML = `<div class="muted">Loading…</div>`;
  const decks = await api('/api/decks');
  const names = new Set(decks.map(d => d.name));
  const hasKids = n => decks.some(d => d.name.startsWith(n + '::'));
  const hidden = d => [...collapsed].some(c => d.name.startsWith(c + '::'));
  const c = (v, cls) => `<div class="cnt ${v ? cls : 'z'}">${v}</div>`;
  const tot = decks.filter(d => d.depth === 0 || !names.has(d.name.split('::').slice(0, -1).join('::'))).reduce((a, d) => ({ n: a.n + d.new, l: a.l + d.learning, r: a.r + d.review }), { n: 0, l: 0, r: 0 });
  view.innerHTML = `
    <div class="deck-head">
      <div><h1>Decks</h1><p class="sub">${decks.length ? `Due today: <b class="c-new">${tot.n}</b> new · <b class="c-learning">${tot.l}</b> learning · <b class="c-review">${tot.r}</b> review` : 'No decks yet · import one with <code>tools/import_apkg.py</code>'}</p></div>
      <div style="display:flex;gap:8px">${decks.length ? `<a class="btn primary" href="#/study">Study all</a>` : ''}</div>
    </div>
    ${decks.length ? `<div class="panel decks">
      <div class="deck-row hdr"><div>Deck</div><div class="cnt">New</div><div class="cnt">Learn</div><div class="cnt">Due</div><div></div></div>
      ${decks.filter(d => !hidden(d)).map(d => `
        <div class="deck-row" data-deck="${esc(d.name)}" data-id="${d.id}">
          <div class="deck-name" style="padding-left:${d.depth * 18}px">
            <span class="twisty" data-tw="${esc(d.name)}">${hasKids(d.name) ? (collapsed.has(d.name) ? '▶' : '▼') : ''}</span>
            <span class="n">${esc(d.short)}</span><span class="tot">${d.total}</span>
          </div>
          ${c(d.new, 'c-new')}${c(d.learning, 'c-learning')}${c(d.review, 'c-review')}
          <button class="icon-btn row-menu" data-stats="${esc(d.name)}" title="Deck stats">▤</button>
        </div>`).join('')}
    </div>` : ''}`;
  $$('.deck-row[data-deck]').forEach(r => r.onclick = e => {
    if (e.target.dataset.tw !== undefined && hasKids(e.target.dataset.tw)) {
      const n = e.target.dataset.tw; collapsed.has(n) ? collapsed.delete(n) : collapsed.add(n);
      try { localStorage.setItem('collapsed', JSON.stringify([...collapsed])); } catch (er) {}
      return decksView();
    }
    if (e.target.dataset.stats) { location.hash = '#/stats/' + encodeURIComponent(e.target.dataset.stats); return; }
    location.hash = '#/study/' + encodeURIComponent(r.dataset.deck);
  });
}

/* ---------------------------------------------------------------- study */
const sheetCache = new Map();
function sheet(text) {
  let s = sheetCache.get(text);
  if (!s) { s = new CSSStyleSheet(); s.replaceSync(text); sheetCache.set(text, s); }
  return s;
}
let katexCss = null;
fetch('/static/vendor/katex/katex.min.css').then(r => r.text()).then(t => { katexCss = sheet(t.replace(/@font-face\s*{[^}]*}/g, '')); });
const BASE_CARD_CSS = `:host{display:block} .card{min-height:200px;padding:20px;overflow-wrap:anywhere} img{max-width:100%;height:auto} audio{max-width:100%}
  .cloze{font-weight:700;color:#2a78d6} .nightMode .cloze{color:#6da7ec} .tmpl-err{color:#c0302f;font-family:monospace}
  #typeans{width:100%;font:inherit;padding:8px 10px;border-radius:8px;border:1px solid #c3c2b7;margin-top:12px;box-sizing:border-box}
  .type-cmp{font-family:ui-monospace,Menlo,monospace;margin-top:12px;line-height:1.8} .tc-ok{background:#1baf7a33} .tc-bad{background:#e3494844;text-decoration:line-through} .tc-miss{background:#eda10044}
  a.hint{color:#2a78d6;font-size:.9em}
  @media (max-width:600px){.card{padding:6px;min-height:150px}}`;

function renderMath(el) {
  if (window.renderMathInElement) renderMathInElement(el, { delimiters: [{ left: '\\(', right: '\\)', display: false }, { left: '\\[', right: '\\]', display: true }, { left: '$$', right: '$$', display: true }], throwOnError: false, ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'input'] });
}
function paintCard(host, html, cssText) {
  const root = host.shadowRoot || host.attachShadow({ mode: 'open' });
  root.adoptedStyleSheets = [sheet(BASE_CARD_CSS), ...(katexCss ? [katexCss] : []), sheet(cssText || '')];
  root.innerHTML = `<div class="card${isDark() ? ' nightMode night_mode' : ''}">${html}</div>`;
  renderMath(root.firstElementChild);
  return root;
}
function preload(html) { html.replace(/src="([^"]+)"/g, (_, u) => { if (!u.endsWith('.mp3')) (new Image()).src = u; }); }
function typeCompare(given, expected) {
  // character-level LCS diff, like Anki's typed-answer comparison
  const a = given, b = expected, n = a.length, m = b.length;
  if (n * m > 250000) return `<div class="type-cmp">${esc(given)}<br>↓<br>${esc(expected)}</div>`;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let i = 0, j = 0, top = '', bot = '';
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { top += `<span class="tc-ok">${esc(a[i])}</span>`; bot += `<span class="tc-ok">${esc(b[j])}</span>`; i++; j++; }
    else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) { bot += `<span class="tc-miss">${esc(b[j])}</span>`; j++; }
    else { top += `<span class="tc-bad">${esc(a[i])}</span>`; i++; }
  }
  return given === expected ? `<div class="type-cmp"><span class="tc-ok">${esc(expected)}</span></div>` : `<div class="type-cmp">${top || '<i>(nothing typed)</i>'}<br>↓<br>${bot}</div>`;
}

let S = null; // study state
function studyRestyle() { if (S && S.card) S.revealed ? showAnswer(true) : showQuestion(); }
async function studyView(deck) {
  S = { deck, card: null, revealed: false, shownAt: 0, counts: null, busy: false, typed: '' };
  document.activeElement?.blur?.();
  view.innerHTML = `
    <div class="study">
      <div class="study-bar">
        <a class="icon-btn" href="#/" title="Back (Esc)">←</a>
        <div class="study-deck">${esc(deck ? deck.split('::').slice(-1)[0] : 'All decks')}</div>
        <div class="qcounts" id="qc"></div>
        <button class="icon-btn mic-btn" id="mic-btn" title="Record spoken answers (M)"><span class="mic-dot"></span><span class="mic-bars"><i></i><i></i><i></i></span><span class="mic-lbl">Mic</span></button>
        <button class="icon-btn flag-btn" id="flag-btn" title="Flag this answer to dive into later (F)">⚑</button>
        <button class="icon-btn" id="susp-btn" title="Suspend card (@)">⊘</button>
        <button class="icon-btn" id="undo-btn" title="Undo (U)">↶</button>
        <button class="icon-btn" id="info-btn" title="Card info (I)">ⓘ</button>
      </div>
      <div class="progress"><div id="prog" style="width:0"></div></div>
      <div class="susp-pop hidden" id="susp-pop"></div>
      <div id="study-body" class="card-wrap"></div>
      <div class="answer-bar" id="abar"></div>
    </div>`;
  $('#undo-btn').onclick = undo;
  $('#susp-btn').onclick = () => S.card && toggleSuspendPop();
  $('#info-btn').onclick = () => S.card && openCardInfo(S.card.id);
  $('#mic-btn').onclick = () => recToggle();
  $('#flag-btn').onclick = () => toggleFlag();
  const onKey = e => {
    if ($('.modal-bg')) { if (e.key === 'Escape') closeModal(); return; }
    const tgt = e.composedPath()[0];
    const typing = tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable);
    if (typing && e.key !== 'Enter') return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (!$('#susp-pop').classList.contains('hidden')) { if (e.key === 'Escape') toggleSuspendPop(false); return; }
    if (e.key === 'Escape') { location.hash = '#/'; return; }
    if (e.key === '@' && S.card) { e.preventDefault(); toggleSuspendPop(true); return; }
    if (!S.card) return;
    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); S.revealed ? answer(3) : showAnswer(); }
    else if (S.revealed && '1234'.includes(e.key)) { e.preventDefault(); answer(+e.key); }
    else if (e.key === 'u' || e.key === 'z') undo();
    else if (e.key === 'i') openCardInfo(S.card.id);
    else if (e.key === 'm') recToggle();
    else if (e.key === 'f') toggleFlag();
    else if (e.key === 'o' && S.revealed && S.card.source_url) location.href = S.card.source_url;
  };
  addEventListener('keydown', onKey);
  cleanup = () => { removeEventListener('keydown', onKey); recDiscard(); recRelease(); S = null; };
  if (REC.on) await recEnsureStream();
  recPaint();
  try { applyStudy(await api('/api/study/next' + (deck ? '?deck=' + encodeURIComponent(deck) : ''))); }
  catch (e) { $('#study-body').innerHTML = `<div class="done-box">${esc(e.message)}</div>`; }
}
function renderCounts() {
  const c = S.counts, st = S.card && S.card.state;
  const cur = st === 'new' ? 'new' : st === 'review' ? 'review' : st ? 'learning' : '';
  $('#qc').innerHTML = `<span class="c-new ${cur === 'new' ? 'cur' : ''}" title="New">${c.new}</span><span class="c-learning ${cur === 'learning' ? 'cur' : ''}" title="Learning">${c.learning}</span><span class="c-review ${cur === 'review' ? 'cur' : ''}" title="Review">${c.review}</span>`;
  const left = c.new + c.learning + c.review, done = c.done_today;
  $('#prog').style.width = (done + left ? (done / (done + left)) * 100 : 100) + '%';
}
function applyStudy(res) {
  if (!S) return;
  S.counts = res.counts;
  S.card = res.card || null;
  S.revealed = false;
  S.flagged = false; paintFlag();
  if (!S.card) {
    recDiscard();
    renderCounts();
    const nd = res.next_learning_due;
    $('#study-body').innerHTML = `<div class="done-box"><div class="big">✓</div><h1>Congratulations!</h1>
      <p class="sub">You've finished ${S.deck ? 'this deck' : 'all decks'} for now · ${res.counts.done_today} reviews today.${nd ? `<br>Next learning card due ${rel(nd)}.` : ''}</p>
      <div style="display:flex;gap:8px;justify-content:center"><a class="btn" href="#/">Decks</a><a class="btn" href="#/stats${S.deck ? '/' + encodeURIComponent(S.deck) : ''}">See stats</a></div></div>`;
    $('#abar').innerHTML = '';
    if (nd) { const wait = Math.max(1, nd - Date.now() / 1000); if (wait < 3600) { const t = setTimeout(() => S && !S.card && studyView(S.deck), wait * 1000 + 500); const prev = cleanup; cleanup = () => { clearTimeout(t); prev && prev(); }; } }
    return;
  }
  renderCounts();
  preload(S.card.answer);
  showQuestion();
  recStart(S.card.id);
}
function fsrsStrip(c) {
  const R = c.retrievability;
  return `<div class="fsrs-strip">
    <div><div class="k">State</div><div class="v" style="text-transform:capitalize;display:flex;align-items:center;gap:6px"><span class="dot" style="background:var(--st-${c.state})"></span>${c.state}</div></div>
    <div title="Probability you recall this card right now"><div class="k">Recall<span class="ks"> · R</span></div><div class="v">${R == null ? '—' : pct(R, 1)}</div><div class="meter"><i style="width:${(R || 0) * 100}%"></i></div></div>
    <div title="Days for R to fall from 100% to 90%"><div class="k">Stability<span class="ks"> · S</span></div><div class="v">${fmtDays(c.stability)}</div></div>
    <div title="1 (easy) – 10 (hard)"><div class="k">Difficulty<span class="ks"> · D</span></div><div class="v">${c.difficulty == null ? '—' : c.difficulty.toFixed(2)}</div><div class="meter"><i style="width:${((c.difficulty || 1) - 1) / 9 * 100}%;background:var(--st-learning)"></i></div></div>
    <div><div class="k">Reviews · lapses</div><div class="v">${c.reps} · ${c.lapses}</div></div>
  </div>`;
}
function sourceLink(c) {
  if (!c.source_url) return '';
  const app = c.source_url.startsWith('bear://') ? 'Bear' : 'source';
  return `<a class="src-link" href="${esc(c.source_url)}" ${c.source_url.startsWith('http') ? 'target="_blank" rel="noopener"' : ''} title="Open the note this card came from (O)">
    <span class="src-ic">↗</span><span class="src-app">Open in ${app}</span><span class="src-lbl">${esc(c.source_label || '')}</span></a>`;
}
function cardFrame(c) {
  return `<div class="card-host" id="card-host"></div><div id="src-slot"></div>
    <div class="card-meta"><span>${esc(c.deck.split('::').slice(-1)[0])}</span>·<span>${esc(c.notetype)}</span>${c.last_review ? `·<span>last seen ${fmtIvl(Date.now() / 1000 - c.last_review)} ago</span>` : ''}</div>
    ${fsrsStrip(c)}`;
}
function showQuestion() {
  const c = S.card;
  $('#study-body').innerHTML = cardFrame(c);
  const root = paintCard($('#card-host'), c.question, c.css);
  const ti = root.querySelector('#typeans');
  if (ti) setTimeout(() => ti.focus(), 0);
  $('#abar').innerHTML = `<button class="reveal" id="reveal">Show answer <kbd>Space</kbd></button>`;
  $('#reveal').onclick = () => showAnswer();
  $('#card-host').onclick = e => { const p = e.composedPath()[0]; if (!S.revealed && !p.closest?.('a,input,button,audio,.hint')) showAnswer(); };
  S.shownAt = performance.now();
}
function showAnswer(restyle) {
  const c = S.card;
  if (!restyle) { const ti = $('#card-host').shadowRoot?.querySelector('#typeans'); S.typed = ti ? ti.value : ''; }
  if (restyle) $('#study-body').innerHTML = cardFrame(c);
  const root = paintCard($('#card-host'), c.answer, c.css);
  const tr = root.querySelector('#typeans-result');
  if (tr) { tr.innerHTML = typeCompare(S.typed.trim(), tr.dataset.expected); }
  const hr = root.querySelector('#answer');
  if (hr && !restyle) setTimeout(() => hr.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 0);
  S.revealed = true;
  if (!restyle) recMarkReveal();
  $('#src-slot').innerHTML = sourceLink(c);
  $('#abar').innerHTML = `<div class="ratings">${RATINGS.map(r => `
    <button class="rate ${r.cls}" data-r="${r.n}"><kbd>${r.n}</kbd><div class="lbl">${r.label}</div><div class="ivl">${fmtIvl(c.previews[r.n])}</div></button>`).join('')}</div>`;
  $$('.rate').forEach(b => b.onclick = () => answer(+b.dataset.r));
  document.activeElement?.blur?.();
}
async function answer(rating) {
  if (!S || S.busy || !S.revealed) return;
  S.busy = true;
  const c = S.card, dur = Math.round(performance.now() - S.shownAt), flagged = S.flagged;
  const take = recStop();
  try {
    const res = await api('/api/study/answer', { json: { card_id: c.id, rating, duration_ms: dur, deck: S.deck } });
    take.then(t => recUpload(c.id, t, { rating, flagged }));
    S.lastAction = { type: 'answer' };
    const a = res.answered, r = RATINGS[rating - 1];
    toast(`<span class="sw" style="background:var(--${r.key})"></span><b>${r.label}</b> → ${fmtIvl(a.interval_secs)} · S ${fmtDays(a.stability_before)} → ${fmtDays(a.stability)} · D ${a.difficulty.toFixed(1)}${a.retrievability != null ? ` · R was ${pct(a.retrievability)}` : ''}`);
    applyStudy(res);
  } catch (e) { toast(esc(e.message)); }
  finally { if (S) S.busy = false; }
}
async function undo() {
  if (!S || S.busy) return;
  S.busy = true;
  try {
    if (S.lastAction && S.lastAction.type === 'suspend') {
      const id = S.lastAction.id; S.lastAction = null;
      await api(`/api/cards/${id}/suspend`, { json: { suspended: false } });
      applyStudy(await api(`/api/study/card/${id}` + (S.deck ? '?deck=' + encodeURIComponent(S.deck) : '')));
      toast('Unsuspended · card restored');
      return;
    }
    const res = await api('/api/study/undo', { json: { deck: S.deck } });
    toast(`Undid <b>${RATINGS[res.undone_rating - 1].label}</b>`);
    applyStudy(res);
  } catch (e) { toast(esc(e.message)); }
  finally { if (S) S.busy = false; }
}

function toggleSuspendPop(show) {
  const pop = $('#susp-pop');
  if (!pop) return;
  const open = show ?? pop.classList.contains('hidden');
  if (!open) { pop.classList.add('hidden'); pop.innerHTML = ''; return; }
  pop.innerHTML = `<div class="sp-head"><b>Suspend this card</b><span class="muted">tap a reason · it moves to your rewrite list</span></div>
    <div class="reason-chips">${SUSPEND_REASONS.map(r => `<button class="rchip" data-r="${esc(r)}">${esc(r)}</button>`).join('')}</div>
    <div class="sp-row"><input class="input" id="sp-reason" placeholder="Or type a reason / fix idea…"><button class="btn primary" id="sp-go">Suspend</button><button class="btn" id="sp-cancel">Cancel</button></div>`;
  pop.classList.remove('hidden');
  $$('.rchip', pop).forEach(b => b.onclick = () => { const v = $('#sp-reason').value.trim(); suspendAndNext(v ? `${b.dataset.r} — ${v}` : b.dataset.r); });
  $('#sp-go').onclick = () => suspendAndNext($('#sp-reason').value);
  $('#sp-cancel').onclick = () => toggleSuspendPop(false);
  $('#sp-reason').onkeydown = e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); suspendAndNext(e.target.value); } if (e.key === 'Escape') toggleSuspendPop(false); };
}
async function suspendAndNext(reason) {
  if (!S || !S.card || S.busy) return;
  S.busy = true;
  const id = S.card.id;
  try {
    await api(`/api/cards/${id}/suspend`, { json: { suspended: true, reason: (reason || '').trim() || null } });
    toggleSuspendPop(false);
    S.lastAction = { type: 'suspend', id };
    applyStudy(await api('/api/study/next' + (S.deck ? '?deck=' + encodeURIComponent(S.deck) : '')));
    toast(`<b>Suspended</b>${reason ? ' · ' + esc(reason) : ''} · <kbd>U</kbd> to undo`);
  } catch (e) { toast(esc(e.message)); }
  finally { if (S) S.busy = false; }
}

/* ---------------------------------------------------------------- card info modal */
function closeModal() { $('.modal-bg')?.remove(); hideTip(); }
async function openCardInfo(id) {
  closeModal();
  const bg = document.createElement('div'); bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal"><div class="muted">Loading…</div></div>`;
  bg.onclick = e => { if (e.target === bg) closeModal(); };
  document.body.append(bg);
  const c = await api('/api/cards/' + id);
  const m = $('.modal', bg);
  const now = Date.now() / 1000;
  const hist = c.history;
  m.innerHTML = `
    <div class="modal-head"><div><h1 style="font-size:18px">Card info</h1><div class="sub">${esc(c.deck)} · ${esc(c.notetype)} · ${esc(c.template)}</div></div>
      <button class="icon-btn" id="m-close">✕</button></div>
    <div class="card-host" id="m-card" style="min-height:0"></div>
    ${sourceLink(c)}
    ${fsrsStrip(c)}
    <div class="sub" style="margin-top:10px">${c.state === 'new' ? 'Not studied yet.' : `Due <b>${fmtDate(c.due)}</b> (${rel(c.due)}) · last review ${c.last_review ? fmtDateTime(c.last_review * 1000) : '—'}`}</div>
    ${c.suspended ? `<div class="susp-note">Suspended${c.suspended_at ? ' ' + fmtDateTime(c.suspended_at * 1000) : ''}${c.suspend_reason ? ` · <b>${esc(c.suspend_reason)}</b>` : ' · no reason given'}</div>` : ''}
    <div style="display:flex;gap:8px;margin:8px 0 16px;flex-wrap:wrap">
      <button class="btn" id="m-susp">${c.suspended ? 'Unsuspend' : 'Suspend…'}</button>
      <button class="btn danger" id="m-reset">Reset to new</button>
    </div>
    <div class="panel susp-form hidden" id="m-susp-form" style="margin-bottom:16px">
      <h2>Why suspend it?</h2><div class="sub">Saved with the card, so suspended cards become a rewrite list (tools/export_suspended.py).</div>
      <div class="reason-chips">${SUSPEND_REASONS.map(r => `<button class="rchip" data-r="${esc(r)}">${esc(r)}</button>`).join('')}</div>
      <input class="input" id="m-reason" placeholder="Reason / how to fix it (optional)" style="width:100%;margin-top:10px">
      <div style="display:flex;gap:8px;margin-top:10px"><button class="btn primary" id="m-susp-go">Suspend</button><button class="btn" id="m-susp-cancel">Cancel</button></div>
    </div>
    ${c.responses.length ? `<div class="panel" style="margin-bottom:14px"><h2>Spoken answers</h2><div class="sub">${c.responses.length} attempt${c.responses.length > 1 ? 's' : ''}, newest first. Use this to see how your answer changes over time.</div>
      <div class="resp-list" id="m-resp">${c.responses.map(r => responseItem(r)).join('')}</div></div>` : ''}
    ${c.curve ? `<div class="panel" style="margin-bottom:14px"><h2>Forgetting curve</h2><div class="sub">Predicted recall over time with S = ${fmtDays(c.stability)}. FSRS schedules the next review when R hits your desired retention.</div><div class="chart" id="m-curve"></div></div>` : ''}
    ${hist.length > 1 ? `<div class="panel" style="margin-bottom:14px"><h2>Memory state over reviews</h2><div class="sub">Stability after each review (days)</div><div class="chart" id="m-stab"></div></div>` : ''}
    <div class="panel"><h2>Review history</h2><div class="sub">${hist.length} reviews</div>
      ${hist.length ? `<div style="overflow:auto"><table class="data"><thead><tr><th>Date</th><th>Rating</th><th>State</th><th class="num">R</th><th class="num">Elapsed</th><th class="num">Stability</th><th class="num">Diff.</th><th class="num">Interval</th><th class="num">Time</th></tr></thead><tbody>
      ${hist.slice().reverse().map(h => `<tr><td>${fmtDateTime(h.ts)}${h.imported ? ' <span class="muted">·imp</span>' : ''}</td><td>${ratingChip(h.rating)}</td><td>${STATE_LABEL[STATES[h.state_before]]} → ${STATE_LABEL[STATES[h.state_after]]}</td>
        <td class="num">${pct(h.retrievability)}</td><td class="num">${h.elapsed_days == null ? '—' : fmtDays(h.elapsed_days)}</td>
        <td class="num">${fmtDays(h.stability_before)} → ${fmtDays(h.stability)}</td><td class="num">${h.difficulty.toFixed(2)}</td>
        <td class="num">${fmtIvl(h.interval_secs)}</td><td class="num">${h.duration_ms ? (h.duration_ms / 1000).toFixed(1) + 's' : '—'}</td></tr>`).join('')}
      </tbody></table></div>` : ''}
    </div>`;
  paintCard($('#m-card', m), c.answer, c.css);
  $('#m-close', m).onclick = closeModal;
  if ($('#m-resp', m)) { bindResponses($('#m-resp', m), () => openCardInfo(id)); renderMath($('#m-resp', m)); }
  $('#m-susp', m).onclick = async () => {
    if (c.suspended) { await api(`/api/cards/${id}/suspend`, { json: { suspended: false } }); toast('Unsuspended'); return openCardInfo(id); }
    $('#m-susp-form', m).classList.remove('hidden'); $('#m-reason', m).focus();
  };
  $$('.rchip', m).forEach(b => b.onclick = () => { const i = $('#m-reason', m); i.value = i.value ? (i.value.includes(b.dataset.r) ? i.value : b.dataset.r + ' — ' + i.value) : b.dataset.r; i.focus(); });
  $('#m-susp-cancel', m).onclick = () => $('#m-susp-form', m).classList.add('hidden');
  const doSuspend = async () => {
    await api(`/api/cards/${id}/suspend`, { json: { suspended: true, reason: $('#m-reason', m).value } });
    toast('Suspended · added to the rewrite list');
    if (S && S.card && S.card.id === id) { closeModal(); S.lastAction = { type: 'suspend', id }; applyStudy(await api('/api/study/next' + (S.deck ? '?deck=' + encodeURIComponent(S.deck) : ''))); }
    else openCardInfo(id);
  };
  $('#m-susp-go', m).onclick = doSuspend;
  $('#m-reason', m).onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); doSuspend(); } e.stopPropagation(); };
  $('#m-reset', m).onclick = async () => { if (confirm('Reset this card to new? Its review history is kept.')) { await api(`/api/cards/${id}/reset`, { method: 'POST' }); openCardInfo(id); } };
  if (c.curve) {
    const st = await settingsCache();
    const xs = c.curve.map(p => p[0]), el = $('#m-curve', m);
    const nowD = c.elapsed_days || 0, dueD = (c.due - c.last_review) / 86400;
    lineChart(el, {
      series: [{ values: c.curve.map(p => p[1]), color: 'var(--seq)' }], xs, xNumeric: true, xLabel: v => v === 0 ? '0' : fmtIvl(v * 86400),
      yMin: Math.min(.5, Math.floor(c.curve[c.curve.length - 1][1] * 10) / 10), yMax: 1, yFmt: v => pct(v),
      refs: [{ y: st.desired_retention, label: `desired ${pct(st.desired_retention)}` }],
      markers: [{ x: Math.min(nowD, xs[xs.length - 1]), label: 'now' }, ...(dueD > 0 && dueD <= xs[xs.length - 1] ? [{ x: dueD, label: 'due' }] : [])],
      tip: i => `<div class="t">Day ${fmtDays(xs[i])}</div>${tipRow('Recall', pct(c.curve[i][1], 1))}`,
    });
  }
  if (hist.length > 1) {
    const el = $('#m-stab', m), vals = hist.map(h => h.stability), mx = Math.max(...vals);
    const step = niceStep(mx);
    lineChart(el, {
      series: [{ values: vals, color: 'var(--seq)', dots: true }], xs: hist.map((_, i) => i + 1), xLabel: v => '#' + v,
      yMin: 0, yMax: Math.ceil(mx / step) * step || 1, yFmt: v => Math.round(v), height: 170,
      tip: i => `<div class="t">Review #${i + 1} · ${fmtDate(hist[i].ts / 1000)}</div>${tipRow('Rating', RATINGS[hist[i].rating - 1].label, `var(--${RATINGS[hist[i].rating - 1].key})`)}${tipRow('Stability', fmtDays(hist[i].stability))}${tipRow('Difficulty', hist[i].difficulty.toFixed(2))}${tipRow('Next interval', fmtIvl(hist[i].interval_secs))}`,
    });
  }
}
const SUSPEND_REASONS = ['List / too many items', 'Ambiguous question', 'Inaccurate', 'Too easy', 'Duplicate', 'Not useful'];
let _settings = null;
async function settingsCache() { return _settings || (_settings = await api('/api/settings')); }

/* ---------------------------------------------------------------- stats */
async function statsView(deck) {
  const days = +(sessionStorage.getItem('stats-days') || 30);
  view.innerHTML = `<div class="muted">Loading…</div>`;
  const [st, decks, settings] = await Promise.all([api(`/api/stats?days=${days}${deck ? '&deck=' + encodeURIComponent(deck) : ''}`), api('/api/decks'), settingsCache()]);
  const ratingColors = RATINGS.map(r => css('--' + r.key));
  const t = st.today;
  const againRate = t.count ? t.again / t.count : null;
  const s = st.states;
  view.innerHTML = `
    <div class="deck-head">
      <div><h1>Statistics</h1><p class="sub">${esc(deck || 'All decks')} · ${st.total_reviews} reviews all-time · ${fmtDur(st.total_time_ms)} studied</p></div>
      <div class="filters" style="margin:0">
        <select class="input" id="st-deck" style="max-width:280px"><option value="">All decks</option>${decks.map(d => `<option ${d.name === deck ? 'selected' : ''} value="${esc(d.name)}">${'  '.repeat(d.depth)}${esc(d.short)}</option>`).join('')}</select>
        <select class="input" id="st-days">${[7, 30, 90, 365].map(n => `<option ${n === days ? 'selected' : ''} value="${n}">Last ${n} days</option>`).join('')}</select>
      </div>
    </div>
    <div class="kpis">
      <div class="kpi"><div class="k">Reviewed today</div><div class="v">${t.count}</div><div class="s">${fmtDur(t.time_ms)} · ${t.count ? (t.time_ms / t.count / 1000).toFixed(1) + 's/card' : '—'}</div></div>
      <div class="kpi"><div class="k">Again rate today</div><div class="v">${pct(againRate)}</div><div class="s">${t.again} of ${t.count} answers</div></div>
      <div class="kpi"><div class="k">True retention (${days}d)</div><div class="v">${pct(st.true_retention, 1)}</div><div class="s">target ${pct(settings.desired_retention)} · review cards only</div></div>
      <div class="kpi"><div class="k">Avg retrievability</div><div class="v">${pct(st.avg_retrievability, 1)}</div><div class="s">≈ ${Math.round(st.known_estimate)} cards known now</div></div>
      <div class="kpi"><div class="k">Streak</div><div class="v">${st.streak}d</div><div class="s">consecutive study days</div></div>
    </div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="panel"><h2>Card states</h2><div class="sub">${s.total} cards · ${s.mature} mature (S ≥ 21d) · ${s.suspended} suspended</div>
        ${segBar(STATES.map(k => ({ v: s[k], color: css('--st-' + k), label: STATE_LABEL[k] })))}
        <div class="state-legend">${STATES.map(k => `<div><div class="lk"><span class="dot" style="background:var(--st-${k})"></span>${STATE_LABEL[k]}</div><div class="lv">${s[k]}</div></div>`).join('')}</div>
      </div>
      <div class="panel"><h2>Responses by card state</h2><div class="sub">How you answered, split by the card's state before the review (last ${days} days)</div>
        <div class="legend">${RATINGS.map(r => `<span><i style="background:var(--${r.key})"></i>${r.label}</span>`).join('')}</div>
        <div class="resp-rows">${STATES.map(k => { const v = st.by_state[k], tot = v.reduce((a, b) => a + b, 0); return `<div class="resp-row"><div class="lab">${STATE_LABEL[k]}</div>${segBar(RATINGS.map((r, i) => ({ v: v[i], color: ratingColors[i], label: r.label })))}<div class="num muted tnum">${tot}</div></div>`; }).join('')}</div>
      </div>
    </div>
    <div class="panel" style="margin-bottom:16px"><h2>Reviews per day</h2><div class="sub">Stacked by response</div>
      <div class="legend">${RATINGS.map(r => `<span><i style="background:var(--${r.key})"></i>${r.label}</span>`).join('')}</div>
      <div class="chart" id="c-daily"></div><div id="t-daily"></div></div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="panel"><h2>Retention per day</h2><div class="sub">Share of review-state cards not rated Again, vs. your desired retention</div><div class="chart" id="c-ret"></div></div>
      <div class="panel"><h2>Forecast</h2><div class="sub">Cards due over the next 30 days (overdue counted today)</div><div class="chart" id="c-fc"></div></div>
    </div>
    <div class="grid g3" style="margin-bottom:16px">
      <div class="panel"><h2>Stability</h2><div class="sub">Days until R drops to 90%</div><div class="chart" id="c-stab"></div></div>
      <div class="panel"><h2>Difficulty</h2><div class="sub">FSRS D, 1 (easy) – 10 (hard)</div><div class="chart" id="c-diff"></div></div>
      <div class="panel"><h2>Retrievability</h2><div class="sub">Current predicted recall</div><div class="chart" id="c-r"></div></div>
    </div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="panel"><h2>FSRS calibration</h2><div class="sub">Predicted R at review vs. actual pass rate. Points on the dashed line = well-calibrated model.</div><div class="chart" id="c-cal"></div></div>
      <div class="panel"><h2>Time of day</h2><div class="sub">Reviews by hour (last ${days} days) — hover for pass rate</div><div class="chart" id="c-hour"></div></div>
    </div>
    <div class="panel" style="margin-bottom:16px"><h2>Activity</h2><div class="sub">Reviews per day, last 52 weeks</div><div id="c-heat"></div></div>
    <div class="panel"><h2>FSRS model</h2><div class="sub">FSRS-6 · desired retention ${pct(settings.desired_retention)} · decay ${st.fsrs.decay.toFixed(4)} · ${settings.parameters ? 'custom parameters' : 'default parameters'}</div>
      <div class="params">${st.fsrs.parameters.map((w, i) => `<div><span class="muted">w${i}</span><b>${w.toFixed(4)}</b></div>`).join('')}</div></div>`;
  $('#st-deck').onchange = e => location.hash = '#/stats' + (e.target.value ? '/' + encodeURIComponent(e.target.value) : '');
  $('#st-days').onchange = e => { sessionStorage.setItem('stats-days', e.target.value); statsView(deck); };

  const ser = st.series;
  const dl = (d) => fmtDate(d.date);
  barChart($('#c-daily'), {
    data: ser, keys: ['again', 'hard', 'good', 'easy'], colors: ratingColors, xLabel: dl,
    tip: d => { const tot = d.again + d.hard + d.good + d.easy; return `<div class="t">${fmtDate(d.date)}</div>${RATINGS.slice().reverse().map(r => tipRow(r.label, d[r.key], ratingColors[r.n - 1])).join('')}${tipRow('Total', tot)}${tipRow('Time', fmtDur(d.time_ms))}`; },
  });
  tableToggle($('#t-daily'), ser.slice().reverse(), [{ h: 'Date', f: d => fmtDate(d.date) }, ...RATINGS.map(r => ({ h: r.label, num: 1, f: d => d[r.key] })), { h: 'Retention', num: 1, f: d => pct(d.retention, 1) }, { h: 'Time', num: 1, f: d => fmtDur(d.time_ms) }]);
  const retVals = ser.map(d => d.retention);
  const minR = Math.min(settings.desired_retention, ...retVals.filter(v => v != null));
  lineChart($('#c-ret'), {
    series: [{ values: retVals, color: 'var(--seq)', dots: ser.length <= 60 }], xs: ser.map(d => d.date), xLabel: v => fmtDate(v),
    yMin: Math.max(0, Math.floor((minR - .05) * 10) / 10), yMax: 1, yFmt: v => pct(v),
    refs: [{ y: settings.desired_retention, label: 'desired' }],
    tip: i => `<div class="t">${fmtDate(ser[i].date)}</div>${tipRow('Retention', pct(ser[i].retention, 1))}${tipRow('Reviews', ser[i].review_n)}`,
  });
  const fc = st.forecast.map((n, i) => ({ n, i }));
  barChart($('#c-fc'), { data: fc, keys: ['n'], colors: [css('--seq')], xLabel: d => d.i === 0 ? 'today' : '+' + d.i + 'd', tip: d => `<div class="t">${d.i === 0 ? 'Today' : fmtDate(st.day_start + d.i * 86400)}</div>${tipRow('Due', d.n)}` });
  const sh = st.stability_hist.map(b => ({ ...b }));
  barChart($('#c-stab'), { data: sh, keys: ['n'], colors: [css('--seq')], height: 170, xLabel: b => b.lo >= 365 ? (b.lo / 365) + 'y' : b.lo + 'd', labelEvery: 4, tip: b => `<div class="t">${b.lo}–${b.hi > 1e8 ? '∞' : b.hi} days</div>${tipRow('Cards', b.n)}` });
  barChart($('#c-diff'), { data: st.difficulty_hist.map((n, i) => ({ n, i })), keys: ['n'], colors: [css('--st-learning')], height: 170, xLabel: d => d.i + 1, tip: d => `<div class="t">D ${d.i + 1}–${d.i + 2}</div>${tipRow('Cards', d.n)}` });
  barChart($('#c-r'), { data: st.retrievability_hist.map((n, i) => ({ n, i })), keys: ['n'], colors: [css('--st-review')], height: 170, xLabel: d => (d.i * 5) + '%', labelEvery: 4, tip: d => `<div class="t">R ${d.i * 5}–${d.i * 5 + 5}%</div>${tipRow('Cards', d.n)}` });
  if (st.calibration.length) calibChart($('#c-cal'), st.calibration); else $('#c-cal').innerHTML = `<div class="empty muted">Needs reviews of review-state cards.</div>`;
  barChart($('#c-hour'), { data: st.by_hour.map(([n, p], h) => ({ n, p, h })), keys: ['n'], colors: [css('--seq')], xLabel: d => d.h, labelEvery: 3, tip: d => `<div class="t">${d.h}:00–${d.h + 1}:00</div>${tipRow('Reviews', d.n)}${tipRow('Pass rate', d.n ? pct(d.p / d.n) : '—')}` });
  heatmap($('#c-heat'), st);
}
function heatmap(el, st) {
  const map = new Map(st.heatmap), vals = st.heatmap.map(x => x[1]).filter(v => v > 0).sort((a, b) => a - b);
  const q = p => vals.length ? vals[Math.min(vals.length - 1, Math.floor(p * vals.length))] : 1;
  const th = [q(.2), q(.4), q(.6), q(.8), q(.95)];
  const lvl = v => v <= 0 ? 0 : 1 + th.filter(t => v > t).length;
  const today = new Date(st.day_start * 1000), dow = today.getDay();
  const start = -(51 * 7 + dow);
  let cols = '', col = '';
  for (let d = start; d <= 0; d++) {
    const v = map.get(d) || 0, l = lvl(v);
    col += `<div class="cell" data-i="${d}" style="${l ? `background:var(--h${l})` : ''}"></div>`;
    if ((d - start) % 7 === 6 || d === 0) { cols += `<div class="col">${col}</div>`; col = ''; }
  }
  el.innerHTML = `<div class="heat chart">${cols}</div><div class="legend" style="margin-top:8px">Less ${[0, 1, 2, 3, 4, 5, 6].map(l => `<i style="background:${l ? `var(--h${l})` : 'var(--surface-3)'}"></i>`).join('')} More</div>`;
  const hm = $('.heat', el); hm.scrollLeft = hm.scrollWidth;
  attachTips(hm, d => `<div class="t">${fmtDate(st.day_start + d * 86400)}</div>${tipRow('Reviews', map.get(d) || 0)}`);
}

/* ---------------------------------------------------------------- browse */
async function browseView() {
  const p = { q: '', state: '', sort: 'due', deck: '', offset: 0 };
  const decks = await api('/api/decks');
  view.innerHTML = `
    <div class="deck-head"><div><h1>Browse</h1><p class="sub" id="b-count"></p></div></div>
    <div class="filters">
      <input class="input f-search" id="b-q" type="search" placeholder="Search fields & tags…">
      <select class="input" id="b-deck"><option value="">All decks</option>${decks.map(d => `<option value="${esc(d.name)}">${'  '.repeat(d.depth)}${esc(d.short)}</option>`).join('')}</select>
      <select class="input" id="b-state"><option value="">Any state</option>${STATES.map(s => `<option value="${s}">${STATE_LABEL[s]}</option>`).join('')}<option value="suspended">Suspended</option></select>
      <select class="input" id="b-sort"><option value="due">Sort: due</option><option value="stability">Sort: stability</option><option value="difficulty">Sort: difficulty</option><option value="lapses">Sort: lapses</option><option value="reps">Sort: reviews</option><option value="added">Sort: added</option></select>
    </div>
    <div class="browse-wrap"><table class="data"><thead><tr><th>Front</th><th class="hide-t">Deck</th><th>State</th><th class="hide-m">Due</th><th class="num">Stability</th><th class="hide-t">Difficulty</th><th>R</th><th class="num hide-t">Reps</th><th class="num hide-t">Lapses</th></tr></thead><tbody id="b-body"></tbody></table></div>
    <div style="display:flex;justify-content:center;margin-top:12px"><button class="btn hidden" id="b-more">Load more</button></div>`;
  let seq = 0;
  const load = async (append) => {
    const my = ++seq;
    const qs = new URLSearchParams({ q: p.q, sort: p.sort, limit: 150, offset: p.offset });
    if (p.state) qs.set('state', p.state); if (p.deck) qs.set('deck', p.deck);
    const r = await api('/api/browse?' + qs);
    if (my !== seq) return;
    $('#b-count').textContent = `${r.total} cards`;
    const html = r.items.map(c => `<tr class="click" data-id="${c.id}">
      <td class="cell-front" title="${esc(c.front)}"><div>${esc(c.front)}</div></td><td class="muted hide-t">${esc((c.deck || '').split('::').slice(-1)[0])}</td>
      <td>${c.suspended ? `<span class="chip" style="--c:var(--muted)" title="${esc(c.suspend_reason || 'no reason given')}">Suspended</span>` : stateChip(c.state)}</td>
      <td class="hide-m">${c.due ? rel(c.due) : '—'}</td><td class="num">${fmtDays(c.stability)}</td>
      <td class="hide-t">${c.difficulty == null ? '—' : `<span class="mini"><i style="width:${(c.difficulty - 1) / 9 * 100}%;background:var(--st-learning)"></i></span>${c.difficulty.toFixed(1)}`}</td>
      <td>${c.retrievability == null ? '—' : `<span class="mini"><i style="width:${c.retrievability * 100}%"></i></span>${pct(c.retrievability)}`}</td>
      <td class="num hide-t">${c.reps}</td><td class="num hide-t">${c.lapses}</td></tr>`).join('');
    const body = $('#b-body');
    if (append) body.insertAdjacentHTML('beforeend', html); else body.innerHTML = html;
    $('#b-more').classList.toggle('hidden', p.offset + r.items.length >= r.total);
  };
  let t;
  $('#b-q').oninput = e => { clearTimeout(t); t = setTimeout(() => { p.q = e.target.value; p.offset = 0; load(); }, 120); };
  ['deck', 'state', 'sort'].forEach(k => $('#b-' + k).onchange = e => { p[k] = e.target.value; p.offset = 0; load(); });
  $('#b-more').onclick = () => { p.offset += 150; load(true); };
  $('#b-body').onclick = e => { const tr = e.target.closest('tr[data-id]'); if (tr) openCardInfo(+tr.dataset.id); };
  const onKey = e => { if (e.key === 'Escape') closeModal(); };
  addEventListener('keydown', onKey); cleanup = () => removeEventListener('keydown', onKey);
  load();
}

/* ---------------------------------------------------------------- spoken answers (recorder) */
/* One recording per card: starts when the card appears, ends when you rate it. The audio is uploaded, transcribed
   in the background and deleted on the server; only the text is kept. Near-silent or very short takes are dropped. */
const REC = { on: false, stream: null, ctx: null, analyser: null, seg: null, before: null, t0: 0, revealMs: null, meter: null, cardId: null };
try { REC.on = localStorage.getItem('rec') === '1'; } catch (e) {}
const REC_MIME = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || '';
/* A part is sent for transcription only if at least SPEECH_MS of it was clearly above silence (RMS over SPEECH_RMS).
   Kept deliberately low: a dropped answer is worse than a wasted transcription. */
const SPEECH_RMS = 0.015, SPEECH_MS = 250;
const pendingResp = new Set();
const micPref = () => { try { return localStorage.getItem('mic-device') || ''; } catch (e) { return ''; } };

async function recEnsureStream() {
  if (REC.stream) return true;
  const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  const dev = micPref();
  try {
    try {
      REC.stream = await navigator.mediaDevices.getUserMedia({ audio: dev ? { ...base, deviceId: { exact: dev } } : base });
    } catch (e) {
      if (!dev || !['OverconstrainedError', 'NotFoundError'].includes(e.name)) throw e;
      REC.stream = await navigator.mediaDevices.getUserMedia({ audio: base }); // chosen mic is gone: use the default
      toast('Selected microphone not found · using the default one', 3500);
    }
  } catch (e) {
    REC.on = false; try { localStorage.setItem('rec', '0'); } catch (er) {}
    toast(`Microphone unavailable · ${esc(e.message)}`, 3500); recPaint(); return false;
  }
  try { // level meter: drives the mic animation and drops silent parts
    REC.ctx = new AudioContext();
    REC.analyser = REC.ctx.createAnalyser(); REC.analyser.fftSize = 1024;
    REC.ctx.createMediaStreamSource(REC.stream).connect(REC.analyser);
    if (REC.ctx.state !== 'running') addEventListener('pointerdown', () => REC.ctx?.resume(), { once: true });
  } catch (e) { REC.analyser = null; }
  return true;
}
function recRelease() {
  clearInterval(REC.meter); REC.meter = null;
  REC.stream?.getTracks().forEach(t => t.stop()); REC.stream = null;
  REC.ctx?.close().catch(() => {}); REC.ctx = REC.analyser = null;
}
async function recToggle() {
  REC.on = !REC.on;
  try { localStorage.setItem('rec', REC.on ? '1' : '0'); } catch (e) {}
  if (REC.on) {
    if (!window.MediaRecorder) { REC.on = false; toast('This browser cannot record audio'); return recPaint(); }
    if (await recEnsureStream() && S && S.card) recStart(S.card.id);
    if (REC.on) toast('Mic on · each answer is transcribed and saved to <b>Answers</b>');
  } else { recDiscard(); recRelease(); toast('Mic off'); }
  recPaint();
}
function recPaint() {
  const b = $('#mic-btn'); if (!b) return;
  b.classList.toggle('on', REC.on);
  b.classList.toggle('live', !!REC.seg);
  if (!REC.seg) b.style.setProperty('--lvl', 0);
  b.title = REC.on ? 'Recording your answer · M to turn the mic off' : 'Record spoken answers (M)';
}
function meterOn() { return !!(REC.analyser && REC.ctx && REC.ctx.state === 'running'); }
function recMeter() { // every 100ms: count speech in the current part and animate the mic button
  clearInterval(REC.meter);
  if (!REC.analyser) return;
  const buf = new Float32Array(REC.analyser.fftSize);
  REC.meter = setInterval(() => {
    if (!meterOn()) return;
    REC.analyser.getFloatTimeDomainData(buf);
    let sum = 0; for (const v of buf) sum += v * v;
    const rms = Math.sqrt(sum / buf.length);
    if (REC.seg && REC.seg.speechMs != null && rms >= SPEECH_RMS) REC.seg.speechMs += 100;
    // fast attack, slow release, sqrt curve so quiet speech still moves the bars
    REC.lvl = REC.seg ? Math.max(Math.min(1, Math.sqrt(rms * 6)), (REC.lvl || 0) * 0.7) : 0;
    $('#mic-btn')?.style.setProperty('--lvl', REC.lvl.toFixed(2));
  }, 100);
}
function recSegment() {
  const mr = new MediaRecorder(REC.stream, REC_MIME ? { mimeType: REC_MIME, audioBitsPerSecond: 32000 } : {});
  // speechMs = null means "couldn't measure", and such a part is always sent
  const seg = { mr, chunks: [], start: Date.now(), speechMs: meterOn() ? 0 : null };
  mr.ondataavailable = e => { if (e.data.size) seg.chunks.push(e.data); };
  mr.start(1000);
  return seg;
}
function recClose(seg) { // resolves to {blob, ms, speechMs} once the recorder has flushed
  const ms = Date.now() - seg.start;
  return new Promise(res => {
    seg.mr.onstop = () => res({ blob: new Blob(seg.chunks, { type: seg.mr.mimeType || 'audio/webm' }), ms, speechMs: seg.speechMs });
    try { seg.mr.stop(); } catch (e) { res(null); }
  });
}
function recStart(cardId) {
  recDiscard();
  if (!REC.on || !REC.stream) return recPaint();
  if (REC.ctx && REC.ctx.state !== 'running') REC.ctx.resume().catch(() => {});
  REC.t0 = Date.now(); REC.revealMs = null; REC.before = null; REC.cardId = cardId;
  REC.seg = recSegment();
  if (!REC.meter) recMeter();
  recPaint();
}
/* Flipping the card ends the "before" part (your recall attempt) and starts the "after" part. */
function recMarkReveal() {
  if (!REC.seg || REC.revealMs != null) return;
  REC.revealMs = Date.now() - REC.t0;
  REC.before = recClose(REC.seg);
  REC.seg = recSegment();
}
/* Stops the current take and resolves to {before, after, ...}. Detaches it at once so the next card can record. */
function recStop() {
  if (!REC.seg) return Promise.resolve(null);
  const take = { t0: REC.t0, duration: Date.now() - REC.t0, revealMs: REC.revealMs, cardId: REC.cardId };
  const last = recClose(REC.seg), before = REC.before;
  REC.seg = null; REC.before = null; recPaint();
  return Promise.all([before, last]).then(([b, l]) => before ? { ...take, before: b, after: l } : { ...take, before: l, after: null });
}
function recDiscard() {
  const seg = REC.seg; REC.seg = null; REC.before = null;
  if (seg) { seg.mr.ondataavailable = null; try { seg.mr.stop(); } catch (e) {} }
}
const hasSpeech = p => !!(p && p.blob.size && p.ms >= 700 && (p.speechMs == null || p.speechMs >= SPEECH_MS));
async function recUpload(cardId, t, { rating, flagged }) {
  if (!t || t.cardId !== cardId) return;
  const before = hasSpeech(t.before) ? t.before : null, after = hasSpeech(t.after) ? t.after : null;
  if (!before && !after) return; // nothing said: don't spend a transcription on silence
  const fd = new FormData(), ext = b => b.type.includes('mp4') ? 'm4a' : 'webm';
  if (before) fd.append('audio', before.blob, 'before.' + ext(before.blob));
  if (after) fd.append('audio_after', after.blob, 'after.' + ext(after.blob));
  Object.entries({ ts: t.t0, duration_ms: t.duration, reveal_ms: t.revealMs, rating, flagged }).forEach(([k, v]) => v != null && fd.append(k, v));
  try {
    const r = await api(`/api/cards/${cardId}/responses`, { method: 'POST', body: fd });
    if (!r.transcription) return toast('Answer saved, but the server has no OPENAI_API_KEY so it can\'t transcribe yet', 3500);
    pendingResp.add(r.id); pollResponses();
  } catch (e) { toast(`Couldn't upload your answer · ${esc(e.message)}`, 3500); }
}
let pollT = null;
function pollResponses() {
  if (pollT || !pendingResp.size) return;
  pollT = setTimeout(async () => {
    pollT = null;
    try {
      const r = await api('/api/responses?ids=' + [...pendingResp].join(','));
      for (const it of r.items) {
        if (it.status === 'pending') continue;
        pendingResp.delete(it.id);
        if (it.status === 'done') {
          const n = (it.analysis?.unsure || []).length;
          const txt = it.transcript || it.transcript_after || '';
          toast(`<b>Answer saved</b> · ${esc(txt.slice(0, 48))}${txt.length > 48 ? '…' : ''}${n ? ` · ${n} to dive into` : ''}`, 3200);
        } else if (it.status === 'error') toast(`Transcription failed · ${esc(it.error || '')}`, 4000);
        if (current?.name === 'answers' && !$('.modal-bg')) answersReload?.();
      }
      [...pendingResp].forEach(id => { if (!r.items.some(it => it.id === id)) pendingResp.delete(id); });
    } catch (e) {}
    pollResponses();
  }, 2500);
}
function toggleFlag() {
  if (!S || !S.card) return;
  S.flagged = !S.flagged; paintFlag();
  toast(S.flagged ? '<b>Flagged</b> · this answer goes to your dive-into list' : 'Flag removed');
}
function paintFlag() { $('#flag-btn')?.classList.toggle('on', !!(S && S.flagged)); }

/* ---------------------------------------------------------------- spoken answers (display) */
const fmtSecs = ms => ms == null ? '' : ms < 60000 ? Math.round(ms / 1000) + 's' : Math.floor(ms / 60000) + 'm ' + String(Math.round(ms / 1000) % 60).padStart(2, '0') + 's';
function responseItem(r, withQuestion = false) {
  const a = r.analysis || {}, unsure = a.unsure || [], missed = a.missed || [];
  const flip = r.reveal_ms != null ? `<div class="resp-flip"><span>card flipped${r.reveal_ms ? ' · ' + fmtSecs(r.reveal_ms) : ''}</span></div>` : '';
  const body = r.status === 'done' ? (r.transcript_after != null
      ? `<div class="resp-text${r.transcript ? '' : ' muted'}">${r.transcript ? esc(r.transcript) : 'Nothing said before flipping.'}</div>${flip}<div class="resp-text after${r.transcript_after ? '' : ' muted'}">${r.transcript_after ? esc(r.transcript_after) : 'Nothing said after flipping.'}</div>`
      : `<div class="resp-text">${esc(r.transcript)}</div>`)
    : r.status === 'pending' ? `<div class="resp-text muted">Transcribing…</div>`
    : r.status === 'empty' ? `<div class="resp-text muted">No speech detected.</div>`
    : `<div class="resp-text bad">Transcription failed: ${esc(r.error || '')} <button class="linkish" data-retry="${r.id}">Retry</button></div>`;
  return `<div class="resp${r.flagged ? ' flagged' : ''}" data-rid="${r.id}">
    ${withQuestion ? `<div class="resp-q" data-card="${r.card_id}">${esc(r.question || '')}</div>` : ''}
    <div class="resp-meta">${fmtDateTime(r.ts)}${r.rating ? ' · ' + ratingChip(r.rating) : ''}${r.duration_ms ? ` · ${fmtSecs(r.duration_ms)}` : ''}${withQuestion && r.deck ? ` · ${esc(r.deck.split('::').slice(-1)[0])}` : ''}${withQuestion && r.attempts > 1 ? ` · <span class="linkish" data-card="${r.card_id}">${r.attempts} attempts</span>` : ''}
      <span class="spacer"></span>
      <button class="icon-btn flag-btn${r.flagged ? ' on' : ''}" data-flag="${r.id}" title="${r.flagged ? 'Unflag' : 'Flag to dive into later'}">⚑</button>
      <button class="icon-btn" data-del="${r.id}" title="Delete this answer">✕</button></div>
    ${body}
    ${unsure.length ? `<div class="resp-tags"><span class="k">Unsure</span>${unsure.map(x => `<span class="tag unsure">${esc(x)}</span>`).join('')}</div>` : ''}
    ${missed.length ? `<div class="resp-tags"><span class="k">Missed</span>${missed.map(x => `<span class="tag missed">${esc(x)}</span>`).join('')}</div>` : ''}
    ${r.flagged ? `<input class="input resp-note" data-note="${r.id}" placeholder="What to dive into…" value="${esc(r.note || '')}">` : ''}
  </div>`;
}
function bindResponses(host, reload) {
  host.onclick = async e => {
    const t = e.target.closest('[data-flag],[data-del],[data-retry],[data-card]'); if (!t) return;
    if (t.dataset.flag) { const on = !t.classList.contains('on'); await api('/api/responses/' + t.dataset.flag, { method: 'PATCH', json: { flagged: on } }); reload(); }
    else if (t.dataset.del) { if (confirm('Delete this answer?')) { await api('/api/responses/' + t.dataset.del, { method: 'DELETE' }); reload(); } }
    else if (t.dataset.retry) { await api(`/api/responses/${t.dataset.retry}/retry`, { method: 'POST' }); pendingResp.add(+t.dataset.retry); pollResponses(); reload(); }
    else if (t.dataset.card) openCardInfo(+t.dataset.card);
  };
  host.onchange = e => { const n = e.target.dataset.note; if (n) api('/api/responses/' + n, { method: 'PATCH', json: { note: e.target.value } }).then(() => toast('Note saved')); };
  host.onkeydown = e => { if (e.target.dataset.note) e.stopPropagation(); };
}

let answersReload = null;
async function answersView() {
  const p = { q: '', deck: '', show: sessionStorage.getItem('answers-show') || '', offset: 0 };
  const decks = await api('/api/decks');
  view.innerHTML = `
    <div class="deck-head"><div><h1>Answers</h1><p class="sub" id="a-count">Your spoken answers, newest first</p></div></div>
    <div id="a-warn"></div>
    <div class="filters">
      <input class="input f-search" id="a-q" type="search" placeholder="Search answers & questions…">
      <select class="input" id="a-deck"><option value="">All decks</option>${decks.map(d => `<option value="${esc(d.name)}">${'  '.repeat(d.depth)}${esc(d.short)}</option>`).join('')}</select>
      <select class="input" id="a-show"><option value="">All answers</option><option value="gaps">To dive into (flagged or unsure)</option><option value="flagged">Flagged only</option></select>
    </div>
    <div class="resp-list" id="a-list"></div>
    <div style="display:flex;justify-content:center;margin-top:12px"><button class="btn hidden" id="a-more">Load more</button></div>`;
  $('#a-show').value = p.show;
  let seq = 0;
  const load = async append => {
    const my = ++seq;
    const qs = new URLSearchParams({ q: p.q, limit: 50, offset: p.offset });
    if (p.deck) qs.set('deck', p.deck);
    if (p.show === 'flagged') qs.set('flagged', 'true'); else if (p.show === 'gaps') qs.set('gaps', 'true');
    const r = await api('/api/responses?' + qs);
    if (my !== seq || !$('#a-list')) return;
    $('#a-count').textContent = `${r.total} spoken answer${r.total === 1 ? '' : 's'}${p.show ? '' : ' · newest first'}`;
    $('#a-warn').innerHTML = r.configured ? '' : `<div class="susp-note" style="margin:0 0 12px">The server has no <b>OPENAI_API_KEY</b>, so new recordings wait until one is set.</div>`;
    const html = r.items.map(it => responseItem(it, true)).join('');
    const list = $('#a-list');
    if (append) list.insertAdjacentHTML('beforeend', html);
    else list.innerHTML = html || `<div class="empty muted">No answers yet. Turn on the mic in a study session (<kbd>M</kbd>) and answer out loud; each answer shows up here once it's transcribed.</div>`;
    $('#a-more').classList.toggle('hidden', p.offset + r.items.length >= r.total);
    renderMath(list);
    r.items.filter(it => it.status === 'pending').forEach(it => pendingResp.add(it.id)); pollResponses();
  };
  answersReload = () => { p.offset = 0; load(); };
  bindResponses($('#a-list'), answersReload);
  let t;
  $('#a-q').oninput = e => { clearTimeout(t); t = setTimeout(() => { p.q = e.target.value; p.offset = 0; load(); }, 150); };
  $('#a-deck').onchange = e => { p.deck = e.target.value; p.offset = 0; load(); };
  $('#a-show').onchange = e => { p.show = e.target.value; sessionStorage.setItem('answers-show', p.show); p.offset = 0; load(); };
  $('#a-more').onclick = () => { p.offset += 50; load(true); };
  const onKey = e => { if (e.key === 'Escape') closeModal(); };
  addEventListener('keydown', onKey); cleanup = () => { removeEventListener('keydown', onKey); answersReload = null; };
  load();
}

/* ---------------------------------------------------------------- settings */
async function micSettings() {
  const sel = $('#s-mic'), msg = $('#s-mic-msg');
  if (!navigator.mediaDevices?.enumerateDevices) { sel.innerHTML = '<option>Not supported in this browser</option>'; sel.disabled = true; return; }
  const fill = async (hint = true) => {
    // before mic permission, browsers hide ids and names, so only "System default" is offered
    const mics = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput' && d.deviceId && d.deviceId !== 'default');
    const cur = micPref(), named = mics.length > 0;
    sel.innerHTML = `<option value="">System default</option>` + mics.map((d, i) =>
      `<option value="${esc(d.deviceId)}" ${d.deviceId === cur ? 'selected' : ''}>${esc(d.label || `Microphone ${i + 1}`)}</option>`).join('');
    if (cur && !mics.some(d => d.deviceId === cur)) sel.insertAdjacentHTML('beforeend', `<option value="${esc(cur)}" selected>Saved microphone (not connected)</option>`);
    if (hint) msg.textContent = named ? '' : 'Press Test once to allow microphone access and see device names.';
  };
  await fill();
  navigator.mediaDevices.ondevicechange = () => $('#s-mic') && fill(false);
  sel.onchange = () => {
    try { sel.value ? localStorage.setItem('mic-device', sel.value) : localStorage.removeItem('mic-device'); } catch (e) {}
    recRelease(); // the next study session opens the newly chosen mic
    toast('Microphone saved');
  };
  let stop = null;
  $('#s-mic-test').onclick = async () => {
    if (stop) return stop();
    const dev = sel.value, lvl = $('#s-mic-lvl i');
    let stream, ctx;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: dev ? { deviceId: { exact: dev } } : true }); }
    catch (e) { msg.textContent = `Couldn't open the microphone: ${e.message}`; return; }
    await fill();
    ctx = new AudioContext(); const an = ctx.createAnalyser(); an.fftSize = 1024; ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize); let heard = 0;
    const t = setInterval(() => {
      an.getFloatTimeDomainData(buf); let sum = 0; for (const v of buf) sum += v * v;
      const rms = Math.sqrt(sum / buf.length); if (rms >= SPEECH_RMS) heard += 100;
      lvl.style.width = Math.min(100, rms * 900) + '%';
    }, 100);
    $('#s-mic-test').textContent = 'Stop'; msg.textContent = 'Say something…';
    stop = () => {
      clearInterval(t); clearTimeout(auto); stream.getTracks().forEach(x => x.stop()); ctx.close().catch(() => {});
      lvl.style.width = '0'; stop = null;
      if ($('#s-mic-test')) { $('#s-mic-test').textContent = 'Test'; msg.textContent = heard >= SPEECH_MS ? 'Heard you ✓' : 'Heard nothing. Check the selected microphone.'; }
    };
    const auto = setTimeout(() => stop && stop(), 6000);
    const prev = cleanup; cleanup = () => { stop && stop(); prev && prev(); };
  };
}

async function settingsView() {
  const s = _settings = await api('/api/settings');
  view.innerHTML = `
    <h1>Settings</h1><p class="sub">Scheduler: FSRS-6 (py-fsrs). Changes apply to the next answer.</p>
    <div class="panel"><div class="form">
      <div class="field"><label>Desired retention</label><div class="row"><input type="range" id="s-ret" min="0.70" max="0.99" step="0.01" value="${s.desired_retention}"><b class="tnum" id="s-ret-v">${pct(s.desired_retention)}</b></div>
        <div class="help">Probability of recall FSRS aims for when a card comes due. Higher = more reviews, shorter intervals.</div></div>
      <div class="grid g2">
        <div class="field"><label>New cards / day</label><input class="input" type="number" id="s-new" min="0" value="${s.new_per_day}"></div>
        <div class="field"><label>Max reviews / day</label><input class="input" type="number" id="s-rev" min="0" value="${s.reviews_per_day}"></div>
        <div class="field"><label>Learning steps (minutes)</label><input class="input" id="s-ls" value="${s.learning_steps_min.join(' ')}"><div class="help">Space-separated, e.g. "1 10"</div></div>
        <div class="field"><label>Relearning steps (minutes)</label><input class="input" id="s-rs" value="${s.relearning_steps_min.join(' ')}"></div>
        <div class="field"><label>Maximum interval (days)</label><input class="input" type="number" id="s-max" value="${s.maximum_interval}"></div>
        <div class="field"><label>Next day starts at (hour)</label><input class="input" type="number" min="0" max="23" id="s-roll" value="${s.day_rollover_hour}"></div>
        <div class="field"><label>Learn-ahead limit (minutes)</label><input class="input" type="number" id="s-ahead" value="${s.learn_ahead_min}"></div>
        <div class="field"><label><input type="checkbox" id="s-fuzz" ${s.enable_fuzzing ? 'checked' : ''}> Interval fuzz</label><div class="help">Spreads reviews so cards learned together don't stay clumped.</div></div>
      </div>
      <div class="field"><label>FSRS parameters (21 weights)</label><textarea class="input" id="s-params" placeholder="Leave empty for defaults">${s.parameters ? s.parameters.join(', ') : ''}</textarea>
        <div class="help">Current: ${s.effective_parameters.map(w => w.toFixed(4)).join(', ')}<br>Paste weights from Anki's FSRS optimizer, or fit them on your own history below.</div></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" id="s-save">Save</button><button class="btn" id="s-opt">Optimize parameters from my reviews</button><button class="btn" id="s-def">Reset parameters to default</button></div>
      <div class="sub" id="s-msg"></div>
    </div></div>
    <div class="panel" style="margin-top:16px"><h2>Keyboard</h2><div class="sub" style="margin:6px 0 0;line-height:2">
      <kbd>Space</kbd> show answer / Good · <kbd>1</kbd> Again · <kbd>2</kbd> Hard · <kbd>3</kbd> Good · <kbd>4</kbd> Easy · <kbd>U</kbd> undo · <kbd>@</kbd> suspend · <kbd>M</kbd> mic on/off · <kbd>F</kbd> flag answer · <kbd>I</kbd> card info · <kbd>O</kbd> open source note · <kbd>Esc</kbd> back</div></div>
    <div class="panel" style="margin-top:16px"><h2>Microphone</h2><div class="sub">For spoken answers (<kbd>M</kbd> in a study session). Saved on this device.</div>
      <div class="mic-row"><select class="input" id="s-mic"></select><button class="btn" id="s-mic-test">Test</button><span class="mic-test" id="s-mic-lvl"><i></i></span></div>
      <div class="sub" id="s-mic-msg" style="margin:8px 0 0"></div></div>`;
  micSettings();
  api('/api/session').then(x => { if (x.auth_required) { const b = document.createElement('button'); b.className = 'btn'; b.textContent = 'Sign out of this device'; b.onclick = async () => { await api('/api/logout', { method: 'POST' }); loginView(); }; $('#s-save').parentElement.append(b); } });
  $('#s-ret').oninput = e => $('#s-ret-v').textContent = pct(+e.target.value);
  const nums = v => v.split(/[\s,]+/).filter(Boolean).map(Number);
  const save = async (extra = {}) => {
    try {
      const params = $('#s-params').value.trim();
      _settings = await api('/api/settings', { json: {
        desired_retention: +$('#s-ret').value, new_per_day: +$('#s-new').value, reviews_per_day: +$('#s-rev').value,
        learning_steps_min: nums($('#s-ls').value), relearning_steps_min: nums($('#s-rs').value), maximum_interval: +$('#s-max').value,
        day_rollover_hour: +$('#s-roll').value, learn_ahead_min: +$('#s-ahead').value, enable_fuzzing: $('#s-fuzz').checked,
        parameters: params ? nums(params) : null, ...extra } });
      toast('Settings saved'); settingsView();
    } catch (e) { $('#s-msg').textContent = e.message; }
  };
  $('#s-save').onclick = () => save();
  $('#s-def').onclick = () => { $('#s-params').value = ''; save({ parameters: null }); };
  $('#s-opt').onclick = async () => {
    $('#s-msg').textContent = 'Optimizing… this can take a while.';
    try { _settings = await api('/api/optimize', { method: 'POST' }); toast('Parameters optimized'); settingsView(); }
    catch (e) { $('#s-msg').textContent = e.message; }
  };
}

if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) navigator.serviceWorker.register('/sw.js').catch(() => {});
route();
