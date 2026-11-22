"""NSE daily feeds: FII/DII provisional flows, bulk & block deals, corporate announcements (capital events only)."""
import csv, io, re, sys
from datetime import datetime, timedelta
from common import Http, connect, upsert, insert_new, doc, obs, hid, run, num, today, slug
from investors import resolve

FIIDII = "https://www.nseindia.com/api/fiidiiTradeReact"
DEALS_CSV = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType={t}&from={a}&to={b}&csv=true"
ANN = "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={a}&to_date={b}"


def job_fiidii(con):
    h = Http(nse=True)
    j = h.get(FIIDII).json()
    n = 0
    for r in j:
        k = "fii" if r["category"].startswith("FII") else "dii" if r["category"] == "DII" else None
        if not k:
            continue
        dt = datetime.strptime(r["date"], "%d-%b-%Y").date().isoformat()
        d = doc(con, "nse_fiidii", "https://www.nseindia.com/reports/fii-dii", f"NSE FII/DII provisional {dt}", publication_date=dt, data_period=dt)
        for m, key in (("net", "netValue"), ("buy", "buyValue"), ("sell", "sellValue")):
            obs(con, "nse_fiidii", f"{k}_{m}_cash_inr_cr", "market", "india_cash_market", dt, num(r[key]), "INR crore", period_start=dt, doc_id=d, label="VERIFIED FACT")
        n += 1
    if not n:
        raise ValueError("no FII/DII rows")
    return {"rows_in": len(j), "rows_new": n, "period": dt, "pub": dt}


def company_for(con, sym, name):
    cid = "NSE:" + sym
    if not con.execute("SELECT 1 FROM companies WHERE company_id=?", (cid,)).fetchone():
        upsert(con, "companies", dict(company_id=cid, name=name, symbol=sym, isin=None, cin=None, listed=1, parent_group=None, industry_id=None,
                                      sub_industry_id=None, index_membership=None, source_id="nse_deals"), "company_id")
    r = con.execute("SELECT industry_id FROM companies WHERE company_id=?", (cid,)).fetchone()
    return cid, r["industry_id"] if r else None


def job_deals(con, days=None):
    h = Http(nse=True)
    last = con.execute("SELECT max(txn_date) FROM transactions WHERE source_id='nse_deals'").fetchone()[0]
    end = today()
    start = (datetime.fromisoformat(last).date() - timedelta(days=3)) if last and not days else end - timedelta(days=days or 365)
    rows_in = new = dup = 0
    s = start
    while s <= end:
        e = min(s + timedelta(days=13), end)
        for t, kind in (("bulk_deals", "bulk"), ("block_deals", "block")):
            url = DEALS_CSV.format(t=t, a=s.strftime("%d-%m-%Y"), b=e.strftime("%d-%m-%Y"))
            try:
                txt = h.get(url, headers={"Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals", "Accept": "*/*"}, pause=1.5).content.decode("utf-8-sig", "ignore")
            except Exception as ex:  # noqa: BLE001
                print("deals fail", url, ex); continue
            rd = list(csv.reader(io.StringIO(txt)))
            if not rd:
                continue
            hdr = [c.strip().lower() for c in rd[0]]
            if "symbol" not in hdr:
                continue
            ix = {k: hdr.index(k) for k in hdr}
            d = doc(con, "nse_deals", url.replace("&csv=true", ""), f"NSE {kind} deals {s}..{e}", data_period=f"{s}..{e}")
            for r in rd[1:]:
                if len(r) < 7:
                    continue
                try:
                    dt = datetime.strptime(r[ix["date"]].strip(), "%d-%b-%Y").date().isoformat()
                except ValueError:
                    continue
                sym, nm, client, side = r[ix["symbol"]].strip(), r[ix["security name"]].strip(), r[ix["client name"]].strip(), r[ix["buy / sell"]].strip().upper()
                qty, px = num(r[ix["quantity traded"]]), num(r[ix["trade price / wght. avg. price"]])
                rows_in += 1
                cid, ind = company_for(con, sym, nm)
                iid, gid, cat = resolve(con, client)
                tid = "nse_" + kind + "_" + hid(dt, sym, client, side, qty, px)
                ok = insert_new(con, "transactions", dict(txn_id=tid, txn_type="secondary_purchase" if side == "BUY" else "secondary_sale",
                     evidence_label="VERIFIED FACT", txn_date=dt, announcement_date=dt, investor_id=iid, company_id=cid, industry_id=ind,
                     instrument=f"equity ({kind} deal)", side=side, quantity=qty, price=px, amount=(qty * px if qty and px else None), currency="INR",
                     amount_inr_cr=round(qty * px / 1e7, 7) if qty and px else None, related_txn_id=None,
                     description=f"{client} {side.lower()} {int(qty or 0):,} shares of {nm} at Rs {px} ({kind} deal; value = qty x price)",
                     doc_id=d, source_id="nse_deals"), "txn_id")
                new += ok; dup += (not ok)
        con.commit()
        s = e + timedelta(days=1)
    return {"rows_in": rows_in, "rows_new": new, "dup": dup, "period": con.execute("SELECT max(txn_date) FROM transactions WHERE source_id='nse_deals'").fetchone()[0]}


ANN_TYPES = [  # (regex on NSE subject or text, txn_type, table)
    (r"^Acquisition", "acquisition", "acquisitions"), (r"Sale or disposal|Divest", "divestment", "divestments"),
    (r"Amalgamation|Merger", "merger", None), (r"Demerger|Scheme of Arrangement", "merger", None),
    (r"Qualified Institutional|\bQIP\b", "primary_issuance", None), (r"Preferential", "primary_issuance", None),
    (r"Allotment of Securities|Warrants|Rights Issue|Fund Rais", "primary_issuance", None),
    (r"Joint Venture|\bJV\b", "joint_venture", None),
    (r"Commencement of commercial production", "corporate_capex", "capex_commissioned"),
    (r"capacity expansion|capex|capital expenditure|greenfield|brownfield|new plant|expansion of", "corporate_capex", "capex_announced"),
]
AMT = re.compile(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\.?|lakh|lakhs|million|mn|billion|bn)\b", re.I)


def amount_cr(text):
    vals = set()
    for v, u in AMT.findall(text or ""):
        x = num(v)
        if x is None:
            continue
        u = u.lower()
        x = x if u.startswith("cr") else x / 100 if u.startswith("lakh") else x / 10 if u in ("million", "mn") else x * 100
        vals.add(round(x, 2))
    return vals.pop() if len(vals) == 1 else None  # 0 or 2+ different amounts -> undisclosed (no guessing)


def classify_ann(desc, text):
    if re.search(r"^(Bonus|ESOP|Trading Window|Credit Rating)", desc, re.I) or re.search(r"ESOP|ESPS|ESOS|Employee Stock", text[:250], re.I):
        return None, None
    if re.search(r"Allotment|Committee", desc, re.I) and re.search(r"Non[- ]Convertible|NCD|Commercial Paper|Debenture|Bonds?\b", text[:300], re.I):
        return "capital_raised", None  # debt raised
    if re.search(r"Allotment of Securities", desc, re.I) and not re.search(r"Qualified Institutional|QIP|Preferential|Warrant|Rights", text, re.I):
        return None, None
    for rx, tt, tab in ANN_TYPES[:8]:
        if re.search(rx, desc, re.I):
            return tt, tab
    blob = f"{desc} {text}"
    for rx, tt, tab in ANN_TYPES:
        if re.search(rx, blob, re.I) and (tt != "corporate_capex" or re.search(r"Board Meeting|Updates|Press Release|Commencement|General", desc, re.I)):
            return tt, tab
    return None, None


def job_ann(con, days=None):
    h = Http(nse=True)
    last = con.execute("SELECT max(announcement_date) FROM transactions WHERE source_id='nse_announcements'").fetchone()[0]
    end = today()
    start = (datetime.fromisoformat(last[:10]).date() - timedelta(days=1)) if last and not days else end - timedelta(days=days or 90)
    rows_in = new = dup = 0
    s = start
    while s <= end:
        e = min(s + timedelta(days=2), end)
        try:
            j = h.get(ANN.format(a=s.strftime("%d-%m-%Y"), b=e.strftime("%d-%m-%Y")), pause=1.5, timeout=90).json()
        except Exception as ex:  # noqa: BLE001
            print("ann fail", s, ex); s = e + timedelta(days=1); continue
        for a in j:
            desc, text = a.get("desc") or "", a.get("attchmntText") or ""
            tt, tab = classify_ann(desc, text)
            if not tt:
                continue
            rows_in += 1
            dt = datetime.strptime(a["an_dt"][:11], "%d-%b-%Y").date().isoformat()
            cid, ind = company_for(con, a["symbol"], a.get("sm_name") or a["symbol"])
            url = a.get("attchmntFile") or "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
            d = doc(con, "nse_announcements", url, f"{a['symbol']}: {desc}", publication_date=dt, data_period=dt, label="REPORTED ANNOUNCEMENT")
            amt = amount_cr(text)
            tid = "nse_ann_" + hid(a.get("seq_id"), a["symbol"], dt)
            ok = insert_new(con, "transactions", dict(txn_id=tid, txn_type=tt, evidence_label="REPORTED ANNOUNCEMENT", txn_date=None, announcement_date=dt,
                 investor_id=None, company_id=cid, industry_id=ind, instrument=("debt (NCD/CP/bond)" if tt == "capital_raised" else None), side="NA", quantity=None, price=None, amount=None, currency="INR",
                 amount_inr_cr=amt, related_txn_id=None, description=f"[{desc}] {text[:600]}", doc_id=d, source_id="nse_announcements"), "txn_id")
            if ok:
                if tab == "acquisitions":
                    upsert(con, "acquisitions", dict(acquisition_id=tid, txn_id=tid, acquirer_company_id=cid, target_name=None, stake_pct=None, amount_inr_cr=amt, status="announced"), "acquisition_id")
                elif tab == "divestments":
                    upsert(con, "divestments", dict(divestment_id=tid, txn_id=tid, seller_company_id=cid, asset_name=None, amount_inr_cr=amt, status="announced"), "divestment_id")
                elif tab and tab.startswith("capex"):
                    upsert(con, "capex", dict(capex_id=tid, txn_id=tid, company_id=cid, industry_id=ind, description=text[:300], amount_inr_cr=amt,
                                              stage="commissioned" if tab.endswith("commissioned") else "announced", evidence_label="REPORTED ANNOUNCEMENT", doc_id=d), "capex_id")
            new += ok; dup += (not ok)
        con.commit()
        s = e + timedelta(days=1)
    return {"rows_in": rows_in, "rows_new": new, "dup": dup, "period": str(end)}


if __name__ == "__main__":
    which = sys.argv[1:] or ["fiidii", "deals", "ann"]
    if "fiidii" in which:
        run("nse_fiidii", job_fiidii)
    if "deals" in which:
        run("nse_deals", job_deals)
    if "ann" in which:
        run("nse_announcements", job_ann)
