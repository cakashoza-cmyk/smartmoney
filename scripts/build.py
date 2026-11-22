"""Intelligence layer: rule-based agents, convergence, five scores x three horizons, auditor, JSON/XLSX export.
No LLM anywhere. Every number traces to observations/transactions/ownership rows with a source document."""
from __future__ import annotations
import json, math, re, statistics as st
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from common import connect, hid, now, today, ROOT, upsert
from investors import classify_name
from registry import GROUPS

EXP = ROOT / "data" / "export"
WEIGHTS_FILE = ROOT / "data" / "weights.json"
TODAY = today()
INST_CATS = ("mf", "aif", "insurance", "pension", "bank", "nbfc", "other_fi", "swf_domestic", "fpi1", "fpi2", "other_foreign_inst", "swf_foreign")
DOM_CATS = ("mf", "aif", "insurance", "pension", "bank", "nbfc", "other_fi", "swf_domestic")
FOR_CATS = ("fpi1", "fpi2", "other_foreign_inst", "swf_foreign")
CORE_SECTORS = None  # filled from industries table (NSE macro sectors)

DEFAULT_WEIGHTS = {
    "capital_flow": {
        "1-3y": {"fpi_flow_3m": 25, "inst_share_change_qoq": 20, "inst_breadth_qoq": 20, "deals_net_inst_90d": 15, "new_independent_holders": 10, "bank_credit_fytd": 10},
        "3-10y": {"fpi_flow_persistence_36m": 20, "fpi_flow_12m": 15, "inst_share_change_yoy": 15, "bank_credit_yoy": 20, "aif_sector_growth_yoy": 15, "corporate_capital_events_180d": 15},
        "10-20y": {"fpi_cum_since_2017": 30, "bank_credit_yoy": 20, "aif_sector_growth_yoy": 20, "policy_commitments": 30},
    },
    "investor_activity": {
        "1-3y": {"new_positions_qoq": 40, "increased_positions_qoq": 30, "net_deal_buys_90d": 30},
        "3-10y": {"positions_held_5q": 40, "persistence_quarters": 40, "sector_breadth": 20},
        "10-20y": {"positions_held_5q": 50, "persistence_quarters": 50},
    },
    "industry_evidence": {
        "1-3y": {"bank_credit_fytd": 40, "rating_balance_12m": 30, "corporate_capital_events_180d": 30},
        "3-10y": {"bank_credit_yoy": 30, "rating_balance_12m": 20, "policy_commitments": 25, "aif_sector_growth_yoy": 25},
        "10-20y": {"policy_commitments": 50, "bank_credit_yoy": 25, "aif_sector_growth_yoy": 25},
    },
    "company_evidence": {
        "1-3y": {"inst_share_change_qoq": 40, "independent_holders": 30, "promoter_change_qoq": 30},
        "3-10y": {"inst_share_change_yoy": 40, "independent_holders": 30, "promoter_change_yoy": 30},
        "10-20y": {"independent_holders": 50, "inst_share_change_yoy": 50},
    },
    "valuation_context": {
        "1-3y": {"pe_percentile_10y": 100}, "3-10y": {"pe_percentile_10y": 100}, "10-20y": {"pe_percentile_10y": 100},
    },
}
NOT_AVAILABLE = {  # components the prompt asks for that no free structured source supplies (shown as insufficient data, never zero)
    "investor_activity": ["realised investment performance", "track record / failures", "governance standards"],
    "industry_evidence": ["addressable market", "supply constraints", "competitive intensity", "industry profitability", "technology change", "barriers to entry"],
    "company_evidence": ["return on invested capital", "cash flow", "balance sheet", "management quality", "execution ability", "competitive advantage"],
    "valuation_context": ["company-level valuation", "expected returns", "margin of safety", "scenario analysis"],
}


def weights():
    if WEIGHTS_FILE.exists():
        try:
            return json.loads(WEIGHTS_FILE.read_text())
        except Exception:  # noqa: BLE001
            pass
    WEIGHTS_FILE.write_text(json.dumps(DEFAULT_WEIGHTS, indent=1))
    return DEFAULT_WEIGHTS


def pct_rank(vals: dict):
    """Percentile rank 0-100 among non-null values. None stays None (insufficient data, never 0)."""
    xs = sorted(v for v in vals.values() if v is not None and not (isinstance(v, float) and math.isnan(v)))
    out = {}
    for k, v in vals.items():
        if v is None or len(xs) < 3:
            out[k] = None
            continue
        below = sum(1 for x in xs if x < v); eq = sum(1 for x in xs if x == v)
        out[k] = round(100 * (below + 0.5 * (eq - 1)) / (len(xs) - 1), 1) if len(xs) > 1 else 50.0
    return out


def combine(comp_scores: dict, w: dict, min_cover=0.5):
    """Weighted mean over available components; None if <50% of weight is available."""
    tot = sum(w.values()); have = {k: v for k, v in comp_scores.items() if v is not None and k in w}
    cov = sum(w[k] for k in have) / tot if tot else 0
    if cov < min_cover:
        return None, round(cov, 2)
    return round(sum(have[k] * w[k] for k in have) / sum(w[k] for k in have), 1), round(cov, 2)


def conf(cov):
    return "high" if cov >= 0.85 else "medium" if cov >= 0.65 else "low" if cov >= 0.5 else "insufficient"


def r1(x, n=1):
    return None if x is None else round(x, n)


class B:
    def __init__(self):
        self.con = connect()
        self.c = self.con.cursor()
        self.W = weights()
        self.ind = {r["industry_id"]: r["name"] for r in self.q("SELECT * FROM industries")}
        self.core = [i for i in self.ind if i not in ("sovereign", "others", "personal_retail_loans", "trade_wholesale_and_retail", "agriculture_and_allied", "infrastructure_cross_sector")]
        self.src = {r["source_id"]: dict(r) for r in self.q("SELECT * FROM sources")}
        self.conclusions = []

    def q(self, sql, *a):
        return [dict(r) for r in self.con.execute(sql, a)]

    def q1(self, sql, *a):
        r = self.con.execute(sql, a).fetchone()
        return r[0] if r else None

    # ------------------------------------------------------------------ re-resolve investor groups (rule changes apply retroactively)
    def reresolve(self):
        from common import slug
        for r in self.q("SELECT investor_id, name, group_id FROM investors"):
            gid, cat, rule = classify_name(r["name"])
            if not gid:
                gid = "self_" + slug(r["name"])[:60]
                if not self.q1("SELECT 1 FROM investor_groups WHERE group_id=?", gid):
                    upsert(self.con, "investor_groups", dict(group_id=gid, name=r["name"].title(), category=cat, country=None, aum_disclosed=None, passive_flag=0,
                                                             trading_flag=0, notes="no known parent; entity is its own group (" + rule + ")", source_url=None), "group_id")
            if gid != r["group_id"]:
                self.con.execute("UPDATE investors SET group_id=?, match_rule=? WHERE investor_id=?", (gid, rule, r["investor_id"]))
        self.con.commit()
        self.groups = {r["group_id"]: r for r in self.q("SELECT * FROM investor_groups")}

    def fixups(self):
        """Idempotent data repairs. Tiny deals were once rounded to 0.00 crore; recompute from quantity x price (4 decimals)."""
        self.con.execute("UPDATE transactions SET amount_inr_cr=round(quantity*price/1e7, 4) WHERE source_id='nse_deals' AND amount_inr_cr=0 AND quantity>0 AND price>0")
        self.con.commit()

    def excluded_group(self, gid):
        g = self.groups.get(gid) or {}
        return bool(g.get("trading_flag") or g.get("passive_flag") or g.get("category") in ("individual_or_unknown", "corporate", "promoter"))

    # ------------------------------------------------------------------ helpers over observations
    def series(self, metric, ent):
        return [(r["period_end"], r["value"], r["period_start"]) for r in self.q(
            "SELECT period_end, value, period_start FROM observations WHERE metric=? AND entity_id=? ORDER BY period_end", metric, ent)]

    # ------------------------------------------------------------------ FPI (NSDL)
    def fpi(self):
        rows = self.q("SELECT entity_id, period_start, period_end, value FROM observations WHERE metric='fpi_net_equity_inr_cr' ORDER BY period_end")
        sub = {r["sub_industry_id"]: r["industry_id"] for r in self.q("SELECT sub_industry_id, industry_id FROM sub_industries WHERE sub_industry_id LIKE 'nsdl_legacy_%'")}
        by = defaultdict(lambda: defaultdict(float)); has = defaultdict(lambda: defaultdict(bool))
        for r in rows:
            e = r["entity_id"]; e = sub.get(e, e)
            if r["value"] is None or e is None or e.startswith("nsdl_legacy_"):
                continue
            by[e][r["period_end"]] += r["value"]; has[e][r["period_end"]] = True
        periods = sorted({p for e in by for p in by[e]})
        auc = {}
        for e in by:
            a = self.q("SELECT period_end, value FROM observations WHERE metric='fpi_auc_equity_inr_cr' AND entity_id=? ORDER BY period_end DESC LIMIT 1", e)
            auc[e] = a[0] if a else None
        self.fpi_by, self.fpi_periods, self.fpi_auc = by, periods, auc
        last = periods[-1] if periods else None
        out = {}
        for e in by:
            ps = [p for p in periods if p in by[e]]
            def window(n):
                sel = ps[-n:]
                return sum(by[e][p] for p in sel) if len(sel) == n else None
            monthly = defaultdict(float)
            for p in ps:
                monthly[p[:7]] += by[e][p]
            ms = sorted(monthly)[-36:]
            pos = sum(1 for m in ms if monthly[m] > 0)
            a = auc[e]["value"] if auc.get(e) else None
            out[e] = {"net_3m": window(6), "net_12m": window(24), "net_36m": window(72), "cum_since_2017": sum(by[e][p] for p in ps if p >= "2017-01-01"),
                      "pos_months_36": pos, "months_36": len(ms), "auc": a, "auc_date": auc[e]["period_end"] if auc.get(e) else None,
                      "monthly": [[m, round(monthly[m])] for m in sorted(monthly)], "last_period": last}
        self.fpi_stats = out
        return out

    # ------------------------------------------------------------------ ownership (shareholding patterns)
    def ownership(self):
        qs = [r["period_end"] for r in self.q("SELECT period_end, count(DISTINCT company_id) n FROM ownership WHERE doc_id IS NOT NULL AND holder_category='public' GROUP BY 1 HAVING n>=200 ORDER BY 1")]
        self.quarters = qs
        cur, prev, yago = (qs[-1] if qs else None), (qs[-2] if len(qs) > 1 else None), (qs[-5] if len(qs) > 4 else (qs[0] if len(qs) > 2 else None))
        self.q_cur, self.q_prev, self.q_yago = cur, prev, yago
        own = defaultdict(dict)
        for r in self.q("SELECT company_id, period_end, holder_category, pct FROM ownership WHERE holder_name IS NULL AND pct IS NOT NULL"):
            own[r["company_id"]].setdefault(r["period_end"], {})[r["holder_category"]] = r["pct"]
        named = defaultdict(lambda: defaultdict(dict))
        for r in self.q("SELECT o.company_id, o.period_end, o.holder_name, o.pct, o.holder_category, i.group_id, o.doc_id FROM ownership o JOIN investors i ON i.investor_id=o.investor_id WHERE o.holder_name IS NOT NULL"):
            if self.excluded_group(r["group_id"]) or r["holder_category"] in ("named:ForeignDirectInvestment",):
                continue
            g = named[r["company_id"]][r["period_end"]]
            g.setdefault(r["group_id"], {"pct": 0.0, "names": [], "doc": r["doc_id"]})
            g[r["group_id"]]["pct"] += r["pct"]; g[r["group_id"]]["names"].append(r["holder_name"])
        self.own, self.named = own, named
        comp = {}
        for c in self.q("SELECT * FROM companies WHERE index_membership LIKE 'NIFTY 500%'"):
            cid = c["company_id"]; o = own.get(cid, {})
            def inst(qd):
                if not qd or "public" not in qd:
                    return None
                return sum(qd.get(k, 0) for k in INST_CATS)
            def dom(qd):
                return None if not qd or "public" not in qd else sum(qd.get(k, 0) for k in DOM_CATS)
            def fo(qd):
                return None if not qd or "public" not in qd else sum(qd.get(k, 0) for k in FOR_CATS)
            oc, op, oy = o.get(cur), o.get(prev), o.get(yago)
            ng_cur, ng_prev = named[cid].get(cur, {}), named[cid].get(prev, {})
            new_groups = [g for g in ng_cur if g not in ng_prev] if prev and ng_prev is not None and (op and "public" in op) else []
            exited = [g for g in ng_prev if g not in ng_cur] if cur and (oc and "public" in oc) else []
            prom = lambda qd: (qd or {}).get("promoter")
            d = lambda a, b: None if a is None or b is None else round(a - b, 3)
            comp[cid] = {"id": cid, "symbol": c["symbol"], "name": c["name"], "industry": c["industry_id"], "sub": c["sub_industry_id"],
                         "inst": r1(inst(oc), 2), "inst_qoq": d(inst(oc), inst(op)), "inst_yoy": d(inst(oc), inst(oy)),
                         "dom_qoq": d(dom(oc), dom(op)), "for_qoq": d(fo(oc), fo(op)), "dom_yoy": d(dom(oc), dom(oy)), "for_yoy": d(fo(oc), fo(oy)),
                         "mf": (oc or {}).get("mf"), "mf_qoq": d((oc or {}).get("mf"), (op or {}).get("mf")), "fpi": r1(fo(oc), 2),
                         "promoter": prom(oc), "promoter_qoq": d(prom(oc), prom(op)), "promoter_yoy": d(prom(oc), prom(oy)),
                         "independent_holders": len(ng_cur) if oc else None, "new_groups": new_groups, "exited_groups": exited, "has_cur": bool(oc and "public" in oc)}
        self.comp = comp
        return comp

    # ------------------------------------------------------------------ deals
    def deals(self, days=90):
        since = (TODAY - timedelta(days=days)).isoformat()
        rows = self.q("""SELECT t.*, i.group_id, i.name inv_name FROM transactions t JOIN investors i ON i.investor_id=t.investor_id
                         WHERE t.source_id='nse_deals' AND t.txn_date>=? """, since)
        by_co = defaultdict(lambda: defaultdict(float)); by_grp = defaultdict(lambda: defaultdict(float)); trading = 0; indiv = 0
        for r in rows:
            g = r["group_id"]
            if self.excluded_group(g):
                if (self.groups.get(g) or {}).get("trading_flag"):
                    trading += 1
                else:
                    indiv += 1
                continue
            v = (r["amount_inr_cr"] or 0) * (1 if r["side"] == "BUY" else -1)
            by_co[r["company_id"]][g] += v; by_grp[g][r["company_id"]] += v
        self.deal_co, self.deal_grp = by_co, by_grp
        self.deal_counts = {"rows": len(rows), "excluded_trading": trading, "excluded_other": indiv}
        return by_co

    # ------------------------------------------------------------------ sector metrics
    def sector_metrics(self):
        M = {}
        for s in self.ind:
            M[s] = {}
        # FPI
        for s, f in self.fpi_stats.items():
            if s not in M:
                continue
            a = f["auc"]
            M[s]["fpi_flow_3m"] = (f["net_3m"] / a * 100) if a and f["net_3m"] is not None else None
            M[s]["fpi_flow_12m"] = (f["net_12m"] / a * 100) if a and f["net_12m"] is not None else None
            M[s]["fpi_flow_persistence_36m"] = (f["pos_months_36"] / f["months_36"] * 100) if f["months_36"] >= 24 else None
            M[s]["fpi_cum_since_2017"] = (f["cum_since_2017"] / a * 100) if a else None
            M[s]["_fpi"] = f
        # ownership aggregates per sector (median of company changes + breadth)
        bys = defaultdict(list)
        for c in self.comp.values():
            if c["industry"] and c["has_cur"]:
                bys[c["industry"]].append(c)
        for s, cs in bys.items():
            q = [c["inst_qoq"] for c in cs if c["inst_qoq"] is not None]; y = [c["inst_yoy"] for c in cs if c["inst_yoy"] is not None]
            dq = [c["dom_qoq"] for c in cs if c["dom_qoq"] is not None]; fq = [c["for_qoq"] for c in cs if c["for_qoq"] is not None]
            M[s]["inst_share_change_qoq"] = st.median(q) if len(q) >= 3 else None
            M[s]["inst_share_change_yoy"] = st.median(y) if len(y) >= 3 else None
            M[s]["inst_breadth_qoq"] = (sum(1 for x in q if x > 0) / len(q) * 100) if len(q) >= 3 else None
            M[s]["dom_change_qoq"] = st.median(dq) if len(dq) >= 3 else None
            M[s]["for_change_qoq"] = st.median(fq) if len(fq) >= 3 else None
            M[s]["new_independent_holders"] = sum(len(c["new_groups"]) for c in cs)
            M[s]["_companies"] = len(cs)
        # deals
        for cid, gs in self.deal_co.items():
            ind = (self.comp.get(cid) or {}).get("industry") or self.q1("SELECT industry_id FROM companies WHERE company_id=?", cid)
            if ind in M:
                M[ind]["deals_net_inst_90d"] = M[ind].get("deals_net_inst_90d", 0) + sum(gs.values())
        # bank credit (RBI SIBC): outstanding-weighted YoY over mapped codes (leaf codes only to avoid double counting)
        last = self.q1("SELECT max(period_end) FROM observations WHERE metric='bank_credit_outstanding_inr_cr'")
        self.sibc_last = last
        if last:
            rows = self.q("""SELECT o.entity_id, o.value amt, s.industry_id, s.name,
                                (SELECT value FROM observations y WHERE y.metric='bank_credit_yoy_pct' AND y.entity_id=o.entity_id AND y.period_end=o.period_end) yoy,
                                (SELECT value FROM observations y WHERE y.metric='bank_credit_fy_pct' AND y.entity_id=o.entity_id AND y.period_end=o.period_end) fy
                             FROM observations o JOIN sub_industries s ON s.sub_industry_id=o.entity_id
                             WHERE o.metric='bank_credit_outstanding_inr_cr' AND o.period_end=?""", last)
            codes = {r["entity_id"][5:] for r in rows}
            leaf = [r for r in rows if not any(c.startswith(r["entity_id"][5:] + ".") for c in codes)]
            agg = defaultdict(lambda: [0.0, 0.0, 0.0])
            for r in leaf:
                if r["industry_id"] in M and r["industry_id"] != "others" and r["yoy"] is not None:
                    agg[r["industry_id"]][0] += r["amt"]; agg[r["industry_id"]][1] += r["amt"] * r["yoy"]; agg[r["industry_id"]][2] += r["amt"] * (r["fy"] or 0)
            for s, (a, wy, wf) in agg.items():
                M[s]["bank_credit_yoy"] = wy / a if a else None
                M[s]["bank_credit_fytd"] = wf / a if a else None
                M[s]["_credit_outstanding"] = a
            self.sibc_rows = rows
        else:
            self.sibc_rows = []
        # AIF sector growth (cumulative investment, latest vs ~1y earlier)
        aq = [r["period_end"] for r in self.q("SELECT DISTINCT period_end FROM observations WHERE metric='aif_sector_invested_cum_inr_cr' ORDER BY 1")]
        if len(aq) >= 2:
            cur = aq[-1]; ya = next((q for q in reversed(aq) if q <= (date.fromisoformat(cur) - timedelta(days=330)).isoformat()), aq[0])
            amap = {r["source_label"]: r["industry_id"] for r in self.q("SELECT source_label, industry_id FROM industry_map WHERE source_id='sebi_aif'")}
            cs = defaultdict(lambda: [0.0, 0.0])
            from common import slug
            for lab, ind in amap.items():
                if not ind or ind not in M:
                    continue
                a = self.q1("SELECT value FROM observations WHERE metric='aif_sector_invested_cum_inr_cr' AND entity_id=? AND period_end=?", "aif_sector_" + slug(lab), cur)
                b = self.q1("SELECT value FROM observations WHERE metric='aif_sector_invested_cum_inr_cr' AND entity_id=? AND period_end=?", "aif_sector_" + slug(lab), ya)
                if a is not None and b:
                    cs[ind][0] += a; cs[ind][1] += b
            for s, (a, b) in cs.items():
                M[s]["aif_sector_growth_yoy"] = (a / b - 1) * 100 if b else None
            self.aif_q = (ya, cur)
        # corporate capital events (announcements, REPORTED) 180d
        since = (TODAY - timedelta(days=180)).isoformat()
        for r in self.q("""SELECT c.industry_id s, count(*) n FROM transactions t JOIN companies c ON c.company_id=t.company_id
                           WHERE t.source_id='nse_announcements' AND t.announcement_date>=? AND t.txn_type IN ('acquisition','corporate_capex','joint_venture','primary_issuance','merger')
                           GROUP BY 1""", since):
            if r["s"] in M:
                M[r["s"]]["corporate_capital_events_180d"] = r["n"]
        # policy commitments (PIB cabinet approvals, REPORTED) - count over 365d
        for r in self.q("SELECT industry_id s, count(*) n, sum(amount_inr_cr) a FROM commitments WHERE commitment_id LIKE 'pibc_%' AND period>=? GROUP BY 1",
                        (TODAY - timedelta(days=365)).isoformat()):
            if r["s"] in M:
                M[r["s"]]["policy_commitments"] = r["n"]
        # ratings balance (CRISIL, counted actions, 12m, min 5)
        since = (TODAY - timedelta(days=365)).isoformat()
        rb = defaultdict(lambda: {"up": 0, "down": 0, "neg": 0, "counted": 0, "inc": 0})
        for r in self.q("SELECT industry_id, detail FROM debt WHERE source_id='crisil_ratings' AND period>=?", since):
            d = json.loads(r["detail"]); s = r["industry_id"] or "unclassified"
            if d["action"] == "inc_new":
                rb[s]["inc"] += 1
            if not d["counted"]:
                continue
            rb[s]["counted"] += 1; rb[s]["up"] += d["action"] == "upgrade"; rb[s]["down"] += d["action"] in ("downgrade", "downgrade_inc", "default"); rb[s]["neg"] += d["negative"]
        self.ratings = rb
        for s, v in rb.items():
            if s in M and v["counted"] >= 5:
                M[s]["rating_balance_12m"] = (v["up"] - v["neg"]) / v["counted"] * 100
        # valuation context: sector index P/E percentile vs its own 10y history
        from ingest_official import SECTOR_INDICES
        from common import slug
        self.pe = {}
        for name, s in SECTOR_INDICES.items():
            ent = "idx_" + slug(name)
            rows = self.q("SELECT period_end, value FROM observations WHERE metric='index_pe' AND entity_id=? AND value IS NOT NULL AND period_end>=? ORDER BY period_end",
                          ent, (TODAY - timedelta(days=3653)).isoformat())
            if len(rows) < 250:
                continue
            v = rows[-1]["value"]; xs = [r["value"] for r in rows]
            pctl = sum(1 for x in xs if x < v) / len(xs) * 100
            self.pe[name] = {"industry": s, "pe": v, "as_of": rows[-1]["period_end"], "pctl_10y": round(pctl, 1), "median_10y": round(st.median(xs), 1),
                             "from": rows[0]["period_end"], "n": len(xs), "monthly": [[r["period_end"], r["value"]] for i, r in enumerate(rows) if i % 21 == 0 or i == len(rows) - 1]}
            if s and s in M and "pe_percentile_10y" not in M[s]:
                M[s]["pe_percentile_10y"] = pctl; M[s]["_pe_index"] = name
        self.M = M
        return M

    # ------------------------------------------------------------------ scores
    def score_sectors(self):
        out = {}
        comps = set()
        for sc in ("capital_flow", "industry_evidence", "valuation_context"):
            for hz, w in self.W[sc].items():
                comps |= set(w)
        ranks = {k: pct_rank({s: self.M[s].get(k) for s in self.core}) for k in comps}
        for sc in ("capital_flow", "industry_evidence", "valuation_context"):
            out[sc] = {}
            for hz, w in self.W[sc].items():
                out[sc][hz] = {}
                for s in self.core:
                    if sc == "valuation_context":
                        v = self.M[s].get("pe_percentile_10y")
                        cs = {"pe_percentile_10y": None if v is None else round(v, 1)}
                    else:
                        cs = {k: ranks[k].get(s) for k in w}
                    score, cov = combine(cs, w)
                    out[sc][hz][s] = {"score": score, "coverage": cov, "confidence": conf(cov),
                                      "components": [{"name": k, "weight": w[k], "raw": r1(self.M[s].get(k), 2), "score": cs[k], "missing": cs[k] is None} for k in w],
                                      "not_assessed": NOT_AVAILABLE.get(sc, [])}
                    upsert(self.con, "scoring_history", dict(score_id=hid(sc, hz, "industry", s, TODAY), score_name=sc, horizon=hz, subject_type="industry", subject_id=s,
                                                             as_of=TODAY.isoformat(), score=score, components=json.dumps(out[sc][hz][s]["components"]), confidence=conf(cov),
                                                             missing=json.dumps([c["name"] for c in out[sc][hz][s]["components"] if c["missing"]] + NOT_AVAILABLE.get(sc, []))), "score_id")
        self.sector_scores = out
        return out

    def score_companies(self):
        cs = [c for c in self.comp.values() if c["has_cur"]]
        raw = {"inst_share_change_qoq": {c["id"]: c["inst_qoq"] for c in cs}, "inst_share_change_yoy": {c["id"]: c["inst_yoy"] for c in cs},
               "independent_holders": {c["id"]: c["independent_holders"] for c in cs}, "promoter_change_qoq": {c["id"]: c["promoter_qoq"] for c in cs},
               "promoter_change_yoy": {c["id"]: c["promoter_yoy"] for c in cs}}
        ranks = {k: pct_rank(v) for k, v in raw.items()}
        for hz, w in self.W["company_evidence"].items():
            for c in cs:
                comp = {k: ranks[k].get(c["id"]) for k in w}
                s, cov = combine(comp, w)
                c.setdefault("scores", {})[hz] = {"score": s, "confidence": conf(cov), "components": [{"name": k, "weight": w[k], "raw": raw[k].get(c["id"]), "score": comp[k], "missing": comp[k] is None} for k in w]}
                upsert(self.con, "scoring_history", dict(score_id=hid("company_evidence", hz, c["id"], TODAY), score_name="company_evidence", horizon=hz, subject_type="company",
                                                         subject_id=c["id"], as_of=TODAY.isoformat(), score=s, components=json.dumps(c["scores"][hz]["components"]),
                                                         confidence=conf(cov), missing=json.dumps(NOT_AVAILABLE["company_evidence"])), "score_id")

    # ------------------------------------------------------------------ investors
    def investors(self):
        cur, prev = self.q_cur, self.q_prev
        prof = {}
        for cid, per in self.named.items():
            for q, gs in per.items():
                for g, v in gs.items():
                    p = prof.setdefault(g, {"positions": defaultdict(dict)})
                    p["positions"][cid][q] = round(v["pct"], 3)
        for g, cs in self.deal_grp.items():
            prof.setdefault(g, {"positions": defaultdict(dict)})
        out = []
        for g, p in prof.items():
            meta = self.groups.get(g) or {}
            pos = p["positions"]
            new = [c for c, qq in pos.items() if cur in qq and prev and prev not in qq and (self.own.get(c, {}).get(prev) or {}).get("public") is not None]
            inc = [c for c, qq in pos.items() if cur in qq and prev in qq and qq[cur] > qq[prev] + 0.05]
            dec = [c for c, qq in pos.items() if cur in qq and prev in qq and qq[cur] < qq[prev] - 0.05]
            ex = [c for c, qq in pos.items() if prev in qq and cur not in qq and (self.own.get(c, {}).get(cur) or {}).get("public") is not None]
            held = [c for c, qq in pos.items() if cur in qq]
            persist = [len(qq) for qq in pos.values()]
            sectors = defaultdict(int)
            for c in held:
                sectors[(self.comp.get(c) or {}).get("industry") or "unclassified"] += 1
            deals = self.deal_grp.get(g, {})
            names = sorted({n for c in self.named for q in self.named[c] for gg, v in self.named[c][q].items() if gg == g for n in v["names"]})[:8]
            out.append({"id": g, "name": meta.get("name") or g, "category": meta.get("category"), "country": meta.get("country"), "aum": meta.get("aum_disclosed"),
                        "entities": names, "held": len(held), "new": new, "increased": inc, "decreased": dec, "exited": ex,
                        "persistence_q": r1(st.mean(persist), 2) if persist else None, "sectors": dict(sorted(sectors.items(), key=lambda x: -x[1])),
                        "deal_net_90d_cr": r1(sum(deals.values()), 1) if deals else None, "deal_companies": len(deals),
                        "positions": {c: qq for c, qq in pos.items()}, "parent_rule": (meta.get("notes") or "")[:140]})
        raw = {"new_positions_qoq": {o["id"]: len(o["new"]) for o in out}, "increased_positions_qoq": {o["id"]: len(o["increased"]) for o in out},
               "net_deal_buys_90d": {o["id"]: o["deal_net_90d_cr"] for o in out}, "positions_held_5q": {o["id"]: o["held"] for o in out},
               "persistence_quarters": {o["id"]: o["persistence_q"] for o in out}, "sector_breadth": {o["id"]: len(o["sectors"]) for o in out}}
        ranks = {k: pct_rank(v) for k, v in raw.items()}
        for o in out:
            o["scores"] = {}
            for hz, w in self.W["investor_activity"].items():
                comp = {k: ranks[k].get(o["id"]) for k in w}
                s, cov = combine(comp, w)
                o["scores"][hz] = {"score": s, "confidence": conf(cov), "components": [{"name": k, "weight": w[k], "raw": raw[k].get(o["id"]), "score": comp[k], "missing": comp[k] is None} for k in w],
                                   "not_assessed": NOT_AVAILABLE["investor_activity"]}
        out.sort(key=lambda o: (-(len(o["new"]) + len(o["increased"])), -o["held"]))
        self.inv = out
        return out

    # ------------------------------------------------------------------ convergence
    def convergence(self):
        rows = []
        for cid, c in self.comp.items():
            shp_new = set(c["new_groups"])
            deal_buy = {g for g, v in self.deal_co.get(cid, {}).items() if v > 0}
            groups = shp_new | deal_buy
            if len(groups) >= 2:
                rows.append({"company": cid, "symbol": c["symbol"], "name": c["name"], "industry": c["industry"], "independent_groups": len(groups),
                             "groups": sorted(groups), "via_shareholding": sorted(shp_new), "via_deals": sorted(deal_buy),
                             "domestic_qoq": c["dom_qoq"], "foreign_qoq": c["for_qoq"], "promoter_qoq": c["promoter_qoq"]})
        for cid, gs in self.deal_co.items():  # companies outside the Nifty 500 (deals only)
            if cid in self.comp:
                continue
            buy = {g for g, v in gs.items() if v > 0}
            if len(buy) >= 2:
                co = self.q("SELECT name, symbol, industry_id FROM companies WHERE company_id=?", cid)[0]
                rows.append({"company": cid, "symbol": co["symbol"], "name": co["name"], "industry": co["industry_id"], "independent_groups": len(buy), "groups": sorted(buy),
                             "via_shareholding": [], "via_deals": sorted(buy), "domestic_qoq": None, "foreign_qoq": None, "promoter_qoq": None})
        rows.sort(key=lambda r: -r["independent_groups"])
        for r in rows:
            r["group_names"] = {g: (self.groups.get(g) or {}).get("name", g) for g in r["groups"]}
        sec = defaultdict(set)
        for r in rows:
            sec[r["industry"] or "unclassified"] |= set(r["groups"])
        self.conv = rows
        self.conv_sector = {s: len(g) for s, g in sec.items()}
        return rows

    # ------------------------------------------------------------------ agents (rule-based) + auditor
    def add(self, agent, horizon, subj_type, subj, statement, label, refs, contra=None, confidence="medium"):
        cid = hid(agent, subj_type, subj, statement[:80], TODAY)
        self.conclusions.append(dict(conclusion_id=cid, agent=agent, horizon=horizon, subject_type=subj_type, subject_id=subj, statement=statement, evidence_label=label,
                                     evidence_refs=json.dumps(refs), contradicting_refs=json.dumps(contra or []), confidence=confidence, auditor_status="pending",
                                     auditor_notes=None, created_at=now()))

    def agents(self):
        nm = lambda s: self.ind.get(s, s)
        fmt = lambda x: f"{x:,.0f}"
        # Agent 1: Capital Flow Researcher (FPI by sector, last 3 months)
        flows = [(s, f["net_3m"]) for s, f in self.fpi_stats.items() if s in self.core and f["net_3m"] is not None]
        flows.sort(key=lambda x: x[1])
        lastp = self.fpi_periods[-1] if self.fpi_periods else None
        if flows:
            for s, v in flows[-3:][::-1] + flows[:3]:
                refs = [r["obs_id"] for r in self.q("SELECT obs_id FROM observations WHERE metric='fpi_net_equity_inr_cr' AND entity_id=? ORDER BY period_end DESC LIMIT 6", s)]
                contra = []
                dq = self.M.get(s, {}).get("dom_change_qoq")
                if dq is not None and ((v < 0 and dq > 0) or (v > 0 and dq < 0)):
                    contra.append(f"Domestic institutions' median holding change in {nm(s)} companies was {dq:+.2f} pp last quarter (shareholding patterns), the opposite direction.")
                self.add("Capital Flow Researcher", "1-3y", "industry", s,
                         f"FPIs {'bought' if v > 0 else 'sold'} a net Rs {fmt(abs(v))} crore of {nm(s)} equity in the 6 fortnights to {lastp} (NSDL).",
                         "VERIFIED FACT", refs, contra, "high")
        tot = self.fpi_stats.get("total")
        if tot and tot["net_12m"] is not None:
            self.add("Capital Flow Researcher", "1-3y", "market", "total", f"All-sector FPI net equity flow over the last 24 fortnights: Rs {fmt(tot['net_12m'])} crore (NSDL, to {lastp}).",
                     "VERIFIED FACT", [r["obs_id"] for r in self.q("SELECT obs_id FROM observations WHERE metric='fpi_net_equity_inr_cr' AND entity_id='total' ORDER BY period_end DESC LIMIT 24")], [], "high")
        # Agent 2: Investor Behaviour Analyst
        for o in self.inv[:6]:
            if not (o["new"] or o["increased"]):
                continue
            refs = [d for c in (o["new"] + o["increased"])[:5] for d in [self.q1("SELECT doc_id FROM ownership o JOIN investors i ON i.investor_id=o.investor_id WHERE i.group_id=? AND o.company_id=? AND o.period_end=? LIMIT 1", o["id"], c, self.q_cur)] if d]
            self.add("Investor Behaviour Analyst", "1-3y", "investor_group", o["id"],
                     f"{o['name']}: {len(o['new'])} new and {len(o['increased'])} increased above-1% holdings in Nifty 500 companies in the quarter to {self.q_cur} (fund family counted once).",
                     "VERIFIED FACT", refs, [f"{len(o['decreased'])} holdings reduced, {len(o['exited'])} dropped below 1% or exited"] if (o["decreased"] or o["exited"]) else [], "high")
        # Agent 3: Industry Research Analyst (credit + flows agreement)
        for s in self.core:
            m = self.M[s]
            cy, f12 = m.get("bank_credit_yoy"), m.get("fpi_flow_12m")
            if cy is None or f12 is None:
                continue
            sys_yoy = self.q1("SELECT value FROM observations WHERE metric='bank_credit_yoy_pct' AND entity_id='sibc_2' AND period_end=?", self.sibc_last)
            if sys_yoy is None:
                continue
            agree = (cy > sys_yoy and f12 > 0) or (cy < sys_yoy and f12 < 0)
            refs = [r["obs_id"] for r in self.q("SELECT obs_id FROM observations o JOIN sub_industries s ON s.sub_industry_id=o.entity_id WHERE o.metric='bank_credit_yoy_pct' AND s.industry_id=? AND o.period_end=?", s, self.sibc_last)][:4]
            refs += [r["obs_id"] for r in self.q("SELECT obs_id FROM observations WHERE metric='fpi_net_equity_inr_cr' AND entity_id=? ORDER BY period_end DESC LIMIT 2", s)]
            txt = (f"{nm(s)}: bank credit grew {cy:.1f}% YoY (industry total {sys_yoy:.1f}%) while FPI 12-month net flow was {f12:+.1f}% of FPI holdings. "
                   + ("Both streams point the same way." if agree else "The two streams disagree."))
            self.add("Industry Research Analyst", "3-10y", "industry", s, txt, "AI INTERPRETATION", refs,
                     [] if agree else ["Credit and portfolio flows point in opposite directions; neither is treated as confirmation."], "medium" if agree else "low")
        # Agent 4: Global Environment Analyst
        for sid, lab in (("DFII10", "US 10-year real yield"), ("DTWEXBGS", "US dollar broad index"), ("DCOILBRENTEU", "Brent crude"), ("DFF", "US Fed funds rate")):
            r = self.q("SELECT obs_id, period_end, value FROM observations WHERE metric=? ORDER BY period_end DESC LIMIT 13", "fred_" + sid)
            if len(r) >= 13 and r[0]["value"] is not None and r[12]["value"]:
                ch = r[0]["value"] - r[12]["value"]
                self.add("Global Environment Analyst", "3-10y", "global", sid, f"{lab}: {r[0]['value']:.2f} on {r[0]['period_end']}, {ch:+.2f} vs a year earlier (FRED).",
                         "VERIFIED FACT", [r[0]["obs_id"], r[12]["obs_id"]], [], "high")
        # Agent 5: Corporate Intelligence Analyst
        ev = self.q("""SELECT txn_type, count(*) n, sum(amount_inr_cr IS NOT NULL) w FROM transactions WHERE source_id='nse_announcements' AND announcement_date>=? GROUP BY 1""",
                    (TODAY - timedelta(days=90)).isoformat())
        if ev:
            refs = [r["txn_id"] for r in self.q("SELECT txn_id FROM transactions WHERE source_id='nse_announcements' ORDER BY announcement_date DESC LIMIT 10")]
            self.add("Corporate Intelligence Analyst", "1-3y", "market", "announcements",
                     "Capital events filed with NSE in the last 90 days: " + ", ".join(f"{r['txn_type'].replace('_', ' ')} {r['n']}" for r in ev) +
                     f". Amount stated in the filing summary for {sum(r['w'] for r in ev)} of them; the rest are undisclosed (no estimates).", "REPORTED ANNOUNCEMENT", refs, [], "medium")
        # Agent 6: Credit Intelligence Analyst
        for r in sorted([r for r in self.sibc_rows if r["yoy"] is not None and r["industry_id"] not in (None, "others")], key=lambda r: r["yoy"])[:3]:
            self.add("Credit Intelligence Analyst", "3-10y", "industry", r["entity_id"], f"Slowest bank-credit growth: {r['name']} {r['yoy']:+.1f}% YoY to {self.sibc_last} (RBI SIBC; outstanding stock, not new sanctions).",
                     "VERIFIED FACT", [self.q1("SELECT obs_id FROM observations WHERE metric='bank_credit_yoy_pct' AND entity_id=? AND period_end=?", r["entity_id"], self.sibc_last)], [], "high")
        for s, v in self.ratings.items():
            if s in self.ind and v["counted"] >= 10 and v["neg"] / v["counted"] >= 0.15:
                self.add("Credit Intelligence Analyst", "1-3y", "industry", s, f"{nm(s)}: {v['neg']} negative of {v['counted']} counted CRISIL rating actions in 12 months ({v['neg']/v['counted']*100:.0f}%).",
                         "VERIFIED FACT", [r["debt_id"] for r in self.q("SELECT debt_id FROM debt WHERE source_id='crisil_ratings' AND industry_id=? ORDER BY period DESC LIMIT 5", s)], [], "medium")
        # Agent 7: Capital Attention Analyst (renamed from 'Investment Opportunity Analyst'; no buy/sell language)
        for s in sorted(self.core, key=lambda s: -(self.sector_scores["capital_flow"]["1-3y"][s]["score"] or -1))[:3]:
            sc = self.sector_scores["capital_flow"]["1-3y"][s]
            if sc["score"] is None:
                continue
            pe = self.M[s].get("pe_percentile_10y")
            flags = [f"valuation context: sector index P/E is at the {pe:.0f}th percentile of its 10-year range"] if pe is not None and pe >= 80 else []
            self.add("Capital Attention Analyst", "1-3y", "industry", s, f"{nm(s)} ranks high on 1-3y capital attention (score {sc['score']:.0f}/100, {sc['confidence']} confidence). High attention is not a recommendation.",
                     "AI INTERPRETATION", [f"score:{s}:1-3y"], flags, sc["confidence"])
        # discrepancy checks (conflicting evidence across sources)
        self.discrepancies = []
        t1 = self.q("SELECT value, period_end FROM observations WHERE metric='aif_investments_cum_inr_cr' AND entity_id='aif_grand_total' ORDER BY period_end DESC LIMIT 1")
        if t1:
            t2 = self.q1("SELECT value FROM observations WHERE metric='aif_sector_invested_cum_inr_cr' AND entity_id='aif_sector_grand_total' AND period_end=?", t1[0]["period_end"])
            if t2 is not None and abs(t1[0]["value"] - t2) > 1:
                self.discrepancies.append({"topic": f"AIF cumulative investments, quarter to {t1[0]['period_end']}", "a": f"SEBI summary table: Rs {fmt(t1[0]['value'])} crore",
                                           "b": f"SEBI sector table: Rs {fmt(t2)} crore", "note": "Same SEBI page, different exclusions (sector table excludes some investee types). Both shown; neither adjusted."})
        nse_m = self.q("SELECT substr(period_end,1,7) m, sum(value) v, count(*) n FROM observations WHERE metric='fii_net_cash_inr_cr' GROUP BY 1")
        for r in nse_m:
            nsdl = sum(v for p, v in (self.fpi_by.get("total") or {}).items() if p.startswith(r["m"]))
            if r["n"] >= 15 and nsdl:
                self.discrepancies.append({"topic": f"FPI equity flows {r['m']}", "a": f"NSE provisional FII cash market: Rs {fmt(r['v'])} crore ({r['n']} days)",
                                           "b": f"NSDL final FPI equity (all routes): Rs {fmt(nsdl)} crore", "note": "NSE excludes primary market and is provisional; NSDL is final."})
        # Agent 8: Research Auditor (deterministic)
        kept = []
        for c in self.conclusions:
            refs = json.loads(c["evidence_refs"]); notes = []
            ok_refs = [r for r in refs if r and (r.startswith("score:") or self.q1("SELECT 1 FROM observations WHERE obs_id=?", r) or self.q1("SELECT 1 FROM transactions WHERE txn_id=?", r)
                                                 or self.q1("SELECT 1 FROM debt WHERE debt_id=?", r) or self.q1("SELECT 1 FROM source_documents WHERE doc_id=?", r))]
            if not ok_refs:
                c["auditor_status"] = "rejected"; notes.append("no traceable evidence row")
            else:
                c["auditor_status"] = "accepted"
            if re.search(r"\b(buy|sell|target|undervalued|attractive|recommend)\w*\b", c["statement"].replace("bought", "").replace("sold", ""), re.I):
                c["auditor_status"] = "rejected"; notes.append("recommendation language")
            if json.loads(c["contradicting_refs"]):
                c["auditor_status"] = "flagged" if c["auditor_status"] == "accepted" else c["auditor_status"]; notes.append("contradicting evidence shown")
            stale = [s for s, v in self.src.items() if v.get("status") == "working" and self.is_stale(v)]
            c["auditor_notes"] = "; ".join(notes) or "evidence rows present, dated, sourced"
            kept.append(c)
        # structural audit checks
        self.audit_checks = self.structural_checks()
        self.con.execute("DELETE FROM ai_conclusions WHERE created_at LIKE ?", (TODAY.isoformat() + "%",))
        for c in kept:
            upsert(self.con, "ai_conclusions", c, "conclusion_id")
        self.con.commit()
        return kept

    def structural_checks(self):
        chk = []
        n = self.q1("SELECT count(*) FROM deployments d JOIN commitments c ON c.commitment_id=d.commitment_id WHERE d.deployment_id=c.commitment_id")
        chk.append({"check": "Commitments and deployments are separate rows (never the same id, never summed)", "ok": n == 0, "detail": f"{n} overlaps"})
        bad = self.q1("SELECT count(*) FROM transactions WHERE doc_id IS NULL")
        chk.append({"check": "Every transaction has a source document", "ok": bad == 0, "detail": f"{bad} without source"})
        bad = self.q1("SELECT count(*) FROM observations WHERE doc_id IS NULL")
        chk.append({"check": "Every observation has a source document", "ok": bad == 0, "detail": f"{bad} without source"})
        bad = self.q1("SELECT count(*) FROM source_documents WHERE publication_date IS NULL AND data_period IS NULL")
        chk.append({"check": "Every source document has a publication date or data period", "ok": bad == 0, "detail": f"{bad} undated"})
        dup = sum(1 for r in self.conv if len(set(r["groups"])) != len(r["groups"]))
        fam = [g for r in self.conv for g in r["groups"] if self.excluded_group(g)]
        chk.append({"check": "Convergence counts parent groups once; trading desks, index funds and individuals excluded", "ok": dup == 0 and not fam, "detail": f"{dup} duplicates, {len(fam)} excluded groups found"})
        z = self.q1("SELECT count(*) FROM transactions WHERE amount_inr_cr = 0")
        chk.append({"check": "Undisclosed amounts stored as NULL, not zero", "ok": z == 0, "detail": f"{z} zero amounts"})
        return chk

    def is_stale(self, s):
        if not s.get("last_success") or not s.get("max_age_days"):
            return s.get("status") in ("working", "partial")
        ref = s.get("latest_data_period") or s.get("last_success")[:10]
        try:
            ref_d = date.fromisoformat(ref[:10])
        except Exception:  # noqa: BLE001
            ref_d = date.fromisoformat(s["last_success"][:10])
        lag = {"nsdl_fpi_sector": 10, "rbi_sibc": 45, "sebi_aif": 75, "nse_shp": 60, "amfi_monthly": 15, "worldbank": 400}.get(s["source_id"], 0)
        return (TODAY - ref_d).days > s["max_age_days"] + lag


# ====================================================================== export
SCENARIOS = [  # authored hypotheses, labelled SCENARIO; no numeric forecasts. Evidence is pulled live from the DB.
    {"id": "energy_transition", "theme": "Energy transition and grid storage", "industries": ["power", "capital_goods"], "wb": ["EG.FEC.RNEW.ZS"], "pib_rx": "solar|renewable|battery|hydrogen|nuclear|transmission|power",
     "scenario": "If India keeps adding renewable capacity and storage, demand could shift toward transmission, storage and grid equipment.",
     "confirm": "Renewable share of energy rising; bank credit to power growing faster than total industry credit; storage/transmission projects being commissioned (not only announced).",
     "invalidate": "Renewable share flat for several years; power-sector credit slowing or rating downgrades rising; announced projects not commissioned."},
    {"id": "electronics", "theme": "Electronics and semiconductor manufacturing", "industries": ["capital_goods", "consumer_durables", "information_technology"], "wb": ["TX.VAL.TECH.MF.ZS", "NV.IND.MANF.ZS"], "pib_rx": "semiconductor|electronics|chip",
     "scenario": "If supply chains keep diversifying out of China, India could take a larger share of electronics assembly and, later, components.",
     "confirm": "High-tech share of manufactured exports rising; bank credit to electronics growing; cabinet-approved semiconductor units reaching commercial production.",
     "invalidate": "High-tech export share flat; manufacturing share of GDP falling; approved units delayed or cancelled."},
    {"id": "demographics", "theme": "Working-age population and consumption", "industries": ["fast_moving_consumer_goods", "consumer_services", "consumer_durables", "financial_services"], "wb": ["SP.POP.1564.TO.ZS", "SP.URB.TOTL.IN.ZS", "NY.GDP.PCAP.CD"], "pib_rx": "skill|employment|consum",
     "scenario": "A large working-age population and rising urbanisation could keep consumption and household credit demand growing for years.",
     "confirm": "Working-age share still rising; urban share rising; personal-loan credit growing without rising delinquency.",
     "invalidate": "Working-age share peaking earlier than expected; household credit growth with rising stress."},
    {"id": "ageing_health", "theme": "Ageing and healthcare", "industries": ["healthcare"], "wb": ["SP.POP.65UP.TO.ZS"], "pib_rx": "health|medical|pharma|hospital",
     "scenario": "As the share of people over 65 rises, healthcare services, pharma and insurance demand could grow faster than GDP.",
     "confirm": "65+ share rising; healthcare credit and AIF investment in healthcare growing.",
     "invalidate": "Healthcare capital flows falling while the population ages (pricing or regulation limiting returns)."},
    {"id": "infrastructure", "theme": "Urbanisation and transport infrastructure", "industries": ["construction", "construction_materials", "infrastructure_cross_sector", "realty"], "wb": ["SP.URB.TOTL.IN.ZS", "NE.GDI.TOTL.ZS"], "pib_rx": "railway|highway|road|port|airport|metro|corridor|urban|housing",
     "scenario": "Urbanisation and public capex could sustain demand for construction, cement and logistics over the next two decades.",
     "confirm": "Gross capital formation share of GDP holding up; infrastructure credit growing; cabinet outlays turning into completed projects.",
     "invalidate": "Capital formation share falling; infrastructure credit shrinking (roads/railways already negative in some months)."},
    {"id": "water_food", "theme": "Water and food security", "industries": ["agriculture_and_allied", "chemicals"], "wb": ["ER.H2O.FWST.ZS"], "pib_rx": "water|irrigation|fertili|food|crop|farmer|fisher",
     "scenario": "Water stress and climate risk could raise the strategic value of irrigation, water treatment, fertiliser and food processing.",
     "confirm": "Freshwater withdrawal ratio high/rising; agri and food-processing credit growing; policy outlays for water and irrigation.",
     "invalidate": "No sustained capital flow into these segments despite the stress indicators."},
    {"id": "digital_ai", "theme": "Digital adoption, data centres and AI", "industries": ["information_technology", "telecommunication"], "wb": ["IT.NET.USER.ZS", "GB.XPD.RSDV.GD.ZS"], "pib_rx": r"\bAI\b|artificial intelligence|data cent|digital|semiconductor|broadband",
     "scenario": "Wider internet use and AI adoption could raise demand for data centres, power and telecom capacity.",
     "confirm": "Internet users rising; R&D spend rising; telecom and IT credit and portfolio flows positive.",
     "invalidate": "R&D share flat; telecom credit shrinking; FPIs persistently selling IT and telecom."},
    {"id": "defence_space", "theme": "Defence and space manufacturing", "industries": ["capital_goods"], "wb": [], "pib_rx": "defen[cs]e|space|aerospace|ship",
     "scenario": "Government push for domestic defence and space production could create a sustained order base for manufacturers.",
     "confirm": "Recurring cabinet approvals and contracts; capital goods credit and institutional ownership rising.",
     "invalidate": "Approvals not converting to orders; capital goods flows turning negative."},
]

TAB_METHOD = {
    "1-3y": {"question": "Where is institutional capital moving in the immediate and medium term?",
             "method": "Recent money only: FPI net equity flows over the last 6 fortnights (as % of FPI holdings in the sector), quarter-on-quarter change in institutional shareholding (median company), breadth (share of companies where institutions raised their stake), non-trading institutional net buying in bulk/block deals over 90 days, new independent >1% holders, and bank credit growth since March. Each component is a percentile rank across sectors.",
             "not_used": "Price moves, analyst views, news."},
    "3-10y": {"question": "Which industries attract long-duration capital?",
              "method": "Persistence and commitment: share of the last 36 months with positive FPI flows, 12-month FPI flow, year-on-year institutional shareholding change, bank credit YoY (RBI SIBC), growth in cumulative AIF investment by sector (SEBI), and corporate capital events filed with NSE (acquisitions, capex, JVs, QIPs) in 180 days.",
              "not_used": "Single-quarter swings; announced amounts are not added to deployed money."},
    "10-20y": {"question": "Where is capital positioning for structural change?",
               "method": "No forecasts. Themes are ranked by how many independent official indicators currently point the same way (World Bank structural series over 10 years, bank credit, AIF investment, FPI flows since 2017, Cabinet approvals). Each theme is a SCENARIO with explicit confirm and invalidate conditions.",
               "not_used": "Extrapolated growth rates, market-size estimates, company names."},
}

DISCLAIMER = ("Educational research on public capital-flow disclosures. Not investment advice and not a recommendation to buy, sell or hold any security. "
              "The author is not a SEBI-registered Investment Adviser or Research Analyst. Capital attention is not a view on returns.")


def jdump(name, obj):
    p = EXP / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, separators=(",", ":"), default=str))


def export(b: B):
    nm = lambda s: b.ind.get(s, s or "Unclassified")
    gname = lambda g: (b.groups.get(g) or {}).get("name", g)
    # -------------------------------------------------- sources + freshness + quality
    srcs = []
    for s in b.q("SELECT * FROM sources ORDER BY category, source_id"):
        s["stale"] = b.is_stale(s) if s["status"] in ("working", "partial") else None
        last = b.q("SELECT run_at, ok, error, rows_in, rows_new, duplicates_skipped FROM extraction_logs WHERE source_id=? ORDER BY run_at DESC LIMIT 1", s["source_id"])
        s["last_run"] = last[0] if last else None
        if last and not last[0]["ok"] and s["status"] == "working":
            s["status"] = "partial" if s["last_success"] else "blocked"
        srcs.append(s)
    cats = defaultdict(list)
    for s in srcs:
        cats[s["category"]].append(s)
    fresh = {c: {"last_success": max((s["last_success"] or "" for s in v), default="") or None, "stale_sources": [s["source_id"] for s in v if s["stale"]],
                 "working": sum(s["status"] == "working" for s in v), "total": len(v)} for c, v in cats.items()}
    fails = b.q("SELECT source_id, run_at, error FROM extraction_logs WHERE ok=0 ORDER BY run_at DESC LIMIT 40")
    dups = b.q("SELECT source_id, sum(duplicates_skipped) d, sum(rows_new) n FROM extraction_logs GROUP BY 1")
    missing = {
        "companies_without_industry": b.q1("SELECT count(*) FROM companies WHERE industry_id IS NULL"),
        "companies_total": b.q1("SELECT count(*) FROM companies"),
        "nifty500_without_latest_shp": sum(1 for c in b.comp.values() if not c["has_cur"]),
        "transactions_amount_undisclosed": b.q1("SELECT count(*) FROM transactions WHERE amount_inr_cr IS NULL"),
        "transactions_total": b.q1("SELECT count(*) FROM transactions"),
        "transactions_without_industry": b.q1("SELECT count(*) FROM transactions WHERE industry_id IS NULL AND company_id IS NOT NULL"),
        "rating_actions_without_industry": b.q1("SELECT count(*) FROM debt WHERE source_id='crisil_ratings' AND industry_id IS NULL"),
        "rating_actions_total": b.q1("SELECT count(*) FROM debt WHERE source_id='crisil_ratings'"),
        "investors_without_parent": b.q1("SELECT count(*) FROM investors WHERE group_id LIKE 'self_%'"),
        "investors_total": b.q1("SELECT count(*) FROM investors"),
    }
    counts = {t: b.q1(f"SELECT count(*) FROM {t}") for t in ("sources", "source_documents", "extraction_logs", "industries", "sub_industries", "investor_groups", "investors", "companies",
                                                            "ownership", "transactions", "commitments", "deployments", "acquisitions", "divestments", "capex", "debt", "observations", "ai_conclusions", "scoring_history")}
    meta = {"generated": now(), "disclaimer": DISCLAIMER, "quarters": b.quarters, "q_cur": b.q_cur, "q_prev": b.q_prev, "fpi_last": b.fpi_periods[-1] if b.fpi_periods else None,
            "sibc_last": b.sibc_last, "sources": srcs, "freshness": fresh, "industries": b.ind,
            "quality": {"counts": counts, "missing": missing, "failed_jobs": fails, "duplicates": dups, "stale": [s["source_id"] for s in srcs if s["stale"]],
                        "audit_checks": b.audit_checks, "discrepancies": b.discrepancies, "deal_filter": b.deal_counts},
            "weights": b.W, "not_assessed": NOT_AVAILABLE, "methods": TAB_METHOD,
            "groups": {g: {"name": v["name"], "category": v["category"], "trading": v["trading_flag"], "passive": v["passive_flag"]} for g, v in b.groups.items() if not g.startswith("self_")}}
    jdump("meta.json", meta)

    # -------------------------------------------------- executive time series (client aggregates by period)
    fpi_tot = sorted((p, v) for p, v in (b.fpi_by.get("total") or {}).items())
    fpi_sec = {s: [[p, round(v)] for p, v in sorted(b.fpi_by[s].items()) if p >= "2023-01-01"] for s in b.fpi_by if s in b.core}
    fii = b.q("SELECT period_end d, value v FROM observations WHERE metric='fii_net_cash_inr_cr' ORDER BY 1")
    dii = b.q("SELECT period_end d, value v FROM observations WHERE metric='dii_net_cash_inr_cr' ORDER BY 1")
    mf = defaultdict(float); mf_pass = defaultdict(float); mf_all = defaultdict(float)
    for r in b.q("SELECT entity_id, period_end, value FROM observations WHERE metric='mf_net_inflow_inr_cr' AND entity_id!='amfi_grand_total'"):
        e = r["entity_id"]
        if "growth_equity" in e or e.startswith("amfi_equity"):
            mf[r["period_end"]] += r["value"] or 0
        if "index_fund" in e or "etf" in e:
            mf_pass[r["period_end"]] += r["value"] or 0
        mf_all[r["period_end"]] += r["value"] or 0
    inst_deals = defaultdict(float)
    for r in b.q("SELECT t.txn_date d, t.side, t.amount_inr_cr a, i.group_id g FROM transactions t JOIN investors i ON i.investor_id=t.investor_id WHERE t.source_id='nse_deals'"):
        if not b.excluded_group(r["g"]) and r["a"]:
            inst_deals[r["d"]] += r["a"] * (1 if r["side"] == "BUY" else -1)
    aif = {}
    for r in b.q("SELECT entity_id, metric, period_end, value FROM observations WHERE source_id='sebi_aif' AND metric IN ('aif_commitments_cum_inr_cr','aif_funds_raised_cum_inr_cr','aif_investments_cum_inr_cr') ORDER BY period_end"):
        aif.setdefault(r["entity_id"], {}).setdefault(r["period_end"], {})[r["metric"].split("_")[1]] = r["value"]
    events = b.q("""SELECT t.txn_id id, t.txn_type type, t.announcement_date d, t.amount_inr_cr a, t.company_id c, co.name cn, co.industry_id s, t.description x, sd.url u, t.evidence_label l
                    FROM transactions t LEFT JOIN companies co ON co.company_id=t.company_id LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id
                    WHERE t.source_id IN ('nse_announcements','pib_cabinet') ORDER BY t.announcement_date DESC""")
    comm = b.q("""SELECT c.commitment_id id, c.scope, c.period, c.amount_inr_cr a, c.evidence_label l, c.industry_id s, sd.url u FROM commitments c LEFT JOIN source_documents sd ON sd.doc_id=c.doc_id ORDER BY c.period DESC""")
    big_deals = b.q("""SELECT t.txn_id id, t.txn_date d, t.side, t.amount_inr_cr a, co.symbol sym, co.name cn, co.industry_id s, i.name inv, i.group_id g, sd.url u
                       FROM transactions t JOIN investors i ON i.investor_id=t.investor_id JOIN companies co ON co.company_id=t.company_id LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id
                       WHERE t.source_id='nse_deals' AND t.txn_date>=? ORDER BY t.amount_inr_cr DESC""", (TODAY - timedelta(days=60)).isoformat())
    big_deals = [d for d in big_deals if not b.excluded_group(d["g"])][:40]
    for d in big_deals:
        d["gname"] = gname(d["g"])
    wb_fdi = b.q("SELECT period_end, value FROM observations WHERE metric='wb_BX.KLT.DINV.CD.WD' AND entity_id='IND' ORDER BY 1")
    unusual = []
    for s, ser in b.fpi_by.items():
        if s not in b.core:
            continue
        xs = [v for p, v in sorted(ser.items())][-73:]
        if len(xs) > 30:
            hist, last = xs[:-1], xs[-1]
            sd = st.pstdev(hist) or 1
            z = (last - st.mean(hist)) / sd
            if abs(z) >= 2:
                unusual.append({"industry": s, "z": round(z, 1), "last": round(last), "period": b.fpi_periods[-1]})
    top_co = sorted([c for c in b.comp.values() if c["inst_qoq"] is not None], key=lambda c: -c["inst_qoq"])[:15]
    themes = defaultdict(lambda: {"n": 0, "items": []})
    for e in events:
        if e["d"] and e["d"] >= (TODAY - timedelta(days=120)).isoformat() and e["type"] in ("capital_commitment", "announced_investment", "corporate_capex"):
            m = re.search(r"Theme: ([^.]+)$", e["x"] or "")
            k = m.group(1) if m and m.group(1) != "unclassified" else (nm(e["s"]) if e["s"] else None)
            if k:
                themes[k]["n"] += 1; themes[k]["items"].append(e["id"])
    exe = {"fpi_total": [[p, round(v)] for p, v in fpi_tot if p >= "2017-01-01"], "fpi_sector": fpi_sec, "fii": [[r["d"], r["v"]] for r in fii], "dii": [[r["d"], r["v"]] for r in dii],
           "mf_equity": sorted([[k, round(v)] for k, v in mf.items()]), "mf_passive": sorted([[k, round(v)] for k, v in mf_pass.items()]), "mf_all": sorted([[k, round(v)] for k, v in mf_all.items()]),
           "inst_deals": sorted([[k, round(v, 1)] for k, v in inst_deals.items()]), "aif": aif, "events": events[:400], "commitments": comm[:300], "big_deals": big_deals,
           "wb_fdi": [[r["period_end"][:4], r["value"]] for r in wb_fdi], "unusual": unusual, "top_companies": top_co,
           "themes": sorted([{"theme": k, **v} for k, v in themes.items()], key=lambda x: -x["n"])[:12],
           "active_investors": [{k: o[k] for k in ("id", "name", "category", "held", "deal_net_90d_cr")} | {"new": len(o["new"]), "increased": len(o["increased"]), "exited": len(o["exited"])} for o in b.inv[:15]],
           "sibc_total": b.q("SELECT entity_id, period_end, value FROM observations WHERE metric IN ('bank_credit_outstanding_inr_cr') AND entity_id IN ('sibc_2','sibc_3','sibc_1','sibc_4') ORDER BY period_end"),
           "infra_credit": b.q("SELECT period_end d, value v FROM observations WHERE metric='bank_credit_yoy_pct' AND entity_id='sibc_2.18' ORDER BY 1")}
    jdump("executive.json", exe)

    # -------------------------------------------------- sectors
    subs = {r["sub_industry_id"]: r for r in b.q("SELECT * FROM sub_industries")}
    sectors = []
    for s in list(b.core) + ["agriculture_and_allied", "infrastructure_cross_sector", "trade_wholesale_and_retail", "personal_retail_loans"]:
        m = b.M.get(s, {})
        cos = [c for c in b.comp.values() if c["industry"] == s]
        f = b.fpi_stats.get(s, {})
        credit = [dict(code=r["entity_id"][5:], name=r["name"], outstanding=r["amt"], yoy=r["yoy"], fy=r["fy"]) for r in b.sibc_rows if r["industry_id"] == s]
        hold = defaultdict(lambda: {"companies": 0, "new": 0})
        for c in cos:
            for g in b.named.get(c["id"], {}).get(b.q_cur, {}):
                hold[g]["companies"] += 1
            for g in c["new_groups"]:
                hold[g]["new"] += 1
        major = sorted([{"group": g, "name": gname(g), **v} for g, v in hold.items()], key=lambda x: (-x["new"], -x["companies"]))[:12]
        bysub = defaultdict(list)
        for c in cos:
            bysub[c["sub"] or "other_" + s].append(c["id"])
        txs = b.q("""SELECT t.txn_id id, t.txn_type type, coalesce(t.txn_date,t.announcement_date) d, t.amount_inr_cr a, t.side, co.symbol sym, i.name inv, i.group_id g, t.evidence_label l, sd.url u
                     FROM transactions t JOIN companies co ON co.company_id=t.company_id LEFT JOIN investors i ON i.investor_id=t.investor_id LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id
                     WHERE co.industry_id=? ORDER BY t.amount_inr_cr DESC LIMIT 200""", s)
        txs = [t for t in txs if not t["g"] or not b.excluded_group(t["g"])][:25]
        caps = b.q("""SELECT t.txn_id id, t.txn_type type, t.announcement_date d, t.amount_inr_cr a, co.symbol sym, substr(t.description,1,220) x, sd.url u FROM transactions t
                      JOIN companies co ON co.company_id=t.company_id LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id
                      WHERE co.industry_id=? AND t.txn_type IN ('corporate_capex','acquisition','joint_venture') ORDER BY t.announcement_date DESC LIMIT 15""", s)
        rt = b.ratings.get(s)
        risks = []
        if m.get("pe_percentile_10y") is not None and m["pe_percentile_10y"] >= 80:
            risks.append(f"Valuation context: {m.get('_pe_index')} P/E at the {m['pe_percentile_10y']:.0f}th percentile of its 10-year range.")
        if f.get("net_12m") is not None and f["net_12m"] < 0:
            risks.append(f"FPIs net sellers over 12 months (Rs {f['net_12m']:,.0f} crore).")
        if rt and rt["counted"] >= 5 and rt["neg"] / rt["counted"] >= 0.15:
            risks.append(f"CRISIL: {rt['neg']} of {rt['counted']} counted rating actions negative in 12 months.")
        if m.get("bank_credit_yoy") is not None and m["bank_credit_yoy"] < 0:
            risks.append("Bank credit to the sector is shrinking year on year.")
        sectors.append({"id": s, "name": nm(s), "metrics": {k: r1(v, 2) for k, v in m.items() if not k.startswith("_")},
                        "fpi": {k: f.get(k) for k in ("net_3m", "net_12m", "net_36m", "cum_since_2017", "auc", "auc_date", "pos_months_36", "months_36")} if f else None,
                        "fpi_monthly": f.get("monthly", []), "credit": credit, "credit_outstanding": m.get("_credit_outstanding"),
                        "companies": len(cos), "convergence_groups": b.conv_sector.get(s, 0),
                        "major_investors": major, "subs": [{"id": k, "name": (subs.get(k) or {}).get("name") or "Other " + nm(s), "companies": v} for k, v in sorted(bysub.items(), key=lambda x: -len(x[1]))],
                        "top_attention": [c["id"] for c in sorted([c for c in cos if c["inst_qoq"] is not None], key=lambda c: -c["inst_qoq"])[:10]],
                        "withdrawal": [c["id"] for c in sorted([c for c in cos if c["inst_qoq"] is not None], key=lambda c: c["inst_qoq"])[:8]],
                        "transactions": txs, "capacity_events": caps, "ratings": rt, "risks": risks,
                        "competitive_intensity": None, "pe": next((dict(name=k, **{x: v[x] for x in ("pe", "as_of", "pctl_10y", "median_10y", "from", "monthly")}) for k, v in b.pe.items() if v["industry"] == s), None),
                        "scores": {sc: {hz: b.sector_scores[sc][hz].get(s) for hz in b.sector_scores[sc]} for sc in b.sector_scores} if s in b.core else None})
    jdump("sectors.json", {"sectors": sectors, "legacy_note": "NSDL used ~40 finer sectors until Mar 2022; those are mapped to today's NSE sectors by name (approximate) for the long history."})

    # -------------------------------------------------- companies
    cos = b.q("SELECT company_id, name, symbol, industry_id, sub_industry_id, index_membership, listed FROM companies")
    dealn = defaultdict(int)
    for r in b.q("SELECT company_id, count(*) n FROM transactions GROUP BY 1"):
        dealn[r["company_id"]] = r["n"]
    idx = []
    for c in cos:
        x = b.comp.get(c["company_id"], {})
        sc = (x.get("scores") or {}).get("1-3y", {}).get("score")
        idx.append([c["company_id"], c["symbol"], c["name"], c["industry_id"], c["sub_industry_id"], 1 if (c["index_membership"] or "").startswith("NIFTY 500") else 0,
                    x.get("inst"), x.get("inst_qoq"), x.get("promoter"), x.get("promoter_qoq"), x.get("independent_holders"), len(x.get("new_groups") or []), dealn.get(c["company_id"], 0), sc])
    jdump("companies.json", {"cols": ["id", "symbol", "name", "industry", "sub", "nifty500", "inst_pct", "inst_qoq_pp", "promoter_pct", "promoter_qoq_pp", "independent_holders", "new_groups", "events", "evidence_1_3y"], "rows": idx})
    notable = {r["company_id"] for r in b.q("SELECT DISTINCT company_id FROM transactions WHERE source_id!='nse_deals' AND company_id IS NOT NULL")}
    notable |= {cid for cid in b.deal_co}  # companies with non-trading institutional deals in 90 days
    import shutil
    shutil.rmtree(EXP / "co", ignore_errors=True)
    for c in cos:
        cid = c["company_id"]
        if not (c["index_membership"] or cid in notable):
            continue
        o = b.own.get(cid, {})
        hist = {q: {k: v for k, v in d.items() if k in INST_CATS + ("promoter", "public", "fdi", "govt", "bodies_corporate", "retail_small", "retail_large", "nri", "promoter_summary", "public_summary")} for q, d in o.items()}
        named = {q: [{"group": g, "gname": gname(g), "pct": round(v["pct"], 3), "names": v["names"]} for g, v in sorted(gs.items(), key=lambda x: -x[1]["pct"])]
                 for q, gs in b.named.get(cid, {}).items()}
        docs = {r["period_end"]: r["url"] for r in b.q("SELECT DISTINCT o.period_end, sd.url FROM ownership o JOIN source_documents sd ON sd.doc_id=o.doc_id WHERE o.company_id=?", cid)}
        tl = b.q("""SELECT t.txn_id id, t.txn_type type, coalesce(t.txn_date,t.announcement_date) d, t.side, t.quantity q, t.price p, t.amount_inr_cr a, i.name inv, i.group_id g, t.description x, t.evidence_label l, sd.url u
                    FROM transactions t LEFT JOIN investors i ON i.investor_id=t.investor_id LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id WHERE t.company_id=? ORDER BY d DESC LIMIT 300""", cid)
        for t in tl:
            g = b.groups.get(t["g"]) or {}
            t["flag"] = "trading desk / broker" if g.get("trading_flag") else "index fund" if g.get("passive_flag") else "individual" if g.get("category") == "individual_or_unknown" else None
            if t["flag"] == "individual":
                t["inv"] = "Individual investor (name withheld here; see the NSE source)"
            t["gname"] = g.get("name") if not t["flag"] else None
        x = b.comp.get(cid, {})
        jdump(f"co/{c['symbol']}.json", {"id": cid, "name": c["name"], "symbol": c["symbol"], "industry": c["industry_id"], "sub": c["sub_industry_id"], "index": c["index_membership"],
                                          "ownership": hist, "named": named, "shp_docs": docs, "timeline": tl, "summary": {k: v for k, v in x.items() if k not in ("scores",)},
                                          "scores": x.get("scores"), "cin": None, "parent_group": None,
                                          "not_assessed": NOT_AVAILABLE["company_evidence"] + ["PE/VC investors in unlisted rounds (paid databases)", "debt raised (only NCD/CP allotment filings)"]})

    # -------------------------------------------------- transactions explorer (400 days; trading desks and individuals left out, counted)
    txall = b.q("""SELECT t.txn_id, t.txn_type, coalesce(t.txn_date,t.announcement_date) d, co.symbol, co.name, co.industry_id, i.group_id, i.name inv, t.side, t.amount_inr_cr a,
                          t.evidence_label l, sd.url, t.source_id FROM transactions t LEFT JOIN companies co ON co.company_id=t.company_id LEFT JOIN investors i ON i.investor_id=t.investor_id
                          LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id WHERE coalesce(t.txn_date,t.announcement_date)>=? ORDER BY 3 DESC""", (TODAY - timedelta(days=400)).isoformat())
    trows, skipped = [], {"trading_or_broker": 0, "individual_or_corporate": 0}
    for r in txall:
        g = b.groups.get(r["group_id"]) or {}
        if r["group_id"] and g.get("trading_flag"):
            skipped["trading_or_broker"] += 1; continue
        if r["group_id"] and g.get("category") in ("individual_or_unknown", "corporate", "promoter"):
            skipped["individual_or_corporate"] += 1; continue
        trows.append([r["txn_id"], r["txn_type"], r["d"], r["symbol"], r["name"], r["industry_id"], r["group_id"], g.get("name"), r["inv"], r["side"], r["a"], r["l"],
                      r["url"] if r["source_id"] != "nse_deals" else None, r["source_id"], g.get("country"), 1 if g.get("passive_flag") else 0])
    jdump("transactions.json", {"cols": ["id", "type", "date", "symbol", "company", "industry", "group", "group_name", "investor", "side", "amount_cr", "label", "url", "source", "country", "passive"],
                                "rows": trows, "skipped": skipped, "deals_url": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"})

    # -------------------------------------------------- investors + convergence
    inv = []
    for o in b.inv:
        o2 = dict(o); o2["positions"] = {cid.split(":")[1]: qq for cid, qq in o["positions"].items()}
        for k in ("new", "increased", "decreased", "exited"):
            o2[k] = [c.split(":")[1] for c in o[k]]
        inv.append(o2)
    agg_inv = [{"id": "agg_fpi", "name": "All FPIs (aggregate, NSDL)", "category": "fpi", "note": "Net equity flow by sector from NSDL; no names."},
               {"id": "agg_mf", "name": "All mutual funds (aggregate, AMFI)", "category": "mutual_fund", "note": "Net inflows by scheme category from AMFI."},
               {"id": "agg_aif", "name": "All AIFs (aggregate, SEBI)", "category": "aif", "note": "Commitments, funds raised and investments by AIF category."}]
    jdump("investors.json", {"groups": inv, "aggregates": agg_inv, "convergence": b.conv[:300], "q_cur": b.q_cur, "q_prev": b.q_prev,
                             "rules": "Names are mapped to parent groups by fixed name rules (registry.py). Funds of one family count once. Trading desks, brokers, ODI/P-note desks, index funds/ETFs and individuals are excluded from convergence and activity counts. Below-1% holdings are not disclosed by companies and are invisible here."})

    # -------------------------------------------------- horizons + radar
    def rank(sc, hz, n=20, rev=False):
        d = b.sector_scores[sc][hz]
        xs = [(s, v) for s, v in d.items() if v["score"] is not None]
        xs.sort(key=lambda x: (x[1]["score"] if not rev else -x[1]["score"]), reverse=True)
        out = []
        for s, v in xs[:n]:
            why = sorted([c for c in v["components"] if c["score"] is not None], key=lambda c: -c["score"] * c["weight"])[:2]
            flags = []
            pe = b.M[s].get("pe_percentile_10y")
            if pe is not None and pe >= 80:
                flags.append(f"rich valuation context ({pe:.0f}th pct)")
            rt = b.ratings.get(s)
            if rt and rt["counted"] >= 5 and rt["neg"] / rt["counted"] >= 0.15:
                flags.append("rating downgrades elevated")
            flags += ["competition, capital efficiency, oversupply: not assessed (no free structured source)"]
            out.append({"id": s, "name": nm(s), "score": v["score"], "confidence": v["confidence"], "components": v["components"],
                        "why": [f"{c['name'].replace('_', ' ')}: {c['raw']} (rank {c['score']:.0f}/100, weight {c['weight']})" for c in why], "flags": flags})
        return out
    gen = []
    for th in SCENARIOS:
        ev = []
        for ind in th["wb"]:
            r = b.q("SELECT period_end, value, obs_id FROM observations WHERE metric=? AND entity_id='IND' AND value IS NOT NULL ORDER BY period_end", "wb_" + ind)
            if len(r) >= 2:
                a = next((x for x in r if x["period_end"] >= f"{int(r[-1]['period_end'][:4]) - 10}"), r[0])
                ev.append({"kind": "structural", "label": ind, "from": [a["period_end"][:4], a["value"]], "to": [r[-1]["period_end"][:4], r[-1]["value"]],
                           "direction": "up" if r[-1]["value"] > a["value"] else "down", "ref": r[-1]["obs_id"], "evidence_label": "VERIFIED FACT", "source": "World Bank WDI"})
        for s in th["industries"]:
            m = b.M.get(s, {})
            if m.get("bank_credit_yoy") is not None:
                ev.append({"kind": "credit", "label": f"Bank credit YoY, {nm(s)}", "value": round(m["bank_credit_yoy"], 1), "direction": "up" if m["bank_credit_yoy"] > 0 else "down", "evidence_label": "VERIFIED FACT", "source": "RBI SIBC"})
            if m.get("fpi_cum_since_2017") is not None:
                ev.append({"kind": "portfolio", "label": f"FPI net flow since 2017, {nm(s)} (% of holdings)", "value": round(m["fpi_cum_since_2017"], 1), "direction": "up" if m["fpi_cum_since_2017"] > 0 else "down", "evidence_label": "VERIFIED FACT", "source": "NSDL"})
            if m.get("aif_sector_growth_yoy") is not None:
                ev.append({"kind": "private", "label": f"AIF cumulative investment growth, {nm(s)}", "value": round(m["aif_sector_growth_yoy"], 1), "direction": "up" if m["aif_sector_growth_yoy"] > 0 else "down", "evidence_label": "VERIFIED FACT", "source": "SEBI"})
        pol = b.q("SELECT t.txn_id, t.announcement_date d, t.description x, sd.url u FROM transactions t JOIN source_documents sd ON sd.doc_id=t.doc_id WHERE t.source_id IN ('pib_cabinet','nse_announcements') AND t.announcement_date>=?",
                  (TODAY - timedelta(days=365)).isoformat())
        pol = [p for p in pol if re.search(th["pib_rx"], p["x"] or "", re.I)]
        if pol:
            ev.append({"kind": "announcements", "label": "Government / corporate announcements matching the theme (12 months)", "value": len(pol), "direction": "up", "evidence_label": "REPORTED ANNOUNCEMENT", "source": "PIB / NSE", "items": pol[:8]})
        up = sum(1 for e in ev if e["direction"] == "up"); down = sum(1 for e in ev if e["direction"] == "down")
        gen.append({**{k: th[k] for k in ("id", "theme", "scenario", "confirm", "invalidate")}, "industries": [nm(s) for s in th["industries"]], "evidence": ev, "supporting": up, "contrary": down,
                    "label": "SCENARIO", "status": "insufficient data" if len(ev) < 3 else ("evidence mostly supportive" if up > 2 * down else "mixed evidence" if up >= down else "evidence mostly contrary")})
    gen.sort(key=lambda g: (-(g["supporting"] - g["contrary"]), -g["supporting"]))
    rot = sorted([{"id": s, "name": nm(s), "domestic": r1(b.M[s].get("dom_change_qoq"), 3), "foreign": r1(b.M[s].get("for_change_qoq"), 3), "fpi_3m": r1((b.fpi_stats.get(s) or {}).get("net_3m"), 0)}
                  for s in b.core if b.M[s].get("dom_change_qoq") is not None], key=lambda x: -(x["domestic"] or 0))
    amfi_cat = defaultdict(list)
    for r in b.q("SELECT entity_id, period_end, value FROM observations WHERE metric='mf_net_inflow_inr_cr' AND period_end>=? ORDER BY period_end", (TODAY - timedelta(days=400)).isoformat()):
        amfi_cat[r["entity_id"]].append([r["period_end"], r["value"]])
    newent = [{"company": c["id"], "symbol": c["symbol"], "name": c["name"], "industry": c["industry"], "groups": [gname(g) for g in c["new_groups"]]} for c in b.comp.values() if c["new_groups"]]
    newent.sort(key=lambda x: -len(x["groups"]))
    hz = {"methods": TAB_METHOD,
          "1-3y": {"ranking": rank("capital_flow", "1-3y"), "accumulation": [c["id"] for c in top_co], "rotation": rot, "new_entries": newent[:40], "amfi": amfi_cat,
                   "deals": big_deals[:20], "fii": exe["fii"][-60:], "dii": exe["dii"][-60:], "fpi_total": exe["fpi_total"][-48:]},
          "3-10y": {"ranking": rank("capital_flow", "3-10y"), "industry_evidence": rank("industry_evidence", "3-10y"),
                    "credit": sorted([dict(code=r["entity_id"][5:], name=r["name"], yoy=r["yoy"], outstanding=r["amt"], industry=r["industry_id"]) for r in b.sibc_rows if r["yoy"] is not None], key=lambda r: -r["yoy"]),
                    "aif": aif, "capital_events": [e for e in events if e["type"] in ("corporate_capex", "acquisition", "joint_venture", "merger")][:40],
                    "supply_chain": {c: b.q("SELECT period_end, value FROM observations WHERE metric='wb_BX.KLT.DINV.CD.WD' AND entity_id=? ORDER BY 1", c) for c in ("IND", "CHN", "VNM", "IDN", "MEX")},
                    "manufacturing": {c: b.q("SELECT period_end, value FROM observations WHERE metric='wb_NV.IND.MANF.ZS' AND entity_id=? ORDER BY 1", c) for c in ("IND", "CHN", "VNM", "IDN", "MEX")},
                    "forecast_note": "Long-term demand and capacity forecasts: not produced. No free official source publishes them in structured form, and this system does not extrapolate."},
          "10-20y": {"themes": gen, "wb": {ind: b.q("SELECT period_end, value FROM observations WHERE metric=? AND entity_id='IND' ORDER BY 1", "wb_" + ind) for ind in
                                           ("SP.POP.1564.TO.ZS", "SP.POP.65UP.TO.ZS", "SP.URB.TOTL.IN.ZS", "EG.FEC.RNEW.ZS", "GB.XPD.RSDV.GD.ZS", "IT.NET.USER.ZS", "NV.IND.MANF.ZS", "NE.GDI.TOTL.ZS", "SP.DYN.TFRT.IN", "ER.H2O.FWST.ZS")},
                     "demography_compare": {c: b.q("SELECT period_end, value FROM observations WHERE metric='wb_SP.POP.1564.TO.ZS' AND entity_id=? ORDER BY 1", c) for c in ("IND", "CHN", "VNM", "IDN", "MEX")}}}
    jdump("horizons.json", hz)
    attn = []
    for c in sorted([c for c in b.comp.values() if c["inst_qoq"] is not None], key=lambda c: -c["inst_qoq"])[:50]:
        fl = []
        pe = b.M.get(c["industry"], {}).get("pe_percentile_10y")
        if pe is not None and pe >= 80:
            fl.append(f"sector valuation context rich ({pe:.0f}th pct)")
        if c["promoter_qoq"] is not None and c["promoter_qoq"] < -0.5:
            fl.append(f"promoter stake fell {c['promoter_qoq']:.2f} pp")
        if c["for_qoq"] is not None and c["dom_qoq"] is not None and c["for_qoq"] * c["dom_qoq"] < 0:
            fl.append("domestic and foreign institutions moved in opposite directions")
        attn.append({"id": c["id"], "symbol": c["symbol"], "name": c["name"], "industry": c["industry"], "inst_qoq": c["inst_qoq"], "dom_qoq": c["dom_qoq"], "for_qoq": c["for_qoq"],
                     "new_groups": [gname(g) for g in c["new_groups"]], "why": f"Institutional holding {c['inst_qoq']:+.2f} pp in the quarter to {b.q_cur} (MF {c['mf_qoq'] if c['mf_qoq'] is not None else 'n/a'} pp)", "flags": fl})
    contr = sorted([x for x in rot if x["domestic"] is not None and x["foreign"] is not None and x["domestic"] > 0 and x["foreign"] < 0], key=lambda x: -(x["domestic"] - x["foreign"]))
    withd = sorted([{"id": s, "name": nm(s), "fpi_12m": r1((b.fpi_stats.get(s) or {}).get("net_12m"), 0), "inst_qoq": r1(b.M[s].get("inst_share_change_qoq"), 3), "credit_yoy": r1(b.M[s].get("bank_credit_yoy"), 1),
                     "score": b.sector_scores["capital_flow"]["1-3y"][s]["score"]} for s in b.core if b.sector_scores["capital_flow"]["1-3y"][s]["score"] is not None], key=lambda x: x["score"])[:20]
    subrank = sorted([{"id": r["entity_id"], "name": r["name"], "basis": "RBI SIBC bank credit YoY", "value": r["yoy"], "industry": r["industry_id"]} for r in b.sibc_rows
                      if r["yoy"] is not None and r["industry_id"] not in (None, "others", "personal_retail_loans") and "." in r["entity_id"]], key=lambda x: -x["value"])[:20]
    radar = {"sectors": {h: rank("capital_flow", h) for h in ("1-3y", "3-10y")}, "themes_10_20": gen, "sub_sectors": subrank, "companies_attention": attn,
             "multi_investor": b.conv[:20], "private_companies": {"rows": [], "status": "insufficient data", "reason": "Unlisted funding rounds need paid databases (Tracxn, Venture Intelligence, VCCEdge) or MCA filings (login and per-document fees). Connectors are built but not connected."},
             "contrarian": contr[:20], "contrarian_rule": "Domestic institutions (MF, insurance, pension, banks, AIF) raised their median stake while foreign institutions cut theirs, in the latest quarter.",
             "withdrawal": withd, "valuation": b.pe, "language_note": "'Capital attention' replaces 'opportunity' and 'attractiveness': it measures where disclosed money is moving, not whether a security is worth owning."}
    jdump("radar.json", radar)

    # -------------------------------------------------- credit
    cr = {"sibc": [dict(code=r["entity_id"][5:], name=r["name"], outstanding=r["amt"], yoy=r["yoy"], fy=r["fy"], industry=r["industry_id"]) for r in b.sibc_rows],
          "sibc_last": b.sibc_last, "sibc_history": defaultdict(list),
          "ratings": {s: v for s, v in b.ratings.items()},
          "recent_actions": b.q("SELECT d.period, d.borrower, d.industry_id, d.detail, sd.url FROM debt d LEFT JOIN source_documents sd ON sd.doc_id=d.doc_id WHERE d.source_id='crisil_ratings' AND (d.detail LIKE '%\"action\": \"upgrade%' OR d.detail LIKE '%downgrade%' OR d.detail LIKE '%default%') ORDER BY d.period DESC LIMIT 150"),
          "debt_raised": b.q("SELECT t.announcement_date d, co.symbol sym, co.name cn, t.amount_inr_cr a, substr(t.description,1,200) x, sd.url u FROM transactions t JOIN companies co ON co.company_id=t.company_id LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id WHERE t.txn_type='capital_raised' ORDER BY d DESC LIMIT 60"),
          "not_available": ["sanctioned vs disbursed credit by sector", "project finance sanctions", "NBFC on-lending by end sector", "refinancing vs new productive lending split"]}
    for r in b.q("SELECT entity_id, period_end, value FROM observations WHERE metric='bank_credit_yoy_pct' ORDER BY period_end"):
        cr["sibc_history"][r["entity_id"][5:]].append([r["period_end"], r["value"]])
    jdump("credit.json", cr)

    # -------------------------------------------------- global
    fred = {}
    for sid in ("DFF", "DGS10", "DFII10", "DTWEXBGS", "DCOILBRENTEU", "DEXINUS"):
        fred[sid] = [[r["period_end"], r["value"]] for r in b.q("SELECT period_end, value FROM observations WHERE metric=? ORDER BY period_end", "fred_" + sid)]
    # computed sensitivity: monthly FPI total vs change in US real yield (ESTIMATED, correlation only)
    sens = None
    if fred["DFII10"] and b.fpi_by.get("total"):
        ry = {d[:7]: v for d, v in fred["DFII10"]}
        mon = defaultdict(float)
        for p, v in b.fpi_by["total"].items():
            mon[p[:7]] += v
        ks = sorted(k for k in mon if k in ry)
        pairs = [(mon[k], ry[k] - ry[ks[i - 1]]) for i, k in enumerate(ks) if i > 0 and ks[i - 1] in ry]
        if len(pairs) > 24:
            x = [p[1] for p in pairs]; y = [p[0] for p in pairs]
            mx, my = st.mean(x), st.mean(y)
            cov = sum((a - mx) * (c - my) for a, c in zip(x, y)); vx = sum((a - mx) ** 2 for a in x); vy = sum((c - my) ** 2 for c in y)
            sens = {"corr": round(cov / math.sqrt(vx * vy), 2) if vx and vy else None, "months": len(pairs), "from": ks[0], "to": ks[-1]}
    def chg(sid, k=12):
        s = fred.get(sid) or []
        return (s[-1][1], s[-1][0], round(s[-1][1] - s[-1 - k][1], 2)) if len(s) > k else (None, None, None)
    dev = []
    for sid, title, india_plus, india_minus, inval in (
        ("DFII10", "US real interest rates", "Domestic-demand sectors with low foreign ownership", "Sectors with high FPI ownership (financials, IT) see more foreign selling when real yields rise",
         "Correlation between real-yield changes and FPI flows weakens or turns positive over a full year."),
        ("DTWEXBGS", "US dollar strength", "Exporters earning in dollars (IT services, pharma exports)", "Importers of commodities and foreign-currency borrowers",
         "Dollar weakens for several months without a change in FPI flow direction."),
        ("DCOILBRENTEU", "Crude oil price", "Upstream oil producers", "Oil marketing, aviation, paints, chemicals using crude derivatives",
         "Oil moves but margins and credit in these sectors do not."),
        ("DFF", "US policy rate", "Rate-sensitive domestic sectors if Indian rates follow down", "Emerging-market portfolio flows when the Fed tightens",
         "FPI flows to India rise while the Fed tightens.")):
        v, d, c = chg(sid)
        dev.append({"id": sid, "title": title,
                    "what": {"label": "VERIFIED FACT", "text": f"{v:.2f} on {d}; change over 12 months: {c:+.2f} (FRED {sid})." if v is not None else "insufficient data (FRED not reachable on the last run)"},
                    "why": {"label": "UNVERIFIED INFORMATION", "text": "Causes are not determined by this system. See central-bank and EIA statements; no story is generated."},
                    "consequences": {"label": "SCENARIO", "text": f"Historically associated channels: {india_minus.lower()}."},
                    "benefit": {"label": "AI INTERPRETATION", "text": india_plus + " (rule-based mapping, not a forecast)."},
                    "lose": {"label": "AI INTERPRETATION", "text": india_minus + " (rule-based mapping, not a forecast)."},
                    "companies": {"label": "—", "text": "Not assessed. This platform does not name individual companies as beneficiaries (SEBI)."},
                    "evidence": {"label": "ESTIMATED VALUE", "text": (f"Correlation of monthly FPI net equity flow with the monthly change in US 10-year real yield, {sens['from']} to {sens['to']}: {sens['corr']} over {sens['months']} months (computed here from NSDL and FRED)." if sid == "DFII10" and sens else "See sector FPI flows and bank credit on the Sector map.")},
                    "invalidate": {"label": "SCENARIO", "text": inval}, "series": fred.get(sid, [])[-120:]})
    sc_fdi = {c: b.q("SELECT period_end, value FROM observations WHERE metric='wb_BX.KLT.DINV.CD.WD' AND entity_id=? ORDER BY 1", c) for c in ("IND", "CHN", "VNM", "IDN", "MEX")}
    dev.append({"id": "supply_chain", "title": "Supply-chain relocation",
                "what": {"label": "VERIFIED FACT", "text": "FDI net inflows (World Bank) for India, China, Vietnam, Indonesia and Mexico are charted below; read the latest year against the 10-year path."},
                "why": {"label": "UNVERIFIED INFORMATION", "text": "Not determined by this system."},
                "consequences": {"label": "SCENARIO", "text": "If FDI into China keeps falling while India, Vietnam and Mexico hold up, manufacturing capacity may be moving."},
                "benefit": {"label": "AI INTERPRETATION", "text": "Electronics assembly, capital goods, chemicals (rule-based mapping)."},
                "lose": {"label": "AI INTERPRETATION", "text": "Not determined."},
                "companies": {"label": "—", "text": "Not assessed (no company names)."},
                "evidence": {"label": "VERIFIED FACT", "text": "DPIIT sector FDI would show where it lands, but dpiit.gov.in blocks automated access; World Bank totals only."},
                "invalidate": {"label": "SCENARIO", "text": "India's FDI inflows falling alongside China's."}, "fdi": sc_fdi})
    dev.append({"id": "trade_geopolitics", "title": "Tariffs, trade policy and geopolitics",
                "what": {"label": "—", "text": "insufficient data: no structured free tariff/trade-policy feed connected in v1 (WTO, UNCTAD planned)."},
                "why": {"label": "—", "text": "—"}, "consequences": {"label": "—", "text": "—"}, "benefit": {"label": "—", "text": "—"}, "lose": {"label": "—", "text": "—"},
                "companies": {"label": "—", "text": "Not assessed."}, "evidence": {"label": "—", "text": "—"}, "invalidate": {"label": "—", "text": "—"}})
    jdump("global.json", {"developments": dev, "fred": fred, "sensitivity": sens,
                          "demography": {c: b.q("SELECT period_end, value FROM observations WHERE metric='wb_SP.POP.65UP.TO.ZS' AND entity_id=? ORDER BY 1", c) for c in ("IND", "CHN", "VNM", "IDN", "MEX")}})

    # -------------------------------------------------- conclusions + search
    jdump("conclusions.json", b.q("SELECT * FROM ai_conclusions WHERE created_at LIKE ? ORDER BY agent", TODAY.isoformat() + "%"))
    srch = [["industry", s, nm(s)] for s in b.ind] + [["sub", k, v["name"]] for k, v in subs.items() if not k.startswith("nsdl_legacy")]
    srch += [["company", c["company_id"], f"{c['name']} ({c['symbol']})"] for c in cos]
    srch += [["investor", o["id"], o["name"] + (" — " + ", ".join(o["entities"][:3]) if o["entities"] else "")] for o in b.inv]
    srch += [["transaction", e["id"], f"{e['d']} {e['type'].replace('_', ' ')}: {(e['cn'] or '')} {(e['x'] or '')[:80]}"] for e in events[:400]]
    srch += [["source", s["source_id"], s["name"]] for s in srcs]
    jdump("search.json", srch)
    # -------------------------------------------------- Excel workbook
    try:
        xlsx(b, sectors, attn, events, comm)
    except Exception as e:  # noqa: BLE001
        print("xlsx failed", e)


def xlsx(b, sectors, attn, events, comm):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "README"
    ws.append(["India Smart Money Intelligence Dashboard, export"]); ws.append(["Generated", now()]); ws.append([DISCLAIMER])
    ws.append(["Commitments and deployments are on separate sheets and are never added together. Blank = undisclosed / insufficient data."])
    w = wb.create_sheet("Sectors")
    w.append(["sector", "FPI net 3m (Rs cr)", "FPI net 12m (Rs cr)", "FPI holdings (Rs cr)", "bank credit YoY %", "median inst. stake change QoQ (pp)", "capital flow score 1-3y", "capital flow score 3-10y", "P/E percentile 10y"])
    for s in sectors:
        f = s["fpi"] or {}; m = s["metrics"]; sc = s["scores"] or {}
        w.append([s["name"], f.get("net_3m"), f.get("net_12m"), f.get("auc"), m.get("bank_credit_yoy"), m.get("inst_share_change_qoq"),
                  ((sc.get("capital_flow") or {}).get("1-3y") or {}).get("score"), ((sc.get("capital_flow") or {}).get("3-10y") or {}).get("score"), m.get("pe_percentile_10y")])
    w = wb.create_sheet("Institutional attention")
    w.append(["symbol", "company", "sector", "inst. stake change pp", "domestic pp", "foreign pp", "new independent holders", "flags"])
    for a in attn:
        w.append([a["symbol"], a["name"], b.ind.get(a["industry"]), a["inst_qoq"], a["dom_qoq"], a["for_qoq"], ", ".join(a["new_groups"]), "; ".join(a["flags"])])
    w = wb.create_sheet("Deployments (verified)")
    w.append(["id", "scope", "period", "amount Rs cr", "linked commitment", "label"])
    for r in b.q("SELECT deployment_id, scope, period, amount_inr_cr, commitment_id, evidence_label FROM deployments ORDER BY period DESC"):
        w.append(list(r.values()))
    w = wb.create_sheet("Commitments (announced)")
    w.append(["id", "scope", "period", "amount Rs cr", "label", "source"])
    for r in comm:
        w.append([r["id"], r["scope"], r["period"], r["a"], r["l"], r["u"]])
    w = wb.create_sheet("Transactions")
    w.append(["id", "type", "date", "symbol", "investor", "side", "amount Rs cr", "label", "source"])
    for r in b.q("""SELECT t.txn_id, t.txn_type, coalesce(t.txn_date,t.announcement_date), co.symbol, i.name, t.side, t.amount_inr_cr, t.evidence_label, sd.url, i.group_id FROM transactions t
                    LEFT JOIN companies co ON co.company_id=t.company_id LEFT JOIN investors i ON i.investor_id=t.investor_id LEFT JOIN source_documents sd ON sd.doc_id=t.doc_id ORDER BY 3 DESC LIMIT 20000"""):
        v = list(r.values()); g = v.pop()
        if g and (b.groups.get(g) or {}).get("category") == "individual_or_unknown":
            v[4] = "Individual investor"
        w.append(v)
    w = wb.create_sheet("Sources")
    w.append(["id", "name", "category", "url", "status", "reliability", "last success", "latest data period", "limitations"])
    for s in b.q("SELECT source_id, name, category, url, status, reliability, last_success, latest_data_period, limitations FROM sources"):
        w.append(list(s.values()))
    wb.save(EXP / "smartmoney.xlsx")


def main():
    b = B()
    b.fixups(); b.reresolve(); b.fpi(); b.ownership(); b.deals(); b.sector_metrics(); b.score_sectors(); b.score_companies(); b.investors(); b.convergence(); b.agents()
    b.con.commit()
    export(b)
    print("built", now(), "quarters", b.quarters[-3:], "conclusions", len(b.conclusions), "convergence", len(b.conv))


if __name__ == "__main__":
    main()
