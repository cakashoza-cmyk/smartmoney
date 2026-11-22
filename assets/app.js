/* India Smart Money Intelligence Dashboard - static client. Data: data/export/*.json built by scripts/build.py.
   No numbers are produced here except sums/filters over exported, source-linked rows and weight re-combination of exported component scores. */
'use strict';
const E = 'data/export/', V = Date.now().toString().slice(0, 7);
const D = {}; const T = {}; let META = null;
const $ = (s, el = document) => el.querySelector(s), $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const NA = '<span class="na">insufficient data</span>';
const isNum = x => typeof x === 'number' && isFinite(x);
const inr = (x, d = 0) => isNum(x) ? x.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }) : null;
const cr = (x, d = 0) => isNum(x) ? `<span class="${x > 0 ? 'pos' : x < 0 ? 'neg' : ''}">₹${inr(x, d)} cr</span>` : NA;
const crp = x => isNum(x) ? `₹${inr(x)} cr` : NA;
const pp = (x, d = 2) => isNum(x) ? `<span class="${x > 0 ? 'pos' : x < 0 ? 'neg' : ''}">${x > 0 ? '+' : ''}${x.toFixed(d)} pp</span>` : NA;
const pc = (x, d = 1) => isNum(x) ? `<span class="${x > 0 ? 'pos' : x < 0 ? 'neg' : ''}">${x > 0 ? '+' : ''}${x.toFixed(d)}%</span>` : NA;
const num = (x, d = 1) => isNum(x) ? x.toFixed(d) : NA;
const LABC = { 'VERIFIED FACT': 'VF', 'REPORTED ANNOUNCEMENT': 'RA', 'ESTIMATED VALUE': 'EV', 'AI INTERPRETATION': 'AI', 'SCENARIO': 'SC', 'UNVERIFIED INFORMATION': 'UN' };
const lab = l => LABC[l] ? `<span class="lab ${LABC[l]}">${esc(l)}</span>` : (l && l !== '—' ? `<span class="lab UN">${esc(l)}</span>` : '');
const ind = id => (META && META.industries[id]) || (id ? id.replace(/_/g, ' ') : 'Unclassified');
const sc = s => isNum(s) ? `<span class="score">${s.toFixed(0)}</span>` : '<span class="score na">insufficient data</span>';
const bar = (v, max = 100, col) => isNum(v) ? `<div class="bar"><i style="width:${Math.max(2, Math.min(100, Math.abs(v) / max * 100))}%;${col ? 'background:' + col : ''}"></i></div>` : '';
const srcA = (u, t = 'source') => u ? `<a class="src" href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a>` : '';
const srcId = id => { const s = META && META.sources.find(x => x.source_id === id); return s ? `<a class="src" href="#/sources/${id}" title="${esc(s.limitations || '')}">${esc(s.name)}</a>${s.stale ? ' <span class="chip st">stale</span>' : ''}` : esc(id); };
const coLink = (id, label) => id ? `<a href="#/companies/${esc(String(id).split(':').pop())}">${esc(label || String(id).split(':').pop())}</a>` : '';
const invLink = (id, label) => id ? `<a href="#/investors/${esc(id)}">${esc(label || id)}</a>` : '';
const secLink = id => id ? `<a href="#/sectors/${esc(id)}">${esc(ind(id))}</a>` : 'Unclassified';
const store = { get: (k, d) => { try { return JSON.parse(localStorage.getItem('sm_' + k)) ?? d } catch { return d } }, set: (k, v) => localStorage.setItem('sm_' + k, JSON.stringify(v)) };

async function J(n) {
  if (D[n]) return D[n];
  const r = await fetch(E + n + '?v=' + V);
  if (!r.ok) throw new Error(n + ': HTTP ' + r.status);
  return (D[n] = await r.json());
}

/* ---------------- tables with sort + CSV ---------------- */
let TID = 0;
function tbl(cols, rows, opt = {}) {
  const id = opt.id || ('t' + (++TID));
  T[id] = { cols, rows, opt };
  return `<div class="noprint flt" style="justify-content:space-between"><span class="muted small">${rows.length} rows${opt.note ? ' · ' + opt.note : ''}</span><span><button class="small" onclick="csv('${id}')">CSV</button></span></div><div class="tw"><table id="${id}">${thead(id)}<tbody>${tbody(id)}</tbody></table></div>`;
}
function thead(id) { const { cols } = T[id]; return '<thead><tr>' + cols.map((c, i) => `<th class="${c.n ? 'n' : ''}" onclick="sortT('${id}',${i})" title="${esc(c.t || '')}">${esc(c.h)}</th>`).join('') + '</tr></thead>'; }
function tbody(id) { const { cols, rows, opt } = T[id]; return rows.slice(0, opt.max || 2000).map(r => '<tr>' + cols.map(c => `<td class="${c.n ? 'n' : ''}">${c.f ? c.f(r) : esc(c.v(r) ?? '')}</td>`).join('') + '</tr>').join('') || `<tr><td colspan="${cols.length}" class="na">${opt.empty || 'insufficient data'}</td></tr>`; }
window.sortT = (id, i) => {
  const t = T[id], c = t.cols[i]; t.dir = t.si === i ? -(t.dir || 1) : (c.n ? -1 : 1); t.si = i;
  t.rows.sort((a, b) => { const x = c.v(a), y = c.v(b); if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * t.dir; });
  $('#' + id + ' tbody').innerHTML = tbody(id);
};
window.csv = id => {
  const t = T[id]; const q = v => { v = v == null ? '' : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const txt = [t.cols.map(c => q(c.h)).join(',')].concat(t.rows.map(r => t.cols.map(c => q(c.v(r))).join(','))).join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['\ufeff# ' + META.disclaimer + '\n' + txt], { type: 'text/csv' })); a.download = (t.opt.file || id) + '.csv'; a.click();
};

/* ---------------- charts (inline SVG) ---------------- */
function bars(data, o = {}) { // data [[label, value]]
  if (!data || !data.length) return `<p class="na">insufficient data</p>`;
  const W = o.w || 640, H = o.h || 160, P = 30, n = data.length, vals = data.map(d => d[1] || 0);
  const mx = Math.max(...vals.map(Math.abs), 1), bw = (W - P - 4) / n, z = H / 2 + (o.pos ? H / 2 - 14 : 0);
  const sy = v => (o.pos ? (H - 14) : (H / 2 - 4)) * Math.abs(v) / mx;
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="none" role="img"><line class="ax" x1="${P}" x2="${W}" y1="${z}" y2="${z}"/>`;
  data.forEach((d, i) => { const v = d[1] || 0, h = sy(v), x = P + i * bw; s += `<rect x="${x + 0.5}" y="${v >= 0 ? z - h : z}" width="${Math.max(1, bw - 1)}" height="${Math.max(0.5, h)}" fill="${v >= 0 ? 'var(--pos)' : 'var(--neg)'}"><title>${esc(d[0])}: ${inr(v)}</title></rect>`; });
  const step = Math.max(1, Math.ceil(n / 8));
  data.forEach((d, i) => { if (i % step === 0) s += `<text x="${P + i * bw}" y="${H - 1}">${esc(String(d[0]).slice(0, 7))}</text>`; });
  s += `<text x="0" y="10">${inr(mx)}</text>${o.pos ? '' : `<text x="0" y="${H - 14}">-${inr(mx)}</text>`}</svg>`;
  return s + (o.cap ? `<div class="src">${o.cap}</div>` : '');
}
const PAL = ['#6aa9ff', '#f5a524', '#2fbf71', '#ef5350', '#b48cf2', '#4dd0e1', '#ff8a65', '#aed581', '#90a4ae'];
function lines(series, o = {}) { // series [{name, pts:[[x(str date or year), y]]}]
  series = series.filter(s => s.pts && s.pts.length > 1);
  if (!series.length) return `<p class="na">insufficient data</p>`;
  const W = o.w || 640, H = o.h || 180, P = 36, all = series.flatMap(s => s.pts);
  const xs = [...new Set(all.map(p => String(p[0])))].sort(), xi = Object.fromEntries(xs.map((x, i) => [x, i]));
  const ys = all.map(p => p[1]).filter(isNum); let lo = Math.min(...ys), hi = Math.max(...ys); if (o.zero) lo = Math.min(lo, 0); if (hi === lo) hi = lo + 1;
  const X = x => P + (xi[String(x)] / Math.max(1, xs.length - 1)) * (W - P - 8), Y = y => 8 + (hi - y) / (hi - lo) * (H - 26);
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img"><line class="ax" x1="${P}" x2="${W}" y1="${H - 18}" y2="${H - 18}"/>`;
  if (lo < 0 && hi > 0) s += `<line class="ax" x1="${P}" x2="${W}" y1="${Y(0)}" y2="${Y(0)}" stroke-dasharray="3 3"/>`;
  series.forEach((sr, k) => { const c = sr.color || PAL[k % PAL.length]; const d = sr.pts.filter(p => isNum(p[1])).map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join(''); s += `<path d="${d}" fill="none" stroke="${c}" stroke-width="1.6"><title>${esc(sr.name)}</title></path>`; const lp = sr.pts[sr.pts.length - 1]; if (isNum(lp[1])) s += `<circle cx="${X(lp[0])}" cy="${Y(lp[1])}" r="2.5" fill="${c}"><title>${esc(sr.name)} ${esc(lp[0])}: ${lp[1]}</title></circle>`; });
  const step = Math.max(1, Math.ceil(xs.length / 7)); xs.forEach((x, i) => { if (i % step === 0) s += `<text x="${X(x) - 10}" y="${H - 4}">${esc(x.slice(0, 7))}</text>`; });
  s += `<text x="0" y="12">${+hi.toFixed(2)}</text><text x="0" y="${H - 20}">${+lo.toFixed(2)}</text></svg>`;
  s += '<div class="small">' + series.map((sr, k) => `<span style="color:${sr.color || PAL[k % PAL.length]}">■</span> ${esc(sr.name)}`).join(' &nbsp; ') + '</div>';
  return s + (o.cap ? `<div class="src">${o.cap}</div>` : '');
}
const heat = v => { if (!isNum(v)) return 'var(--bg3)'; const a = Math.min(1, Math.abs(v - 50) / 50); return v >= 50 ? `rgba(47,191,113,${0.15 + 0.7 * a})` : `rgba(239,83,80,${0.15 + 0.7 * a})`; };

/* ---------------- weights (admin) ---------------- */
function W() { return store.get('weights', null) || META.weights; }
function recombine(components, w) { // same rule as build.py: weighted mean of available percentile components, null if <50% of weight available
  let tot = 0, have = 0, acc = 0; for (const c of components) { const wt = (w && w[c.name] != null) ? w[c.name] : c.weight; tot += wt; if (isNum(c.score)) { have += wt; acc += c.score * wt; } }
  return tot && have / tot >= 0.5 ? acc / have : null;
}
function rescoreRank(list, scName, hz) { const w = (W()[scName] || {})[hz]; if (!store.get('weights', null)) return list; return list.map(r => ({ ...r, score: recombine(r.components, w) })).sort((a, b) => (b.score ?? -1) - (a.score ?? -1)); }

/* ---------------- shell: router, search, freshness ---------------- */
const ROUTES = {};
const page = (html) => { $('#app').innerHTML = html; };
async function route() {
  const h = location.hash.replace(/^#\/?/, '') || 'executive'; const [r, ...rest] = h.split('/'); const arg = decodeURIComponent(rest.join('/'));
  $$('nav a').forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#/' + r));
  page('<p class="muted">Loading…</p>');
  try { await (ROUTES[r] || ROUTES.executive)(arg); } catch (e) { console.error(e); page(`<div class="card"><h2>Could not load this view</h2><p class="na">${esc(e.message)}</p><p class="muted">Data files are built by the scheduled pipeline. If this persists, the last build failed; see Data quality.</p></div>`); }
  window.scrollTo(0, 0);
}
function freshBar() {
  const f = META.freshness, names = { listed_equity: 'Listed equity', private_markets: 'Private markets', strategic_fdi: 'FDI', corporate: 'Corporate', credit: 'Credit', policy: 'Policy', global: 'Global', valuation: 'Valuation', paid: 'Paid sources' };
  $('#fresh').innerHTML = `<span>Built ${esc(META.generated.slice(0, 16).replace('T', ' '))} IST</span>` + Object.entries(f).filter(([c]) => c !== 'paid').map(([c, v]) =>
    `<span class="${v.stale_sources.length ? 'stale' : ''}" title="${v.working}/${v.total} sources working${v.stale_sources.length ? '; stale: ' + v.stale_sources.join(', ') : ''}">${esc(names[c] || c)}: ${v.last_success ? esc(v.last_success.slice(0, 10)) : 'never'}${v.stale_sources.length ? ' ⚠ stale' : ''}</span>`).join('');
}
let SRCH = null;
async function initSearch() {
  const inp = $('#q'), box = $('#qres');
  inp.addEventListener('input', async () => {
    const q = inp.value.trim().toLowerCase(); if (q.length < 2) { box.hidden = true; return; }
    SRCH = SRCH || await J('search.json');
    const toks = q.split(/\s+/); const hits = SRCH.filter(r => toks.every(t => (r[2] + ' ' + r[1]).toLowerCase().includes(t))).slice(0, 30);
    const href = r => ({ industry: '#/sectors/' + r[1], sub: '#/sectors/sub:' + r[1], company: '#/companies/' + r[1].split(':').pop(), investor: '#/investors/' + r[1], transaction: '#/companies/tx:' + r[1], source: '#/sources/' + r[1] }[r[0]]);
    box.innerHTML = hits.length ? hits.map(r => `<a href="${href(r)}"><span class="chip">${r[0]}</span> ${esc(r[2])}</a>`).join('') : '<div class="na" style="padding:8px">No match</div>';
    box.hidden = false;
  });
  box.addEventListener('click', () => { box.hidden = true; inp.value = ''; });
  document.addEventListener('click', e => { if (!box.contains(e.target) && e.target !== inp) box.hidden = true; });
}
const hz = () => $('#hz').value;

/* ---------------- period helpers ---------------- */
function periodWindow(p, from, to) {
  const t = new Date(); const iso = d => d.toISOString().slice(0, 10); const today = iso(t);
  const back = n => { const d = new Date(t); d.setDate(d.getDate() - n); return iso(d); };
  const fyStart = (t.getMonth() >= 3 ? t.getFullYear() : t.getFullYear() - 1) + '-04-01';
  return ({ daily: [back(1), today], weekly: [back(7), today], monthly: [back(31), today], quarterly: [back(92), today], fy: [fyStart, today], cy: [t.getFullYear() + '-01-01', today], '12m': [back(365), today], custom: [from || back(90), to || today] })[p] || [back(92), today];
}
const inW = (d, w) => d && d >= w[0] && d <= w[1];
const sumW = (ser, w) => { const xs = (ser || []).filter(p => inW(p[0], w)); return xs.length ? { v: xs.reduce((a, p) => a + (p[1] || 0), 0), n: xs.length, from: xs[0][0], to: xs[xs.length - 1][0] } : null; };
const monthly = ser => { const m = {}; (ser || []).forEach(([d, v]) => { const k = d.slice(0, 7); m[k] = (m[k] || 0) + (v || 0); }); return Object.entries(m).sort(); };

/* ---------------- EXECUTIVE ---------------- */
ROUTES.executive = async () => {
  const [x, hzd] = await Promise.all([J('executive.json'), J('horizons.json')]);
  const per = store.get('period', 'quarterly'), cf = store.get('pfrom', ''), ct = store.get('pto', '');
  const w = periodWindow(per, cf, ct);
  const fpiS = Object.fromEntries(Object.entries(x.fpi_sector).map(([s, ser]) => [s, sumW(ser, w)]));
  const fpiT = sumW(x.fpi_total, w), fii = sumW(x.fii, w), dii = sumW(x.dii, w), mfE = sumW(x.mf_equity, w), deals = sumW(x.inst_deals, w);
  // AIF deployments: change in cumulative investments over quarters inside window (all categories total)
  const aifTot = x.aif.aif_grand_total || {}; const aq = Object.keys(aifTot).sort();
  const aifD = (() => { const inq = aq.filter(q => inW(q, w)); if (!inq.length) return null; const i0 = aq.indexOf(inq[0]); if (i0 < 1) return null; const last = aifTot[inq[inq.length - 1]], base = aifTot[aq[i0 - 1]]; return { inv: last.investments - base.investments, comm: last.commitments - base.commitments, raised: last.funds - base.funds, from: aq[i0 - 1], to: inq[inq.length - 1] }; })();
  const streams = [['FPI net equity (NSDL)', fpiT], ['Mutual fund net inflow, active equity (AMFI)', mfE], ['AIF new investments (SEBI, Δ cumulative)', aifD ? { v: aifD.inv, from: aifD.from, to: aifD.to } : null]];
  const have = streams.filter(s => s[1]); const totDep = have.length === streams.length ? have.reduce((a, s) => a + s[1].v, 0) : null;
  const ev = x.events.filter(e => inW(e.d, w));
  const commW = x.commitments.filter(c => inW(c.period, w) && String(c.id).startsWith('pibc_'));
  const annAmt = ev.filter(e => ['capital_commitment', 'announced_investment', 'corporate_capex', 'acquisition'].includes(e.type) && isNum(e.a));
  const commTot = commW.filter(c => isNum(c.a)).reduce((a, c) => a + c.a, 0) + annAmt.reduce((a, e) => a + e.a, 0);
  const secRank = Object.entries(fpiS).filter(([, v]) => v).sort((a, b) => b[1].v - a[1].v);
  const posSec = secRank.filter(s => s[1].v > 0).length;
  const bigD = x.big_deals.filter(d => inW(d.d, w) && d.side === 'BUY');
  const actInv = new Set(x.big_deals.filter(d => inW(d.d, w)).map(d => d.g));
  const acq = ev.filter(e => e.type === 'acquisition').sort((a, b) => (b.a || -1) - (a.a || -1));
  const pl = { daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly', quarterly: 'Quarterly', fy: 'Financial year to date', cy: 'Calendar year to date', '12m': 'Last 12 months', custom: 'Custom' };
  const k = (t, v, s, l) => `<div class="kpi"><div class="kt">${t}</div><div class="kv">${v}</div><div class="ks">${s || ''}</div>${l ? lab(l) : ''}</div>`;
  const rng = s => s ? `${s.from} → ${s.to}` : 'no data in window';
  const tabs = ['Listed equity', 'PE / VC / AIF', 'Strategic / FDI', 'Corporate capex', 'Infra & real assets', 'Debt & credit'];
  const st = store.get('stream', 0);
  page(`<h1>Executive overview</h1>
  <div class="card noprint flt"><b>Period</b> ${Object.entries(pl).map(([kk, v]) => `<button class="${kk === per ? 'on' : ''}" onclick="setPer('${kk}')">${v}</button>`).join('')}
   <span ${per === 'custom' ? '' : 'hidden'}><input type="date" id="pf" value="${esc(cf)}"> to <input type="date" id="pt" value="${esc(ct)}"> <button onclick="setPer('custom',1)">Apply</button></span>
   <span class="muted small">Window ${w[0]} to ${w[1]}. Each source reports on its own cycle (NSDL fortnightly, AMFI monthly, SEBI quarterly); only periods that end inside the window count, so a short window may show insufficient data.</span></div>
  <div class="kpis">
   ${k('1 · Verified capital deployed', totDep != null ? crp(totDep) : NA, 'Sum of three non-overlapping disclosed streams: ' + streams.map(s => `${s[0]} ${s[1] ? crp(s[1].v) : 'n/a'}`).join('; ') + '. Excludes credit and announcements.', 'VERIFIED FACT')}
   ${k('2 · Announced commitments', commW.length + annAmt.length ? crp(commTot) : NA, `${commW.length} Cabinet approvals with stated outlay, ${annAmt.length} company filings with a stated amount. Not added to deployments.${aifD ? ' AIF new commitments ' + crp(aifD.comm) + ' (separate).' : ''}`, 'REPORTED ANNOUNCEMENT')}
   ${k('3 · Transactions recorded', inr(ev.length + (deals ? deals.n : 0)) || '0', `${ev.length} filings/approvals; institutional bulk/block deal days ${deals ? deals.n : 0}`, 'VERIFIED FACT')}
   ${k('4 · Active institutional investors', actInv.size || NA, 'Distinct parent groups in large non-trading bulk/block deals in the window (top deals list; shareholding changes on the Investors page).', 'VERIFIED FACT')}
   ${k('5 · Sectors with FPI net inflow', secRank.length ? `${posSec} of ${secRank.length}` : NA, 'NSDL sector data, fortnights inside the window', 'VERIFIED FACT')}
   ${k('FPI net (NSDL)', fpiT ? cr(fpiT.v) : NA, rng(fpiT), 'VERIFIED FACT')}
   ${k('FII / DII cash (NSE, provisional)', fii || dii ? `${fii ? cr(fii.v) : NA} / ${dii ? cr(dii.v) : NA}` : NA, fii ? `${fii.n} trading days; history starts ${x.fii[0] ? x.fii[0][0] : 'n/a'}` : 'NSE publishes only the latest day; history builds daily from the pipeline start', 'VERIFIED FACT')}
   ${k('MF net inflow, active equity (AMFI)', mfE ? cr(mfE.v) : NA, rng(mfE), 'VERIFIED FACT')}
  </div>
  <div class="g2">
   <div class="card"><h3>6 · Largest sector inflows (FPI, window)</h3>${secRank.length ? '<table>' + secRank.slice(0, 6).map(([s, v]) => `<tr><td>${secLink(s)}</td><td class="n">${cr(v.v)}</td></tr>`).join('') + '</table>' : NA}<div class="src">${srcId('nsdl_fpi_sector')}</div></div>
   <div class="card"><h3>7 · Largest sector outflows (FPI, window)</h3>${secRank.length ? '<table>' + secRank.slice(-6).reverse().map(([s, v]) => `<tr><td>${secLink(s)}</td><td class="n">${cr(v.v)}</td></tr>`).join('') + '</table>' : NA}<div class="src">${srcId('nsdl_fpi_sector')}</div></div>
   <div class="card"><h3>8 · Themes in recent filings and approvals (120 days)</h3>${x.themes.length ? '<table>' + x.themes.map(t => `<tr><td>${esc(t.theme)}</td><td class="n">${t.n}</td></tr>`).join('') + '</table>' : NA}<div class="src">${lab('REPORTED ANNOUNCEMENT')} count of NSE filings and PIB Cabinet releases by keyword theme</div></div>
   <div class="card"><h3>9 · Acquisitions filed (window)</h3>${acq.length ? '<table>' + acq.slice(0, 8).map(e => `<tr><td>${e.d}</td><td>${coLink(e.c, e.cn)}</td><td class="n">${isNum(e.a) ? crp(e.a) : '<span class="na">undisclosed</span>'}</td><td>${srcA(e.u)}</td></tr>`).join('') + '</table>' : NA}</div>
   <div class="card"><h3>10 · Largest institutional purchases (bulk/block, 60 days)</h3>${bigD.length ? '<table>' + bigD.slice(0, 8).map(d => `<tr><td>${d.d}</td><td>${coLink(d.sym, d.sym)}</td><td>${invLink(d.g, d.gname)}</td><td class="n">${crp(d.a)}</td></tr>`).join('') + '</table>' : NA}<div class="src">${srcId('nse_deals')} · trading desks, brokers, index funds and individuals excluded</div></div>
   <div class="card"><h3>Unusual FPI sector flows (latest fortnight)</h3>${x.unusual.length ? '<table>' + x.unusual.map(u => `<tr><td>${secLink(u.industry)}</td><td class="n">${cr(u.last)}</td><td class="n">${u.z > 0 ? '+' : ''}${u.z}σ</td></tr>`).join('') + '</table>' : '<p class="muted">No sector beyond 2 standard deviations of its 3-year fortnightly history.</p>'}<div class="src">${lab('ESTIMATED VALUE')} z-score computed here from NSDL</div></div>
  </div>
  <div class="card"><div class="tabs noprint">${tabs.map((t, i) => `<button class="${i === st ? 'on' : ''}" onclick="store.set('stream',${i});route()">${t}</button>`).join('')}</div><div id="stream">${streamView(st, x, w)}</div></div>
  <div class="card"><h2>Horizon comparison</h2><div class="g3">${['1-3y', '3-10y'].map(h => `<div><h3>${h}</h3><ol>${(hzd[h].ranking || []).slice(0, 5).map(r => `<li>${secLink(r.id)} ${sc(r.score)} <span class="muted small">${esc(r.confidence)}</span></li>`).join('') || NA}</ol><div class="muted small">${esc(hzd.methods[h].question)}</div></div>`).join('')}
   <div><h3>10-20y</h3><ol>${hzd['10-20y'].themes.slice(0, 5).map(t => `<li>${esc(t.theme)} ${lab('SCENARIO')}<div class="muted small">${esc(t.status)}: ${t.supporting} supporting, ${t.contrary} contrary indicators</div></li>`).join('')}</ol></div></div>
   <p class="muted small">Ranks show capital attention: where disclosed money is moving. They are not views on returns or on any security.</p></div>`);
};
window.setPer = (p, c) => { store.set('period', p); if (c) { store.set('pfrom', $('#pf').value); store.set('pto', $('#pt').value); } route(); };
function streamView(i, x, w) {
  const fm = monthly(x.fpi_total).slice(-60);
  if (i === 0) return `<div class="g2"><div><h3>FPI net equity, monthly (₹ cr)</h3>${bars(fm, { cap: srcId('nsdl_fpi_sector') })}</div>
     <div><h3>MF net inflows, monthly (₹ cr)</h3>${lines([{ name: 'Active equity', pts: x.mf_equity }, { name: 'Index funds + ETFs (passive)', pts: x.mf_passive }], { zero: 1, cap: srcId('amfi_monthly') })}</div>
     <div><h3>FII / DII provisional cash, daily (₹ cr)</h3>${lines([{ name: 'FII/FPI', pts: x.fii }, { name: 'DII', pts: x.dii }], { zero: 1, cap: srcId('nse_fiidii') + ' · history accumulates from pipeline start' })}</div>
     <div><h3>Institutional net bulk/block deals, daily (₹ cr)</h3>${bars(x.inst_deals.slice(-120), { cap: srcId('nse_deals') + ' · non-trading, non-passive groups' })}</div></div>`;
  if (i === 1) { const cats = Object.keys(x.aif).filter(k => k !== 'aif_grand_total'); const tot = x.aif.aif_grand_total || {}; const q = Object.keys(tot).sort();
    return `<p>${lab('VERIFIED FACT')} SEBI publishes cumulative AIF commitments, funds raised and investments each quarter. Commitments (promises) and investments (deployed) are separate lines and never added.</p>
     ${lines([{ name: 'Commitments (cumulative)', pts: q.map(k => [k, tot[k].commitments]) }, { name: 'Funds raised', pts: q.map(k => [k, tot[k].funds]) }, { name: 'Investments made', pts: q.map(k => [k, tot[k].investments]) }], { cap: srcId('sebi_aif') })}
     ${tbl([{ h: 'Category', v: r => r[0].replace('aif_', '').replace(/_/g, ' ') }, { h: 'Quarter', v: r => r[1] }, { h: 'Commitments ₹ cr', n: 1, v: r => r[2].commitments, f: r => crp(r[2].commitments) }, { h: 'Raised ₹ cr', n: 1, v: r => r[2].funds, f: r => crp(r[2].funds) }, { h: 'Invested ₹ cr', n: 1, v: r => r[2].investments, f: r => crp(r[2].investments) }],
       cats.map(c => { const qs = Object.keys(x.aif[c]).sort(); const l = qs[qs.length - 1]; return [c, l, x.aif[c][l]]; }), { file: 'aif_categories' })}
     <p class="muted small">PE/VC deal-level data (rounds, investors, valuations) needs paid databases: ${srcId('tracxn')}, ${srcId('venture_intelligence')}, ${srcId('vccedge')}. Not connected.</p>`; }
  if (i === 2) return `<h3>FDI net inflows, India (US$, World Bank)</h3>${bars(x.wb_fdi.map(([y, v]) => [y, v / 1e9]), { pos: 0, cap: srcId('worldbank') + ' · US$ billion · annual' })}
     <p class="muted small">Sector-level FDI (DPIIT factsheets) is ${META.sources.find(s => s.source_id === 'dpiit_fdi')?.status || 'unavailable'}: dpiit.gov.in refuses automated access. Strategic M&A appears under Corporate capex when filed with NSE.</p>`;
  if (i === 3) { const ev = x.events.filter(e => ['corporate_capex', 'acquisition', 'joint_venture', 'merger', 'divestment', 'primary_issuance', 'capital_raised'].includes(e.type));
    return tbl([{ h: 'Date', v: r => r.d }, { h: 'Type', v: r => r.type.replace(/_/g, ' ') }, { h: 'Company', v: r => r.cn, f: r => coLink(r.c, r.cn) }, { h: 'Sector', v: r => ind(r.s), f: r => secLink(r.s) }, { h: 'Stated ₹ cr', n: 1, v: r => r.a, f: r => isNum(r.a) ? crp(r.a) : '<span class="na">undisclosed</span>' }, { h: 'Label', v: r => r.l, f: r => lab(r.l) }, { h: 'Filing', v: r => r.u, f: r => srcA(r.u, 'NSE') }], ev, { file: 'corporate_events', max: 300, note: 'amount only when exactly one amount appears in the filing summary' }); }
  if (i === 4) { const tot = x.aif.aif_grand_total || {}; const infra = Object.entries(x.aif).filter(([kk]) => /cat_i_infra|infrastructure/.test(kk));
    return `<div class="g2"><div><h3>Bank credit to infrastructure, YoY %</h3>${lines([{ name: 'Infrastructure (RBI SIBC code 2.18)', pts: x.infra_credit.map(r => [r.d, r.v]) }], { zero: 1, cap: srcId('rbi_sibc') })}</div>
     <div><h3>Cabinet approvals (PIB)</h3>${tbl([{ h: 'Date', v: r => r.period }, { h: 'Scope', v: r => r.scope }, { h: 'Outlay ₹ cr', n: 1, v: r => r.a, f: r => isNum(r.a) ? crp(r.a) : '<span class="na">not stated</span>' }, { h: '', v: r => r.u, f: r => srcA(r.u, 'PIB') }], x.commitments.filter(c => String(c.id).startsWith('pibc_')), { file: 'cabinet_approvals', max: 50 })}</div></div>
     <p class="muted small">${infra.length ? '' : 'AIF infrastructure category split: see PE / VC / AIF tab. '}InvITs/REITs fundraising (SEBI) is not ingested in v1.</p>`; }
  const tot = x.sibc_total;
  return `<h3>Non-food bank credit outstanding by broad sector (₹ cr)</h3>${lines(['sibc_1', 'sibc_2', 'sibc_3', 'sibc_4'].map((e, k) => ({ name: ['Agriculture', 'Industry', 'Services', 'Personal loans'][k], pts: tot.filter(r => r.entity_id === e).map(r => [r.period_end, r.value]) })), { cap: srcId('rbi_sibc') + ' · outstanding stock, not new sanctions' })}
    <p><a href="#/credit">Full credit view →</a></p>`;
}

/* ---------------- component table (score transparency) ---------------- */
function compTable(c, scName, hzn) {
  if (!c) return NA; const w = (W()[scName] || {})[hzn] || {};
  return `<table class="small"><tr><th>Component</th><th class="n">Raw value</th><th class="n">Rank 0-100</th><th class="n">Weight</th></tr>` + c.components.map(x =>
    `<tr><td>${esc(x.name.replace(/_/g, ' '))}</td><td class="n">${x.raw == null ? NA : esc(typeof x.raw === 'number' ? +x.raw.toFixed(2) : x.raw)}</td><td class="n">${isNum(x.score) ? x.score.toFixed(0) : NA}</td><td class="n">${w[x.name] ?? x.weight}</td></tr>`).join('') +
    `</table>${c.not_assessed && c.not_assessed.length ? `<div class="muted small">Not assessed (no free structured source): ${esc(c.not_assessed.join(', '))}</div>` : ''}`;
}

/* ---------------- THREE HORIZONS ---------------- */
ROUTES.horizons = async (arg) => {
  const h = await J('horizons.json'); const cur = arg || store.get('hztab', hz()); store.set('hztab', cur);
  const m = h.methods[cur];
  const head = `<h1>Three-horizon analysis</h1><div class="tabs">${['1-3y', '3-10y', '10-20y'].map(x => `<a class="btn ${x === cur ? 'on' : ''}" href="#/horizons/${x}">${{ '1-3y': '1-3 years', '3-10y': '3-10 years', '10-20y': '10-20 years' }[x]}</a>`).join('')}</div>
   <div class="card method"><b>${esc(m.question)}</b><p>${esc(m.method)}</p><p class="muted small">Not used: ${esc(m.not_used)}</p></div>`;
  const rk = (list, scName) => tbl([{ h: '#', n: 1, v: r => r._i }, { h: 'Sector', v: r => r.name, f: r => secLink(r.id) }, { h: 'Score', n: 1, v: r => r.score, f: r => sc(r.score) + bar(r.score) }, { h: 'Confidence', v: r => r.confidence },
    { h: 'Main drivers', v: r => r.why.join('; '), f: r => `<span class="small">${esc(r.why.join('; '))}</span>` }, { h: 'Flags', v: r => r.flags.join('; '), f: r => `<span class="small muted">${esc(r.flags.join('; '))}</span>` },
    { h: 'Detail', v: () => '', f: r => `<details><summary>components</summary>${compTable(r, scName, cur)}</details>` }], rescoreRank(list, scName, cur).map((r, i) => ({ ...r, _i: i + 1 })), { file: 'ranking_' + cur });
  if (cur === '1-3y') { const x = h['1-3y'];
    const amfiCats = Object.entries(x.amfi).map(([k, v]) => ({ k, last: v[v.length - 1], sum: v.slice(-12).reduce((a, p) => a + (p[1] || 0), 0) })).filter(r => !/grand_total/.test(r.k)).sort((a, b) => b.sum - a.sum);
    const cos = await J('companies.json'); const cm = Object.fromEntries(cos.rows.map(r => [r[0], r]));
    page(head + `<div class="card"><h2>Capital attention ranking, 1-3 years</h2>${rk(x.ranking, 'capital_flow')}</div>
     <div class="g2"><div class="card"><h3>FPI net equity, last 24 months (₹ cr)</h3>${bars(monthly(x.fpi_total).slice(-24), { cap: srcId('nsdl_fpi_sector') })}</div>
      <div class="card"><h3>Sector rotation: domestic vs foreign institutions (median company, pp QoQ)</h3>${tbl([{ h: 'Sector', v: r => r.name, f: r => secLink(r.id) }, { h: 'Domestic', n: 1, v: r => r.domestic, f: r => pp(r.domestic, 3) }, { h: 'Foreign', n: 1, v: r => r.foreign, f: r => pp(r.foreign, 3) }, { h: 'FPI 3m ₹ cr', n: 1, v: r => r.fpi_3m, f: r => cr(r.fpi_3m) }], x.rotation, { file: 'rotation' })}<div class="src">${srcId('nse_shp')} · ${srcId('nsdl_fpi_sector')}</div></div>
      <div class="card"><h3>Companies with the largest institutional stake increase (latest quarter)</h3>${tbl([{ h: 'Company', v: r => cm[r]?.[2], f: r => coLink(r, cm[r]?.[2]) }, { h: 'Sector', v: r => ind(cm[r]?.[3]) }, { h: 'Inst. Δ pp', n: 1, v: r => cm[r]?.[7], f: r => pp(cm[r]?.[7]) }], x.accumulation, { file: 'accumulation' })}<div class="src">${srcId('nse_shp')} ${lab('VERIFIED FACT')}</div></div>
      <div class="card"><h3>New above-1% institutional holders (latest quarter)</h3>${tbl([{ h: 'Company', v: r => r.name, f: r => coLink(r.company, r.name) }, { h: 'New groups', v: r => r.groups.join(', ') }], x.new_entries, { file: 'new_entries' })}<div class="src">${srcId('nse_shp')}</div></div>
      <div class="card"><h3>MF flows by category, last 12 months (₹ cr)</h3>${tbl([{ h: 'Category', v: r => r.k.replace(/^amfi_/, '').replace(/_/g, ' ') }, { h: '12m net', n: 1, v: r => r.sum, f: r => cr(r.sum) }, { h: 'Latest month', v: r => r.last?.[0] }, { h: 'Latest ₹ cr', n: 1, v: r => r.last?.[1], f: r => cr(r.last?.[1]) }], amfiCats, { file: 'amfi_categories' })}<div class="src">${srcId('amfi_monthly')}</div></div>
      <div class="card"><h3>Largest institutional bulk/block deals (60 days)</h3>${tbl([{ h: 'Date', v: r => r.d }, { h: 'Company', v: r => r.sym, f: r => coLink(r.sym, r.sym) }, { h: 'Group', v: r => r.gname, f: r => invLink(r.g, r.gname) }, { h: 'Side', v: r => r.side }, { h: '₹ cr', n: 1, v: r => r.a, f: r => crp(r.a) }], x.deals, { file: 'deals' })}<div class="src">${srcId('nse_deals')}</div></div></div>`);
  } else if (cur === '3-10y') { const x = h['3-10y'];
    page(head + `<div class="card"><h2>Long-duration capital ranking, 3-10 years</h2>${rk(x.ranking, 'capital_flow')}</div>
     <div class="card"><h2>Industry evidence (credit, ratings, policy, private capital)</h2>${rk(x.industry_evidence, 'industry_evidence')}</div>
     <div class="g2"><div class="card"><h3>Bank credit growth by industry, YoY % (${esc(META.sibc_last || '')})</h3>${tbl([{ h: 'RBI code', v: r => r.code }, { h: 'Industry', v: r => r.name }, { h: 'YoY %', n: 1, v: r => r.yoy, f: r => pc(r.yoy) }, { h: 'Outstanding ₹ cr', n: 1, v: r => r.outstanding, f: r => crp(r.outstanding) }], x.credit, { file: 'credit_yoy', max: 80 })}<div class="src">${srcId('rbi_sibc')}</div></div>
      <div class="card"><h3>Manufacturing share of GDP, % (World Bank)</h3>${lines(Object.entries(x.manufacturing).map(([c, v]) => ({ name: c, pts: v.map(r => [r.period_end.slice(0, 4), r.value]) })), { cap: srcId('worldbank') })}
       <h3>FDI net inflows, US$ bn (supply-chain context)</h3>${lines(Object.entries(x.supply_chain).map(([c, v]) => ({ name: c, pts: v.filter(r => r.period_end >= '2005').map(r => [r.period_end.slice(0, 4), r.value / 1e9]) })), { zero: 1, cap: srcId('worldbank') })}</div>
      <div class="card"><h3>Capital events filed (acquisitions, capex, JVs)</h3>${tbl([{ h: 'Date', v: r => r.d }, { h: 'Type', v: r => r.type.replace(/_/g, ' ') }, { h: 'Company', v: r => r.cn, f: r => coLink(r.c, r.cn) }, { h: 'Stated ₹ cr', n: 1, v: r => r.a, f: r => isNum(r.a) ? crp(r.a) : '<span class="na">undisclosed</span>' }, { h: '', v: r => r.u, f: r => srcA(r.u, 'NSE') + ' ' + lab(r.l) }], x.capital_events, { file: 'capital_events' })}</div>
      <div class="card"><h3>Long-term forecasts</h3><p class="na">${esc(x.forecast_note)}</p></div></div>`);
  } else { const x = h['10-20y']; const WBN = { 'SP.POP.1564.TO.ZS': 'Working-age population, % of total', 'SP.POP.65UP.TO.ZS': 'Population 65+, %', 'SP.URB.TOTL.IN.ZS': 'Urban population, %', 'EG.FEC.RNEW.ZS': 'Renewable energy, % of final consumption', 'GB.XPD.RSDV.GD.ZS': 'R&D spend, % of GDP', 'IT.NET.USER.ZS': 'Internet users, %', 'NV.IND.MANF.ZS': 'Manufacturing, % of GDP', 'NE.GDI.TOTL.ZS': 'Gross capital formation, % of GDP', 'SP.DYN.TFRT.IN': 'Fertility rate', 'ER.H2O.FWST.ZS': 'Freshwater withdrawal, % of resources' };
    page(head + `<div class="card warn"><b>Evidence and labelled scenarios only.</b> No forecasts, market sizes or company names. Each theme is a ${lab('SCENARIO')} with conditions that would confirm or invalidate it; the evidence list is pulled from official data on every build.</div>
     ${x.themes.map(t => `<div class="card"><h3>${esc(t.theme)} ${lab('SCENARIO')} <span class="chip">${esc(t.status)}</span></h3><p>${esc(t.scenario)}</p>
      <div class="g2"><div><b>Would confirm:</b> ${esc(t.confirm)}</div><div><b>Would invalidate:</b> ${esc(t.invalidate)}</div></div><p class="small muted">Industries: ${esc(t.industries.join(', '))}</p>
      <table class="small"><tr><th>Evidence</th><th>Value</th><th>Direction</th><th>Label / source</th></tr>${t.evidence.map(e => `<tr><td>${esc(e.label)}${e.items ? `<details><summary>${e.items.length} items</summary>${e.items.map(i => `<div>${esc(i.d)} ${esc((i.x || '').slice(0, 140))} ${srcA(i.u)}</div>`).join('')}</details>` : ''}</td><td class="n">${e.from ? `${e.from[0]}: ${(+e.from[1]).toFixed(1)} → ${e.to[0]}: ${(+e.to[1]).toFixed(1)}` : esc(e.value)}</td><td class="${e.direction === 'up' ? 'pos' : 'neg'}">${e.direction}</td><td>${lab(e.evidence_label)} ${esc(e.source)}</td></tr>`).join('') || `<tr><td colspan=4 class="na">insufficient data</td></tr>`}</table></div>`).join('')}
     <div class="card"><h2>Structural indicators, India (World Bank)</h2><div class="g3">${Object.entries(x.wb).map(([k, v]) => `<div><h4>${esc(WBN[k] || k)}</h4>${lines([{ name: 'India', pts: v.filter(r => r.value != null).map(r => [r.period_end.slice(0, 4), r.value]) }], { h: 120 })}</div>`).join('')}</div><div class="src">${srcId('worldbank')} ${lab('VERIFIED FACT')}</div></div>
     <div class="card"><h3>Working-age share, India vs peers</h3>${lines(Object.entries(x.demography_compare).map(([c, v]) => ({ name: c, pts: v.filter(r => r.value != null).map(r => [r.period_end.slice(0, 4), r.value]) })), { cap: srcId('worldbank') })}</div>`);
  }
};

/* ---------------- SECTORS ---------------- */
ROUTES.sectors = async (arg) => {
  const S = await J('sectors.json'); const h = hz();
  if (arg && arg.startsWith('sub:')) return subView(S, arg.slice(4));
  if (arg) return sectorView(S, arg);
  const cols = [['fpi_flow_3m', 'FPI 3m % of holdings'], ['fpi_flow_12m', 'FPI 12m %'], ['inst_share_change_qoq', 'Inst. Δ QoQ pp'], ['inst_breadth_qoq', 'Breadth %'], ['bank_credit_yoy', 'Credit YoY %'], ['aif_sector_growth_yoy', 'AIF growth %'], ['corporate_capital_events_180d', 'Capital events 180d'], ['pe_percentile_10y', 'P/E pctl 10y']];
  const pr = {}; cols.forEach(([k]) => { const xs = S.sectors.map(s => s.metrics[k]).filter(isNum).sort((a, b) => a - b); pr[k] = v => isNum(v) && xs.length > 2 ? xs.filter(x => x < v).length / (xs.length - 1) * 100 : null; });
  const hzKey = h === '10-20y' ? '3-10y' : h;
  const rows = S.sectors.map(s => ({ ...s, cf: s.scores ? recombineIf(s.scores.capital_flow?.[hzKey], 'capital_flow', hzKey) : null, ie: s.scores ? recombineIf(s.scores.industry_evidence?.[hzKey], 'industry_evidence', hzKey) : null }));
  page(`<h1>Sector capital map</h1><p class="muted">Each cell is the sector's raw value; colour is its rank among sectors (green higher, red lower; P/E colour shows richness, not quality). Click a sector to drill into sub-industries and companies. Horizon: <b>${esc(hzKey)}</b> (header selector).</p>
   <div class="card">${tbl([{ h: 'Sector', v: r => r.name, f: r => secLink(r.id) }, { h: 'Capital attention', n: 1, v: r => r.cf, f: r => sc(r.cf) }, { h: 'Industry evidence', n: 1, v: r => r.ie, f: r => sc(r.ie) },
     ...cols.map(([k, t]) => ({ h: t, n: 1, v: r => r.metrics[k], f: r => `<span class="cell" style="background:${heat(pr[k](r.metrics[k]))}">${isNum(r.metrics[k]) ? (+r.metrics[k]).toFixed(k === 'inst_share_change_qoq' ? 2 : 1) : '<span class="na">n/a</span>'}</span>` })),
     { h: 'FPI 12m ₹ cr', n: 1, v: r => r.fpi?.net_12m, f: r => cr(r.fpi?.net_12m) }, { h: 'Companies', n: 1, v: r => r.companies }], rows, { file: 'sector_map', note: 'n/a = insufficient data' })}
   <div class="src">${['nsdl_fpi_sector', 'nse_shp', 'rbi_sibc', 'sebi_aif', 'nse_announcements', 'nse_sector_pe'].map(srcId).join(' · ')}</div><p class="muted small">${esc(S.legacy_note)}</p></div>`);
};
function recombineIf(c, scName, hzn) { if (!c) return null; return store.get('weights', null) ? recombine(c.components, (W()[scName] || {})[hzn]) : c.score; }
async function sectorView(S, id) {
  const s = S.sectors.find(x => x.id === id); if (!s) return page(`<p class="na">Unknown sector ${esc(id)}</p>`);
  const cos = await J('companies.json'); const cm = Object.fromEntries(cos.rows.map(r => [r[0], r]));
  const f = s.fpi || {}, m = s.metrics; const h = hz() === '10-20y' ? '3-10y' : hz();
  const watch = store.get('watch', []); const watching = watch.some(w => w.type === 'industry' && w.id === id);
  const k = (t, v, src) => `<div class="kpi"><div class="kt">${t}</div><div class="kv">${v}</div><div class="ks">${src || ''}</div></div>`;
  page(`<p><a href="#/sectors">← Sector map</a></p><h1>${esc(s.name)} <button class="small noprint" onclick="toggleWatch('industry','${id}','${esc(s.name)}')">${watching ? '★ Watching' : '☆ Watch'}</button></h1>
   <div class="kpis">${k('FPI net, 3 months', cr(f.net_3m), 'NSDL, 6 fortnights')}${k('FPI net, 12 months', cr(f.net_12m), 'NSDL, 24 fortnights')}${k('FPI holdings', crp(f.auc), esc(f.auc_date || ''))}${k('FPI positive months (36)', f.months_36 ? `${f.pos_months_36}/${f.months_36}` : NA)}
    ${k('Bank credit YoY', pc(m.bank_credit_yoy), 'RBI SIBC ' + esc(META.sibc_last || ''))}${k('Inst. stake Δ QoQ (median)', pp(m.inst_share_change_qoq, 3), META.q_cur ? 'to ' + META.q_cur : '')}${k('AIF investment growth', pc(m.aif_sector_growth_yoy), 'SEBI, ~1 year')}${k('Valuation context', s.pe ? `${s.pe.pe.toFixed(1)}× <span class="small">(${s.pe.pctl_10y.toFixed(0)}th pctl)</span>` : NA, s.pe ? esc(s.pe.name) + ' · ' + esc(s.pe.as_of) : '')}
    ${k('Competitive intensity', NA, 'no free structured source')}</div>
   <div class="g2"><div class="card"><h3>FPI net equity flow, monthly (₹ cr)</h3>${bars(s.fpi_monthly.slice(-120), { cap: srcId('nsdl_fpi_sector') + ' · pre-Apr 2022 mapped from older NSDL sectors' })}</div>
    <div class="card"><h3>Scores</h3>${s.scores ? Object.entries(s.scores).map(([n, v]) => `<details><summary>${esc(n.replace(/_/g, ' '))}: ${sc(recombineIf(v[h], n, h))} <span class="muted small">${esc(v[h]?.confidence || '')}</span></summary>${compTable(v[h], n, h)}</details>`).join('') : '<p class="na">Not scored (cross-sector or credit-only category)</p>'}
     <h3>Risks and flags</h3>${s.risks.length ? '<ul>' + s.risks.map(r => `<li>${esc(r)}</li>`).join('') + '</ul>' : '<p class="muted">No rule-based flag triggered.</p>'}</div>
    <div class="card"><h3>Sub-industries</h3>${tbl([{ h: 'Sub-industry', v: r => r.name, f: r => `<a href="#/sectors/sub:${esc(r.id)}">${esc(r.name)}</a>` }, { h: 'Companies', n: 1, v: r => r.companies.length }], s.subs, { file: id + '_subs' })}</div>
    <div class="card"><h3>Bank credit by RBI industry code</h3>${tbl([{ h: 'Code', v: r => r.code }, { h: 'Name', v: r => r.name }, { h: 'Outstanding ₹ cr', n: 1, v: r => r.outstanding, f: r => crp(r.outstanding) }, { h: 'YoY %', n: 1, v: r => r.yoy, f: r => pc(r.yoy) }, { h: 'FYTD %', n: 1, v: r => r.fy, f: r => pc(r.fy) }], s.credit, { file: id + '_credit', empty: 'No RBI SIBC code maps to this sector' })}<div class="src">${srcId('rbi_sibc')}</div></div>
    <div class="card"><h3>Major institutional groups (above-1% holders, ${esc(META.q_cur || '')})</h3>${tbl([{ h: 'Group', v: r => r.name, f: r => invLink(r.group, r.name) }, { h: 'Companies held', n: 1, v: r => r.companies }, { h: 'New this quarter', n: 1, v: r => r.new }], s.major_investors, { file: id + '_investors' })}<div class="src">${srcId('nse_shp')}</div></div>
    <div class="card"><h3>Institutional stake: largest rises and falls</h3><div class="g2"><div><b>Rising</b>${s.top_attention.map(c => `<div>${coLink(c, cm[c]?.[2])} ${pp(cm[c]?.[7])}</div>`).join('') || NA}</div><div><b>Falling (withdrawal)</b>${s.withdrawal.map(c => `<div>${coLink(c, cm[c]?.[2])} ${pp(cm[c]?.[7])}</div>`).join('') || NA}</div></div></div>
    <div class="card"><h3>Largest transactions</h3>${tbl([{ h: 'Date', v: r => r.d }, { h: 'Type', v: r => r.type.replace(/_/g, ' ') }, { h: 'Company', v: r => r.sym, f: r => coLink(r.sym, r.sym) }, { h: 'Investor', v: r => r.inv }, { h: 'Side', v: r => r.side }, { h: '₹ cr', n: 1, v: r => r.a, f: r => isNum(r.a) ? crp(r.a) : '<span class="na">undisclosed</span>' }, { h: '', v: r => r.l, f: r => lab(r.l) + ' ' + srcA(r.u) }], s.transactions, { file: id + '_transactions' })}</div>
    <div class="card"><h3>Capacity and capital events</h3>${tbl([{ h: 'Date', v: r => r.d }, { h: 'Type', v: r => r.type.replace(/_/g, ' ') }, { h: 'Company', v: r => r.sym, f: r => coLink(r.sym, r.sym) }, { h: 'Summary', v: r => r.x, f: r => `<span class="small">${esc(r.x)}</span>` }, { h: '₹ cr', n: 1, v: r => r.a, f: r => isNum(r.a) ? crp(r.a) : '<span class="na">undisclosed</span>' }, { h: '', v: r => r.u, f: r => srcA(r.u, 'NSE') }], s.capacity_events, { file: id + '_capacity' })}</div>
    <div class="card"><h3>Credit ratings (CRISIL, 12 months)</h3>${s.ratings ? `<p>${s.ratings.counted} counted actions: ${s.ratings.up} upgrades, ${s.ratings.down} downgrades, ${s.ratings.neg} negative; ${s.ratings.inc} moved to 'issuer not cooperating'.</p>` : NA}<div class="src">${srcId('crisil_ratings')}</div></div></div>`);
}
async function subView(S, sid) {
  const s = S.sectors.find(x => x.subs.some(u => u.id === sid)); if (!s) return page(`<p class="na">Unknown sub-industry</p>`);
  const sub = s.subs.find(u => u.id === sid); const cos = await J('companies.json'); const cm = Object.fromEntries(cos.rows.map(r => [r[0], r]));
  page(`<p><a href="#/sectors">Sector map</a> › ${secLink(s.id)}</p><h1>${esc(sub.name)}</h1>
   <div class="card">${tbl([{ h: 'Company', v: r => cm[r]?.[2], f: r => coLink(r, cm[r]?.[2]) }, { h: 'Inst. %', n: 1, v: r => cm[r]?.[6], f: r => num(cm[r]?.[6], 2) }, { h: 'Inst. Δ pp', n: 1, v: r => cm[r]?.[7], f: r => pp(cm[r]?.[7]) }, { h: 'Promoter %', n: 1, v: r => cm[r]?.[8], f: r => num(cm[r]?.[8], 2) }, { h: 'Independent >1% holders', n: 1, v: r => cm[r]?.[10] }, { h: 'New groups', n: 1, v: r => cm[r]?.[11] }, { h: 'Company evidence 1-3y', n: 1, v: r => cm[r]?.[13], f: r => sc(cm[r]?.[13]) }], sub.companies, { file: sid })}
   <div class="src">${srcId('nse_shp')} · sub-industry from NSE sector index constituents</div></div>`);
}

/* ---------------- INVESTORS ---------------- */
const CATN = { mutual_fund: 'Mutual fund', insurance: 'Insurance', pension: 'Pension', sovereign: 'Sovereign wealth', fpi: 'Foreign portfolio', private_equity: 'Private equity', dfi: 'Development finance', government: 'Government', bank: 'Bank', aif: 'AIF', individual_or_unknown: 'Individual / unknown', corporate: 'Corporate', other_institution: 'Other institution' };
ROUTES.investors = async (arg) => {
  const I = await J('investors.json'); const h = hz();
  if (arg) return investorView(I, arg);
  const cmp = store.get('cmp', []);
  const cats = [...new Set(I.groups.map(g => g.category))].filter(Boolean).sort(); const fc = store.get('invcat', '');
  const rows = I.groups.filter(g => !fc || g.category === fc).map(g => ({ ...g, act: g.scores?.[h] ? recombineIf(g.scores[h], 'investor_activity', h) : null }));
  page(`<h1>Investors</h1><p class="muted">${esc(I.rules)}</p>
   <div class="card noprint flt"><label>Category <select onchange="store.set('invcat',this.value);route()"><option value="">All</option>${cats.map(c => `<option ${c === fc ? 'selected' : ''} value="${c}">${esc(CATN[c] || c)}</option>`).join('')}</select></label>
    <span class="muted small">Tick two or more groups to compare (${cmp.length} selected) <button class="small" onclick="location.hash='#/investors/compare'">Compare</button> <button class="small" onclick="store.set('cmp',[]);route()">Clear</button></span></div>
   <div class="card"><h2>Aggregates without names</h2>${I.aggregates.map(a => `<div>${esc(a.name)}: <span class="muted">${esc(a.note)}</span></div>`).join('')}</div>
   <div class="card"><h2>Institutional groups (quarter to ${esc(I.q_cur || 'n/a')})</h2>${tbl([{ h: '', v: () => '', f: r => `<input type="checkbox" ${cmp.includes(r.id) ? 'checked' : ''} onchange="toggleCmp('${esc(r.id)}')">` }, { h: 'Group', v: r => r.name, f: r => invLink(r.id, r.name) }, { h: 'Category', v: r => CATN[r.category] || r.category }, { h: 'Country', v: r => r.country || '' },
     { h: 'Holdings >1%', n: 1, v: r => r.held }, { h: 'New', n: 1, v: r => r.new.length }, { h: 'Increased', n: 1, v: r => r.increased.length }, { h: 'Reduced', n: 1, v: r => r.decreased.length }, { h: 'Exited/<1%', n: 1, v: r => r.exited.length },
     { h: 'Net deals 90d ₹ cr', n: 1, v: r => r.deal_net_90d_cr, f: r => cr(r.deal_net_90d_cr) }, { h: 'Activity ' + h, n: 1, v: r => r.act, f: r => sc(r.act) }], rows, { file: 'investors', max: 600 })}<div class="src">${srcId('nse_shp')} · ${srcId('nse_deals')}</div></div>
   <div class="card"><h2>Convergence: companies where several independent groups are adding</h2><p class="muted small">Count of distinct parent groups that became new above-1% holders in the latest quarter or were net buyers in bulk/block deals in 90 days. Fund families counted once; trading desks, index funds, individuals and corporates excluded. Signals attention only.</p>
    ${tbl([{ h: 'Company', v: r => r.name, f: r => coLink(r.company, r.name) }, { h: 'Sector', v: r => ind(r.industry), f: r => secLink(r.industry) }, { h: 'Independent groups', n: 1, v: r => r.independent_groups }, { h: 'Via shareholding', v: r => r.via_shareholding.map(g => META.groups[g]?.name || g).join(', ') }, { h: 'Via deals', v: r => r.via_deals.map(g => META.groups[g]?.name || g).join(', ') }, { h: 'Domestic Δ pp', n: 1, v: r => r.domestic_qoq, f: r => pp(r.domestic_qoq) }, { h: 'Foreign Δ pp', n: 1, v: r => r.foreign_qoq, f: r => pp(r.foreign_qoq) }], I.convergence, { file: 'convergence' })}</div>`);
};
window.toggleCmp = id => { let c = store.get('cmp', []); c = c.includes(id) ? c.filter(x => x !== id) : c.concat(id); store.set('cmp', c); };
async function investorView(I, id) {
  if (id === 'compare') { const ids = store.get('cmp', []); const gs = I.groups.filter(g => ids.includes(g.id)); if (gs.length < 2) return page('<p><a href="#/investors">← Investors</a></p><p class="na">Select at least two groups on the Investors page.</p>');
    const allc = [...new Set(gs.flatMap(g => Object.keys(g.positions)))]; const both = allc.filter(c => gs.every(g => g.positions[c]?.[I.q_cur] != null));
    return page(`<p><a href="#/investors">← Investors</a></p><h1>Compare: ${gs.map(g => esc(g.name)).join(' vs ')}</h1>
     <div class="card">${tbl([{ h: 'Metric', v: r => r[0] }, ...gs.map((g, i) => ({ h: g.name, v: r => r[i + 1] }))], [['Holdings >1%', ...gs.map(g => g.held)], ['New', ...gs.map(g => g.new.length)], ['Increased', ...gs.map(g => g.increased.length)], ['Reduced', ...gs.map(g => g.decreased.length)], ['Exited', ...gs.map(g => g.exited.length)], ['Net deals 90d ₹ cr', ...gs.map(g => g.deal_net_90d_cr)], ['Avg quarters held', ...gs.map(g => g.persistence_q)], ['Top sectors', ...gs.map(g => Object.keys(g.sectors).slice(0, 3).map(ind).join(', '))]], { file: 'compare' })}</div>
     <div class="card"><h3>Companies all selected groups hold above 1% (${both.length})</h3>${tbl([{ h: 'Company', v: r => r, f: r => coLink(r) }, ...gs.map(g => ({ h: g.name + ' %', n: 1, v: r => g.positions[r]?.[I.q_cur] }))], both, { file: 'overlap' })}</div>`); }
  const g = I.groups.find(x => x.id === id); if (!g) return page(`<p class="na">Group not found or not institutional (${esc(id)}).</p>`);
  const qs = META.quarters.slice(-5); const h = hz();
  const watching = store.get('watch', []).some(w => w.type === 'investor' && w.id === id);
  page(`<p><a href="#/investors">← Investors</a></p><h1>${esc(g.name)} <button class="small noprint" onclick="toggleWatch('investor','${esc(id)}','${esc(g.name)}')">${watching ? '★ Watching' : '☆ Watch'}</button></h1>
   <div class="card"><p>${esc(CATN[g.category] || g.category)}${g.country ? ' · ' + esc(g.country) : ''} · AUM: ${g.aum ? esc(g.aum) : NA}</p><p class="small">Entities matched: ${esc(g.entities.join('; ')) || 'none above 1%'}</p><p class="small muted">Parent rule: ${esc(g.parent_rule || 'name match')}</p>
    <p class="small muted">Not assessed: realised performance, track record, governance (not disclosed in structured public form).</p></div>
   <div class="g2"><div class="card"><h3>Activity score (${h})</h3>${g.scores?.[h] ? sc(recombineIf(g.scores[h], 'investor_activity', h)) + compTable(g.scores[h], 'investor_activity', h) : NA}</div>
    <div class="card"><h3>Sector spread of current holdings</h3><table>${Object.entries(g.sectors).map(([s, n]) => `<tr><td>${secLink(s)}</td><td class="n">${n}</td></tr>`).join('') || `<tr><td class="na">insufficient data</td></tr>`}</table></div></div>
   <div class="card"><h3>Above-1% positions by quarter (% of company)</h3>${tbl([{ h: 'Company', v: r => r[0], f: r => coLink(r[0]) }, ...qs.map(q => ({ h: q, n: 1, v: r => r[1][q], f: r => r[1][q] != null ? r[1][q].toFixed(2) : '<span class="muted">—</span>' })), { h: 'Status', v: r => g.new.includes(r[0]) ? 'new' : g.increased.includes(r[0]) ? 'increased' : g.decreased.includes(r[0]) ? 'reduced' : g.exited.includes(r[0]) ? 'exited / below 1%' : '' }], Object.entries(g.positions), { file: id + '_positions', note: '— = not disclosed (below 1% or not held)' })}<div class="src">${srcId('nse_shp')}</div></div>`);
}

/* ---------------- COMPANIES + TRANSACTIONS ---------------- */
ROUTES.companies = async (arg) => {
  if (arg && arg.startsWith('tx:')) return txView(arg.slice(3));
  if (arg === 'transactions') return txExplorer();
  if (arg) return companyView(arg);
  const C = await J('companies.json'); const f = store.get('cof', { s: '', n5: 1, q: '' });
  const rows = C.rows.filter(r => (!f.s || r[3] === f.s) && (!f.n5 || r[5]) && (!f.q || (r[1] + ' ' + r[2]).toLowerCase().includes(f.q.toLowerCase())));
  page(`<h1>Company tracker</h1><div class="tabs"><a class="btn on" href="#/companies">Companies</a><a class="btn" href="#/companies/transactions">Transactions explorer</a></div>
   <div class="card noprint flt"><input placeholder="Filter by name or symbol" value="${esc(f.q)}" onchange="setCof('q',this.value)"> <select onchange="setCof('s',this.value)"><option value="">All sectors</option>${Object.entries(META.industries).map(([k, v]) => `<option value="${k}" ${k === f.s ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>
    <label><input type="checkbox" ${f.n5 ? 'checked' : ''} onchange="setCof('n5',this.checked?1:0)"> Nifty 500 only</label></div>
   <div class="card">${tbl([{ h: 'Symbol', v: r => r[1], f: r => coLink(r[1], r[1]) }, { h: 'Company', v: r => r[2] }, { h: 'Sector', v: r => ind(r[3]) }, { h: 'Inst. %', n: 1, v: r => r[6], f: r => num(r[6], 2) }, { h: 'Inst. Δ QoQ pp', n: 1, v: r => r[7], f: r => pp(r[7]) }, { h: 'Promoter %', n: 1, v: r => r[8], f: r => num(r[8], 2) }, { h: 'Promoter Δ pp', n: 1, v: r => r[9], f: r => pp(r[9]) }, { h: 'Independent >1% holders', n: 1, v: r => r[10] }, { h: 'New groups', n: 1, v: r => r[11] }, { h: 'Events', n: 1, v: r => r[12] }, { h: 'Company evidence 1-3y', n: 1, v: r => r[13], f: r => sc(r[13]) }], rows, { file: 'companies', max: 1500 })}
   <div class="src">${srcId('nse_universe')} · ${srcId('nse_shp')} (quarter to ${esc(META.q_cur || '')})</div></div>`);
};
window.setCof = (k, v) => { const f = store.get('cof', { s: '', n5: 1, q: '' }); f[k] = v; store.set('cof', f); route(); };
async function txExplorer() {
  const X = await J('transactions.json'); const f = store.get('txf', { t: '', s: '', g: '', from: '', to: '', l: '', min: '', c: '', q: '' });
  const types = [...new Set(X.rows.map(r => r[1]))].sort(); const labs = [...new Set(X.rows.map(r => r[11]))].filter(Boolean); const ctys = [...new Set(X.rows.map(r => r[14]))].filter(Boolean).sort();
  const rows = X.rows.filter(r => (!f.t || r[1] === f.t) && (!f.s || r[5] === f.s) && (!f.g || (r[7] || r[8] || '').toLowerCase().includes(f.g.toLowerCase())) && (!f.from || r[2] >= f.from) && (!f.to || r[2] <= f.to) && (!f.l || r[11] === f.l) && (!f.min || (isNum(r[10]) && r[10] >= +f.min)) && (!f.c || r[14] === f.c) && (!f.q || ((r[3] || '') + ' ' + (r[4] || '')).toLowerCase().includes(f.q.toLowerCase())));
  const sel = (k, opts, lbl) => `<select onchange="setTxf('${k}',this.value)"><option value="">${lbl}</option>${opts.map(o => `<option value="${esc(o[0])}" ${o[0] === f[k] ? 'selected' : ''}>${esc(o[1])}</option>`).join('')}</select>`;
  page(`<h1>Transactions explorer</h1><div class="tabs"><a class="btn" href="#/companies">Companies</a><a class="btn on" href="#/companies/transactions">Transactions explorer</a></div>
   <div class="card noprint flt">${sel('t', types.map(t => [t, t.replace(/_/g, ' ')]), 'All types')}${sel('s', Object.entries(META.industries), 'All sectors')}${sel('l', labs.map(l => [l, l]), 'All labels')}${sel('c', ctys.map(c => [c, c]), 'All countries')}
    <input placeholder="Investor / group" value="${esc(f.g)}" onchange="setTxf('g',this.value)"><input placeholder="Company" value="${esc(f.q)}" onchange="setTxf('q',this.value)">
    <input type="date" value="${esc(f.from)}" onchange="setTxf('from',this.value)"><input type="date" value="${esc(f.to)}" onchange="setTxf('to',this.value)"><input type="number" placeholder="Min ₹ cr" value="${esc(f.min)}" onchange="setTxf('min',this.value)" style="width:90px">
    <button class="small" onclick="store.set('txf',{});route()">Reset</button></div>
   <div class="card">${tbl([{ h: 'Date', v: r => r[2] }, { h: 'Type', v: r => r[1].replace(/_/g, ' ') }, { h: 'Company', v: r => r[4] || r[3], f: r => r[3] ? coLink(r[3], r[4] || r[3]) : esc(r[4] || '') }, { h: 'Sector', v: r => ind(r[5]) }, { h: 'Investor', v: r => r[8], f: r => r[6] && !String(r[6]).startsWith('self_') ? invLink(r[6], r[8]) : esc(r[8] || '') }, { h: 'Group', v: r => r[7] }, { h: 'Side', v: r => r[9] }, { h: '₹ cr', n: 1, v: r => r[10], f: r => isNum(r[10]) ? crp(r[10]) : '<span class="na">undisclosed</span>' }, { h: 'Label', v: r => r[11], f: r => lab(r[11]) + (r[15] ? ' <span class="chip">index fund</span>' : '') }, { h: 'Source', v: r => r[12] || X.deals_url, f: r => srcA(r[12] || X.deals_url, r[13]) }, { h: '', v: () => '', f: r => `<a href="#/companies/tx:${esc(r[0])}">detail</a>` }], rows, { file: 'transactions', max: 1500, note: `last 400 days; ${X.skipped.trading_or_broker} trading/broker and ${X.skipped.individual_or_corporate} individual/corporate rows left out (see NSE source); table shows first 1,500, CSV has all filtered rows` })}</div>`);
}
window.setTxf = (k, v) => { const f = store.get('txf', {}); f[k] = v; store.set('txf', f); route(); };
async function txView(id) {
  const X = await J('transactions.json'); const r = X.rows.find(x => x[0] === id); const x = await J('executive.json'); const e = x.events.find(z => z.id === id);
  if (!r && !e) return page(`<p class="na">Transaction ${esc(id)} not in the last 400 days of exported rows. Download the Excel workbook for the full history.</p>`);
  const o = r ? Object.fromEntries(X.cols.map((c, i) => [c, r[i]])) : { id: e.id, type: e.type, date: e.d, company: e.cn, industry: e.s, amount_cr: e.a, label: e.l, url: e.u };
  page(`<p><a href="#/companies/transactions">← Transactions</a></p><h1>${esc((o.type || '').replace(/_/g, ' '))}: ${esc(o.company || '')}</h1><div class="card"><table>${Object.entries(o).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${k === 'url' ? srcA(v) : k === 'label' ? lab(v) : v == null ? (k === 'amount_cr' ? '<span class="na">undisclosed</span>' : '—') : esc(v)}</td></tr>`).join('')}${e ? `<tr><th>description</th><td>${esc(e.x)}</td></tr>` : ''}</table></div>`);
}
async function companyView(sym) {
  let c; try { c = await J('co/' + sym + '.json'); } catch { return page(`<p class="na">No detail file for ${esc(sym)} (only Nifty 500 and companies with recorded transactions have one).</p>`); }
  const qs = Object.keys(c.ownership).sort(); const h = hz() === '10-20y' ? '3-10y' : hz();
  const ser = (k, n) => ({ name: n, pts: qs.filter(q => c.ownership[q][k] != null).map(q => [q, c.ownership[q][k]]) });
  const sumc = (q, ks) => ks.reduce((a, k) => a + (c.ownership[q][k] || 0), 0);
  const inst = { name: 'All institutions', pts: qs.filter(q => c.ownership[q].public != null).map(q => [q, sumc(q, ['mf', 'aif', 'insurance', 'pension', 'bank', 'nbfc', 'other_fi', 'swf_domestic', 'fpi1', 'fpi2', 'other_foreign_inst', 'swf_foreign'])]) };
  const fpi = { name: 'Foreign portfolio', pts: qs.filter(q => c.ownership[q].public != null).map(q => [q, sumc(q, ['fpi1', 'fpi2', 'other_foreign_inst', 'swf_foreign'])]) };
  const nq = Object.keys(c.named).sort().slice(-5); const groups = [...new Set(nq.flatMap(q => c.named[q].map(x => x.gname)))];
  const watching = store.get('watch', []).some(w => w.type === 'company' && w.id === sym);
  const s = c.summary || {};
  page(`<p><a href="#/companies">← Companies</a> · ${secLink(c.industry)}</p><h1>${esc(c.name)} <span class="muted">${esc(c.symbol)}</span> <button class="small noprint" onclick="toggleWatch('company','${esc(sym)}','${esc(c.name)}')">${watching ? '★ Watching' : '☆ Watch'}</button></h1>
   <div class="kpis"><div class="kpi"><div class="kt">Institutional holding</div><div class="kv">${isNum(s.inst) ? s.inst.toFixed(2) + '%' : NA}</div><div class="ks">Δ QoQ ${pp(s.inst_qoq)} · YoY ${pp(s.inst_yoy)}</div></div>
    <div class="kpi"><div class="kt">Promoter</div><div class="kv">${isNum(s.promoter) ? s.promoter.toFixed(2) + '%' : NA}</div><div class="ks">Δ QoQ ${pp(s.promoter_qoq)}</div></div>
    <div class="kpi"><div class="kt">Independent >1% holders</div><div class="kv">${s.independent_holders ?? NA}</div><div class="ks">new: ${(s.new_groups || []).map(g => META.groups[g]?.name || g).join(', ') || 'none'}</div></div>
    <div class="kpi"><div class="kt">Company evidence (${h})</div><div class="kv">${sc(c.scores?.[h] ? recombineIf(c.scores[h], 'company_evidence', h) : null)}</div><div class="ks">${c.scores?.[h] ? esc(c.scores[h].confidence) + ' confidence' : ''}</div></div></div>
   <div class="g2"><div class="card"><h3>Shareholding by category, % (quarterly)</h3>${lines([ser('promoter', 'Promoter'), inst, ser('mf', 'Mutual funds'), fpi, ser('insurance', 'Insurance')], { cap: srcId('nse_shp') + ' · ' + qs.map(q => c.shp_docs[q] ? srcA(c.shp_docs[q], q) : '').filter(Boolean).slice(-5).join(' ') })}</div>
    <div class="card"><h3>Score components</h3>${c.scores?.[h] ? compTable(c.scores[h], 'company_evidence', h) : NA}<div class="muted small">Not assessed: ${esc(c.not_assessed.join(', '))}</div></div></div>
   <div class="card"><h3>Named institutional holders above 1% (parent group, % of company)</h3>${tbl([{ h: 'Group', v: r => r, f: r => { const g = nq.flatMap(q => c.named[q]).find(x => x.gname === r); return invLink(g?.group, r); } }, ...nq.map(q => ({ h: q, n: 1, v: r => c.named[q].find(x => x.gname === r)?.pct, f: r => { const v = c.named[q].find(x => x.gname === r)?.pct; return v != null ? v.toFixed(2) : '<span class="muted">—</span>'; } }))], groups, { file: sym + '_holders', note: '— = below 1% or not held (not disclosed)' })}</div>
   <div class="card"><h3>Timeline: deals, filings, capital events</h3>${tbl([{ h: 'Date', v: r => r.d }, { h: 'Type', v: r => r.type.replace(/_/g, ' ') }, { h: 'Investor / detail', v: r => r.inv || r.x, f: r => r.g && !r.flag && !String(r.g).startsWith('self_') ? invLink(r.g, r.inv) : `<span class="small">${esc((r.inv || r.x || '').slice(0, 200))}</span>` }, { h: 'Group', v: r => r.gname || r.flag || '' }, { h: 'Side', v: r => r.side }, { h: '₹ cr', n: 1, v: r => r.a, f: r => isNum(r.a) ? crp(r.a) : '<span class="na">undisclosed</span>' }, { h: '', v: r => r.l, f: r => lab(r.l) + ' ' + srcA(r.u) }], c.timeline, { file: sym + '_timeline' })}</div>
   <div class="card small muted">CIN, parent group of the company, unlisted funding rounds: ${NA}. Ownership below 1% per holder is not disclosed by companies.</div>`);
}

/* ---------------- GLOBAL ---------------- */
ROUTES.global = async () => {
  const G = await J('global.json');
  const Q = [['what', 'What happened'], ['why', 'Why it happened'], ['consequences', 'Likely economic consequences'], ['benefit', 'Indian industries that may benefit'], ['lose', 'Indian industries that may lose'], ['companies', 'Companies'], ['evidence', 'Capital-flow evidence'], ['invalidate', 'What would invalidate this view']];
  const FN = { DFF: 'US Fed funds rate %', DGS10: 'US 10y yield %', DFII10: 'US 10y real yield %', DTWEXBGS: 'US dollar broad index', DCOILBRENTEU: 'Brent US$/bbl', DEXINUS: 'INR per US$' };
  page(`<h1>Global developments</h1><div class="card warn">Each row is labelled. ${lab('VERIFIED FACT')} rows are data; ${lab('AI INTERPRETATION')} rows are fixed rule-based mappings written in advance, not generated text; ${lab('SCENARIO')} rows are conditional. No causes are asserted.</div>
   <div class="card"><h3>Market series (FRED, month-end)</h3><div class="g3">${Object.entries(G.fred).map(([k, v]) => `<div><h4>${esc(FN[k] || k)}</h4>${lines([{ name: k, pts: v.slice(-120) }], { h: 120 })}</div>`).join('')}</div><div class="src">${srcId('fred')}</div></div>
   ${G.developments.map(d => `<div class="card"><h2>${esc(d.title)}</h2><table class="small">${Q.map(([k, t]) => `<tr><th style="width:24%">${t}</th><td>${lab(d[k]?.label)} ${esc(d[k]?.text)}</td></tr>`).join('')}</table>
    ${d.fdi ? lines(Object.entries(d.fdi).map(([c, v]) => ({ name: c, pts: v.filter(r => r.period_end >= '2005' && r.value != null).map(r => [r.period_end.slice(0, 4), r.value / 1e9]) })), { zero: 1, cap: srcId('worldbank') + ' · FDI net inflows US$ bn' }) : ''}</div>`).join('')}
   ${G.sensitivity ? `<div class="card"><h3>Computed sensitivity ${lab('ESTIMATED VALUE')}</h3><p>Correlation between monthly NSDL FPI net equity flow and the monthly change in the US 10-year real yield, ${esc(G.sensitivity.from)} to ${esc(G.sensitivity.to)} (${G.sensitivity.months} months): <b>${G.sensitivity.corr}</b>. Correlation is not causation.</p></div>` : ''}
   <div class="card"><h3>Population aged 65+, % (World Bank)</h3>${lines(Object.entries(G.demography).map(([c, v]) => ({ name: c, pts: v.filter(r => r.value != null).map(r => [r.period_end.slice(0, 4), r.value]) })), { cap: srcId('worldbank') })}</div>`);
};

/* ---------------- CREDIT ---------------- */
ROUTES.credit = async () => {
  const C = await J('credit.json');
  const leaf = C.sibc.filter(r => r.yoy != null && r.code.includes('.') && r.industry !== 'others');
  const up = [...leaf].sort((a, b) => b.yoy - a.yoy).slice(0, 12), dn = [...leaf].sort((a, b) => a.yoy - b.yoy).slice(0, 12);
  const rt = Object.entries(C.ratings).filter(([, v]) => v.counted >= 5).map(([s, v]) => ({ s, ...v, negsh: v.neg / v.counted * 100 }));
  const pick = store.get('crpick', '2'); const hist = C.sibc_history[pick] || [];
  page(`<h1>Credit and debt</h1><div class="card method">Bank credit here is <b>outstanding stock</b> (RBI SIBC), not new sanctions or disbursements. Sanctioned vs disbursed credit, project finance sanctions and NBFC on-lending by end sector are ${NA}: ${esc(C.not_available.join('; '))}. Corporate debt raised is limited to NCD/CP allotments filed with NSE.</div>
   <div class="g2"><div class="card"><h3>Fastest-growing bank credit (YoY %, ${esc(C.sibc_last || '')})</h3><table>${up.map(r => `<tr><td>${esc(r.name)}</td><td class="n">${pc(r.yoy)}</td><td>${bar(r.yoy, 60, 'var(--pos)')}</td></tr>`).join('')}</table></div>
    <div class="card"><h3>Slowest / contracting</h3><table>${dn.map(r => `<tr><td>${esc(r.name)}</td><td class="n">${pc(r.yoy)}</td><td>${bar(r.yoy, 60, 'var(--neg)')}</td></tr>`).join('')}</table></div></div>
   <div class="card"><h3>History, YoY % <select onchange="store.set('crpick',this.value);route()">${C.sibc.map(r => `<option value="${esc(r.code)}" ${r.code === pick ? 'selected' : ''}>${esc(r.code)} ${esc(r.name)}</option>`).join('')}</select></h3>${lines([{ name: pick, pts: hist }], { zero: 1, cap: srcId('rbi_sibc') })}</div>
   <div class="card"><h3>All RBI industry codes</h3>${tbl([{ h: 'Code', v: r => r.code }, { h: 'Name', v: r => r.name }, { h: 'Mapped sector', v: r => ind(r.industry), f: r => r.industry ? secLink(r.industry) : '' }, { h: 'Outstanding ₹ cr', n: 1, v: r => r.outstanding, f: r => crp(r.outstanding) }, { h: 'YoY %', n: 1, v: r => r.yoy, f: r => pc(r.yoy) }, { h: 'FYTD %', n: 1, v: r => r.fy, f: r => pc(r.fy) }], C.sibc, { file: 'rbi_sibc' })}</div>
   <div class="g2"><div class="card"><h3>CRISIL rating actions by sector (12 months, sectors with 5+ counted actions)</h3>${tbl([{ h: 'Sector', v: r => ind(r.s), f: r => secLink(r.s) }, { h: 'Counted', n: 1, v: r => r.counted }, { h: 'Upgrades', n: 1, v: r => r.up }, { h: 'Downgrades/defaults', n: 1, v: r => r.down }, { h: 'Negative %', n: 1, v: r => r.negsh, f: r => num(r.negsh, 0) }, { h: 'Not cooperating (new)', n: 1, v: r => r.inc }], rt, { file: 'ratings_by_sector' })}<div class="src">${srcId('crisil_ratings')} · other agencies (ICRA, CARE, India Ratings) not yet ingested</div></div>
    <div class="card"><h3>Recent upgrades, downgrades, defaults</h3>${tbl([{ h: 'Date', v: r => r.period }, { h: 'Borrower', v: r => r.borrower }, { h: 'Sector', v: r => ind(r.industry_id) }, { h: 'Action', v: r => { try { return JSON.parse(r.detail).action } catch { return '' } } }, { h: '', v: r => r.url, f: r => srcA(r.url, 'CRISIL') }], C.recent_actions, { file: 'rating_actions' })}</div></div>
   <div class="card"><h3>Debt raised (NCD / CP allotments filed with NSE)</h3>${tbl([{ h: 'Date', v: r => r.d }, { h: 'Company', v: r => r.cn, f: r => coLink(r.sym, r.cn) }, { h: '₹ cr', n: 1, v: r => r.a, f: r => isNum(r.a) ? crp(r.a) : '<span class="na">undisclosed</span>' }, { h: 'Summary', v: r => r.x, f: r => `<span class="small">${esc(r.x)}</span>` }, { h: '', v: r => r.u, f: r => srcA(r.u, 'NSE') }], C.debt_raised, { file: 'debt_raised' })}</div>`);
};

/* ---------------- CAPITAL ATTENTION RADAR ---------------- */
ROUTES.radar = async () => {
  const R = await J('radar.json'); const h = hz();
  const rs = r => tbl([{ h: 'Sector', v: x => x.name, f: x => secLink(x.id) }, { h: 'Attention', n: 1, v: x => x.score, f: x => sc(x.score) }, { h: 'Confidence', v: x => x.confidence }, { h: 'Why', v: x => x.why.join('; '), f: x => `<span class="small">${esc(x.why.join('; '))}</span>` }, { h: 'Flags', v: x => x.flags.join('; '), f: x => `<span class="small muted">${esc(x.flags.join('; '))}</span>` }], rescoreRank(r, 'capital_flow', h), { file: 'radar_sectors_' + h });
  page(`<h1>Capital attention radar</h1><div class="card warn">${esc(R.language_note)} Nothing here says a security is worth buying or selling.</div>
   <div class="card"><h2>Sectors receiving the most capital attention (${h === '10-20y' ? '10-20y: see themes below' : h})</h2>${h === '10-20y' ? '' : rs(R.sectors[h] || [])}</div>
   <div class="card"><h2>10-20 year themes ${lab('SCENARIO')}</h2>${tbl([{ h: 'Theme', v: t => t.theme, f: t => `<a href="#/horizons/10-20y">${esc(t.theme)}</a>` }, { h: 'Evidence status', v: t => t.status }, { h: 'Supporting', n: 1, v: t => t.supporting }, { h: 'Contrary', n: 1, v: t => t.contrary }, { h: 'Industries', v: t => t.industries.join(', ') }], R.themes_10_20, { file: 'themes' })}</div>
   <div class="g2"><div class="card"><h3>Sub-sectors with the fastest bank-credit growth</h3>${tbl([{ h: 'Sub-sector', v: x => x.name }, { h: 'Sector', v: x => ind(x.industry) }, { h: 'YoY %', n: 1, v: x => x.value, f: x => pc(x.value) }], R.sub_sectors, { file: 'sub_sectors' })}<div class="src">${srcId('rbi_sibc')}</div></div>
    <div class="card"><h3>Contrarian institutional moves</h3><p class="small muted">${esc(R.contrarian_rule)}</p>${tbl([{ h: 'Sector', v: x => x.name, f: x => secLink(x.id) }, { h: 'Domestic pp', n: 1, v: x => x.domestic, f: x => pp(x.domestic, 3) }, { h: 'Foreign pp', n: 1, v: x => x.foreign, f: x => pp(x.foreign, 3) }, { h: 'FPI 3m ₹ cr', n: 1, v: x => x.fpi_3m, f: x => cr(x.fpi_3m) }], R.contrarian, { file: 'contrarian' })}</div>
    <div class="card"><h3>Listed companies with rising institutional attention</h3>${tbl([{ h: 'Company', v: x => x.name, f: x => coLink(x.id, x.name) }, { h: 'Sector', v: x => ind(x.industry) }, { h: 'Inst. Δ pp', n: 1, v: x => x.inst_qoq, f: x => pp(x.inst_qoq) }, { h: 'New groups', v: x => x.new_groups.join(', ') }, { h: 'Flags', v: x => x.flags.join('; '), f: x => `<span class="small muted">${esc(x.flags.join('; '))}</span>` }], R.companies_attention, { file: 'company_attention' })}<div class="src">${srcId('nse_shp')}</div></div>
    <div class="card"><h3>Companies where several independent groups are adding</h3>${tbl([{ h: 'Company', v: x => x.name, f: x => coLink(x.company, x.name) }, { h: 'Groups', n: 1, v: x => x.independent_groups }, { h: 'Who', v: x => x.groups.map(g => META.groups[g]?.name || g).join(', '), f: x => `<span class="small">${esc(x.groups.map(g => META.groups[g]?.name || g).join(', '))}</span>` }], R.multi_investor, { file: 'multi_investor' })}</div>
    <div class="card"><h3>Private companies receiving funding</h3><p class="na">${esc(R.private_companies.status)}</p><p class="small muted">${esc(R.private_companies.reason)}</p></div>
    <div class="card"><h3>Capital withdrawal (lowest 1-3y attention)</h3>${tbl([{ h: 'Sector', v: x => x.name, f: x => secLink(x.id) }, { h: 'Score', n: 1, v: x => x.score, f: x => sc(x.score) }, { h: 'FPI 12m ₹ cr', n: 1, v: x => x.fpi_12m, f: x => cr(x.fpi_12m) }, { h: 'Inst. Δ pp', n: 1, v: x => x.inst_qoq, f: x => pp(x.inst_qoq, 3) }, { h: 'Credit YoY', n: 1, v: x => x.credit_yoy, f: x => pc(x.credit_yoy) }], R.withdrawal, { file: 'withdrawal' })}</div>
    <div class="card"><h3>Valuation context (sector index P/E vs own 10-year history)</h3>${tbl([{ h: 'Index', v: x => x[0] }, { h: 'Sector', v: x => ind(x[1].industry) }, { h: 'P/E', n: 1, v: x => x[1].pe, f: x => num(x[1].pe, 1) }, { h: '10y median', n: 1, v: x => x[1].median_10y }, { h: 'Percentile', n: 1, v: x => x[1].pctl_10y, f: x => `<span class="cell" style="background:${heat(x[1].pctl_10y)}">${num(x[1].pctl_10y, 0)}</span>` }, { h: 'As of', v: x => x[1].as_of }], Object.entries(R.valuation), { file: 'valuation_context', note: 'context only, not a view on value' })}<div class="src">${srcId('nse_sector_pe')}</div></div></div>`);
};

/* ---------------- DATA QUALITY ---------------- */
ROUTES.quality = async () => {
  const Q = META.quality; const cons = await J('conclusions.json');
  const m = Q.missing; const pct = (a, b) => b ? ` (${(a / b * 100).toFixed(1)}%)` : '';
  page(`<h1>Data quality report</h1>
   <div class="g2"><div class="card"><h3>Row counts</h3><table>${Object.entries(Q.counts).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${inr(v)}</td></tr>`).join('')}</table></div>
    <div class="card"><h3>Missing or undisclosed fields</h3><table>
     <tr><td>Companies without sector</td><td class="n">${m.companies_without_industry} of ${m.companies_total}${pct(m.companies_without_industry, m.companies_total)}</td></tr>
     <tr><td>Nifty 500 companies without the latest shareholding filing</td><td class="n">${m.nifty500_without_latest_shp}</td></tr>
     <tr><td>Transactions with undisclosed amount (kept as blank, not zero)</td><td class="n">${inr(m.transactions_amount_undisclosed)} of ${inr(m.transactions_total)}${pct(m.transactions_amount_undisclosed, m.transactions_total)}</td></tr>
     <tr><td>Transactions on companies without sector</td><td class="n">${inr(m.transactions_without_industry)}</td></tr>
     <tr><td>Rating actions not mapped to a sector</td><td class="n">${m.rating_actions_without_industry} of ${m.rating_actions_total}</td></tr>
     <tr><td>Investor entities with no known parent group</td><td class="n">${inr(m.investors_without_parent)} of ${inr(m.investors_total)}</td></tr>
     <tr><td>Bulk/block rows in 90d: excluded as trading desks / brokers; as individuals/corporates</td><td class="n">${Q.deal_filter ? `${Q.deal_filter.excluded_trading} ; ${Q.deal_filter.excluded_other} of ${Q.deal_filter.rows}` : NA}</td></tr></table></div></div>
   <div class="card"><h3>Research Auditor: structural checks</h3><table>${Q.audit_checks.map(c => `<tr><td>${c.ok ? '<span class="pos">PASS</span>' : '<span class="neg">FAIL</span>'}</td><td>${esc(c.check)}</td><td class="muted">${esc(c.detail)}</td></tr>`).join('')}</table></div>
   <div class="card"><h3>Conflicting evidence between sources</h3>${tbl([{ h: 'Topic', v: r => r.topic }, { h: 'Source A', v: r => r.a }, { h: 'Source B', v: r => r.b }, { h: 'Note', v: r => r.note }], Q.discrepancies, { file: 'discrepancies', empty: 'No overlapping periods yet' })}</div>
   <div class="card"><h3>Agent conclusions and auditor verdicts</h3><p class="small muted">Eight rule-based agents (no language model; all numbers computed from stored rows). The auditor rejects any conclusion without a traceable evidence row or with recommendation language, and flags any with contradicting evidence.</p>
    ${tbl([{ h: 'Agent', v: r => r.agent }, { h: 'Horizon', v: r => r.horizon }, { h: 'Statement', v: r => r.statement, f: r => `<span class="small">${esc(r.statement)}</span>` }, { h: 'Label', v: r => r.evidence_label, f: r => lab(r.evidence_label) }, { h: 'Confidence', v: r => r.confidence }, { h: 'Auditor', v: r => r.auditor_status, f: r => `<span class="chip ${r.auditor_status === 'accepted' ? 'ok' : r.auditor_status === 'flagged' ? 'st' : 'bad'}">${esc(r.auditor_status)}</span>` }, { h: 'Notes / contrary evidence', v: r => r.auditor_notes + ' ' + r.contradicting_refs, f: r => `<span class="small">${esc(r.auditor_notes)}${JSON.parse(r.contradicting_refs || '[]').map(x => '<br>⚠ ' + esc(x)).join('')}</span>` }, { h: 'Evidence rows', n: 1, v: r => JSON.parse(r.evidence_refs || '[]').length }], cons, { file: 'conclusions' })}</div>
   <div class="g2"><div class="card"><h3>Stale sources</h3>${Q.stale.length ? Q.stale.map(srcId).join('<br>') : '<p class="pos">None</p>'}</div>
    <div class="card"><h3>Failed jobs (latest 40)</h3>${tbl([{ h: 'Source', v: r => r.source_id }, { h: 'Run', v: r => r.run_at?.slice(0, 16) }, { h: 'Error', v: r => r.error, f: r => `<span class="small">${esc((r.error || '').slice(0, 160))}</span>` }], Q.failed_jobs, { file: 'failed_jobs', empty: 'none' })}</div>
    <div class="card"><h3>Duplicates skipped by stable IDs</h3>${tbl([{ h: 'Source', v: r => r.source_id }, { h: 'New rows', n: 1, v: r => r.n }, { h: 'Duplicates skipped', n: 1, v: r => r.d }], Q.duplicates, { file: 'duplicates' })}</div></div>`);
};

/* ---------------- SOURCES + METHODOLOGY ---------------- */
ROUTES.sources = async (arg) => {
  const S = META.sources; const stc = s => ({ working: 'ok', partial: 'st', blocked: 'bad', needs_credentials: 'bad', not_built: '' }[s] || '');
  page(`<h1>Source registry and methodology</h1>
   <div class="card">${tbl([{ h: 'Source', v: r => r.name, f: r => `<b id="s_${esc(r.source_id)}">${esc(r.name)}</b>${r.official ? '' : ' <span class="chip st">unofficial</span>'}<div class="small muted">${esc(r.source_id)}</div>` }, { h: 'Category', v: r => r.category }, { h: 'Status', v: r => r.status, f: r => `<span class="chip ${stc(r.status)}">${esc(r.status)}</span>${r.stale ? ' <span class="chip st">stale</span>' : ''}` },
     { h: 'Reliability', v: r => r.reliability }, { h: 'Frequency', v: r => r.frequency }, { h: 'Latest data period', v: r => r.latest_data_period }, { h: 'Last retrieved', v: r => r.last_success, f: r => esc((r.last_success || 'never').slice(0, 16)) }, { h: 'Last run', v: r => r.last_run?.run_at, f: r => r.last_run ? `${r.last_run.ok ? '✓' : '✗'} ${esc(r.last_run.run_at.slice(0, 16))} · ${r.last_run.rows_new ?? 0} new` : '' },
     { h: 'Limitations', v: r => r.limitations, f: r => `<span class="small">${esc(r.limitations || '')}${r.credentials_needed ? '<br><b>Needs:</b> ' + esc(r.credentials_needed) : ''}</span>` }, { h: 'URL', v: r => r.url, f: r => srcA(r.url, 'open') }], S, { file: 'sources' })}</div>
   <div class="card"><h2>Evidence labels</h2><table class="small">
    <tr><td>${lab('VERIFIED FACT')}</td><td>A number published by an official or exchange source, stored with its document and date.</td></tr>
    <tr><td>${lab('REPORTED ANNOUNCEMENT')}</td><td>Stated by a company or the government in a filing or release (intent or approval); not yet verified as deployed.</td></tr>
    <tr><td>${lab('ESTIMATED VALUE')}</td><td>Computed here from verified inputs (z-scores, correlations, percentiles). Method shown next to it.</td></tr>
    <tr><td>${lab('AI INTERPRETATION')}</td><td>A rule-based reading written in advance (no language model). Never a number source.</td></tr>
    <tr><td>${lab('SCENARIO')}</td><td>A conditional hypothesis with explicit confirm and invalidate conditions. Not a forecast.</td></tr>
    <tr><td>${lab('UNVERIFIED INFORMATION')}</td><td>Not confirmed by any registered source; shown only to mark the gap.</td></tr></table></div>
   <div class="card"><h2>How the scores work</h2><p>Five scores (capital attention, investor activity, industry evidence, company evidence, valuation context) for each horizon. Each component is a percentile rank (0-100) among sectors, groups or companies; the score is the weighted mean of components that have data. If less than half the weight has data the score shows <i>insufficient data</i>. Confidence: high ≥85% of weight covered, medium ≥65%, low ≥50%. Weights are in <code>data/weights.json</code> and the Admin page. Components the brief asks for that no free structured source supplies are listed as <i>not assessed</i>, never filled with zero.</p>
    <h3>Current weights</h3><pre class="small">${esc(JSON.stringify(W(), null, 1))}</pre>
    <h3>Investor classification</h3><p>Shareholder and deal-party names are mapped to parent groups by fixed name rules (for example every "SBI ... Fund" scheme maps to SBI Funds Management). Trading firms, broker proprietary desks, ODI/P-note desks and index funds/ETFs are flagged and excluded from convergence and activity counts. Names that match no rule become their own group.</p>
    <h3>Commitments vs deployments</h3><p>Stored in separate tables with linking IDs (for AIFs: commitments raised vs investments made; for Cabinet approvals: outlay approved, no deployment recorded). They are never added together anywhere.</p>
    <h3>Agents</h3><p>Capital Flow Researcher, Investor Behaviour Analyst, Industry Research Analyst, Global Environment Analyst, Corporate Intelligence Analyst, Credit Intelligence Analyst, Capital Attention Analyst, Research Auditor. All are deterministic Python rules in <code>scripts/build.py</code>; there is no language model in the pipeline.</p>
    <p><a href="schema.sql" target="_blank">Database schema (schema.sql)</a> · <a href="https://github.com/cakashoza-cmyk/smartmoney" target="_blank" rel="noopener">Code and pipeline</a></p></div>`);
  if (arg) { const el = document.getElementById('s_' + arg); if (el) { el.scrollIntoView(); el.closest('tr').style.outline = '2px solid var(--acc)'; } }
};

/* ---------------- WATCHLIST + ALERTS (localStorage) ---------------- */
window.toggleWatch = (type, id, name) => { let w = store.get('watch', []); w = w.some(x => x.type === type && x.id === id) ? w.filter(x => !(x.type === type && x.id === id)) : w.concat({ type, id, name, added: new Date().toISOString().slice(0, 10) }); store.set('watch', w); route(); };
async function checkAlerts() {
  const al = store.get('alerts', []); if (!al.length) return [];
  const [S, C] = await Promise.all([J('sectors.json'), J('companies.json')]); const cm = Object.fromEntries(C.rows.map(r => [r[1], r]));
  return al.map(a => { let v = null;
    if (a.kind === 'sector_fpi3m') v = S.sectors.find(s => s.id === a.id)?.fpi?.net_3m;
    if (a.kind === 'sector_credit') v = S.sectors.find(s => s.id === a.id)?.metrics.bank_credit_yoy;
    if (a.kind === 'company_inst') v = cm[a.id]?.[7];
    const hit = isNum(v) && (a.op === '>' ? v > a.th : v < a.th); return { ...a, v, hit }; });
}
ROUTES.watch = async () => {
  const w = store.get('watch', []); const res = await checkAlerts();
  page(`<h1>Watchlist and alerts</h1><p class="muted">Stored only in this browser (localStorage). Nothing is sent anywhere. Alerts are checked against the latest build each time you open this page.</p>
   <div class="card"><h3>Watchlist</h3>${w.length ? '<table>' + w.map(x => `<tr><td><span class="chip">${esc(x.type)}</span></td><td><a href="#/${x.type === 'industry' ? 'sectors' : x.type === 'company' ? 'companies' : 'investors'}/${esc(x.id)}">${esc(x.name)}</a></td><td class="muted">${esc(x.added)}</td><td><button class="small" onclick="toggleWatch('${x.type}','${esc(x.id)}','')">Remove</button></td></tr>`).join('') + '</table>' : '<p class="muted">Use ☆ Watch on any sector, company or investor page.</p>'}</div>
   <div class="card"><h3>Alerts</h3>${res.length ? '<table>' + res.map((a, i) => `<tr><td>${a.hit ? '<span class="chip st">TRIGGERED</span>' : '<span class="chip">waiting</span>'}</td><td>${esc(a.label)}</td><td class="n">${isNum(a.v) ? a.v.toFixed(2) : NA}</td><td><button class="small" onclick="delAlert(${i})">Delete</button></td></tr>`).join('') + '</table>' : '<p class="muted">No alerts.</p>'}
    <div class="flt noprint"><select id="ak"><option value="sector_fpi3m">Sector FPI net 3m (₹ cr)</option><option value="sector_credit">Sector bank credit YoY %</option><option value="company_inst">Company institutional Δ QoQ pp (symbol)</option></select>
     <input id="aid" placeholder="sector id (e.g. capital_goods) or symbol"><select id="aop"><option>&gt;</option><option>&lt;</option></select><input id="ath" type="number" placeholder="threshold" style="width:110px"><button onclick="addAlert()">Add alert</button></div></div>`);
};
window.addAlert = () => { const a = { kind: $('#ak').value, id: $('#aid').value.trim(), op: $('#aop').value, th: +$('#ath').value }; if (!a.id || !isFinite(a.th)) return; a.label = `${$('#ak').selectedOptions[0].text}: ${a.id} ${a.op} ${a.th}`; store.set('alerts', store.get('alerts', []).concat(a)); route(); };
window.delAlert = i => { const a = store.get('alerts', []); a.splice(i, 1); store.set('alerts', a); route(); };

/* ---------------- ADMIN (client-side only) ---------------- */
ROUTES.admin = async () => {
  const on = store.get('admin', false); const w = W();
  page(`<h1>Admin: score weights</h1><div class="card warn"><b>Client-side admin mode.</b> Changes apply only in this browser: rankings are recomputed from the published component ranks with your weights. Real role-based access (who may change the official weights) needs a hosted backend with authentication, which this zero-cost static deployment does not have. To change the published weights, edit <code>data/weights.json</code> in the repository; the next pipeline run uses it.</div>
   ${on ? `<div class="card">${Object.entries(w).map(([scn, hs]) => `<h3>${esc(scn.replace(/_/g, ' '))}</h3><div class="g3">${Object.entries(hs).map(([h, cs]) => `<div><b>${h}</b>${Object.entries(cs).map(([c, v]) => `<div class="flt"><label style="flex:1" class="small">${esc(c.replace(/_/g, ' '))}</label><input type="number" min="0" max="100" value="${v}" data-s="${scn}" data-h="${h}" data-c="${c}" style="width:70px"></div>`).join('')}</div>`).join('')}</div>`).join('')}
    <div class="flt"><button onclick="saveW()">Apply in this browser</button><button onclick="localStorage.removeItem('sm_weights');route()">Reset to published</button><button onclick="expW()">Export weights.json</button><button onclick="store.set('admin',false);route()">Leave admin mode</button></div></div>`
    : `<div class="card"><button onclick="store.set('admin',true);route()">Enter admin mode (this browser)</button></div>`}
   <p class="muted small">${store.get('weights', null) ? '<b>Custom weights active in this browser.</b>' : 'Published weights in use.'}</p>`);
};
window.saveW = () => { const w = JSON.parse(JSON.stringify(W())); $$('input[data-s]').forEach(i => { w[i.dataset.s][i.dataset.h][i.dataset.c] = Math.max(0, +i.value || 0); }); store.set('weights', w); route(); };
window.expW = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(W(), null, 1)], { type: 'application/json' })); a.download = 'weights.json'; a.click(); };

/* ---------------- init ---------------- */
(async function init() {
  const th = store.get('theme', 'dark'); document.documentElement.dataset.theme = th;
  $('#theme').onclick = () => { const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = t; store.set('theme', t); };
  $('#print').onclick = () => window.print();
  $('#hz').value = store.get('hz', '1-3y'); $('#hz').onchange = () => { store.set('hz', $('#hz').value); route(); };
  try { META = await J('meta.json'); } catch (e) { $('#app').innerHTML = `<div class="card"><h2>Data not built yet</h2><p class="na">${esc(e.message)}</p></div>`; return; }
  freshBar(); initSearch();
  window.addEventListener('hashchange', route); route();
})();
