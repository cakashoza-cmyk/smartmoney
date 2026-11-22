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


def export_valuation(con, L: Loader, names, sectors):
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
    jdump("valuation.json", {"generated": now(), "reported_price": price, "sector_pe": pe, "valuations": vals,
                             "not_ingested": ["revenue", "operating profit", "capital expenditure", "working capital", "tax paid", "ROIC", "shares outstanding / market value", "net debt"],
                             "note": "Company financial statements are not ingested in Sprint 1, so every model input is analyst-entered with a source note. Reported context shown: month-end price derived from fund-house files (market value / shares held) and the sector index P/E (NSE)."})


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
    export_valuation(con, L, names, sectors)
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
