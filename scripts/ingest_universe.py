"""Listed universe: Nifty 500 + sector index membership -> companies, sub_industries."""
import csv, io
from common import Http, connect, upsert, doc, slug, run
from registry import SUB_INDUSTRIES

N500 = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"


def job(con):
    h = Http()
    r = h.get(N500)
    d = doc(con, "nse_universe", N500, "Nifty 500 constituents", data_period="current", content=r.content)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if len(rows) < 450:
        raise ValueError(f"only {len(rows)} rows")
    for x in rows:
        sym = x["Symbol"].strip()
        upsert(con, "companies", dict(company_id="NSE:" + sym, name=x["Company Name"].strip(), symbol=sym, isin=x["ISIN Code"].strip(), cin=None, listed=1,
                                      parent_group=None, industry_id=slug(x["Industry"]), sub_industry_id=None, index_membership="NIFTY 500", source_id="nse_universe"), "company_id")
        upsert(con, "industry_map", dict(source_id="nse_universe", source_label=x["Industry"], industry_id=slug(x["Industry"]), sub_industry_id=None), "source_id, source_label")
    # sub-industry = most specific NSE sectoral index (later keys in SUB_INDUSTRIES override broader ones)
    order = ["niftyfinance", "niftyhealthcare", "niftybank", "niftypsubank", "niftypharma", "niftyit", "niftyauto", "niftymetal", "niftyrealty",
             "niftyoilgas", "niftyfmcg", "niftymedia", "niftyconsumerdurables"]
    for k in order:
        u = f"https://archives.nseindia.com/content/indices/ind_{k}list.csv"
        try:
            rr = h.get(u)
        except Exception as e:  # noqa: BLE001
            print("skip", k, e); continue
        doc(con, "nse_universe", u, f"{SUB_INDUSTRIES[k][1]} constituents", data_period="current", content=rr.content)
        for x in csv.DictReader(io.StringIO(rr.text)):
            sym = x["Symbol"].strip()
            con.execute("UPDATE companies SET sub_industry_id=? WHERE company_id=? AND (industry_id=? )", (k, "NSE:" + sym, slug(SUB_INDUSTRIES[k][0])))
            con.execute("UPDATE companies SET index_membership=index_membership||', '||? WHERE company_id=? AND instr(index_membership, ?)=0",
                        (SUB_INDUSTRIES[k][1].split("(")[-1].rstrip(")"), "NSE:" + sym, SUB_INDUSTRIES[k][1].split("(")[-1].rstrip(")")))
    return {"rows_in": len(rows), "rows_new": len(rows), "period": "current"}


if __name__ == "__main__":
    run("nse_universe", job)
