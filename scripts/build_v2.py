"""Smart Money Intelligence 2.0 build step (runs after build.py; v1 exports are untouched).
1. apply versioned migrations; 2. detect signals from existing data; 3. link signals to entities;
4. load analyst hypotheses / thesis updates / valuations from data/analyst (reviewed commits only); 5. export data/export/v2/*.json.
No language model is used; no hypothesis is created, scored or promoted by the pipeline."""
from __future__ import annotations
import json, os, sys
from datetime import date, timedelta
from pathlib import Path
from common import connect, now, today, ROOT
from migrate import apply_all, applied
from intelligence.signal_detector import Detector, store, relationships, RULES, MECHANISM, AGENCY
from intelligence.opportunity_graph import Loader, STAGES, END_STAGES, STAGE_CRITERIA, DIMENSIONS, HORIZONS
from intelligence import valuation_engine as ve
from intelligence import fundamentals as FUND

EXP = Path(os.environ["SM_EXPORT"]) if os.environ.get("SM_EXPORT") else ROOT / "data" / "export"
ANALYST = Path(os.environ["SM_ANALYST"]) if os.environ.get("SM_ANALYST") else ROOT / "data" / "analyst"
V2 = EXP / "v2"
DISCLOSURE = "For educational and research purposes only; not investment advice; users must make their own decisions under their own registrations."


def jdump(name, obj):
    V2.mkdir(parents=True, exist_ok=True)
    (V2 / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str))


def rows(con, sql, *a):
    cur = con.execute(sql, a)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def entity_names(con, meta):
    names = dict(meta.get("industries", {}))
    for r in con.execute("SELECT company_id, name, symbol FROM companies"):
        names[r[0]] = r[1]
    return names


def export_signals(con, names, days=400):
    since = (today() - timedelta(days=days)).isoformat()
    sig = rows(con, """SELECT s.*, sd.url, src.name source_name FROM signals s LEFT JOIN source_documents sd ON sd.doc_id=s.doc_id
                       LEFT JOIN sources src ON src.source_id=s.source_id WHERE s.observed_at>=? ORDER BY s.observed_at DESC, s.signal_type""", since)
    for s in sig:
        s["entity_name"] = names.get(s["entity_id"], s["entity_id"])
        s["refs"] = len(json.loads(s.pop("refs_json") or "[]"))
        if s["entity_type"] == "company":
            r = con.execute("SELECT industry_id, symbol FROM companies WHERE company_id=?", (s["entity_id"],)).fetchone()
            s["industry_id"], s["symbol"] = (r[0], r[1]) if r else (None, None)
        else:
            s["industry_id"] = s["entity_id"]
    jdump("signals.json", {"generated": now(), "rules": {k: {"type": v["type"], "text": v["text"], "fresh_days": v["fresh_days"], "mechanism": MECHANISM[k]} for k, v in RULES.items()},
                           "agencies": AGENCY, "signals": sig})
    return sig


def export_opportunities(con, L: Loader, names):
    out = []
    for o in rows(con, "SELECT * FROM opportunities ORDER BY updated_at DESC"):
        oid = o["opportunity_id"]
        detail = json.loads(o.pop("detail_json") or "{}")
        hist = rows(con, "SELECT * FROM thesis_updates WHERE opportunity_id=? ORDER BY update_date, recorded_at", oid)
        ev = L.evidence(oid)
        for e in ev:
            e["entity_name"] = names.get(e["entity_id"], e["entity_id"])
        scs = rows(con, "SELECT * FROM opportunity_scenarios WHERE opportunity_id=? ORDER BY scenario_name", oid)
        for s in scs:
            s["assumptions"] = json.loads(s.pop("assumptions_json") or "null")
        comps = [dict(c, name=names.get(c["company_id"], c["company_id"])) for c in detail.get("companies", [])]
        vals = [v for v in L.vals if v.get("opportunity_id") == oid]
        crit = L.criteria(oid, detail)
        cur = o["stage"]
        nxt = None
        if cur in STAGES:
            i = STAGES.index(cur)
            for s in STAGES[i + 1:]:
                if crit[s]["met"]:
                    nxt = s
        o.update(detail=detail, companies=comps, history=hist, evidence=ev, scenarios=scs, criteria=crit, criteria_met_for_later_stage=nxt,
                 coverage=L.coverage(oid), related_unlinked=L.related_unlinked(oid, o["industry_id"], [c["company_id"] for c in comps])[:40],
                 industry_name=names.get(o["industry_id"], o["industry_id"]), valuation_ids=[v["valuation_id"] for v in vals],
                 overdue=bool(o.get("next_review") and o["next_review"] < today().isoformat()))
        o["scores"] = {k: o.pop(k) for k in ("demand_score", "economics_score", "competition_score", "capital_score", "execution_score", "valuation_score")}
        out.append(o)
    jdump("opportunities.json", {"generated": now(), "stages": STAGES, "end_stages": END_STAGES, "stage_criteria": STAGE_CRITERIA, "dimensions": DIMENSIONS,
                                 "horizons": HORIZONS, "opportunities": out, "analyst_file_errors": L.errors, "analyst_file_warnings": L.warnings})
    return out


def export_fundamentals(con, names):
    """Reported company financials + derived metrics (formulas stated). Unknown = null, shown as 'insufficient data'."""
    has = con.execute("SELECT 1 FROM sqlite_master WHERE name='company_financials'").fetchone()
    metrics = FUND.all_companies(con) if has else {}
    for cid, m in metrics.items():
        m["name"] = names.get(cid, cid)
        m["industry_id"] = (con.execute("SELECT industry_id FROM companies WHERE company_id=?", (cid,)).fetchone() or [None])[0]
        segs = con.execute("SELECT segment, revenue_cr, result_cr FROM company_segments WHERE company_id=? AND period_end=? AND basis=? ORDER BY revenue_cr DESC",
                           (cid, m["latest_quarter"], m["basis"])).fetchall() if has else []
        m["segments"] = [{"segment": a, "revenue_cr": None if b is None else round(b, 1), "result_cr": None if c is None else round(c, 1)} for a, b, c in segs]
        hist = con.execute("SELECT period_end, revenue_cr, ebitda_cr, pat_cr FROM company_financials WHERE company_id=? AND period_type='Q' AND basis=? ORDER BY period_end",
                           (cid, m["basis"])).fetchall()
        m["quarters"] = [[a, None if b is None else round(b, 1), None if c is None else round(c, 1), None if d is None else round(d, 1)] for a, b, c, d in hist]
    sec = FUND.sector_aggregates(con, metrics) if metrics else {}
    for v in sec.values():
        v.pop("company_ids", None)
    src = con.execute("SELECT status, last_success, latest_data_period FROM sources WHERE source_id='nse_financials'").fetchone()
    jdump("fundamentals.json", {"generated": now(), "formulas": FUND.FORMULAS, "units": "Rs crore unless stated",
                                "source": {"id": "nse_financials", "status": src and src[0], "last_success": src and src[1], "latest_period": src and src[2],
                                           "url": "https://www.nseindia.com/companies-listing/corporate-integrated-filing"},
                                "quarter_cols": ["period_end", "revenue_cr", "ebitda_cr", "pat_cr"],
                                "companies": metrics, "sectors": sec,
                                "notes": ["Values as tagged in the company's XBRL filing (consolidated when filed). Revenue is as reported and can include excise or other duties; a change in presentation can move growth and margins.",
                                          "SEBI integrated filing starts with the quarter ended Mar-2025, so growth comparisons begin with the Mar-2026 quarter.",
                                          "Balance sheet and cash flow appear only in half-year filings (Sep and Mar).",
                                          "Banks, NBFCs and insurers: EBITDA, net debt, ROCE and ROIC are not computed."]})
    return metrics


def _series(con, metric, entity_type, entity_id, n=None):
    q = "SELECT o.period_end, o.value, sd.url FROM observations o LEFT JOIN source_documents sd ON sd.doc_id=o.doc_id WHERE o.metric=? AND o.entity_type=? AND o.entity_id=? AND o.value IS NOT NULL ORDER BY o.period_end"
    r = con.execute(q, (metric, entity_type, entity_id)).fetchall()
    return r[-n:] if n else r


def export_industry(con, names):
    """Trade by HS chapter mapped to sectors, IIP by industry mapped to sectors, OBICUS capacity utilisation, commodity prices."""
    try:
        from ingest_industry import HS_SECTOR, IIP_SECTOR, iip_sectors
        from intelligence.signal_detector import COMMODITY_SECTORS
    except Exception:  # noqa: BLE001
        return
    from ingest_official import FRED
    hs_names = {r[0]: r[1].split(":", 1)[1] for r in con.execute("SELECT entity_id, metric FROM observations WHERE metric LIKE 'hs_name:%'")}
    iip_labels = {r[0]: r[1].split(":", 1)[1] for r in con.execute("SELECT entity_id, metric FROM observations WHERE metric LIKE 'iip_label:%'")}
    sectors = {}
    # trade: per sector, per financial year, sum of mapped chapters
    for metric, key in (("trade_export_usd_mn", "exports"), ("trade_import_usd_mn", "imports")):
        for hs, pe, v, url in con.execute("SELECT o.entity_id, o.period_end, o.value, sd.url FROM observations o LEFT JOIN source_documents sd ON sd.doc_id=o.doc_id WHERE o.metric=? AND o.value IS NOT NULL", (metric,)):
            for sec in HS_SECTOR.get(hs, []):
                t = sectors.setdefault(sec, {}).setdefault("trade", {"chapters": {}, "years": {}})
                t["chapters"][hs] = hs_names.get(hs, hs)
                y = t["years"].setdefault(pe, {"exports": 0.0, "imports": 0.0})
                y[key] += v
    for sec, d in sectors.items():
        t = d["trade"]
        rows = []
        for pe in sorted(t["years"]):
            y = t["years"][pe]; tot = y["exports"] + y["imports"]
            rows.append({"fy_end": pe, "exports_usd_mn": round(y["exports"], 1), "imports_usd_mn": round(y["imports"], 1),
                         "net_usd_mn": round(y["exports"] - y["imports"], 1), "import_share_pct": round(100 * y["imports"] / tot, 1) if tot else None})
        t["years"] = rows
    # IIP
    for key in [r[0] for r in con.execute("SELECT DISTINCT entity_id FROM observations WHERE metric='iip_yoy_pct_b2022'")]:
        for sec in iip_sectors(key):
            s = _series(con, "iip_yoy_pct_b2022", "iip_industry", key, 24)
            idx = _series(con, "iip_index_b2022", "iip_industry", key, 24)
            sectors.setdefault(sec, {}).setdefault("iip", []).append({"key": key, "label": iip_labels.get(key, key), "yoy": [[a, b] for a, b, _ in s],
                                                                      "index": [[a, b] for a, b, _ in idx], "url": s[-1][2] if s else None})
    gen = _series(con, "iip_yoy_pct_b2022", "iip_industry", "general", 24)
    obicus = {m: [[a, b] for a, b, _ in _series(con, m, "market", "india_manufacturing")] for m in ("obicus_cu_pct", "obicus_cu_sa_pct", "obicus_new_orders_yoy_pct")}
    ob_url = con.execute("SELECT sd.url FROM observations o JOIN source_documents sd ON sd.doc_id=o.doc_id WHERE o.metric='obicus_cu_sa_pct' ORDER BY o.period_end DESC LIMIT 1").fetchone()
    comm = []
    for sid, (lab, secs) in COMMODITY_SECTORS.items():
        s = _series(con, "fred_" + sid, "market", "global", 36)
        if s:
            comm.append({"series": sid, "name": lab, "unit": FRED.get(sid, ("", ""))[1], "values": [[a, b] for a, b, _ in s],
                         "url": f"https://fred.stlouisfed.org/series/{sid}", "sectors": [{"industry_id": a, "why": b} for a, b in secs]})
    status = {r[0]: {"status": r[1], "last_success": r[2], "latest_period": r[3]} for r in con.execute(
        "SELECT source_id, status, last_success, latest_data_period FROM sources WHERE source_id IN ('tradestat_eidb','un_comtrade','mospi_iip','rbi_obicus','fred','oea_core8','jpc_steel','cea_power','coal_ministry','fert_production','wto_timeseries','eia_api','iea_data','imf_datamapper')")}
    jdump("industry.json", {"generated": now(), "sectors": sectors, "iip_general_yoy": [[a, b] for a, b, _ in gen], "obicus": obicus,
                            "obicus_url": ob_url and ob_url[0], "commodities": comm, "source_status": status,
                            "mapping": {"hs_chapter_to_sector": HS_SECTOR, "iip_pattern_to_sector": [[p, s] for p, s in IIP_SECTOR]},
                            "notes": ["Import share = imports / (imports + exports) in the mapped HS chapters: a trade-mix measure, not a share of domestic consumption.",
                                      "HS chapters and IIP industries are mapped to NSE sectors with fixed tables; a chapter or industry can feed more than one sector, and services (IT, telecom services, finance) have no merchandise trade or IIP series.",
                                      "IIP quick estimates are revised in later releases. OBICUS is a survey of about 1,000 manufacturers, aggregate only."]})


def export_valuation(con, L: Loader, names, sectors, metrics=None):
    # reported context per company (no financial statements are ingested; that is stated, not filled)
    latest = rows(con, """SELECT o.company_id, o.period_end, o.value_inr_cr, o.quantity, sd.url, o.source_doc FROM (
                            SELECT company_id, period_end, value_inr_cr, quantity, doc_id, doc_id source_doc,
                                   ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY period_end DESC, quantity DESC) rn
                            FROM ownership WHERE holder_category='mf_portfolio' AND quantity>0 AND value_inr_cr>0) o
                          LEFT JOIN source_documents sd ON sd.doc_id=o.source_doc WHERE o.rn=1""")
    price = {r["company_id"]: {"period": r["period_end"], "price_inr": round(r["value_inr_cr"] * 1e7 / r["quantity"], 2), "url": r["url"]} for r in latest}
    pe = {s["id"]: {"index": (s.get("pe") or {}).get("name"), "pe": (s.get("pe") or {}).get("pe"), "as_of": (s.get("pe") or {}).get("as_of"),
                    "pctl_10y": (s.get("pe") or {}).get("pctl_10y"), "median_10y": (s.get("pe") or {}).get("median_10y")} for s in sectors}
    vals = []
    for v in L.vals:
        a = v.get("assumptions") or {}
        vals.append(dict(v, company_name=names.get(v.get("company_id"), v.get("company_id")), forward=ve.forward(a) if not ve.check(a) else None,
                         reverse=ve.reverse(a) if not ve.check(a) else None, label="SCENARIO (analyst assumptions)"))
    reported = {}
    for cid, m in (metrics or {}).items():
        t = m.get("ttm") or {}; b = m.get("balance_sheet") or {}; mc = m.get("market_cap") or {}; fy = (m.get("fy") or [{}])[-1]
        reported[cid] = {"symbol": m["symbol"], "basis": m["basis"], "financial_sector_format": m["financial_sector_format"],
                         "revenue_ttm_cr": t.get("revenue_cr"), "revenue_ttm_period": t.get("period_end"), "revenue_ttm_quarters": t.get("quarters"),
                         "ebitda_margin_ttm_pct": t.get("ebitda_margin_pct"), "ebit_margin_ttm_pct": t.get("ebit_margin_pct"),
                         "net_debt_cr": b.get("net_debt_cr"), "net_debt_date": b.get("date"), "net_debt_url": b.get("source_url"),
                         "market_cap_cr": mc.get("value_cr"), "market_cap_price_date": mc.get("price_date"), "market_cap_price_url": mc.get("price_url"), "market_cap_label": mc.get("label"),
                         "shares_outstanding": m.get("shares_outstanding"), "capex_fy_cr": fy.get("capex_cr"), "cfo_fy_cr": fy.get("cfo_cr"), "fy_end": fy.get("period_end"),
                         "fy_url": fy.get("source_url"), "returns": m.get("returns"), "source_url": m.get("source_url"), "latest_quarter": m.get("latest_quarter")}
    jdump("valuation.json", {"generated": now(), "reported_price": price, "sector_pe": pe, "valuations": vals, "reported": reported, "formulas": FUND.FORMULAS,
                             "not_ingested": ["working capital detail", "tax paid (cash)", "segment capital employed", "lease liabilities"],
                             "note": "Reported panel: values from the company's NSE XBRL filings (TTM = last four quarters) and an estimated market capitalisation (shares from the filing x NSE close). Analyst assumptions are never prefilled: every model input is entered by the analyst with a source note."})


def export_graph(con, names):
    rel = rows(con, "SELECT relationship_id, from_type, from_id, relation_type, to_type, to_id, mechanism, direction, confidence, valid_from FROM entity_relationships")
    for r in rel:
        r["from_name"] = names.get(r["from_id"], r["from_id"]); r["to_name"] = names.get(r["to_id"], r["to_id"])
    jdump("graph.json", {"generated": now(), "edges": rel})


def main():
    con = connect()
    ran = apply_all(con)
    meta = json.loads((EXP / "meta.json").read_text()) if (EXP / "meta.json").exists() else {}
    sectors = json.loads((EXP / "sectors.json").read_text()).get("sectors", []) if (EXP / "sectors.json").exists() else []
    ts = now()
    sigs = Detector(con, EXP).run()
    new = store(con, sigs, ts)
    relationships(con, sigs, ts)
    L = Loader(con, ANALYST / "opportunities.json", ANALYST / "valuations.json", ts).run()
    con.commit()
    names = entity_names(con, meta)
    s_all = export_signals(con, names)
    opps = export_opportunities(con, L, names)
    metrics = export_fundamentals(con, names)
    export_industry(con, names)
    export_valuation(con, L, names, sectors, metrics)
    export_graph(con, names)
    reg = applied(con)
    jdump("meta_v2.json", {"generated": ts, "disclosure": DISCLOSURE, "migrations": {k: v[0] for k, v in sorted(reg.items())}, "migrations_run_now": ran,
                           "signals_detected_this_build": len(sigs), "signals_new_this_build": new, "signals_exported": len(s_all), "hypotheses": len(opps),
                           "analyst_file_errors": L.errors, "v1_exports_unchanged": True,
                           "principle": "The platform does not try to predict which stock will rise. It records how the economy is changing, which businesses may be exposed, and whether the evidence keeps confirming or contradicting each analyst hypothesis."})
    con.commit()
    print(f"v2 built {ts}: migrations {sorted(reg)} (new {ran}), signals detected {len(sigs)} (new {new}), hypotheses {len(opps)}, analyst errors {len(L.errors)}")
    for e in L.errors:
        print("  analyst file error:", e)
    return L.errors


if __name__ == "__main__":
    errs = main()
    sys.exit(1 if errs and "--strict" in sys.argv else 0)
