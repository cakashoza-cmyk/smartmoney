/* Smart Money Intelligence 2.0 screens (Sprint 1): Signals, Opportunity Discovery (research hypotheses), Opportunity Dossier,
   Investable review, Valuation Lab, Thesis Monitor, Analyst workspace. Data: data/export/v2/*.json built by scripts/build_v2.py.
   Hypotheses are analyst-entered (data/analyst/*.json, committed through a reviewed pull request). Nothing here creates, scores or promotes one.
   No composite score. Valuation numbers are model results of analyst-entered assumptions, never a price objective. */
'use strict';
const EDU = 'For educational and research purposes only; not investment advice; users must make their own decisions under their own registrations.';
const eduBig = () => `<div class="edu big" role="note"><b>Educational and research use only.</b> ${EDU} Every number below the assumptions line is the arithmetic result of analyst-entered inputs, not a forecast and not a price objective.</div>`;
const STG = { discovery: 'Discovery', validation: 'Validation', emergence: 'Emergence', investable_review: 'Investable review', invalidated: 'Invalidated', archived: 'Archived' };
const stg = s => `<span class="chip stg ${esc(s)}">${esc(STG[s] || s)}</span>`;
const dir = d => `<span class="${d === 'positive' ? 'pos' : d === 'negative' ? 'neg' : 'muted'}">${esc(d || '')}</span>`;
const DIMN = { structural_demand: 'Structural demand', industry_economics: 'Industry economics', competitive_position: 'Competitive position', capital_allocation: 'Capital allocation', company_execution: 'Company execution', valuation: 'Valuation' };
const entLink = (t, id, name) => t === 'company' ? coLink(id, name) : t === 'industry' ? secLink(id) : esc(name || id);
const days = (a, b) => (a && b) ? Math.round((new Date(b.slice(0, 10)) - new Date(a.slice(0, 10))) / 864e5) : null;
const pct = (x, d = 1) => isNum(x) ? (x * 100).toFixed(d) + '%' : NA;
const crn = x => isNum(x) ? '₹' + inr(x) + ' cr' : NA;

/* ---------------- Signals ---------------- */
ROUTES.signals = async () => {
  const S = await J('v2/signals.json');
  const f = store.get('sigf', {}); const all = S.signals;
  const rs = all.filter(s => (!f.t || s.signal_type === f.t) && (!f.d || s.direction === f.d) && (!f.r || s.rule_id === f.r) && (!f.i || s.industry_id === f.i) && (!f.st || s.status === f.st));
  const opt = (k, vals, lbl) => `<label>${lbl} <select onchange="setSigf('${k}',this.value)"><option value="">All</option>${vals.map(v => `<option ${f[k] === v ? 'selected' : ''} value="${esc(v)}">${esc(k === 'i' ? ind(v) : v)}</option>`).join('')}</select></label>`;
  const uniq = k => [...new Set(all.map(s => s[k]).filter(Boolean))].sort();
  page(`<h1>Signals</h1>
  <div class="card method"><p>A signal is a measured change in disclosed data, found by a fixed rule (no language model). <b>Observed</b> is the data period the change belongs to; <b>detected</b> is the first build that saw it, so the gap shows how quickly the platform picked it up. <b>Validated</b> means the signal has a source document with a link, its source is working, and the data is fresh for that rule. A signal describes money or credit movement; it is not a view on any security.</p>
  <details><summary>Detection rules (${Object.keys(S.rules).length})</summary><table>${Object.entries(S.rules).map(([k, r]) => `<tr><td><code>${esc(k)}</code></td><td>${esc(r.type)}</td><td>${esc(r.text)}</td></tr>`).join('')}</table></details></div>
  <div class="card noprint flt">${opt('t', uniq('signal_type'), 'Type')}${opt('d', uniq('direction'), 'Direction')}${opt('r', uniq('rule_id'), 'Rule')}${opt('i', uniq('industry_id'), 'Industry')}${opt('st', uniq('status'), 'Status')}<button class="small" onclick="store.set('sigf',{});route()">Reset</button></div>
  <div class="card">${tbl([
    { h: 'Observed', v: r => r.observed_at }, { h: 'Detected', v: r => (r.detected_at || '').slice(0, 10) }, { h: 'Lag (days)', n: 1, v: r => days(r.observed_at, r.detected_at) },
    { h: 'Signal', v: r => r.title, f: r => `${esc(r.title)}<div class="small muted">${esc(r.description || '')}</div>` },
    { h: 'Entity', v: r => r.entity_name, f: r => entLink(r.entity_type, r.entity_id, r.entity_name) },
    { h: 'Direction', v: r => r.direction, f: r => dir(r.direction) }, { h: 'Magnitude', n: 1, v: r => r.magnitude, f: r => isNum(r.magnitude) ? `${r.magnitude} <span class="small muted">${esc(r.unit || '')}</span>` : NA },
    { h: 'Status', v: r => r.status, f: r => `<span class="chip" title="${esc(r.validation_note || '')}">${esc(r.status)}</span>` },
    { h: 'Source', v: r => r.source_name || r.source_id, f: r => `${srcId(r.source_id)} ${srcA(r.url, 'document')} ${lab(r.evidence_label)}` }], rs, { file: 'signals', note: `${all.length} signals exported` })}</div>`);
};
window.setSigf = (k, v) => { const f = store.get('sigf', {}); f[k] = v; store.set('sigf', f); route(); };

/* ---------------- Opportunity Discovery (research hypotheses) ---------------- */
function covChips(c) { return Object.entries(c.dimensions).map(([k, v]) => `<span class="chip ${v ? 'cov' : ''}" title="${v ? 'validated evidence linked' : 'no evidence linked'}">${esc(DIMN[k])}${v ? ' ✓' : ''}</span>`).join(''); }
function evLine(e) { return e ? `${dir(e.direction)} ${esc(e.title || e.explanation || '')} <span class="small muted">(${esc(e.observed_at || '')}; ${esc(e.source_id || '')})</span>` : NA; }
function oppCard(o) {
  const sup = o.evidence.filter(e => e.role === 'supporting'), con = o.evidence.filter(e => e.role === 'contradicting');
  const recent = [...o.evidence].sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at))).slice(0, 3);
  return `<div class="card opp">
   <div class="flt" style="justify-content:space-between"><h2 style="margin:0"><a href="#/opportunities/${esc(o.opportunity_id)}">${esc(o.title)}</a></h2><span>${stg(o.stage)} ${o.starter_hypothesis ? '<span class="chip starter" title="Seeded from detected signals; needs analyst review">starter hypothesis</span>' : ''}</span></div>
   <div class="small muted">${secLink(o.industry_id)} · ${esc(o.geography)} · horizon ${esc(o.horizon)} · owner: ${esc(o.owner)}</div>
   <p>${esc(o.thesis)}</p>
   ${o.criteria_met_for_later_stage ? `<p class="small amb">Criteria for <b>${esc(STG[o.criteria_met_for_later_stage])}</b> are met. The stage changes only when an analyst records a thesis update.</p>` : ''}
   <div class="g2"><div><h3>Recent material developments</h3>${recent.map(e => `<div class="small">${evLine(e)}</div>`).join('') || NA}</div>
   <div><h3>Companies linked (analyst)</h3>${o.companies.map(c => `<div class="small">${coLink(c.company_id, c.name)} <span class="chip">${esc(c.role.replace(/_/g, ' '))}</span> <span class="muted">${esc(c.note || '')}</span></div>`).join('') || NA}
   <div class="small muted">Beneficiaries and pressured companies: ${o.companies.some(c => c.role !== 'context') ? 'see roles above' : 'not yet assessed by an analyst'}</div></div></div>
   <div class="g2"><div><h3>Strongest supporting evidence</h3><div class="small">${evLine(sup[0])}</div></div><div><h3>Strongest opposing evidence</h3><div class="small">${evLine(con[0])}</div></div></div>
   <h3>Evidence coverage (${Math.round(o.coverage.share * 100)}% of 6 dimensions)</h3>${covChips(o.coverage)}
   <div class="small muted">Dimension scores: not assessed in Sprint 1. There is no composite score.</div>
   <div class="small">Next review: <b class="${o.overdue ? 'neg' : ''}">${esc(o.next_review || 'not set')}${o.overdue ? ' (overdue)' : ''}</b> · <a href="#/opportunities/${esc(o.opportunity_id)}">Open dossier →</a></div></div>`;
}
ROUTES.opportunities = async (arg) => {
  if (arg) return dossier(arg);
  const O = await J('v2/opportunities.json'); const f = store.get('oppf', {});
  const os = O.opportunities.filter(o => (!f.i || o.industry_id === f.i) && (!f.h || o.horizon === f.h) && (!f.s || o.stage === f.s) && (!f.c || o.coverage.share >= +f.c) &&
    (!f.e || (f.e === 'contra' ? o.evidence.some(e => e.role === 'contradicting') : !o.evidence.some(e => e.role === 'contradicting'))));
  const opt = (k, vals, lbl, nm = v => v) => `<label>${lbl} <select onchange="setOppf('${k}',this.value)"><option value="">All</option>${vals.map(v => `<option ${String(f[k]) === String(v) ? 'selected' : ''} value="${esc(v)}">${esc(nm(v))}</option>`).join('')}</select></label>`;
  page(`<h1>Opportunity Discovery <span class="muted small">research hypotheses</span></h1>
  <div class="edu">${EDU}</div>
  <div class="card method"><p>Each card is a <b>research hypothesis</b> about how part of the economy is changing. It is not a view on any security. Hypotheses are written by an analyst and committed through a reviewed change (see <a href="#/analyst">Analyst workspace</a>); the pipeline never creates, scores or promotes one. It links evidence, checks the stage criteria and lists new signals for review.</p>
  <p class="small">Stages: ${O.stages.map(s => `${stg(s)} ${esc(O.stage_criteria[s])}`).join('<br>')}</p>
  ${O.analyst_file_errors.length ? `<p class="neg">Analyst file problems: ${O.analyst_file_errors.map(esc).join('; ')}</p>` : ''}</div>
  <div class="card noprint flt">${opt('i', [...new Set(O.opportunities.map(o => o.industry_id))], 'Industry', ind)}${opt('h', O.horizons, 'Horizon')}${opt('s', O.stages.concat(O.end_stages), 'Stage', s => STG[s])}
   ${opt('c', ['0.17', '0.33', '0.5'], 'Evidence coverage ≥', v => Math.round(v * 100) + '%')}${opt('e', ['contra', 'nocontra'], 'Opposing evidence', v => v === 'contra' ? 'has opposing evidence' : 'none linked')}
   <button class="small" onclick="store.set('oppf',{});route()">Reset</button></div>
  ${os.map(oppCard).join('') || '<div class="card na">No hypothesis matches these filters.</div>'}`);
};
window.setOppf = (k, v) => { const f = store.get('oppf', {}); f[k] = v; store.set('oppf', f); route(); };

async function dossier(id) {
  const [O, Vd, Fd, Id] = await Promise.all([J('v2/opportunities.json'), J('v2/valuation.json'), J('v2/fundamentals.json').catch(() => null), J('v2/industry.json').catch(() => null)]);
  const o = O.opportunities.find(x => x.opportunity_id === id);
  if (!o) return page(`<div class="card"><h2>Hypothesis not found</h2><p><a href="#/opportunities">Back to Opportunity Discovery</a></p></div>`);
  const sec = await J('sectors.json').then(s => s.sectors.find(x => x.id === o.industry_id)).catch(() => null);
  const evT = rs => tbl([{ h: 'Role', v: r => r.role }, { h: 'Observed', v: r => r.observed_at }, { h: 'Detected', v: r => (r.detected_at || '').slice(0, 10) },
    { h: 'Evidence', v: r => r.title, f: r => `${esc(r.title || '')}<div class="small muted">${esc(r.explanation || '')}</div>` }, { h: 'Entity', v: r => r.entity_name, f: r => entLink(r.entity_type, r.entity_id, r.entity_name) },
    { h: 'Direction', v: r => r.direction, f: r => dir(r.direction) }, { h: 'Weight (analyst)', n: 1, v: r => r.materiality }, { h: 'Status', v: r => r.signal_status },
    { h: 'Source', v: r => r.source_id, f: r => `${srcId(r.source_id)} ${srcA(r.url, 'document')}` }], rs, { file: 'evidence_' + id });
  const vals = Vd.valuations.filter(v => v.opportunity_id === id);
  const m = sec ? sec.metrics : {};
  const nd = t => `<p class="na">insufficient data: ${t}</p>`;
  page(`<p><a href="#/opportunities">← Opportunity Discovery</a></p>
  <h1>${esc(o.title)} ${stg(o.stage)} ${o.starter_hypothesis ? '<span class="chip starter">starter hypothesis</span>' : ''}</h1>
  ${eduBig()}
  <div class="small muted">Opportunity Dossier · ${secLink(o.industry_id)} · ${esc(o.geography)} · horizon ${esc(o.horizon)} · owner ${esc(o.owner)} · created ${esc(o.created_at)} · next review ${esc(o.next_review || 'not set')}${o.overdue ? ' <b class="neg">overdue</b>' : ''}</div>
  <div class="card"><h3>Hypothesis</h3><p>${esc(o.thesis)}</p>${(o.detail.open_questions || []).length ? `<h3>Open questions</h3><ul>${o.detail.open_questions.map(q => `<li>${esc(q)}</li>`).join('')}</ul>` : ''}</div>
  <div class="card"><h3>Stage criteria (checked by the pipeline; the stage itself is set only by an analyst)</h3><table>${O.stages.map(s => `<tr><td>${stg(s)}</td><td>${o.criteria[s].met ? '<span class="pos">met</span>' : '<span class="muted">not met</span>'}</td><td class="small">${esc(O.stage_criteria[s])}<br><span class="muted">${esc(o.criteria[s].why)}</span></td></tr>`).join('')}</table></div>
  <div class="card"><h3>Structural changes: linked evidence</h3>${evT(o.evidence)}</div>
  <div class="g2">
   <div class="card"><h3>Indian industry context (${esc(o.industry_name || '')})</h3>${sec ? `<table>
    <tr><td>FPI net flow, 3 months, % of FPI holdings</td><td class="n">${pc(m.fpi_flow_3m, 2)}</td></tr><tr><td>FPI net flow, 12 months, % of holdings</td><td class="n">${pc(m.fpi_flow_12m, 2)}</td></tr>
    <tr><td>Fund-house net breadth, latest month</td><td class="n">${pc(m.mf_amc_net_breadth_1m, 0)}</td></tr><tr><td>Institutional breadth, latest quarter</td><td class="n">${isNum(m.inst_breadth_qoq) ? m.inst_breadth_qoq.toFixed(0) + '%' : NA}</td></tr>
    <tr><td>Bank credit, YoY</td><td class="n">${pc(m.bank_credit_yoy)}</td></tr><tr><td>Sector index P/E (${esc((sec.pe || {}).name || '')}), 10-year percentile</td><td class="n">${isNum((sec.pe || {}).pe) ? sec.pe.pe + ' (' + sec.pe.pctl_10y + ')' : NA}</td></tr></table>
    <div class="src">${lab('VERIFIED FACT')} from the v1 sector build · <a href="#/sectors/${esc(o.industry_id)}">full sector page</a></div>` : NA}</div>
   <div class="card"><h3>Industry economics, production and trade</h3>${indCard(o.industry_id, Fd, Id)}</div>
  </div>
  <div class="g2">
   <div class="card"><h3>Company universe (analyst-linked)</h3>${o.companies.length ? `<table>${o.companies.map(c => `<tr><td>${coLink(c.company_id, c.name)}</td><td><span class="chip">${esc(c.role.replace(/_/g, ' '))}</span></td><td class="small">${esc(c.note || '')}</td><td><a href="#/valuation/${esc(c.company_id.split(':').pop())}">Valuation Lab</a></td></tr>`).join('')}</table>` : NA}</div>
   <div class="card"><h3>Valuation (analyst models)</h3>${vals.length ? vals.map(v => `<div>${esc(v.company_name)} · ${esc(v.as_of)} · ${esc(v.analyst)}: model annual return ${pct(v.forward && v.forward.model_annual_return)} ${lab('SCENARIO')}</div>`).join('') : '<p class="na">No analyst valuation linked yet. Use the Valuation Lab and commit the result.</p>'}</div>
  </div>
  <div class="card"><h3>Bull / base / bear scenarios (analyst-assigned probabilities)</h3>${o.scenarios.length ? tbl([{ h: 'Scenario', v: r => r.scenario_name }, { h: 'Probability', n: 1, v: r => r.probability, f: r => isNum(r.probability) ? r.probability + '%' : '<span class="na">not assigned</span>' },
    { h: 'Assumptions', v: r => JSON.stringify(r.assumptions) }, { h: 'Expected outcome', v: r => r.expected_outcome }, { h: 'Confirms if', v: r => r.confirmation_conditions }, { h: 'Invalidated if', v: r => r.invalidation_conditions }, { h: 'Review', v: r => r.review_date }], o.scenarios) : '<p class="na">No scenarios entered yet. Probabilities are analyst-assigned and must total 100%.</p>'}</div>
  <div class="g2"><div class="card"><h3>Confirmation conditions</h3><ul>${(o.detail.confirmation_conditions || []).map(c => `<li>${esc(c)}</li>`).join('') || '<li class="na">none recorded</li>'}</ul></div>
  <div class="card"><h3>Invalidation conditions</h3><ul>${(o.detail.invalidation_conditions || []).map(c => `<li>${esc(c)}</li>`).join('') || '<li class="na">none recorded</li>'}</ul></div></div>
  <div class="card"><h3>New related signals not yet reviewed (120 days)</h3>${tbl([{ h: 'Observed', v: r => r.observed_at }, { h: 'Signal', v: r => r.title }, { h: 'Direction', v: r => r.direction, f: r => dir(r.direction) }, { h: 'Source', v: r => r.source_id, f: r => srcId(r.source_id) }], o.related_unlinked, { empty: 'none: every recent signal for this industry and its companies is already linked' })}</div>
  <div class="card"><h3>Research history (append-only)</h3>${historyT(o.history)}</div>
  <div class="card"><h3>Global developments (Global Radar)</h3>${globCard(o.industry_id, Id)}</div>`);
}
function indCard(ind, Fd, Id) {
  const a = Fd && Fd.sectors ? Fd.sectors[ind] : null, x = Id && Id.sectors ? Id.sectors[ind] : null;
  const rows = [];
  rows.push(`<tr><td>Listed companies' revenue, latest quarter YoY</td><td class="n">${a ? fx(a.revenue_yoy_pct, 1, '%') + ` <span class="small muted">(${a.companies} cos, ${esc(a.quarter || '')})</span>` : NA}</td></tr>`);
  rows.push(`<tr><td>Aggregate EBITDA margin (change YoY)</td><td class="n">${a && isNum(a.ebitda_margin_pct) ? a.ebitda_margin_pct + '% (' + (a.ebitda_margin_change_pp > 0 ? '+' : '') + a.ebitda_margin_change_pp + ' pp)' : NA}</td></tr>`);
  const iip = x && x.iip ? x.iip : [];
  iip.forEach(i => { const l = i.yoy[i.yoy.length - 1]; rows.push(`<tr><td>IIP: ${esc(i.label.split(' | ').pop())}</td><td class="n">${l ? fx(l[1], 1, '%') + ' <span class="small muted">YoY ' + esc(l[0].slice(0, 7)) + '</span>' : NA} ${i.url ? srcA(i.url, 'MoSPI') : ''}</td></tr>`); });
  if (!iip.length) rows.push(`<tr><td>Industrial production (IIP)</td><td>${NA} <span class="small muted">no IIP industry maps to this sector</span></td></tr>`);
  const t = x && x.trade ? x.trade.years : [];
  const ly = t[t.length - 1], py = t[t.length - 2];
  rows.push(`<tr><td>Merchandise exports / imports (${ly ? 'FY to ' + esc(ly.fy_end.slice(0, 4)) : ''})</td><td class="n">${ly ? 'US$ ' + inr(ly.exports_usd_mn) + ' mn / US$ ' + inr(ly.imports_usd_mn) + ' mn' : NA + ' <span class="small muted">no HS chapter maps to this sector</span>'}</td></tr>`);
  if (ly) rows.push(`<tr><td>Import share of trade (previous year)</td><td class="n">${fx(ly.import_share_pct, 1, '%')} (${py ? fx(py.import_share_pct, 1, '%') : NA})</td></tr>`);
  return `<table>${rows.join('')}</table><div class="src">${lab('VERIFIED FACT')} NSE XBRL results, MoSPI IIP, Ministry of Commerce TradeStat · <a href="#/industry/${esc(ind)}">industry data page</a></div>`;
}
function globCard(ind, Id) {
  const cs = Id && Id.commodities ? Id.commodities.filter(c => c.sectors.some(s => s.industry_id === ind)) : [];
  if (!cs.length) return '<p class="na">insufficient data: no tracked commodity is mapped to this sector (see the Global page for rates, the dollar and Brent).</p>';
  return `<table>${cs.map(c => { const v = c.values, l = v[v.length - 1], b = v[v.length - 4]; const ch = l && b && b[1] ? 100 * (l[1] / b[1] - 1) : null;
    return `<tr><td>${esc(c.name)}</td><td class="n">${l ? inr(l[1], 2) + ' ' + esc(c.unit) : NA} <span class="small muted">${l ? esc(l[0].slice(0, 7)) : ''}</span></td><td class="n">${fx(ch, 1, '%')} <span class="small muted">3m</span></td><td class="small">${esc(c.sectors.find(s => s.industry_id === ind).why)}</td><td>${srcA(c.url, 'FRED')}</td></tr>`; }).join('')}</table>
  <div class="src">Commodity-to-sector links are a fixed, rule-based table (first-order exposure only).</div>`;
}

/* ---------------- Industry data (Sprint 2) ---------------- */
ROUTES.industry = async (ind) => {
  const [Id, Fd] = await Promise.all([J('v2/industry.json'), J('v2/fundamentals.json')]);
  const secs = Object.keys(Id.sectors).sort();
  const st = Object.entries(Id.source_status || {});
  const x = ind ? Id.sectors[ind] : null;
  const ob = Id.obicus || {};
  const last = a => a && a.length ? a[a.length - 1] : null;
  page(`<h1>Industry data <span class="muted small">production, capacity, trade, company results</span></h1><div class="edu">${EDU}</div>
  <div class="card noprint flt"><label>Sector <select onchange="location.hash='#/industry/'+this.value"><option value="">Overview</option>${secs.map(s => `<option ${s === ind ? 'selected' : ''} value="${esc(s)}">${esc(s.replace(/_/g, ' '))}</option>`).join('')}</select></label></div>
  ${x ? `<div class="g2"><div class="card"><h3>Production (MoSPI IIP, YoY %)</h3>${(x.iip || []).length ? tbl([{ h: 'Industry', v: r => r.label }, { h: 'Latest month', v: r => (last(r.yoy) || [])[0] }, { h: 'YoY', n: 1, v: r => (last(r.yoy) || [])[1], f: r => fx((last(r.yoy) || [])[1], 1, '%') }, { h: 'Source', v: r => r.url, f: r => srcA(r.url, 'MoSPI') }], x.iip) : '<p class="na">insufficient data: no IIP industry maps to this sector</p>'}</div>
   <div class="card"><h3>Merchandise trade (TradeStat, US$ mn, financial years)</h3>${x.trade ? tbl([{ h: 'FY ending', v: r => r.fy_end }, { h: 'Exports', n: 1, v: r => r.exports_usd_mn, f: r => inr(r.exports_usd_mn) }, { h: 'Imports', n: 1, v: r => r.imports_usd_mn, f: r => inr(r.imports_usd_mn) }, { h: 'Net', n: 1, v: r => r.net_usd_mn, f: r => inr(r.net_usd_mn) }, { h: 'Import share of trade', n: 1, v: r => r.import_share_pct, f: r => fx(r.import_share_pct, 1, '%') }], x.trade.years, { file: 'trade_' + ind }) + `<p class="small muted">HS chapters: ${Object.entries(x.trade.chapters).map(([k, v]) => esc(k + ' ' + v)).join('; ')}</p>` : '<p class="na">insufficient data: no HS chapter maps to this sector</p>'}</div></div>
   <div class="card"><h3>Company results (NSE XBRL, latest quarter)</h3>${coResults(Fd, ind)}</div>` : ''}
  <div class="g2"><div class="card"><h3>Manufacturing capacity utilisation (RBI OBICUS)</h3>${tbl([{ h: 'Quarter ending', v: r => r[0] }, { h: 'CU %', n: 1, v: r => r[1] }, { h: 'CU % (seasonally adjusted)', n: 1, v: r => r[2] }, { h: 'New orders YoY %', n: 1, v: r => r[3] }],
    (ob.obicus_cu_pct || []).map(([d, v]) => [d, v, ((ob.obicus_cu_sa_pct || []).find(z => z[0] === d) || [])[1], ((ob.obicus_new_orders_yoy_pct || []).find(z => z[0] === d) || [])[1]]))} ${Id.obicus_url ? srcA(Id.obicus_url, 'RBI release') : ''}</div>
   <div class="card"><h3>Overall IIP, YoY %</h3>${tbl([{ h: 'Month', v: r => r[0].slice(0, 7) }, { h: 'YoY %', n: 1, v: r => r[1] }], (Id.iip_general_yoy || []).slice(-12).reverse())}</div></div>
  <div class="card"><h3>Global Radar: commodity prices (monthly)</h3>${tbl([{ h: 'Commodity', v: r => r.name }, { h: 'Latest', n: 1, v: r => (last(r.values) || [])[1], f: r => fx((last(r.values) || [])[1], 2) + ' ' + esc(r.unit) }, { h: 'Month', v: r => ((last(r.values) || [])[0] || '').slice(0, 7) },
    { h: '3-month change', n: 1, v: r => { const v = r.values, b = v[v.length - 4]; return b && b[1] ? 100 * (v[v.length - 1][1] / b[1] - 1) : null; }, f: r => { const v = r.values, b = v[v.length - 4]; return b && b[1] ? fx(100 * (v[v.length - 1][1] / b[1] - 1), 1, '%') : NA; } },
    { h: 'Exposed sectors (fixed table)', v: r => r.sectors.map(s => s.industry_id).join(', '), f: r => r.sectors.map(s => `<span title="${esc(s.why)}">${secLink(s.industry_id)}</span>`).join(', ') }, { h: 'Source', v: r => r.url, f: r => srcA(r.url, 'FRED') }], Id.commodities || [], { file: 'commodities' })}</div>
  <div class="card"><h3>Source status</h3>${tbl([{ h: 'Source', v: r => r[0] }, { h: 'Status', v: r => r[1].status }, { h: 'Last success', v: r => r[1].last_success }, { h: 'Latest period', v: r => r[1].latest_period }], st)}</div>
  <div class="card method small">${(Id.notes || []).map(n => `<p>${esc(n)}</p>`).join('')}</div>`);
};
function coResults(Fd, ind) {
  const cs = Object.values(Fd.companies || {}).filter(c => c.industry_id === ind);
  if (!cs.length) return '<p class="na">insufficient data: no filings loaded for this sector</p>';
  return tbl([{ h: 'Company', v: r => r.name, f: r => coLink(r.company_id, r.name) }, { h: 'Quarter', v: r => r.latest_quarter }, { h: 'Revenue ₹ cr', n: 1, v: r => r.q.revenue_cr, f: r => inr(r.q.revenue_cr) },
    { h: 'Revenue YoY', n: 1, v: r => r.q.revenue_yoy_pct, f: r => fx(r.q.revenue_yoy_pct, 1, '%') }, { h: 'EBITDA margin', n: 1, v: r => r.q.ebitda_margin_pct, f: r => fx(r.q.ebitda_margin_pct, 1, '%') },
    { h: 'Margin chg (pp)', n: 1, v: r => r.q.ebitda_margin_change_pp, f: r => fx(r.q.ebitda_margin_change_pp, 1) }, { h: 'ROCE FY', n: 1, v: r => (r.returns || {}).roce_pct, f: r => fx((r.returns || {}).roce_pct, 1, '%') },
    { h: 'ROIC FY', n: 1, v: r => (r.returns || {}).roic_pct, f: r => fx((r.returns || {}).roic_pct, 1, '%') }, { h: 'Incr. ROIC', n: 1, v: r => (r.returns || {}).incremental_roic_pct, f: r => fx((r.returns || {}).incremental_roic_pct, 1, '%') },
    { h: 'Filing', v: r => r.source_url, f: r => srcA(r.source_url, 'XBRL') }], cs, { file: 'results_' + ind });
}
const historyT = h => tbl([{ h: 'Date', v: r => r.update_date }, { h: 'Recorded', v: r => (r.recorded_at || '').slice(0, 16) }, { h: 'From', v: r => r.previous_stage, f: r => r.previous_stage ? stg(r.previous_stage) : '<span class="muted">created</span>' },
  { h: 'To', v: r => r.new_stage, f: r => stg(r.new_stage) }, { h: 'Summary', v: r => r.summary }, { h: 'Author', v: r => r.author }], h, { empty: 'no updates recorded' });

/* ---------------- Investable review ---------------- */
ROUTES.investable = async () => {
  const O = await J('v2/opportunities.json');
  const os = O.opportunities.filter(o => o.stage === 'investable_review');
  page(`<h1>Investable review</h1>${eduBig()}
  <div class="card method"><p>This stage holds hypotheses whose company-level economics, valuation, downside and expected returns have been assessed by an analyst. Criteria: ${esc(O.stage_criteria.investable_review)} An analyst records the move in the thesis history; the pipeline only checks the criteria.</p>
  <p>Being in this stage means the research is complete enough to review. It is not a view on whether to transact in any security; users decide for themselves under their own registrations.</p></div>
  ${os.length ? os.map(oppCard).join('') : `<div class="card"><p class="na">No hypothesis is at this stage yet.</p><p class="small">Closest: ${O.opportunities.map(o => `${esc(o.title)}: ${stg(o.stage)}, investable-review criteria ${o.criteria.investable_review.met ? 'met' : 'not met'} (${esc(o.criteria.investable_review.why)})`).join('<br>') || 'none'}</p></div>`}`);
};

/* ---------------- Thesis Monitor ---------------- */
ROUTES.thesis = async () => {
  const [O, Vd] = await Promise.all([J('v2/opportunities.json'), J('v2/valuation.json')]);
  page(`<h1>Thesis Monitor</h1><div class="edu">${EDU}</div>
  <div class="card method"><p>History is append-only: an update can't be edited, deleted or back-dated (the database refuses it, and the build rejects a changed file). A stage change shows the date it was actually recorded.</p></div>
  ${O.opportunities.map(o => {
    const first = o.history[0], since = first ? first.recorded_at || first.update_date : o.created_at;
    const newer = o.related_unlinked.filter(s => (s.detected_at || '') > (since || ''));
    const vals = Vd.valuations.filter(v => v.opportunity_id === o.opportunity_id).sort((a, b) => a.as_of.localeCompare(b.as_of));
    return `<div class="card"><h2 style="margin-top:0"><a href="#/opportunities/${esc(o.opportunity_id)}">${esc(o.title)}</a> ${stg(o.stage)}</h2>
    <div class="g2"><div><table>
     <tr><td>Original thesis date</td><td>${esc(first ? first.update_date : o.created_at)}</td></tr>
     <tr><td>Original assumptions</td><td class="small">${esc(first ? first.summary : '')}</td></tr>
     <tr><td>Original valuation</td><td>${vals.length ? `${esc(vals[0].as_of)}: model annual return ${pct(vals[0].forward && vals[0].forward.model_annual_return)} ${lab('SCENARIO')}` : '<span class="na">none recorded</span>'}</td></tr>
     <tr><td>Revised valuations</td><td>${vals.length > 1 ? vals.slice(1).map(v => `${esc(v.as_of)}: ${pct(v.forward && v.forward.model_annual_return)}`).join('<br>') : '<span class="na">none</span>'}</td></tr>
     <tr><td>Next review</td><td class="${o.overdue ? 'neg' : ''}">${esc(o.next_review || 'not set')}${o.overdue ? ' (overdue)' : ''}</td></tr>
     <tr><td>Evidence linked</td><td>${o.evidence.filter(e => e.role === 'supporting').length} supporting · ${o.evidence.filter(e => e.role === 'contradicting').length} opposing</td></tr></table></div>
    <div><h3>Invalidation events to watch</h3><ul>${(o.detail.invalidation_conditions || []).map(c => `<li class="small">${esc(c)}</li>`).join('') || '<li class="na">none recorded</li>'}</ul>
     <h3>New evidence since the thesis was recorded</h3>${newer.length ? newer.slice(0, 8).map(s => `<div class="small">${dir(s.direction)} ${esc(s.title)} <span class="muted">${esc(s.observed_at)}</span></div>`).join('') : '<p class="small muted">No new related signals since the thesis was recorded.</p>'}</div></div>
    <h3>Stage history</h3>${historyT(o.history)}</div>`;
  }).join('') || '<div class="card na">No hypotheses recorded.</div>'}`);
};

/* ---------------- Valuation Lab ---------------- */
const VF = [['revenue0', 'Base-year revenue (₹ cr)', 'cr', 1], ['growth', 'Revenue growth per year (%)', '%'], ['margin', 'Operating (EBIT) margin (%)', '%'], ['tax', 'Tax rate (%)', '%'],
  ['roic', 'Return on new invested capital (%)', '%', 0, 'roic'], ['capex_pct', 'Net capex (% of revenue)', '%', 0, 'explicit'], ['wc_pct', 'Working capital (% of revenue added)', '%', 0, 'explicit'],
  ['wacc', 'Cost of capital (%)', '%'], ['g_term', 'Terminal growth (%)', '%'], ['years', 'Horizon (years)', 'n'], ['net_debt', 'Net debt (₹ cr; negative = net cash)', 'cr', 1], ['market_value', 'Current market value of equity (₹ cr)', 'cr', 1]];
function readA() {
  const a = { mode: $('#v_mode').value }; const notes = {};
  for (const [k, , u, note] of VF) { const el = $('#v_' + k); if (!el) continue; const raw = el.value.trim(); a[k] = raw === '' ? null : (u === '%' ? +raw / 100 : +raw); if (note) notes[k] = ($('#n_' + k) || {}).value || ''; }
  return { a, notes };
}
ROUTES.valuation = async (sym) => {
  const [Vd, C] = await Promise.all([J('v2/valuation.json'), J('companies.json')]);
  const cols = C.cols, rows = C.rows.map(r => Object.fromEntries(cols.map((c, i) => [c, r[i]])));
  const co = sym ? rows.find(r => r.symbol === sym) : null;
  const draft = store.get('valdraft_' + (sym || ''), null);
  const pr = co ? Vd.reported_price[co.id] : null, spe = co ? Vd.sector_pe[co.industry] : null;
  const val = (k, u) => { const v = draft && draft.a ? draft.a[k] : null; return v == null ? '' : (u === '%' ? +(v * 100).toFixed(4) : v); };
  const pub = Vd.valuations.filter(v => !co || v.company_id === co.id);
  page(`<h1>Valuation Lab</h1>${eduBig()}
  <div class="card noprint flt"><label>Company <input id="v_co" list="v_list" placeholder="Type a symbol, e.g. ITC" value="${esc(sym || '')}"></label><datalist id="v_list">${rows.filter(r => r.nifty500).map(r => `<option value="${esc(r.symbol)}">${esc(r.name)}</option>`).join('')}</datalist>
   <button onclick="location.hash='#/valuation/'+encodeURIComponent($('#v_co').value.trim().toUpperCase())">Open</button>
   <span class="muted small">Asks: what must happen for this company's equity to compound at 15%, 20% or 25% a year?</span></div>
  <div class="g2">
   <div class="card reported"><h3>Reported data ${lab('VERIFIED FACT')}</h3>${co ? `<table>
    <tr><td>Company</td><td>${coLink(co.id, co.name)} · ${secLink(co.industry)}</td></tr>
    <tr><td>Month-end price in fund-house files</td><td>${pr ? `₹${inr(pr.price_inr, 2)} (${esc(pr.period)}) ${srcA(pr.url, 'file')}<div class="small muted">market value ÷ shares held, as filed by the fund house</div>` : NA}</td></tr>
    <tr><td>Sector index P/E</td><td>${spe && isNum(spe.pe) ? `${spe.pe} (${esc(spe.index)}, ${esc(spe.as_of)}); 10-year percentile ${spe.pctl_10y}, median ${spe.median_10y}` : NA}</td></tr>
    <tr><td>Institutional holding</td><td>${isNum(co.inst_pct) ? co.inst_pct + '% (' + (isNum(co.inst_qoq_pp) ? (co.inst_qoq_pp > 0 ? '+' : '') + co.inst_qoq_pp + ' pp QoQ' : 'QoQ n/a') + ')' : NA}</td></tr>
    <tr><td>Promoter holding</td><td>${isNum(co.promoter_pct) ? co.promoter_pct + '%' : NA}</td></tr>
    ${repRows(Vd, co.id)}
    ${(Vd.not_ingested || []).map(x => `<tr><td>${esc(x)}</td><td>${NA} <span class="small muted">(not ingested; enter it on the right with its source)</span></td></tr>`).join('')}</table>
    <div class="src">${esc(Vd.note)}</div>${repFormulas(Vd)}` : '<p class="muted">Pick a company to see its reported data.</p>'}</div>
   <div class="card assumptions"><h3>Analyst assumptions <span class="lab UN">ANALYST ASSUMPTION</span></h3>
    <p class="small muted">Blank until you enter them. Nothing is prefilled or estimated for you. Figures taken from reports need a source note.</p>
    <label>Reinvestment method <select id="v_mode" onchange="valMode()"><option value="roic" ${(draft && draft.a && draft.a.mode) === 'explicit' ? '' : 'selected'}>From return on new capital</option><option value="explicit" ${(draft && draft.a && draft.a.mode) === 'explicit' ? 'selected' : ''}>Explicit net capex + working capital</option></select></label>
    <table>${VF.map(([k, l, u, note, mode]) => `<tr class="vrow" data-mode="${mode || ''}"><td>${esc(l)}</td><td><input id="v_${k}" type="number" step="any" value="${val(k, u)}" style="width:110px"></td><td>${note ? `<input id="n_${k}" placeholder="source note (required)" value="${esc((draft && draft.notes && draft.notes[k]) || '')}">` : ''}</td></tr>`).join('')}</table>
    <div class="flt"><button onclick="valRun('${esc(sym || '')}')">Calculate</button><button onclick="valSave('${esc(sym || '')}')">Save draft in this browser</button><button onclick="valExport('${esc(co ? co.id : '')}')">Download entry for review (JSON)</button></div>
    <p class="small muted">To publish, add the downloaded entry to <code>data/analyst/valuations.json</code> in a pull request. The build re-checks it and stores it with the date.</p></div>
  </div>
  <div id="v_out"></div>
  <div class="card"><h3>Published analyst valuations${co ? ' for ' + esc(co.name) : ''}</h3>${pub.length ? tbl([{ h: 'As of', v: r => r.as_of }, { h: 'Company', v: r => r.company_name }, { h: 'Analyst', v: r => r.analyst }, { h: 'Model annual return', n: 1, v: r => r.forward && r.forward.model_annual_return, f: r => pct(r.forward && r.forward.model_annual_return) }, { h: 'Label', v: r => r.label }], pub) : '<p class="na">None published yet.</p>'}</div>`);
  valMode(); if (draft && draft.a) valRun(sym || '');
};
const fx = (x, d = 1, suf = '') => isNum(x) ? (+x).toFixed(d) + suf : NA;
function repRows(Vd, cid) {
  const r = (Vd.reported || {})[cid];
  if (!r) return `<tr><td>Company financials</td><td>${NA} <span class="small muted">(no NSE XBRL filing loaded for this company yet)</span></td></tr>`;
  const R = r.returns || {}, fin = r.financial_sector_format;
  const src = (u, t) => u ? srcA(u, t) : '';
  return `<tr><td>Revenue, trailing 4 quarters</td><td>${crn(r.revenue_ttm_cr)} <span class="small muted">to ${esc(r.revenue_ttm_period || '')}</span> ${src(r.source_url, 'XBRL')}<div class="small muted">${r.basis ? esc(r.basis) + ' · ' : ''}base revenue for the model is still entered by you</div></td></tr>
    <tr><td>EBITDA margin, TTM</td><td>${fin ? '<span class="small muted">not computed for lenders/insurers</span>' : fx(r.ebitda_margin_ttm_pct, 1, '%')} · EBIT margin ${fin ? NA : fx(r.ebit_margin_ttm_pct, 1, '%')}</td></tr>
    <tr><td>Net debt (negative = net cash)</td><td>${fin ? '<span class="small muted">not computed for lenders/insurers</span>' : crn(r.net_debt_cr)} <span class="small muted">${esc(r.net_debt_date || '')}</span> ${src(r.net_debt_url, 'XBRL')}</td></tr>
    <tr><td>Market capitalisation ${lab('ESTIMATED VALUE')}</td><td>${crn(r.market_cap_cr)} <span class="small muted">${r.market_cap_price_date ? 'NSE close ' + esc(r.market_cap_price_date) : ''}</span> ${src(r.market_cap_price_url, 'bhavcopy')}<div class="small muted">shares from the latest filing × NSE close</div></td></tr>
    <tr><td>Shares outstanding</td><td>${isNum(r.shares_outstanding) ? inr(r.shares_outstanding / 1e7, 2) + ' cr shares' : NA}</td></tr>
    <tr><td>Capex / operating cash flow, FY to ${esc(r.fy_end || '')}</td><td>${crn(r.capex_fy_cr)} / ${crn(r.cfo_fy_cr)} ${src(r.fy_url, 'XBRL')}</td></tr>
    <tr><td>ROCE / ROIC, FY to ${esc(R.year || '')}</td><td>${fx(R.roce_pct, 1, '%')} / ${fx(R.roic_pct, 1, '%')}${isNum(R.tax_rate_pct) ? ` <span class="small muted">(effective tax ${R.tax_rate_pct}%)</span>` : ''}</td></tr>
    <tr><td>Incremental ROIC (FY vs prior FY)</td><td>${fx(R.incremental_roic_pct, 1, '%')}${R.note ? `<div class="small muted">${esc(R.note)}</div>` : ''}</td></tr>`;
}
const repFormulas = Vd => Vd.formulas ? `<details><summary class="small">Formulas</summary><ul class="small">${Object.values(Vd.formulas).map(f => `<li>${esc(f)}</li>`).join('')}</ul></details>` : '';
window.valMode = () => { const m = $('#v_mode') && $('#v_mode').value; $$('.vrow').forEach(r => { r.hidden = !!r.dataset.mode && r.dataset.mode !== m; }); };
window.valRun = () => {
  const { a } = readA(); const err = VAL.check(a); const out = $('#v_out');
  if (err) { out.innerHTML = `<div class="card"><p class="na">${esc(err)}</p></div>`; return; }
  const f = VAL.forward(a), r = VAL.reverse(a);
  out.innerHTML = `<div class="card results"><h3>Model results of your assumptions ${lab('SCENARIO')}</h3>
   <div class="kpis"><div class="kpi"><div class="kt">Enterprise value (model)</div><div class="kv">${crn(f.enterprise_value)}</div></div>
   <div class="kpi"><div class="kt">Equity value (model)</div><div class="kv">${crn(f.equity_value)}</div><div class="ks">${isNum(f.equity_vs_market) ? (f.equity_vs_market).toFixed(2) + '× the market value you entered' : ''}</div></div>
   <div class="kpi"><div class="kt">Model annual return over ${a.years} years</div><div class="kv">${pct(f.model_annual_return)}</div><div class="ks">if bought at the market value you entered and valued at year ${a.years} on the same assumptions</div></div></div>
   <h3>What must happen to compound at 15%, 20% or 25% a year (other assumptions held)</h3>
   ${tbl([{ h: 'Annual compounding', v: x => x.hurdle, f: x => pct(x.hurdle, 0) }, { h: 'Revenue growth needed every year', n: 1, v: x => x.required_growth, f: x => x.required_growth == null ? '<span class="na">not reached between -20% and 80%</span>' : pct(x.required_growth) },
     { h: `Revenue in year ${a.years} at that growth`, n: 1, v: x => x.revenue_year_n, f: x => crn(x.revenue_year_n) }, { h: `Operating profit after tax, year ${a.years}`, n: 1, v: x => x.nopat_year_n, f: x => crn(x.nopat_year_n) },
     { h: 'Or: EBIT margin needed at your growth', n: 1, v: x => x.required_margin, f: x => x.required_margin == null ? '<span class="na">not reached below 80%</span>' : pct(x.required_margin) }], r.hurdles, { file: 'reverse_dcf' })}
   <details><summary>Year-by-year model</summary>${tbl([{ h: 'Year', n: 1, v: x => x.year }, { h: 'Revenue', n: 1, v: x => x.revenue, f: x => crn(x.revenue) }, { h: 'Operating profit after tax', n: 1, v: x => x.nopat, f: x => crn(x.nopat) }, { h: 'Reinvestment', n: 1, v: x => x.reinvestment, f: x => crn(x.reinvestment) }, { h: 'Free cash flow', n: 1, v: x => x.fcf, f: x => crn(x.fcf) }], f.rows)}</details>
   <p class="small muted">Method: free cash flow = revenue × margin × (1 − tax) − reinvestment; value = discounted cash flows + terminal value at (cost of capital − terminal growth). Year-${a.years} equity = terminal value − (net debt − cumulative free cash flow). Same arithmetic as scripts/intelligence/valuation_engine.py (tested to match).</p></div>`;
};
window.valSave = sym => { store.set('valdraft_' + sym, readA()); valRun(); };
window.valExport = cid => {
  const { a, notes } = readA(); const err = VAL.check(a); if (err) { alert(err); return; }
  if (['revenue0', 'net_debt', 'market_value'].some(k => !notes[k])) { alert('Add a source note for base revenue, net debt and market value.'); return; }
  const today = new Date().toISOString().slice(0, 10);
  const e = { valuation_id: 'val_' + cid.replace(/\W/g, '_').toLowerCase() + '_' + today.replace(/-/g, ''), company_id: cid, opportunity_id: null, as_of: today, analyst: '(your name)', assumptions: a, source_notes: notes };
  const b = new Blob([JSON.stringify(e, null, 2)], { type: 'application/json' }); const l = document.createElement('a'); l.href = URL.createObjectURL(b); l.download = e.valuation_id + '.json'; l.click();
};

/* ---------------- Analyst workspace (admin mode) ---------------- */
ROUTES.analyst = async () => {
  const [O, S] = await Promise.all([J('v2/opportunities.json'), J('v2/signals.json')]);
  const admin = store.get('admin', false); const drafts = store.get('anl_drafts', { opportunities: [], thesis_updates: [] });
  const sigs = S.signals.filter(s => s.status === 'validated');
  page(`<h1>Analyst workspace</h1><div class="edu">${EDU}</div>
  <div class="card method"><p>Hypotheses, thesis updates and valuations are entered here, saved as drafts in this browser, then downloaded and committed to <code>data/analyst/</code> through a pull request. The build checks every entry: known signals only, no scores, scenario probabilities totalling 100%, and thesis updates that are append-only and not back-dated. Nothing is published until the change is merged.</p></div>
  ${admin ? `<div class="g2"><div class="card"><h3>New hypothesis (draft)</h3>
    <label>Title <input id="a_t" style="width:100%"></label><label>Industry <select id="a_i">${Object.entries(META.industries).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select></label>
    <label>Horizon <select id="a_h">${O.horizons.map(h => `<option>${h}</option>`).join('')}</select></label><label>Hypothesis <textarea id="a_th" rows="4" style="width:100%"></textarea></label>
    <label>Supporting signals (Ctrl/Cmd-click for several) <select id="a_sup" multiple size="6" style="width:100%">${sigs.map(s => `<option value="${esc(s.signal_id)}">${esc(s.title)}</option>`).join('')}</select></label>
    <label>Opposing signals <select id="a_con" multiple size="4" style="width:100%">${sigs.map(s => `<option value="${esc(s.signal_id)}">${esc(s.title)}</option>`).join('')}</select></label>
    <label>Owner <input id="a_o"></label> <label>Next review <input id="a_r" type="date"></label>
    <button onclick="anlAdd()">Save draft</button></div>
   <div class="card"><h3>New thesis update (draft)</h3>
    <label>Hypothesis <select id="u_o">${O.opportunities.map(o => `<option value="${esc(o.opportunity_id)}" data-st="${esc(o.stage)}">${esc(o.title)} (now ${esc(STG[o.stage])})</option>`).join('')}</select></label>
    <label>New stage <select id="u_s">${O.stages.concat(O.end_stages).map(s => `<option value="${s}">${esc(STG[s])}</option>`).join('')}</select></label>
    <label>What changed <textarea id="u_sum" rows="3" style="width:100%"></textarea></label><label>Author <input id="u_a"></label>
    <p class="small muted">The date is today's date and the previous stage is the current recorded stage; neither can be changed.</p><button onclick="anlUpd()">Save draft</button></div></div>
   <div class="card"><h3>Drafts in this browser</h3><pre class="small" style="white-space:pre-wrap">${esc(JSON.stringify(drafts, null, 1))}</pre>
    <div class="flt"><button onclick="anlDownload()">Download merged opportunities.json for a pull request</button><button onclick="store.set('anl_drafts',{opportunities:[],thesis_updates:[]});route()">Clear drafts</button><button onclick="store.set('admin',false);route()">Leave admin mode</button></div></div>`
    : `<div class="card"><button onclick="store.set('admin',true);route()">Enter admin mode (this browser)</button> <span class="muted small">Admin mode only unlocks the draft forms in this browser. Publishing always goes through a reviewed commit.</span></div>`}`);
};
const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40);
window.anlAdd = () => {
  const d = store.get('anl_drafts', { opportunities: [], thesis_updates: [] }); const t = $('#a_t').value.trim(), th = $('#a_th').value.trim(); if (!t || !th) { alert('Title and hypothesis are required.'); return; }
  const id = 'opp_' + slug(t), today = new Date().toISOString().slice(0, 10), sel = el => [...$(el).selectedOptions].map(o => o.value);
  d.opportunities.push({ opportunity_id: id, title: t, thesis: th, industry_id: $('#a_i').value, geography: 'India', horizon: $('#a_h').value, owner: $('#a_o').value || 'unassigned', starter_hypothesis: false, created_at: today, next_review: $('#a_r').value || null, companies: [],
    evidence: sel('#a_sup').map(s => ({ signal_id: s, role: 'supporting', materiality: 1, explanation: '' })).concat(sel('#a_con').map(s => ({ signal_id: s, role: 'contradicting', materiality: 1, explanation: '' }))), confirmation_conditions: [], invalidation_conditions: [], scenarios: [] });
  d.thesis_updates.push({ update_id: 'tu_' + id + '_001', opportunity_id: id, update_date: today, previous_stage: null, new_stage: 'discovery', summary: 'Hypothesis recorded.', supporting_evidence: sel('#a_sup'), opposing_evidence: sel('#a_con'), assumptions_changed: null, author: $('#a_o').value || 'unassigned' });
  store.set('anl_drafts', d); route();
};
window.anlUpd = () => {
  const d = store.get('anl_drafts', { opportunities: [], thesis_updates: [] }); const o = $('#u_o'), sum = $('#u_sum').value.trim(); if (!sum) { alert('Describe what changed.'); return; }
  const today = new Date().toISOString().slice(0, 10), oid = o.value;
  d.thesis_updates.push({ update_id: 'tu_' + oid + '_' + Date.now(), opportunity_id: oid, update_date: today, previous_stage: o.selectedOptions[0].dataset.st, new_stage: $('#u_s').value, summary: sum, supporting_evidence: null, opposing_evidence: null, assumptions_changed: null, author: $('#u_a').value || 'unassigned' });
  store.set('anl_drafts', d); route();
};
window.anlDownload = async () => {
  const pub = await fetch('data/analyst/opportunities.json?v=' + Date.now()).then(r => r.json()); const d = store.get('anl_drafts', { opportunities: [], thesis_updates: [] });
  const out = { ...pub, opportunities: pub.opportunities.concat(d.opportunities), thesis_updates: pub.thesis_updates.concat(d.thesis_updates) };
  const b = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' }); const l = document.createElement('a'); l.href = URL.createObjectURL(b); l.download = 'opportunities.json'; l.click();
};
