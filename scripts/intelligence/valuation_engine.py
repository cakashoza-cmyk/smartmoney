"""Valuation arithmetic for the Valuation Lab (Python mirror of assets/valuation.js; tests assert both give the same numbers).
Every input is ANALYST-ENTERED; nothing here reads or invents company financials. Outputs are model results of those
assumptions (labelled SCENARIO), not a view on any security and not a price objective."""
from __future__ import annotations

REQUIRED = ("revenue0", "growth", "margin", "tax", "wacc", "g_term", "years", "net_debt", "market_value")


def _g(a, i):
    g = a["growth"]
    return g[min(i, len(g) - 1)] if isinstance(g, (list, tuple)) else g


def check(a: dict):
    miss = [k for k in REQUIRED if a.get(k) is None]
    if a.get("mode", "roic") == "roic" and a.get("roic") in (None, 0):
        miss.append("roic")
    if a.get("mode") == "explicit" and (a.get("capex_pct") is None or a.get("wc_pct") is None):
        miss.append("capex_pct/wc_pct")
    if miss:
        return "missing: " + ", ".join(miss)
    if a["wacc"] <= a["g_term"]:
        return "cost of capital must be above terminal growth"
    if not (1 <= int(a["years"]) <= 30):
        return "years must be 1-30"
    if a["market_value"] <= 0 or a["revenue0"] <= 0:
        return "market value and base revenue must be positive"
    return None


def _reinv(a, nopat, r_new, r_old, g):
    if a.get("mode", "roic") == "roic":
        return nopat * g / a["roic"]
    return a["capex_pct"] * r_new + a["wc_pct"] * (r_new - r_old)


def forward(a: dict) -> dict:
    err = check(a)
    if err:
        return {"error": err}
    n, w, m, t, gt = int(a["years"]), a["wacc"], a["margin"], a["tax"], a["g_term"]
    r_prev, pv, cum_fcf, rows = a["revenue0"], 0.0, 0.0, []
    for i in range(1, n + 1):
        g = _g(a, i - 1)
        r = r_prev * (1 + g)
        nopat = r * m * (1 - t)
        reinv = _reinv(a, nopat, r, r_prev, g)
        fcf = nopat - reinv
        pv += fcf / (1 + w) ** i
        cum_fcf += fcf
        rows.append({"year": i, "revenue": r, "nopat": nopat, "reinvestment": reinv, "fcf": fcf})
        r_prev = r
    r_t = r_prev * (1 + gt)
    nopat_t = r_t * m * (1 - t)
    fcf_t = nopat_t - _reinv(a, nopat_t, r_t, r_prev, gt)
    tv = fcf_t / (w - gt)
    ev0 = pv + tv / (1 + w) ** n
    eq0 = ev0 - a["net_debt"]
    eq_n = tv - (a["net_debt"] - cum_fcf)
    ret = (eq_n / a["market_value"]) ** (1 / n) - 1 if eq_n > 0 else None
    return {"rows": rows, "terminal_value": tv, "enterprise_value": ev0, "equity_value": eq0, "equity_value_year_n": eq_n,
            "model_annual_return": ret, "equity_vs_market": eq0 / a["market_value"]}


def _solve(f, lo, hi, target, steps=400):
    xs = [lo + (hi - lo) * k / steps for k in range(steps + 1)]
    prev = None
    for x in xs:
        v = f(x)
        if v is None:
            prev = None
            continue
        if prev is not None and (prev[1] - target) * (v - target) <= 0:
            a, b, fa = prev[0], x, prev[1] - target
            for _ in range(60):
                mid = (a + b) / 2
                fm = f(mid)
                if fm is None:
                    break
                if (fm - target) * fa <= 0:
                    b = mid
                else:
                    a, fa = mid, fm - target
            return (a + b) / 2
        prev = (x, v)
    return None


def reverse(a: dict, hurdles=(0.15, 0.20, 0.25)) -> dict:
    """What must happen for the equity to compound at each hurdle rate over the horizon (all other assumptions held)."""
    err = check(a)
    if err:
        return {"error": err}
    out = []
    for h in hurdles:
        fg = lambda g: forward(dict(a, growth=g)).get("model_annual_return")
        fm = lambda m: forward(dict(a, margin=m)).get("model_annual_return")
        g = _solve(fg, -0.20, 0.80, h)
        m = _solve(fm, 0.0, 0.80, h)
        res = {"hurdle": h, "required_growth": g, "required_margin": m}
        if g is not None:
            f = forward(dict(a, growth=g))
            res["revenue_year_n"] = f["rows"][-1]["revenue"]; res["nopat_year_n"] = f["rows"][-1]["nopat"]
        out.append(res)
    return {"hurdles": out, "years": int(a["years"])}
