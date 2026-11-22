"""Signal detector: turns existing, source-linked data into signals with fixed, documented rules.
Inputs are the v1 build outputs (sectors.json, companies.json, mf.json, meta.json; each value traces to DB rows) and DB rows for
rating actions and document references. A signal is a measured change; it is not a view on any security.
observed_at = the data period the change belongs to; detected_at = the first build that saw it (kept on later re-detection)."""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import hid, now, today  # noqa: E402

# Fixed thresholds. Changing one is a methodology change and must be noted in docs/SMART_MONEY_INTELLIGENCE_2.0.md.
RULES = {
    "fpi_sector_3m": {"type": "capital_flow", "source": "nsdl_fpi_sector", "threshold": 1.5, "fresh_days": 45, "confidence": 0.9,
                      "text": "FPI net equity flow over the last 3 months (6 NSDL fortnights) is at least 1.5% of the sector's FPI equity holdings, in either direction."},
    "mf_sector_breadth": {"type": "capital_flow", "source": "amc_portfolios", "threshold": 40, "fresh_days": 75, "confidence": 0.6,
                          "text": "Fund-house net breadth (adds+new minus trims+exits, as % of all moves, active schemes, latest month vs previous) is at least +40% or at most -40%, with 10 or more moves."},
    "mf_stock_breadth": {"type": "capital_flow", "source": "amc_portfolios", "threshold": 3, "fresh_days": 75, "confidence": 0.6,
                         "text": "Three or more fund houses moved the same way in one stock in the latest month (net count of fund houses adding/new minus trimming/exiting)."},
    "rating_balance_90d": {"type": "credit_quality", "source": None, "threshold": 0.6, "min_actions": 6, "fresh_days": 120,
                           "text": "Over the 90 days to the agency's latest action, (upgrades - downgrades) / (upgrades + downgrades) is at least +0.6 or at most -0.6, with 6 or more of them. Defaults are listed but kept out of the balance (many are small-borrower 'D' moves). Each agency separately; 'Issuer Not Cooperating' moves excluded."},
    "bank_credit_yoy": {"type": "credit", "source": "rbi_sibc", "hi": 25.0, "lo": 0.0, "fresh_days": 150, "confidence": 0.9,
                        "text": "Outstanding bank credit to the sector (RBI SIBC, mapped codes, outstanding-weighted) grew 25% or more year on year, or did not grow (0% or less)."},
    "inst_breadth_qoq": {"type": "capital_flow", "source": "nse_shp", "hi": 65.0, "lo": 35.0, "min_companies": 10, "fresh_days": 200, "confidence": 0.8,
                         "text": "Share of the sector's companies whose institutional holding rose quarter on quarter is 65% or more, or 35% or less (10 or more companies)."},
    "inst_share_company": {"type": "capital_flow", "source": "nse_shp", "threshold": 3.0, "fresh_days": 200, "confidence": 0.85,
                           "text": "Institutional holding of a Nifty 500 company changed by 3 percentage points or more quarter on quarter (NSE shareholding pattern)."},
    # ---- Sprint 2: fundamentals, production, trade, capacity, global
    "fin_company_quarter": {"type": "company_execution", "source": "nse_financials", "rev_hi": 20.0, "rev_lo": -10.0, "margin_lo": -5.0, "fresh_days": 150, "confidence": 0.85,
                            "text": "Nifty 500 company, latest reported quarter vs the same quarter a year earlier (same basis): revenue +20% or more with EBITDA margin not lower (lenders/insurers: profit after tax +20% or more), or revenue -10% or less, or EBITDA margin down 5 pp or more. Not emitted when revenue rose 25%+ while margin fell 5 pp+ at the same time (usually a presentation change such as duties included in revenue)."},
    "fin_sector_revenue": {"type": "industry_economics", "source": "nse_financials", "hi": 15.0, "lo": 0.0, "min_companies": 5, "fresh_days": 150, "confidence": 0.8,
                           "text": "Sum of the sector's Nifty 500 company revenues in the latest quarter vs the same quarter a year earlier (companies with both quarters, 5 or more) grew 15% or more, or did not grow."},
    "fin_sector_margin": {"type": "industry_economics", "source": "nse_financials", "threshold": 1.5, "min_companies": 5, "fresh_days": 150, "confidence": 0.75,
                          "text": "Aggregate EBITDA margin of the sector's non-financial Nifty 500 companies changed by 1.5 percentage points or more vs the same quarter a year earlier (5 or more companies)."},
    "iip_sector_3m": {"type": "structural_demand", "source": "mospi_iip", "hi": 8.0, "lo": -2.0, "fresh_days": 120, "confidence": 0.8,
                      "text": "Average year-on-year growth over the latest 3 months of the IIP industries mapped to the sector (MoSPI, base 2022-23) is 8% or more, or -2% or less."},
    "trade_export_fy": {"type": "structural_demand", "source": "tradestat_eidb", "hi": 15.0, "lo": -10.0, "fresh_days": 450, "confidence": 0.8,
                        "text": "India's merchandise exports in the HS chapters mapped to the sector grew 15% or more, or fell 10% or more, in the latest financial year (TradeStat, US$)."},
    "trade_import_share": {"type": "competitive_position", "source": "tradestat_eidb", "threshold": 3.0, "min_trade_usd_mn": 1000, "fresh_days": 450, "confidence": 0.7,
                           "text": "Imports as a share of two-way trade (imports / (imports + exports)) in the sector's mapped HS chapters moved by 3 percentage points or more in the latest financial year (US$ 1 bn+ of trade). Higher = more reliance on imports in that trade."},
    "capacity_utilisation": {"type": "structural_demand", "source": "rbi_obicus", "hi": 75.0, "lo": 70.0, "fresh_days": 200, "confidence": 0.8,
                             "text": "RBI OBICUS seasonally adjusted manufacturing capacity utilisation for the latest quarter is 75% or more, or 70% or less."},
    "commodity_3m": {"type": "global", "source": "fred", "threshold": 15.0, "fresh_days": 100, "confidence": 0.8,
                     "text": "A tracked commodity price (IMF primary commodity series via FRED; Brent from EIA via FRED) moved 15% or more over 3 months (latest monthly value vs 3 months earlier). IMF series are published with about a 6-8 week lag; the period is the month the average covers."},
}
# commodity series -> sectors with the direction of first-order exposure (fixed, rule-based; producer = price up helps realisations)
COMMODITY_SECTORS = {
    "DCOILBRENTEU": ("Brent crude", [("oil_gas_consumable_fuels", "producer/refiner realisations and marketing margins"), ("chemicals", "feedstock cost"), ("automobile_and_auto_components", "fuel cost for users"), ("capital_goods", "upstream capex cycle")]),
    "PCOPPUSDM": ("Copper", [("metals_mining", "producer realisations"), ("capital_goods", "input cost (cables, motors, transformers)"), ("consumer_durables", "input cost")]),
    "PALUMUSDM": ("Aluminium", [("metals_mining", "producer realisations"), ("automobile_and_auto_components", "input cost"), ("capital_goods", "input cost")]),
    "PIORECRUSDM": ("Iron ore", [("metals_mining", "miner realisations; steelmaker input cost")]),
    "PCOALAUUSDM": ("Coal (Australia)", [("power", "imported-coal fuel cost"), ("construction_materials", "kiln fuel cost"), ("metals_mining", "coking/thermal coal cost and coal miner realisations")]),
    "PNGASJPUSDM": ("LNG (Asia)", [("oil_gas_consumable_fuels", "gas importer/distributor costs"), ("chemicals", "fertiliser and petrochemical feedstock cost"), ("power", "gas-based generation cost")]),
    "PZINCUSDM": ("Zinc", [("metals_mining", "producer realisations")]),
    "PNICKUSDM": ("Nickel", [("metals_mining", "stainless steel input cost / producer realisations")]),
    "PCOTTINDUSDM": ("Cotton", [("textiles", "raw material cost")]),
    "PPOILUSDM": ("Palm oil", [("fast_moving_consumer_goods", "edible oil and personal care input cost")]),
    "PRUBBUSDM": ("Natural rubber", [("automobile_and_auto_components", "tyre input cost")]),
    "PSUGAISAUSDM": ("Sugar", [("fast_moving_consumer_goods", "sugar producer realisations; food input cost")]),
    "PWHEAMTUSDM": ("Wheat", [("fast_moving_consumer_goods", "food input cost")]),
}
MECHANISM = {
    "fpi_sector_3m": "Foreign portfolio investors' disclosed net equity buying or selling in the sector",
    "mf_sector_breadth": "Breadth of domestic fund-house position changes in the sector's stocks",
    "mf_stock_breadth": "Several fund houses changed positions in the same company in the same month",
    "rating_balance_90d": "Balance of credit-rating upgrades and downgrades among the sector's rated borrowers",
    "bank_credit_yoy": "Pace of bank lending to the sector (outstanding credit, not new sanctions)",
    "inst_breadth_qoq": "Breadth of institutional holding increases across the sector's listed companies",
    "inst_share_company": "Change in the institutional share of the company's equity",
    "fin_company_quarter": "Reported revenue and operating margin of the company (exchange XBRL filing)",
    "fin_sector_revenue": "Aggregate reported revenue of the sector's listed companies",
    "fin_sector_margin": "Aggregate reported operating (EBITDA) margin of the sector's listed companies",
    "iip_sector_3m": "Industrial production volumes in the industries mapped to the sector (MoSPI IIP)",
    "trade_export_fy": "India's merchandise exports in the sector's mapped HS chapters",
    "trade_import_share": "Reliance on imports in the sector's mapped merchandise trade",
    "capacity_utilisation": "How fully manufacturers' installed capacity is being used (RBI survey)",
    "commodity_3m": "Global commodity price move that changes input costs or realisations for exposed sectors",
}
AGENCY = {"crisil_ratings": "CRISIL", "icra_ratings": "ICRA", "care_ratings": "CARE", "indra_ratings": "India Ratings"}


def _j(exp: Path, name):
    p = exp / name
    return json.loads(p.read_text()) if p.exists() else None


def _days(d1: str, d2: date) -> int:
    try:
        return (d2 - date.fromisoformat(d1[:10])).days
    except Exception:  # noqa: BLE001
        return 10 ** 6


class Detector:
    def __init__(self, con, exp: Path, as_of: date | None = None):
        self.con, self.exp = con, exp
        self.as_of = as_of or today()
        self.meta = _j(exp, "meta.json") or {}
        self.ind_names = self.meta.get("industries", {})
        self.out = []

    # ------------------------------------------------------------------ helpers
    def q(self, sql, *a):
        return self.con.execute(sql, a).fetchall()

    def src_status(self, sid):
        r = self.q("SELECT status FROM sources WHERE source_id=?", sid)
        return r[0][0] if r else None

    def doc_ok(self, doc_id):
        r = self.q("SELECT url FROM source_documents WHERE doc_id=?", doc_id) if doc_id else []
        return bool(r and r[0][0])

    def emit(self, rule, entity_type, entity_id, observed_at, title, description, magnitude, unit, direction, source_id, doc_id, refs, confidence=None, sources_for_status=None):
        R = RULES[rule]
        notes, status = [], "validated"
        if not self.doc_ok(doc_id):
            status = "candidate"; notes.append("no source document with a URL")
        for s in (sources_for_status or [source_id]):
            st = self.src_status(s)
            if st != "working":
                status = "candidate"; notes.append(f"source {s} status is {st}")
        age = _days(observed_at, self.as_of)
        if age > R["fresh_days"]:
            status = "rejected"; notes.append(f"stale: observed {observed_at}, more than {R['fresh_days']} days before {self.as_of}")
        if status == "validated":
            notes.append(f"rule {rule}; source document present; source working; observed {age} days before detection")
        self.out.append(dict(
            signal_id="sig_" + hid(rule, entity_type, entity_id, observed_at, direction), signal_type=R["type"], title=title, description=description,
            entity_type=entity_type, entity_id=entity_id, observed_at=observed_at, valid_from=observed_at, valid_to=None,
            magnitude=None if magnitude is None else round(float(magnitude), 2), unit=unit, direction=direction, evidence_label="VERIFIED FACT",
            confidence=confidence if confidence is not None else R.get("confidence"), source_id=source_id, doc_id=doc_id, status=status,
            rule_id=rule, refs_json=json.dumps(refs[:40]), validation_note="; ".join(notes)))

    def iname(self, i):
        return self.ind_names.get(i, (i or "unclassified").replace("_", " "))

    # ------------------------------------------------------------------ rules
    def fpi(self, sectors):
        R = RULES["fpi_sector_3m"]
        for s in sectors:
            v = s["metrics"].get("fpi_flow_3m"); f = s.get("fpi") or {}
            if v is None or abs(v) < R["threshold"] or not f.get("auc_date"):
                continue
            obs = self.q("SELECT obs_id, doc_id FROM observations WHERE metric='fpi_net_equity_inr_cr' AND entity_type='industry' AND entity_id=? ORDER BY period_end DESC LIMIT 6", s["id"])
            if not obs:
                continue
            d = "positive" if v > 0 else "negative"
            self.emit("fpi_sector_3m", "industry", s["id"], f["auc_date"],
                      f"FPI 3-month net {'inflow' if v > 0 else 'outflow'}: {s['name']} ({v:+.2f}% of FPI holdings)",
                      f"Net FPI equity flow over 6 fortnights to {f['auc_date']}: Rs {f.get('net_3m'):,.0f} cr against FPI equity holdings of Rs {f.get('auc'):,.0f} cr. 12-month net: Rs {f.get('net_12m'):,.0f} cr.",
                      v, "% of FPI equity holdings", d, "nsdl_fpi_sector", obs[0][1], [o[0] for o in obs])

    def mf(self, mfj):
        if not mfj or not mfj.get("month"):
            return
        month = mfj["month"]
        docs = []
        srcs = []
        for g in mfj.get("status", []):
            r = self.q("SELECT doc_id FROM source_documents WHERE url=? ORDER BY data_period DESC LIMIT 1", g.get("url"))
            if r:
                docs.append(r[0][0])
            srcs.append(g.get("source_id"))
        n_groups = len(mfj.get("groups_compared") or [])
        R = RULES["mf_sector_breadth"]
        for s in mfj.get("sectors", []):
            b = s.get("net_breadth_pct")
            if b is None or abs(b) < R["threshold"] or s["industry"] == "unclassified":
                continue
            self.emit("mf_sector_breadth", "industry", s["industry"], month,
                      f"Fund-house net breadth {b:+.0f}%: {s['name']} ({month[:7]})",
                      f"Across {n_groups} fund houses' active schemes, {s['buy_moves']} add/new moves vs {s['sell_moves']} trim/exit moves in this sector's stocks between the two latest month-end files ({s['new_entries']} new, {s['exits']} exits).",
                      b, "% net breadth", "positive" if b > 0 else "negative", "amc_portfolios", docs[0] if docs else None, docs, sources_for_status=srcs)
        R = RULES["mf_stock_breadth"]
        seen = set()
        for k in ("most_added", "most_new", "most_reduced", "most_exited"):
            for x in mfj.get(k, []):
                ng = x.get("net_groups") or 0
                if abs(ng) < R["threshold"] or x["id"] in seen:
                    continue
                seen.add(x["id"])
                pos = ng > 0
                who = (x["new"] + x["add"]) if pos else (x["trim"] + x["exit"])
                self.emit("mf_stock_breadth", "company", x["id"], month,
                          f"{abs(ng)} fund houses {'added or newly held' if pos else 'trimmed or exited'}: {x['name']} ({month[:7]})",
                          f"Fund houses ({', '.join(who)}) changed shares held by 10% or more in the same direction between the two latest month-end files; estimated net value Rs {x.get('est_net_cr') or 0:,.0f} cr (ESTIMATED VALUE: share change x month-end price).",
                          ng, "fund houses (net)", "positive" if pos else "negative", "amc_portfolios", docs[0] if docs else None, docs, sources_for_status=srcs)

    def ratings(self):
        R = RULES["rating_balance_90d"]
        for sid, agency in AGENCY.items():
            last = self.q("SELECT max(period) FROM debt WHERE source_id=? AND measure='rating_action'", sid)[0][0]
            if not last:
                continue
            start = (date.fromisoformat(last) - timedelta(days=90)).isoformat()
            rows = self.q("""SELECT industry_id, json_extract(detail,'$.action'), doc_id, debt_id, period FROM debt
                             WHERE source_id=? AND measure='rating_action' AND period>? AND industry_id IS NOT NULL ORDER BY period DESC""", sid, start)
            by = defaultdict(lambda: {"up": 0, "down": 0, "default": 0, "docs": [], "last": None})
            for ind, act, d, did, per in rows:
                if act not in ("upgrade", "downgrade", "default"):
                    continue
                x = by[ind]
                if act == "upgrade":
                    x["up"] += 1
                elif act == "downgrade":
                    x["down"] += 1
                else:
                    x["default"] += 1
                x["docs"].append(d); x["last"] = x["last"] or per
            for ind, x in by.items():
                n = x["up"] + x["down"]
                if n < R["min_actions"]:
                    continue
                bal = (x["up"] - x["down"]) / n
                if abs(bal) < R["threshold"]:
                    continue
                self.emit("rating_balance_90d", "industry", ind, x["last"],
                          f"{agency}: {x['up']} upgrades vs {x['down']} downgrades in {self.iname(ind)} (90 days)",
                          f"{agency} rating actions on borrowers classified to this sector, {start} to {last}. Balance (up - down) / (up + down) = {bal:+.2f}; defaults ({x['default']}) are reported but not in the balance. Agencies are never added together.",
                          bal * 100, "% net rating balance", "positive" if bal > 0 else "negative", sid, x["docs"][0], x["docs"],
                          confidence=round(min(0.9, 0.4 + n / 50), 2))

    def credit(self, sectors):
        R = RULES["bank_credit_yoy"]
        last = self.meta.get("sibc_last")
        if not last:
            return
        for s in sectors:
            v = s["metrics"].get("bank_credit_yoy")
            if v is None or (R["lo"] < v < R["hi"]):
                continue
            codes = ["sibc_" + c["code"] for c in (s.get("credit") or [])]
            obs = self.q(f"SELECT obs_id, doc_id FROM observations WHERE metric='bank_credit_yoy_pct' AND period_end=? AND entity_id IN ({','.join('?' * len(codes))})", last, *codes) if codes else []
            if not obs:
                continue
            self.emit("bank_credit_yoy", "industry", s["id"], last,
                      f"Bank credit {'+' if v > 0 else ''}{v:.1f}% YoY: {s['name']}",
                      f"Outstanding bank credit to mapped RBI SIBC codes ({', '.join(c['code'] for c in s['credit'])}) as of {last}: Rs {s.get('credit_outstanding') or 0:,.0f} cr, {v:+.1f}% year on year. Outstanding stock, not new sanctions.",
                      v, "% YoY", "positive" if v >= R["hi"] else "negative", "rbi_sibc", obs[0][1], [o[0] for o in obs])

    def shareholding(self, sectors, companies):
        q_cur = self.meta.get("q_cur")
        if not q_cur:
            return
        R = RULES["inst_breadth_qoq"]
        for s in sectors:
            v = s["metrics"].get("inst_breadth_qoq")
            if v is None or (s.get("companies") or 0) < R["min_companies"] or (R["lo"] < v < R["hi"]):
                continue
            docs = [r[0] for r in self.q("""SELECT DISTINCT o.doc_id FROM ownership o JOIN companies c ON c.company_id=o.company_id
                                            WHERE c.industry_id=? AND o.period_end=? AND o.holder_category='mf' AND o.doc_id IS NOT NULL LIMIT 40""", s["id"], q_cur)]
            if not docs:
                continue
            self.emit("inst_breadth_qoq", "industry", s["id"], q_cur,
                      f"Institutional holding rose at {v:.0f}% of {s['name']} companies (quarter to {q_cur})",
                      f"Of {s['companies']} tracked companies in the sector, {v:.0f}% show a higher institutional holding than the previous quarter (median change {s['metrics'].get('inst_share_change_qoq')} pp). NSE shareholding patterns.",
                      v, "% of companies", "positive" if v >= R["hi"] else "negative", "nse_shp", docs[0], docs)
        R = RULES["inst_share_company"]
        cols = companies["cols"]
        for row in companies["rows"]:
            c = dict(zip(cols, row))
            v = c.get("inst_qoq_pp")
            if not c.get("nifty500") or v is None or abs(v) < R["threshold"]:
                continue
            d = self.q("SELECT doc_id FROM ownership WHERE company_id=? AND period_end=? AND doc_id IS NOT NULL LIMIT 1", c["id"], q_cur)
            if not d:
                continue
            self.emit("inst_share_company", "company", c["id"], q_cur,
                      f"Institutional holding {v:+.2f} pp: {c['name']} (quarter to {q_cur})",
                      f"Institutional holding {c.get('inst_pct')}% at {q_cur}, {v:+.2f} percentage points vs the previous quarter (NSE shareholding pattern).",
                      v, "pp QoQ", "positive" if v > 0 else "negative", "nse_shp", d[0][0], [d[0][0]])

    def run(self):
        sectors = (_j(self.exp, "sectors.json") or {}).get("sectors", [])
        companies = _j(self.exp, "companies.json") or {"cols": [], "rows": []}
        self.fpi(sectors); self.mf(_j(self.exp, "mf.json")); self.ratings(); self.credit(sectors); self.shareholding(sectors, companies)
        for fn in (self.fundamentals, self.production, self.trade, self.capacity, self.commodities):
            try:
                fn()
            except Exception as e:  # noqa: BLE001  (a missing Sprint 2 table/source must not stop Sprint 1 rules)
                print(f"detector {fn.__name__} skipped: {type(e).__name__}: {e}")
        return self.out

    # ------------------------------------------------------------------ Sprint 2 rules
    def fundamentals(self):
        from intelligence import fundamentals as F
        if not self.q("SELECT name FROM sqlite_master WHERE name='company_financials'"):
            return
        n500 = {r[0] for r in self.q("SELECT company_id FROM companies WHERE index_membership LIKE 'NIFTY 500%'")}
        names = dict(self.q("SELECT company_id, name FROM companies"))
        metrics = {k: v for k, v in F.all_companies(self.con).items() if k in n500}
        self.fund_metrics = metrics
        R = RULES["fin_company_quarter"]
        for cid, m in metrics.items():
            q = m["q"]; g = q.get("revenue_yoy_pct"); dm = q.get("ebitda_margin_change_pp")
            if g is None:
                continue
            doc = self.q("SELECT doc_id FROM company_financials WHERE company_id=? AND period_type='Q' AND period_end=? AND basis=?", cid, m["latest_quarter"], m["basis"])
            doc = doc[0][0] if doc else None
            yd = self.q("SELECT doc_id FROM company_financials WHERE company_id=? AND period_type='Q' AND period_end=? AND basis=?", cid, q["year_ago_period"], m["basis"])
            refs = [doc] + ([yd[0][0]] if yd else [])
            if g >= 25 and dm is not None and dm <= R["margin_lo"]:
                continue  # mixed: likely a presentation change; not emitted
            pos = (g >= R["rev_hi"] and ((dm is not None and dm >= 0) or (m["financial_sector_format"] and (q.get("pat_yoy_pct") or 0) >= 20)))
            neg = g <= R["rev_lo"] or (dm is not None and dm <= R["margin_lo"])
            if not (pos or neg):
                continue
            mtxt = f"; EBITDA margin {q['ebitda_margin_pct']}% ({dm:+.1f} pp)" if dm is not None else (f"; profit after tax {q['pat_yoy_pct']:+.1f}%" if q.get("pat_yoy_pct") is not None else "")
            self.emit("fin_company_quarter", "company", cid, m["latest_quarter"],
                      f"Revenue {g:+.1f}% YoY{', margin ' + format(dm, '+.1f') + ' pp' if dm is not None else ''}: {names.get(cid, cid)} (quarter to {m['latest_quarter']})",
                      f"{m['basis']} results, quarter ended {m['latest_quarter']} vs {q['year_ago_period']}: revenue from operations Rs {q['revenue_cr']:,.0f} cr ({g:+.1f}%){mtxt}. EBITDA = PBT before exceptional items + finance costs + D&A - other income. Source: NSE integrated filing XBRL.",
                      g, "% revenue YoY", "positive" if pos and not neg else "negative", "nse_financials", doc, refs)
        agg = F.sector_aggregates(self.con, metrics)
        self.fund_sectors = agg
        for sec, a in agg.items():
            if not a["quarter"]:
                continue
            docs = [r[0] for r in self.q(f"SELECT doc_id FROM company_financials WHERE period_type='Q' AND period_end=? AND company_id IN ({','.join('?' * len(a['company_ids']))}) LIMIT 40", a["quarter"], *a["company_ids"])]
            if not docs:
                continue
            R = RULES["fin_sector_revenue"]; g = a["revenue_yoy_pct"]
            if a["companies"] >= R["min_companies"] and g is not None and not (R["lo"] < g < R["hi"]):
                self.emit("fin_sector_revenue", "industry", sec, a["quarter"],
                          f"Sector revenue {g:+.1f}% YoY: {self.iname(sec)} ({a['companies']} companies, quarter to {a['quarter']})",
                          f"Sum of reported revenue from operations of {a['companies']} Nifty 500 companies in the sector with both quarters on the same basis, latest quarter vs a year earlier.",
                          g, "% revenue YoY", "positive" if g >= R["hi"] else "negative", "nse_financials", docs[0], docs)
            R = RULES["fin_sector_margin"]; dm = a["ebitda_margin_change_pp"]
            if a["margin_companies"] >= R["min_companies"] and dm is not None and abs(dm) >= R["threshold"]:
                self.emit("fin_sector_margin", "industry", sec, a["quarter"],
                          f"Sector EBITDA margin {dm:+.1f} pp YoY to {a['ebitda_margin_pct']}%: {self.iname(sec)} (quarter to {a['quarter']})",
                          f"Aggregate EBITDA / revenue of {a['margin_companies']} non-financial Nifty 500 companies in the sector, latest quarter vs a year earlier.",
                          dm, "pp YoY", "positive" if dm > 0 else "negative", "nse_financials", docs[0], docs)

    def production(self):
        from ingest_industry import iip_sectors
        R = RULES["iip_sector_3m"]
        last = self.q("SELECT max(period_end) FROM observations WHERE metric='iip_yoy_pct_b2022'")[0][0]
        if not last:
            return
        months = [r[0] for r in self.q("SELECT DISTINCT period_end FROM observations WHERE metric='iip_yoy_pct_b2022' ORDER BY period_end DESC LIMIT 3")]
        by = defaultdict(list)
        for key, in self.q("SELECT DISTINCT entity_id FROM observations WHERE metric='iip_yoy_pct_b2022' AND period_end=?", last):
            vals = self.q(f"SELECT value, obs_id, doc_id FROM observations WHERE metric='iip_yoy_pct_b2022' AND entity_id=? AND period_end IN ({','.join('?' * len(months))})", key, *months)
            if len(vals) < 3 or any(v[0] is None for v in vals):
                continue
            avg = sum(v[0] for v in vals) / 3
            for sec in iip_sectors(key):
                by[sec].append((key, avg, vals))
        labels = {r[0]: r[1].split(":", 1)[1] for r in self.q("SELECT entity_id, metric FROM observations WHERE metric LIKE 'iip_label:%'")}
        for sec, items in by.items():
            avg = sum(i[1] for i in items) / len(items)
            if R["lo"] < avg < R["hi"]:
                continue
            parts = "; ".join(f"{labels.get(k, k).split(' | ')[-1]} {a:+.1f}%" for k, a, _ in items)
            refs = [v[1] for _, _, vals in items for v in vals]
            self.emit("iip_sector_3m", "industry", sec, last,
                      f"Industrial production {avg:+.1f}% YoY (3-month average): {self.iname(sec)} (to {last[:7]})",
                      f"MoSPI IIP (base 2022-23), average of year-on-year growth for {', '.join(m[:7] for m in sorted(months))} across mapped industries: {parts}. Quick estimates are revised later.",
                      avg, "% YoY (3m avg)", "positive" if avg >= R["hi"] else "negative", "mospi_iip", items[0][2][0][2], refs)

    def trade(self):
        from ingest_industry import HS_SECTOR
        last = self.q("SELECT max(period_end) FROM observations WHERE metric='trade_export_usd_mn'")[0][0]
        if not last:
            return
        prev = f"{int(last[:4]) - 1}{last[4:]}"
        tot = defaultdict(lambda: {"x1": 0, "x0": 0, "m1": 0, "m0": 0, "ch": [], "refs": [], "doc": None})
        for metric, k1, k0 in (("trade_export_usd_mn", "x1", "x0"), ("trade_import_usd_mn", "m1", "m0")):
            for hs, pe, v, oid, d in self.q("SELECT entity_id, period_end, value, obs_id, doc_id FROM observations WHERE metric=? AND period_end IN (?,?)", metric, last, prev):
                for sec in HS_SECTOR.get(hs, []):
                    t = tot[sec]; t[k1 if pe == last else k0] += v or 0
                    if hs not in t["ch"]:
                        t["ch"].append(hs)
                    t["refs"].append(oid)
                    if pe == last and t["doc"] is None:
                        t["doc"] = d
        fy = f"FY{int(last[:4]) - 1}-{last[2:4]}"
        for sec, t in tot.items():
            R = RULES["trade_export_fy"]
            if t["x0"] > 0:
                g = 100 * (t["x1"] / t["x0"] - 1)
                if not (R["lo"] < g < R["hi"]):
                    self.emit("trade_export_fy", "industry", sec, last,
                              f"Exports {g:+.1f}% in {fy}: {self.iname(sec)} (HS {', '.join(sorted(t['ch']))})",
                              f"India's merchandise exports in mapped HS chapters: US$ {t['x1']:,.0f} mn in {fy} vs US$ {t['x0']:,.0f} mn a year earlier (Ministry of Commerce TradeStat). Chapter-to-sector mapping is a fixed table; a chapter can feed several sectors.",
                              g, "% YoY (US$)", "positive" if g > 0 else "negative", "tradestat_eidb", t["doc"], t["refs"])
            R = RULES["trade_import_share"]
            if (t["x1"] + t["m1"]) >= R["min_trade_usd_mn"] and (t["x0"] + t["m0"]) > 0:
                s1 = 100 * t["m1"] / (t["x1"] + t["m1"]); s0 = 100 * t["m0"] / (t["x0"] + t["m0"])
                d = s1 - s0
                if abs(d) >= R["threshold"]:
                    self.emit("trade_import_share", "industry", sec, last,
                              f"Import share of trade {d:+.1f} pp to {s1:.0f}% in {fy}: {self.iname(sec)}",
                              f"Imports / (imports + exports) in mapped HS chapters ({', '.join(sorted(t['ch']))}): {s1:.1f}% in {fy} vs {s0:.1f}% a year earlier. Imports US$ {t['m1']:,.0f} mn, exports US$ {t['x1']:,.0f} mn. This is a trade-mix measure, not a share of domestic consumption (production values are not in this data).",
                              d, "pp YoY", "negative" if d > 0 else "positive", "tradestat_eidb", t["doc"], t["refs"])

    def capacity(self):
        R = RULES["capacity_utilisation"]
        r = self.q("SELECT period_end, value, obs_id, doc_id FROM observations WHERE metric='obicus_cu_sa_pct' ORDER BY period_end DESC LIMIT 2")
        if not r or r[0][1] is None:
            return
        pe, v, oid, d = r[0]
        if R["lo"] < v < R["hi"]:
            return
        prev = f" (previous quarter {r[1][1]}%)" if len(r) > 1 and r[1][1] is not None else ""
        self.emit("capacity_utilisation", "market", "india_manufacturing", pe,
                  f"Manufacturing capacity utilisation {v}% (seasonally adjusted, quarter to {pe})",
                  f"RBI Order Books, Inventories and Capacity Utilisation Survey: seasonally adjusted capacity utilisation {v}% for the quarter ended {pe}{prev}. Aggregate for responding manufacturers; no sector split is published.",
                  v, "% capacity utilisation (SA)", "positive" if v >= R["hi"] else "negative", "rbi_obicus", d, [x[2] for x in r])

    def commodities(self):
        R = RULES["commodity_3m"]
        for sid, (name, secs) in COMMODITY_SECTORS.items():
            r = self.q("SELECT period_end, value, obs_id, doc_id FROM observations WHERE metric=? AND value IS NOT NULL ORDER BY period_end DESC LIMIT 4", "fred_" + sid)
            if len(r) < 4:
                continue
            (pe, v1, oid, d), (pe0, v0) = r[0][:4], (r[3][0], r[3][1])
            if sid.startswith("P") and pe.endswith("-01"):  # IMF monthly averages are dated the 1st: the period is that whole month
                y, m = int(pe[:4]), int(pe[5:7])
                pe = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
            if not v0:
                continue
            ch = 100 * (v1 / v0 - 1)
            if abs(ch) < R["threshold"]:
                continue
            self.emit("commodity_3m", "commodity", sid, pe,
                      f"{name} {ch:+.1f}% over 3 months (to {pe[:7]})",
                      f"{name}: {v1:,.2f} at {pe} vs {v0:,.2f} at {pe0} (FRED series {sid}). Exposed sectors (fixed table): " + "; ".join(f"{self.iname(s)}: {why}" for s, why in secs) + ".",
                      ch, "% over 3 months", "positive" if ch > 0 else "negative", "fred", d, [x[2] for x in r])


def store(con, signals, detected_at=None):
    """Insert new signals; on re-detection keep detected_at/created_at and refresh status, note and last_seen_at."""
    ts = detected_at or now()
    new = 0
    for s in signals:
        cur = con.execute("SELECT 1 FROM signals WHERE signal_id=?", (s["signal_id"],)).fetchone()
        if cur:
            con.execute("UPDATE signals SET status=?, validation_note=?, last_seen_at=?, refs_json=?, confidence=? WHERE signal_id=?",
                        (s["status"], s["validation_note"], ts, s["refs_json"], s["confidence"], s["signal_id"]))
        else:
            row = dict(s, detected_at=ts, created_at=ts, last_seen_at=ts)
            cols = list(row)
            con.execute(f"INSERT INTO signals ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
            new += 1
    return new


def relationships(con, signals, ts=None):
    """Signal -> entity it was observed in; company -> its industry (from the companies table)."""
    ts = ts or now()
    n = 0
    for s in signals:
        rows = [("signal", s["signal_id"], "observed_in", s["entity_type"], s["entity_id"], MECHANISM[s["rule_id"]], s["direction"], s["confidence"], s["doc_id"], s["observed_at"])]
        if s["entity_type"] == "commodity" and s["entity_id"] in COMMODITY_SECTORS:
            for sec, why in COMMODITY_SECTORS[s["entity_id"]][1]:
                rows.append(("commodity", s["entity_id"], "exposes", "industry", sec, why, None, 0.6, None, None))
        if s["entity_type"] == "company":
            r = con.execute("SELECT industry_id FROM companies WHERE company_id=?", (s["entity_id"],)).fetchone()
            if r and r[0]:
                rows.append(("company", s["entity_id"], "belongs_to", "industry", r[0], "NSE/AMFI industry classification of the company", None, 1.0, None, None))
        for ft, fi, rel, tt, ti, mech, d, c, doc, vf in rows:
            rid = "rel_" + hid(ft, fi, rel, tt, ti)
            con.execute("""INSERT INTO entity_relationships (relationship_id, from_type, from_id, relation_type, to_type, to_id, mechanism, direction, confidence, source_doc_id, valid_from, valid_to, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(relationship_id) DO NOTHING""", (rid, ft, fi, rel, tt, ti, mech, d, c, doc, vf, None, ts))
            n += 1
    return n
