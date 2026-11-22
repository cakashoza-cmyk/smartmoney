"""Company financials from NSE 'Integrated Filing - Financials' XBRL (SEBI integrated filing, quarters from Mar-2025 onwards).
Official exchange filings only. Values are taken exactly as tagged; derived fields (EBITDA, EBIT, shares, net debt) are
computed with the formulas in FORMULAS and stored next to the reported inputs. A field that is not tagged stays NULL."""
from __future__ import annotations
import re, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime
from common import Http, connect, doc, hid, now, upsert

SRC = "nse_financials"
LIST = "https://www.nseindia.com/api/integrated-filing-results?index=equities&type=Integrated%20Filing-%20Financials&symbol={sym}"
CR = 1e7
FORMULAS = {
    "ebitda_cr": "PBT before exceptional items + finance costs + depreciation & amortisation - other income",
    "ebit_cr": "PBT before exceptional items + finance costs - other income",
    "shares_outstanding": "paid-up equity share capital / face value per share",
    "net_debt_cr": "(current + non-current borrowings) - (cash & cash equivalents + other bank balances + current investments)",
    "capex_cr": "purchase of property, plant & equipment (+ purchase of intangible assets where tagged), cash flow statement, year to date",
}
# first tag present wins
TAGS = {
    "revenue_cr": ["RevenueFromOperations"],
    "revenue_fin_cr": ["Income", "TotalIncome"],  # banks / insurers: total income as reported
    "other_income_cr": ["OtherIncome"],
    "total_income_cr": ["Income", "TotalIncome"],
    "finance_costs_cr": ["FinanceCosts"],
    "depreciation_cr": ["DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense"],
    "pbt_pre_exceptional_cr": ["ProfitBeforeExceptionalItemsAndTax"],
    "exceptional_cr": ["ExceptionalItemsBeforeTax", "ExceptionalItems"],
    "pbt_cr": ["ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitLossBeforeTax"],
    "tax_cr": ["TaxExpense", "TaxExpenses"],
    "pat_cr": ["ProfitLossForPeriod", "ProfitLossForThePeriod", "ProfitLossAfterTaxAndExtraordinaryItems"],
    "pat_owners_cr": ["ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"],
    "paid_up_capital_cr": ["PaidUpValueOfEquityShareCapital"],
    "face_value": ["FaceValueOfEquityShareCapital"],
    "cfo_cr": ["CashFlowsFromUsedInOperatingActivities"],
    "capex_ppe": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "capex_int": ["PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
}
BS = {"b_cur": ["BorrowingsCurrent"], "b_nc": ["BorrowingsNoncurrent"], "cash": ["CashAndCashEquivalents"],
      "bank": ["BankBalanceOtherThanCashAndCashEquivalents"], "cinv": ["CurrentInvestments"],
      "eq_owners": ["EquityAttributableToOwnersOfParent"], "eq": ["Equity"], "assets": ["Assets"]}
XI = "{http://www.xbrl.org/2003/instance}"


def parse(xml: str):
    """Return {'contexts': {id: (start, end, instant, has_dims)}, 'facts': {(tag, ctx): value}, 'dims': {ctx: member}}."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    ctx = {}
    for c in root.iter(XI + "context"):
        p = c.find(XI + "period")
        st = p.findtext(XI + "startDate"); en = p.findtext(XI + "endDate"); ins = p.findtext(XI + "instant")
        seg = c.find(f"{XI}entity/{XI}segment")
        scen = c.find(XI + "scenario")
        dims = (seg is not None and len(list(seg))) or (scen is not None and len(list(scen)))
        ctx[c.get("id")] = (st, en, ins, bool(dims))
    facts = {}
    for el in root:
        ref = el.get("contextRef")
        if not ref:
            continue
        tag = el.tag.split("}")[-1]
        facts.setdefault((tag, ref), (el.text or "").strip())
    return {"contexts": ctx, "facts": facts}


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def extract(xml: str):
    """Rows for the plain (no dimension) duration contexts: the quarter and the year-to-date period. Segments separately."""
    P = parse(xml); C = P["contexts"]; F = P["facts"]
    plain_dur = {k: v for k, v in C.items() if not v[3] and v[0] and v[1]}
    plain_ins = {k: v for k, v in C.items() if not v[3] and v[2]}
    if not plain_dur:
        return [], []
    end = max(v[1] for v in plain_dur.values())
    cur_dur = {k: v for k, v in plain_dur.items() if v[1] == end}
    ins_end = {k: v for k, v in plain_ins.items() if v[2] == end}

    def first(ctxs, names, scale=CR):
        for n in names:
            for c in ctxs:
                v = _num(F.get((n, c)))
                if v is not None:
                    return v / scale if scale else v
        return None

    def months(s, e):
        a = datetime.strptime(s, "%Y-%m-%d"); b = datetime.strptime(e, "%Y-%m-%d")
        return round(((b - a).days + 1) / 30.44)

    rows = []
    for c, (s, e, _, _) in sorted(cur_dur.items(), key=lambda kv: kv[1][0], reverse=True):
        m = months(s, e)
        r = {"period_start": s, "period_end": e, "months": m}
        for k, names in TAGS.items():
            r[k] = first([c], names, None if k == "face_value" else CR)
        r["period_type"] = None
        rows.append(r)
    # quarter = shortest duration (3 months); YTD = the longer one (6/9/12 months). Q1: both are the same 3-month period.
    rows = sorted(rows, key=lambda r: r["months"])
    out = []
    if rows:
        q = rows[0]
        if q["months"] == 3:  # some filers tag only the year-to-date period; then no quarter row is stored (fundamentals derives it from YTD differences)
            q["period_type"] = "Q"; out.append(q)
        y = rows[-1]
        if y["months"] > 3 or (y["months"] == 3 and y["period_start"][5:7] == "04"):  # Q1: YTD == quarter
            y = dict(y); y["period_type"] = "YTD"; out.append(y)
    ic = list(ins_end)
    bs = {k: first(ic, v) for k, v in BS.items()}
    have_bs = any(bs[k] is not None for k in ("b_cur", "b_nc", "cash", "eq", "eq_owners", "assets"))
    for r in out:
        rev = r.pop("revenue_cr"); rf = r.pop("revenue_fin_cr")
        r["revenue_cr"] = rev if rev is not None else rf
        cp, ci = r.pop("capex_ppe"), r.pop("capex_int")
        r["capex_cr"] = None if cp is None else cp + (ci or 0)
        p, f_, d_, o = r["pbt_pre_exceptional_cr"], r["finance_costs_cr"], r["depreciation_cr"], r["other_income_cr"]
        r["ebit_cr"] = None if None in (p, f_) else p + f_ - (o or 0)
        r["ebitda_cr"] = None if None in (p, f_, d_) else p + f_ + d_ - (o or 0)
        pu, fv = r["paid_up_capital_cr"], r["face_value"]
        if fv is not None and not (0.01 <= fv <= 1000):  # mis-tagged face value in the filing: do not derive shares from it
            r["face_value"] = fv = None
        r["shares_outstanding"] = (pu * CR / fv) if (pu and fv) else None
        if r["period_type"] == "Q":
            r["cfo_cr"] = None; r["capex_cr"] = None  # cash flow is year-to-date only
        if have_bs:
            borrow = None if (bs["b_cur"] is None and bs["b_nc"] is None) else (bs["b_cur"] or 0) + (bs["b_nc"] or 0)
            cash = None if bs["cash"] is None else bs["cash"] + (bs["bank"] or 0) + (bs["cinv"] or 0)
            r.update(borrowings_cr=borrow, cash_cr=cash, equity_cr=bs["eq_owners"] if bs["eq_owners"] is not None else bs["eq"],
                     total_assets_cr=bs["assets"], bs_date=end,
                     net_debt_cr=None if (borrow is None or cash is None) else borrow - cash)
        else:
            r.update(borrowings_cr=None, cash_cr=None, equity_cr=None, total_assets_cr=None, bs_date=None, net_debt_cr=None)
    # segments: contexts with a dimension, duration = the quarter, named by DescriptionOfReportableSegment
    merged = {}
    qctx = [k for k, v in C.items() if v[3] and v[1] == end and v[0] and out and v[0] == out[0]["period_start"]]
    for c in qctx:
        name = F.get(("DescriptionOfReportableSegment", c)) or F.get(("DescriptionOfReportableSegments", c))
        if not name:
            continue
        rv = _num(F.get(("SegmentRevenue", c)) or F.get(("SegmentRevenueFromOperations", c)))
        rs = _num(F.get(("SegmentProfitLossBeforeTaxAndFinanceCosts", c)) or F.get(("SegmentResult", c)))
        m = merged.setdefault(name.strip()[:120], {"segment": name.strip()[:120], "revenue_cr": None, "result_cr": None, "period_end": end})
        if rv is not None and m["revenue_cr"] is None:
            m["revenue_cr"] = rv / CR
        if rs is not None and m["result_cr"] is None:
            m["result_cr"] = rs / CR
    segs = [m for m in merged.values() if m["revenue_cr"] is not None or m["result_cr"] is not None]
    return out, segs


def taxonomy(url):
    m = re.search(r"INTEGRATED_FILING_([A-Z_]+?)_\d", url or "")
    return m.group(1) if m else None


def pick(filings):
    """One filing per quarter: Consolidated when filed (else Standalone); the latest broadcast wins (revisions)."""
    by = {}
    for f in filings:
        if not f.get("xbrl") or "xbrl" not in f["xbrl"]:
            continue
        k = f["qe_Date"]
        rank = (1 if f.get("consolidated") == "Consolidated" else 0, datetime.strptime(f["broadcast_Date"][:20].strip(), "%d-%b-%Y %H:%M:%S") if f.get("broadcast_Date") else datetime.min)
        if k not in by or rank > by[k][0]:
            by[k] = (rank, f)
    return [v[1] for v in by.values()]


def universe(con):
    return [r for r in con.execute("SELECT company_id, symbol FROM companies WHERE index_membership LIKE 'NIFTY 500%' AND symbol IS NOT NULL ORDER BY symbol")]


def job(con, limit=None, symbols=None, pause=0.6):
    h = Http(nse=True)
    seen = {r[0] for r in con.execute("SELECT DISTINCT xbrl_url FROM company_financials")}
    uni = universe(con)
    if symbols:
        uni = [u for u in uni if u[1] in symbols]
    if limit:
        uni = uni[:limit]
    n_new = n_files = fails = consecutive = 0; latest = None; skipped = 0
    for i, (cid, sym) in enumerate(uni):
        try:
            lst = h.get(LIST.format(sym=sym.replace("&", "%26")), tries=2, pause=pause).json().get("data") or []
            consecutive = 0
        except Exception as e:  # noqa: BLE001
            fails += 1; consecutive += 1
            print("list fail", sym, str(e)[:120], flush=True)
            if consecutive >= 8:
                raise RuntimeError(f"NSE stopped answering after {i} companies") from e
            continue
        for f in pick(lst):
            url = f["xbrl"]
            if url in seen:
                skipped += 1; continue
            try:
                xml = h.get(url, tries=2, pause=pause, timeout=60).content
                rows, segs = extract(xml.decode("utf-8", "ignore"))
            except Exception as e:  # noqa: BLE001
                fails += 1; print("xbrl fail", sym, url, str(e)[:120], flush=True); continue
            if not rows:
                continue
            basis = f.get("consolidated") or "Standalone"
            d = doc(con, SRC, url, f"{sym} integrated filing (financials) {basis} quarter ended {f['qe_Date']}",
                    publication_date=(f.get("broadcast_Date") or "")[:11], data_period=rows[0]["period_end"])
            t = now(); tx = taxonomy(url)
            for r in rows:
                if tx != "INDAS":  # lenders / insurers: operating-profit and net-debt formulas do not apply
                    r.update(ebitda_cr=None, ebit_cr=None, net_debt_cr=None)
                upsert(con, "company_financials", dict(fin_id=hid(cid, r["period_type"], r["period_end"], basis), company_id=cid, symbol=sym,
                       basis=basis, taxonomy=tx, audited=f.get("audited"), filing_date=f.get("broadcast_Date"), xbrl_url=url,
                       doc_id=d, source_id=SRC, retrieved_at=t, **r), "fin_id")
                n_new += 1
                latest = max(latest or r["period_end"], r["period_end"])
            for s in segs:
                upsert(con, "company_segments", dict(seg_id=hid(cid, "Q", s["period_end"], basis, s["segment"]), company_id=cid, period_type="Q",
                       basis=basis, xbrl_url=url, doc_id=d, retrieved_at=t, **s), "seg_id")
            n_files += 1; seen.add(url)
        if i % 10 == 0:
            con.commit(); print(f"{i+1}/{len(uni)} {sym} files={n_files} rows={n_new} skipped={skipped} fails={fails}", flush=True)
    con.commit()
    if not n_files and not skipped:
        raise ValueError("no XBRL filings parsed")
    return {"rows_in": len(uni), "rows_new": n_new, "dup": skipped, "period": latest,
            "warn": f"{fails} fetch/parse failures" if fails else None}


if __name__ == "__main__":
    import migrate
    con = connect(); migrate.apply_all(con)
    lim = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    syms = [a for a in sys.argv[1:] if not a.isdigit()] or None
    print(job(con, limit=lim, symbols=syms))
