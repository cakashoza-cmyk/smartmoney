"""Month-on-month changes in mutual fund holdings, from the AMC monthly portfolio files (ingest_amc.py).
Unit of analysis = AMC parent group x company x month, ACTIVE schemes only (index funds/ETFs = passive and arbitrage funds are
left out). Quantities come from two official month-end files (VERIFIED FACT); a rupee value is quantity change x month-end price
implied by the same file (ESTIMATED VALUE). Splits/bonuses are detected from the files themselves (share count up and price down
together across schemes) and the earlier quantity is adjusted. No scoring words, no recommendations."""
import statistics as st
from collections import defaultdict
from datetime import date
from common import hid, upsert

BAND = 0.10  # change in shares held below +/-10% = 'held' (fund inflows/outflows move every holding a little)
BUY_T, SELL_T = ("new", "add"), ("trim", "exit")


def _months_apart(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def _ca_factor(con, prev, cur, cache):
    """company_id -> share-count factor between two month-ends (split/bonus/consolidation), from all MF scheme rows held in both months."""
    if (prev, cur) in cache:
        return cache[(prev, cur)]
    rows = con.execute("""SELECT a.company_id c, a.quantity q0, a.value_inr_cr v0, b.quantity q1, b.value_inr_cr v1
                          FROM ownership a JOIN ownership b ON b.investor_id=a.investor_id AND b.company_id=a.company_id
                          WHERE a.holder_category='mf_portfolio' AND b.holder_category='mf_portfolio' AND a.period_end=? AND b.period_end=?
                            AND a.quantity>0 AND b.quantity>0 AND a.value_inr_cr>0 AND b.value_inr_cr>0""", (prev, cur)).fetchall()
    by = defaultdict(lambda: ([], []))
    for r in rows:
        qr = r["q1"] / r["q0"]; pr = (r["v1"] / r["q1"]) / (r["v0"] / r["q0"])
        by[r["c"]][0].append(qr); by[r["c"]][1].append(pr)
    f = {}
    for c, (qs, ps) in by.items():
        if len(qs) < 2:
            continue
        mq, mp = st.median(qs), st.median(ps)
        if mq >= 1.8 and mp < 0.6:
            f[c] = round(mq) if abs(mq - round(mq)) < 0.15 else round(mq, 2)
        elif mq <= 0.55 and mp > 1.8:
            f[c] = 1 / round(1 / mq) if abs(1 / mq - round(1 / mq)) < 0.15 else round(mq, 4)
    cache[(prev, cur)] = f
    return f


def sector_of(con):
    """company -> industry: the company's own NSE industry; otherwise the industry most Nifty 500 companies with the same AMC industry label carry."""
    ind = {r[0]: r[1] for r in con.execute("SELECT company_id, industry_id FROM companies WHERE industry_id IS NOT NULL")}
    lab = {r[0]: r[1] for r in con.execute("SELECT company_id, label FROM company_labels WHERE source_id='amc_industry'")}
    votes = defaultdict(lambda: defaultdict(int))
    for c, l in lab.items():
        if c in ind:
            votes[l.lower()][ind[c]] += 1
    lab_map = {l: max(v.items(), key=lambda kv: kv[1])[0] for l, v in votes.items() if sum(v.values()) >= 2}
    out, inferred = dict(ind), set()
    for c, l in lab.items():
        if c not in out and l.lower() in lab_map:
            out[c] = lab_map[l.lower()]; inferred.add(c)
    return out, inferred


def compute(con, write=True):
    groups = {r["group_id"]: r["name"] for r in con.execute("SELECT group_id, name FROM investor_groups")}
    per = defaultdict(set)
    for r in con.execute("SELECT DISTINCT i.group_id g, o.period_end p FROM ownership o JOIN investors i ON i.investor_id=o.investor_id WHERE o.holder_category='mf_portfolio'"):
        per[r["g"]].add(r["p"])
    sec, inferred = sector_of(con)
    names = {r[0]: (r[1], r[2]) for r in con.execute("SELECT company_id, symbol, name FROM companies")}
    cache, moves, status = {}, [], []
    for g, ps in sorted(per.items()):
        ps = sorted(ps); cur = ps[-1]
        prev = ps[-2] if len(ps) >= 2 else None
        src = con.execute("""SELECT sd.source_id, sd.doc_id, sd.url FROM ownership o JOIN investors i ON i.investor_id=o.investor_id JOIN source_documents sd ON sd.doc_id=o.doc_id
                             WHERE i.group_id=? AND o.period_end=? AND o.holder_category='mf_portfolio' LIMIT 1""", (g, cur)).fetchone()
        stt = {"group": g, "name": groups.get(g, g), "months": ps, "latest": cur, "compared_with": prev, "source_id": src["source_id"] if src else None, "url": src["url"] if src else None}
        if not prev or _months_apart(prev, cur) != 1:
            stt["note"] = "only one month-end file parsed" if not prev else f"months not consecutive ({prev} to {cur}); no changes computed"
            status.append(stt); continue
        fac = _ca_factor(con, prev, cur, cache)
        q = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # company -> [q0, q1, v0, v1]
        for r in con.execute("""SELECT o.company_id c, o.period_end p, sum(o.quantity) q, sum(o.value_inr_cr) v FROM ownership o JOIN investors i ON i.investor_id=o.investor_id
                                WHERE o.holder_category='mf_portfolio' AND o.scheme_flag='active' AND i.group_id=? AND o.period_end IN (?,?) GROUP BY 1,2""", (g, prev, cur)):
            k = 0 if r["p"] == prev else 1
            q[r["c"]][k] += r["q"] or 0; q[r["c"]][2 + k] += r["v"] or 0
        cnt = defaultdict(int)
        for c, (q0, q1, v0, v1) in q.items():
            f = fac.get(c, 1)
            q0a = q0 * f
            if q0a <= 0 and q1 <= 0:
                continue
            if q0a <= 0:
                kind = "new"
            elif q1 <= 0:
                kind = "exit"
            elif q1 >= q0a * (1 + BAND):
                kind = "add"
            elif q1 <= q0a * (1 - BAND):
                kind = "trim"
            else:
                kind = "held"
            cnt[kind] += 1
            price = (v1 * 1e7 / q1) if q1 > 0 else (v0 * 1e7 / q0a if q0a > 0 else None)
            dq = q1 - q0a
            est = round(dq * price / 1e7, 4) if price else None
            moves.append(dict(group=g, company=c, kind=kind, q0=q0a, q1=q1, dq=dq, est_cr=est, value_cr=round(v1, 4), prev=prev, cur=cur, factor=f if f != 1 else None,
                              industry=sec.get(c), sector_inferred=c in inferred, source_id=stt["source_id"], doc_id=src["doc_id"] if src else None))
        stt["counts"] = dict(cnt); stt["corporate_action_adjusted"] = sum(1 for c in q if c in fac)
        status.append(stt)
    if write:
        _write_txns(con, moves, groups)
    return moves, status


def _write_txns(con, moves, groups):
    TYPE = {"new": ("secondary_purchase", "BUY", "New position"), "add": ("secondary_purchase", "BUY", "Added to position"),
            "trim": ("secondary_sale", "SELL", "Reduced position"), "exit": ("investor_exit", "SELL", "Exited position")}
    done = set()
    for m in moves:
        if m["kind"] not in TYPE:
            continue
        iid = "inv_amcgrp_" + m["group"]
        if iid not in done:
            upsert(con, "investors", dict(investor_id=iid, name=f"{groups.get(m['group'], m['group'])} (active schemes combined)", group_id=m["group"], category="mutual_fund",
                                          match_rule="sum of the AMC's active schemes in its monthly portfolio files"), "investor_id")
            con.execute("DELETE FROM transactions WHERE investor_id=? AND txn_date=? AND txn_id LIKE 'mff_%'", (iid, m["cur"]))
            done.add(iid)
        tt, side, verb = TYPE[m["kind"]]
        desc = (f"{verb}: active schemes held {m['q0']:,.0f} shares at {m['prev']} and {m['q1']:,.0f} at {m['cur']} (change verified from the two month-end portfolio files"
                + (f"; earlier quantity adjusted x{m['factor']} for a split/bonus seen in the files" if m["factor"] else "")
                + "). Rupee amount = share change x month-end price implied by the file (estimate).")
        ind = m["industry"] if not m["sector_inferred"] else None
        upsert(con, "transactions", dict(txn_id="mff_" + hid(m["group"], m["company"], m["cur"]), txn_type=tt, evidence_label="ESTIMATED VALUE", txn_date=m["cur"],
                                         announcement_date=None, investor_id=iid, company_id=m["company"], industry_id=ind, instrument="equity shares", side=side,
                                         quantity=abs(m["dq"]), price=None, amount=None, currency="INR", amount_inr_cr=abs(m["est_cr"]) if m["est_cr"] is not None else None,
                                         related_txn_id=None, description=desc, doc_id=m["doc_id"], source_id=m["source_id"]), "txn_id")
    con.commit()


def summarise(moves, status, names, ind_names, top=40):
    """Latest-month tables: stocks and sectors by number of AMC groups adding/new vs trimming/exiting."""
    latest = max((s["latest"] for s in status if s.get("counts")), default=None)
    mv = [m for m in moves if m["cur"] == latest]
    by_c = defaultdict(lambda: {"new": [], "add": [], "trim": [], "exit": [], "held": [], "est": 0.0})
    for m in mv:
        by_c[m["company"]][m["kind"]].append(m["group"])
        if m["kind"] != "held" and m["est_cr"] is not None:
            by_c[m["company"]]["est"] += m["est_cr"]
    stocks = []
    for c, d in by_c.items():
        sym, nm = names.get(c, (None, c))
        b, s = len(d["new"]) + len(d["add"]), len(d["trim"]) + len(d["exit"])
        stocks.append({"id": c, "symbol": sym, "name": nm, "industry": next((m["industry"] for m in mv if m["company"] == c), None),
                       "new": d["new"], "add": d["add"], "trim": d["trim"], "exit": d["exit"], "held": len(d["held"]), "buy_groups": b, "sell_groups": s, "net_groups": b - s,
                       "est_net_cr": round(d["est"], 2)})
    by_s = defaultdict(lambda: {"buy": 0, "sell": 0, "new": 0, "exit": 0, "stocks": set(), "est": 0.0, "inferred": 0})
    for m in mv:
        s = m["industry"] or "unclassified"
        by_s[s]["stocks"].add(m["company"])
        if m["kind"] in BUY_T: by_s[s]["buy"] += 1
        if m["kind"] in SELL_T: by_s[s]["sell"] += 1
        if m["kind"] == "new": by_s[s]["new"] += 1
        if m["kind"] == "exit": by_s[s]["exit"] += 1
        if m["kind"] != "held" and m["est_cr"] is not None: by_s[s]["est"] += m["est_cr"]
        if m["sector_inferred"]: by_s[s]["inferred"] += 1
    sectors = []
    for s, d in by_s.items():
        n = d["buy"] + d["sell"]
        sectors.append({"industry": s, "name": ind_names.get(s, s), "buy_moves": d["buy"], "sell_moves": d["sell"], "new_entries": d["new"], "exits": d["exit"],
                        "stocks": len(d["stocks"]), "net_breadth_pct": round((d["buy"] - d["sell"]) / n * 100, 1) if n >= 10 else None, "est_net_cr": round(d["est"], 1),
                        "inferred_sector_rows": d["inferred"]})
    sectors.sort(key=lambda x: -(x["net_breadth_pct"] if x["net_breadth_pct"] is not None else -999))
    key = lambda f: sorted([x for x in stocks if f(x)], key=lambda x: (-len(x["new"]) - len(x["add"]) if f is None else 0))
    return {"month": latest, "status": status, "sectors": sectors,
            "most_added": sorted([x for x in stocks if x["buy_groups"]], key=lambda x: (-x["buy_groups"], -x["est_net_cr"]))[:top],
            "most_new": sorted([x for x in stocks if x["new"]], key=lambda x: (-len(x["new"]), -x["est_net_cr"]))[:top],
            "most_reduced": sorted([x for x in stocks if x["sell_groups"]], key=lambda x: (-x["sell_groups"], x["est_net_cr"]))[:top],
            "most_exited": sorted([x for x in stocks if x["exit"]], key=lambda x: (-len(x["exit"]), x["est_net_cr"]))[:top],
            "band_pct": BAND * 100, "groups_compared": [s["group"] for s in status if s.get("counts") and s["latest"] == latest]}
