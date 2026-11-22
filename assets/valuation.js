/* Valuation arithmetic for the Valuation Lab (mirror of scripts/intelligence/valuation_engine.py; tests check both match).
   All inputs are analyst-entered. Outputs are model results of those assumptions (SCENARIO), not a price objective. */
'use strict';
const VAL = (() => {
  const REQUIRED = ['revenue0', 'growth', 'margin', 'tax', 'wacc', 'g_term', 'years', 'net_debt', 'market_value'];
  const gAt = (a, i) => Array.isArray(a.growth) ? a.growth[Math.min(i, a.growth.length - 1)] : a.growth;
  const nil = v => v === null || v === undefined || (typeof v === 'number' && !isFinite(v));
  function check(a) {
    const miss = REQUIRED.filter(k => nil(a[k]));
    const mode = a.mode || 'roic';
    if (mode === 'roic' && (nil(a.roic) || a.roic === 0)) miss.push('roic');
    if (mode === 'explicit' && (nil(a.capex_pct) || nil(a.wc_pct))) miss.push('capex_pct/wc_pct');
    if (miss.length) return 'missing: ' + miss.join(', ');
    if (a.wacc <= a.g_term) return 'cost of capital must be above terminal growth';
    if (!(a.years >= 1 && a.years <= 30)) return 'years must be 1-30';
    if (a.market_value <= 0 || a.revenue0 <= 0) return 'market value and base revenue must be positive';
    return null;
  }
  const reinv = (a, nopat, rNew, rOld, g) => (a.mode || 'roic') === 'roic' ? nopat * g / a.roic : a.capex_pct * rNew + a.wc_pct * (rNew - rOld);
  function forward(a) {
    const err = check(a); if (err) return { error: err };
    const n = Math.trunc(a.years), w = a.wacc, m = a.margin, t = a.tax, gt = a.g_term;
    let rPrev = a.revenue0, pv = 0, cum = 0; const rows = [];
    for (let i = 1; i <= n; i++) {
      const g = gAt(a, i - 1), r = rPrev * (1 + g), nopat = r * m * (1 - t), ri = reinv(a, nopat, r, rPrev, g), fcf = nopat - ri;
      pv += fcf / Math.pow(1 + w, i); cum += fcf; rows.push({ year: i, revenue: r, nopat, reinvestment: ri, fcf }); rPrev = r;
    }
    const rT = rPrev * (1 + gt), nopatT = rT * m * (1 - t), fcfT = nopatT - reinv(a, nopatT, rT, rPrev, gt), tv = fcfT / (w - gt);
    const ev0 = pv + tv / Math.pow(1 + w, n), eq0 = ev0 - a.net_debt, eqN = tv - (a.net_debt - cum);
    const ret = eqN > 0 ? Math.pow(eqN / a.market_value, 1 / n) - 1 : null;
    return { rows, terminal_value: tv, enterprise_value: ev0, equity_value: eq0, equity_value_year_n: eqN, model_annual_return: ret, equity_vs_market: eq0 / a.market_value };
  }
  function solve(f, lo, hi, target, steps = 400) {
    let prev = null;
    for (let k = 0; k <= steps; k++) {
      const x = lo + (hi - lo) * k / steps, v = f(x);
      if (v === null || v === undefined) { prev = null; continue; }
      if (prev && (prev[1] - target) * (v - target) <= 0) {
        let a = prev[0], b = x, fa = prev[1] - target;
        for (let j = 0; j < 60; j++) { const mid = (a + b) / 2, fm = f(mid); if (fm === null || fm === undefined) break; if ((fm - target) * fa <= 0) b = mid; else { a = mid; fa = fm - target; } }
        return (a + b) / 2;
      }
      prev = [x, v];
    }
    return null;
  }
  function reverse(a, hurdles = [0.15, 0.20, 0.25]) {
    const err = check(a); if (err) return { error: err };
    return {
      years: Math.trunc(a.years), hurdles: hurdles.map(h => {
        const g = solve(x => forward({ ...a, growth: x }).model_annual_return, -0.20, 0.80, h);
        const m = solve(x => forward({ ...a, margin: x }).model_annual_return, 0.0, 0.80, h);
        const res = { hurdle: h, required_growth: g, required_margin: m };
        if (g !== null) { const f = forward({ ...a, growth: g }); res.revenue_year_n = f.rows[f.rows.length - 1].revenue; res.nopat_year_n = f.rows[f.rows.length - 1].nopat; }
        return res;
      })
    };
  }
  return { check, forward, reverse };
})();
if (typeof module !== 'undefined') module.exports = VAL;
