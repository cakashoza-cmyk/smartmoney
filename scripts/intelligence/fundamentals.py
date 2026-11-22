"""Derived company fundamentals from reported XBRL rows (company_financials). Every number is either a reported value or a
stated formula over reported values; when an input is missing the result is None ("insufficient data"), never zero.
No forecasting and no assumptions: the tax rate is the company's own effective rate for the same period."""
from __future__ import annotations

FORMULAS = {
    "ttm": "TTM = sum of the latest four consecutive quarters (same reporting basis); a quarter tagged only as year-to-date is derived as YTD(this quarter) - YTD(previous quarter) of the same financial year",
    "ebitda": "EBITDA = PBT before exceptional items + finance costs + depreciation & amortisation - other income",
    "ebit": "EBIT (operating profit) = PBT before exceptional items + finance costs - other income",
    "ebitda_margin": "EBITDA margin = EBITDA / revenue from operations",
    "net_debt": "Net debt = current + non-current borrowings - (cash & equivalents + other bank balances + current investments); leases excluded",
    "capital_employed": "Capital employed = equity attributable to owners + borrowings",
    "invested_capital": "Invested capital = equity attributable to owners + net debt",
    "roce": "ROCE = EBIT (financial year) / average capital employed (opening and closing balance sheets of that year)",
    "roic": "ROIC = NOPAT / average invested capital; NOPAT = EBIT x (1 - effective tax rate); effective tax rate = tax expense / PBT of the same year (not computed when PBT <= 0 or the rate is outside 0-50%)",
    "incremental_roic": "Incremental ROIC = (NOPAT this year - NOPAT last year) / (invested capital at this year end - invested capital at last year end); not meaningful when invested capital did not rise",
    "market_cap": "Market capitalisation (estimate) = shares outstanding (paid-up equity capital / face value, latest filing) x latest NSE closing price",
    "revenue_yoy": "Revenue growth = latest quarter revenue / same quarter a year earlier - 1 (same reporting basis)",
}
FIN_TAX = {"BANKING", "NBFC_INDAS", "NBFC", "LI", "GI", "INSURANCE"}


def _rows(con, cid):
    cur = con.execute("SELECT * FROM company_financials WHERE company_id=? ORDER BY period_end", (cid,))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _r(x, n=2):
    return None if x is None else round(x, n)


def _year_ago(pe):
    y, m, d = pe.split("-")
    return f"{int(y) - 1}-{m}-{d}"


QFIELDS = ("revenue_cr", "ebitda_cr", "ebit_cr", "pat_cr", "other_income_cr")


def _basis(rows):
    """Basis of the most recent filing (consolidated when filed)."""
    r = sorted(rows, key=lambda r: (r["period_end"], r["basis"] == "Consolidated"))
    return r[-1]["basis"] if r else None


def _prev_q_end(pe):
    y, m = int(pe[:4]), int(pe[5:7])
    return {3: f"{y - 1}-12-31", 6: f"{y}-03-31", 9: f"{y}-06-30", 12: f"{y}-09-30"}[m]


def quarters(rows, basis):
    """Reported quarters; a quarter missing as such but present as year-to-date is derived as YTD(this) - YTD(previous quarter)
    of the same financial year (flagged 'derived_from_ytd')."""
    q = {r["period_end"]: dict(r, derived_from_ytd=False) for r in rows if r["period_type"] == "Q" and r["basis"] == basis}
    ytd = {r["period_end"]: r for r in rows if r["period_type"] == "YTD" and r["basis"] == basis}
    for pe, y in ytd.items():
        if pe in q:
            continue
        if y["months"] == 3:
            q[pe] = dict(y, period_type="Q", derived_from_ytd=False); continue
        p = ytd.get(_prev_q_end(pe))
        if p and p["period_start"] == y["period_start"] and (y["months"] - p["months"]) == 3:
            d = dict(y, period_type="Q", months=3, derived_from_ytd=True, period_start=None)
            for k in QFIELDS + ("finance_costs_cr", "depreciation_cr", "pbt_cr", "tax_cr"):
                d[k] = None if y.get(k) is None or p.get(k) is None else y[k] - p[k]
            q[pe] = d
    return [q[k] for k in sorted(q)]


def company(con, cid, price=None):
    """Metrics for one company. price = {'close': float, 'date': str, 'url': str} from the bhavcopy, optional."""
    rows = _rows(con, cid)
    if not rows:
        return None
    # A 'quarter' row that spans 6/9/12 months is a year-to-date figure tagged in the quarter context: use it as year-to-date
    have_ytd = {(r["period_end"], r["basis"]) for r in rows if r["period_type"] == "YTD"}
    fixed = []
    for r in rows:
        if r["period_type"] == "Q" and r["months"] != 3:
            if (r["period_end"], r["basis"]) not in have_ytd and (r["period_start"] or "")[5:] == "04-01":
                fixed.append(dict(r, period_type="YTD"))
            continue
        fixed.append(r)
    rows = fixed
    basis = _basis(rows)
    if not basis:
        return None
    q = quarters(rows, basis)
    if not q:
        return None
    last = q[-1]
    fy = [r for r in rows if r["period_type"] == "YTD" and r["basis"] == basis and (r["months"] or 0) >= 11]
    fin = (last["taxonomy"] or "") in FIN_TAX
    out = {"company_id": cid, "symbol": last["symbol"], "basis": basis, "taxonomy": last["taxonomy"], "financial_sector_format": fin,
           "latest_quarter": last["period_end"], "filing_date": last["filing_date"], "source_url": last["xbrl_url"], "sources": {}}
    out["sources"]["latest_quarter"] = last["xbrl_url"]
    out["derived_quarters"] = [r["period_end"] for r in q if r.get("derived_from_ytd")]
    # latest quarter and growth vs the same quarter a year earlier
    ya = next((r for r in q if r["period_end"] == _year_ago(last["period_end"])), None)
    out["q"] = {k: _r(last.get(k)) for k in ("revenue_cr", "ebitda_cr", "ebit_cr", "pat_cr", "other_income_cr")}
    out["q"]["ebitda_margin_pct"] = None if fin else _r(_div(last["ebitda_cr"], last["revenue_cr"]) and 100 * _div(last["ebitda_cr"], last["revenue_cr"]), 1)
    if ya:
        out["sources"]["year_ago_quarter"] = ya["xbrl_url"]
        g = _div(last["revenue_cr"], ya["revenue_cr"])
        out["q"]["revenue_yoy_pct"] = None if g is None or (ya["revenue_cr"] or 0) <= 0 else _r(100 * (g - 1), 1)
        m0 = None if fin else _div(ya["ebitda_cr"], ya["revenue_cr"])
        m1 = None if fin else _div(last["ebitda_cr"], last["revenue_cr"])
        out["q"]["ebitda_margin_change_pp"] = None if m0 is None or m1 is None else _r(100 * (m1 - m0), 1)
        p0, p1 = ya["pat_cr"], last["pat_cr"]
        out["q"]["pat_yoy_pct"] = None if p0 is None or p1 is None or p0 <= 0 else _r(100 * (p1 / p0 - 1), 1)
        out["q"]["year_ago_period"] = ya["period_end"]
        out["q"]["year_ago_revenue_cr"] = _r(ya["revenue_cr"]); out["q"]["year_ago_ebitda_cr"] = None if fin else _r(ya["ebitda_cr"])
    else:
        out["q"].update(revenue_yoy_pct=None, ebitda_margin_change_pp=None, pat_yoy_pct=None, year_ago_period=None, year_ago_revenue_cr=None, year_ago_ebitda_cr=None)
    # TTM from the last four consecutive quarters
    last4 = q[-4:]
    ttm = None
    if len(last4) == 4 and all(_prev_q_end(last4[i]["period_end"]) == last4[i - 1]["period_end"] for i in range(1, 4)):
        ends = [r["period_end"] for r in last4]
        ttm = {"period_end": ends[-1], "quarters": ends}
        for k in ("revenue_cr", "ebitda_cr", "ebit_cr", "pat_cr"):
            vals = [r[k] for r in last4]
            ttm[k] = None if any(v is None for v in vals) or (fin and k in ("ebitda_cr", "ebit_cr")) else _r(sum(vals))
        ttm["ebitda_margin_pct"] = None if fin or ttm["ebitda_cr"] is None else _r(100 * _div(ttm["ebitda_cr"], ttm["revenue_cr"]), 1)
        ttm["ebit_margin_pct"] = None if fin or ttm["ebit_cr"] is None else _r(100 * _div(ttm["ebit_cr"], ttm["revenue_cr"]), 1)
    out["ttm"] = ttm
    # balance sheet: latest filing with one
    bs = sorted([r for r in rows if r["bs_date"] and r["basis"] == basis], key=lambda r: r["bs_date"])
    b = bs[-1] if bs else None
    out["balance_sheet"] = None if not b else {"date": b["bs_date"], "borrowings_cr": _r(b["borrowings_cr"]), "cash_cr": _r(b["cash_cr"]),
                                               "equity_cr": _r(b["equity_cr"]), "net_debt_cr": None if fin else _r(b["net_debt_cr"]), "source_url": b["xbrl_url"]}
    shares = last["shares_outstanding"] or next((r["shares_outstanding"] for r in reversed(q) if r["shares_outstanding"]), None)
    out["shares_outstanding"] = shares
    out["market_cap"] = None
    if price and shares and price.get("close"):
        out["market_cap"] = {"value_cr": _r(shares * price["close"] / 1e7, 0), "close_inr": price["close"], "price_date": price["date"],
                             "price_url": price.get("url"), "label": "ESTIMATE (shares from latest filing x NSE close)"}
    # financial-year returns on capital
    out["fy"] = []
    for r in fy[-2:]:
        bs_close = next((x for x in rows if x["bs_date"] == r["period_end"] and x["basis"] == basis), None)
        out["fy"].append({"period_end": r["period_end"], "revenue_cr": _r(r["revenue_cr"]), "ebitda_cr": None if fin else _r(r["ebitda_cr"]),
                          "ebit_cr": None if fin else _r(r["ebit_cr"]), "pat_cr": _r(r["pat_cr"]), "cfo_cr": _r(r["cfo_cr"]), "capex_cr": _r(r["capex_cr"]),
                          "tax_cr": r["tax_cr"], "pbt_cr": r["pbt_cr"], "source_url": r["xbrl_url"],
                          "equity_cr": bs_close and bs_close["equity_cr"], "borrowings_cr": bs_close and bs_close["borrowings_cr"],
                          "net_debt_cr": bs_close and bs_close["net_debt_cr"]})
    out["returns"] = returns(out["fy"], fin)
    return out


def _nopat(y):
    if y["ebit_cr"] is None or y["pbt_cr"] in (None, 0) or y["tax_cr"] is None or y["pbt_cr"] <= 0:
        return None, None
    t = y["tax_cr"] / y["pbt_cr"]
    if not (0 <= t <= 0.5):
        return None, t
    return y["ebit_cr"] * (1 - t), t


def returns(fy, fin):
    """ROCE / ROIC for the latest financial year (average of the two year-end balance sheets), incremental ROIC vs the prior year."""
    res = {"roce_pct": None, "roic_pct": None, "incremental_roic_pct": None, "tax_rate_pct": None, "year": None, "note": None}
    if fin:
        res["note"] = "Not computed for banks, NBFCs and insurers (borrowings are operating funding)."
        return res
    if len(fy) < 2:
        res["note"] = "Insufficient data: needs two financial-year filings with balance sheets."
        return res
    p, c = fy[-2], fy[-1]
    res["year"] = c["period_end"]
    ce = [None if (y["equity_cr"] is None or y["borrowings_cr"] is None) else y["equity_cr"] + y["borrowings_cr"] for y in (p, c)]
    ic = [None if (y["equity_cr"] is None or y["net_debt_cr"] is None) else y["equity_cr"] + y["net_debt_cr"] for y in (p, c)]
    if c["ebit_cr"] is not None and None not in ce and sum(ce) > 0:
        res["roce_pct"] = _r(100 * c["ebit_cr"] / (sum(ce) / 2), 1)
    n1, t1 = _nopat(c); n0, _ = _nopat(p)
    res["tax_rate_pct"] = None if t1 is None else _r(100 * t1, 1)
    if n1 is not None and None not in ic and sum(ic) > 0:
        res["roic_pct"] = _r(100 * n1 / (sum(ic) / 2), 1)
    if n1 is not None and n0 is not None and None not in ic:
        d_ic = ic[1] - ic[0]
        if d_ic > 0:
            res["incremental_roic_pct"] = _r(100 * (n1 - n0) / d_ic, 1)
        else:
            res["note"] = "Incremental ROIC not meaningful: invested capital did not rise over the year."
    res["inputs"] = {"capital_employed_cr": [_r(x) for x in ce], "invested_capital_cr": [_r(x) for x in ic],
                     "nopat_cr": [_r(n0), _r(n1)], "years": [p["period_end"], c["period_end"]]}
    return res


def latest_prices(con):
    out = {}
    for cid, pe, v, url in con.execute("""SELECT o.entity_id, o.period_end, o.value, sd.url FROM observations o
                                          LEFT JOIN source_documents sd ON sd.doc_id=o.doc_id
                                          WHERE o.metric='close_inr' AND o.period_end=(SELECT max(period_end) FROM observations WHERE metric='close_inr')"""):
        out[cid] = {"close": v, "date": pe, "url": url}
    return out


def all_companies(con):
    prices = latest_prices(con)
    out = {}
    for (cid,) in con.execute("SELECT DISTINCT company_id FROM company_financials"):
        m = company(con, cid, prices.get(cid))
        if m:
            out[cid] = m
    return out


def sector_aggregates(con, metrics):
    """Sum-of-companies revenue / EBITDA for the latest common quarter vs a year earlier, per NSE sector (non-financial formats only
    for margins). Only companies with both quarters on the same basis are included; the count is reported."""
    ind = dict(con.execute("SELECT company_id, industry_id FROM companies"))
    agg = {}
    for cid, m in metrics.items():
        s = ind.get(cid)
        if not s or m["q"].get("year_ago_period") is None or m["q"]["revenue_cr"] is None:
            continue
        a = agg.setdefault(s, {"period": {}, "n": 0, "rev1": 0, "rev0": 0, "e1": 0, "e0": 0, "ne": 0, "companies": []})
        y0 = (m["q"]["year_ago_revenue_cr"], m["q"]["year_ago_ebitda_cr"])
        if y0[0] is None or y0[0] <= 0:
            continue
        a["n"] += 1; a["rev1"] += m["q"]["revenue_cr"]; a["rev0"] += y0[0]
        a["period"][m["latest_quarter"]] = a["period"].get(m["latest_quarter"], 0) + 1
        a["companies"].append(cid)
        if not m["financial_sector_format"] and m["q"]["ebitda_cr"] is not None and y0[1] is not None:
            a["ne"] += 1; a["e1"] += m["q"]["ebitda_cr"]; a["e0"] += y0[1]
            a.setdefault("rev1_e", 0); a.setdefault("rev0_e", 0)
            a["rev1_e"] += m["q"]["revenue_cr"]; a["rev0_e"] += y0[0]
    out = {}
    for s, a in agg.items():
        per = max(a["period"].items(), key=lambda kv: kv[1])[0] if a["period"] else None
        r = {"companies": a["n"], "quarter": per, "revenue_yoy_pct": _r(100 * (a["rev1"] / a["rev0"] - 1), 1) if a["rev0"] else None,
             "margin_companies": a["ne"], "ebitda_margin_pct": None, "ebitda_margin_change_pp": None, "company_ids": a["companies"]}
        if a["ne"] and a.get("rev0_e") and a.get("rev1_e"):
            m1 = a["e1"] / a["rev1_e"]; m0 = a["e0"] / a["rev0_e"]
            r["ebitda_margin_pct"] = _r(100 * m1, 1); r["ebitda_margin_change_pp"] = _r(100 * (m1 - m0), 1)
        out[s] = r
    return out
