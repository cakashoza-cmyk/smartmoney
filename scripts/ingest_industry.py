"""Sprint 2 industry data: trade (TradeStat, UN Comtrade), production (MoSPI IIP), capacity utilisation (RBI OBICUS),
closing prices (NSE bhavcopy, for an estimated market capitalisation). Official public sources, no keys, no form tricks:
TradeStat is a public form with a CSRF token and no captcha; it is requested a few times per run at most.
All values are stored as observations with a source document; mapping tables to NSE sectors are fixed and exported."""
from __future__ import annotations
import html, io, re, time, zipfile
from datetime import date, timedelta
from common import Http, connect, doc, obs, num, slug, today

# ---------------------------------------------------------------- fixed concordances (documented, editable here only)
# HS chapter -> NSE sectors. A chapter can feed several sectors; chapters not listed are kept but not mapped.
HS_SECTOR = {
    "26": ["metals_mining"], "72": ["metals_mining"], "73": ["metals_mining", "capital_goods"], "74": ["metals_mining"], "75": ["metals_mining"],
    "76": ["metals_mining"], "78": ["metals_mining"], "79": ["metals_mining"], "80": ["metals_mining"], "81": ["metals_mining"],
    "27": ["oil_gas_consumable_fuels"],
    "28": ["chemicals"], "29": ["chemicals", "healthcare"], "31": ["chemicals"], "32": ["chemicals"], "38": ["chemicals"], "39": ["chemicals"],
    "30": ["healthcare"],
    "84": ["capital_goods"], "85": ["capital_goods", "consumer_durables"], "86": ["capital_goods"], "88": ["capital_goods"],
    "89": ["capital_goods"], "93": ["capital_goods"],
    "87": ["automobile_and_auto_components"], "40": ["automobile_and_auto_components", "chemicals"],
    "25": ["construction_materials"], "68": ["construction_materials"], "69": ["construction_materials"], "70": ["construction_materials"],
    "50": ["textiles"], "51": ["textiles"], "52": ["textiles"], "53": ["textiles"], "54": ["textiles"], "55": ["textiles"], "56": ["textiles"],
    "57": ["textiles"], "58": ["textiles"], "59": ["textiles"], "60": ["textiles"], "61": ["textiles"], "62": ["textiles"], "63": ["textiles"],
    "15": ["fast_moving_consumer_goods"], "17": ["fast_moving_consumer_goods"], "18": ["fast_moving_consumer_goods"], "19": ["fast_moving_consumer_goods"],
    "20": ["fast_moving_consumer_goods"], "21": ["fast_moving_consumer_goods"], "22": ["fast_moving_consumer_goods"], "24": ["fast_moving_consumer_goods"],
    "33": ["fast_moving_consumer_goods"], "34": ["fast_moving_consumer_goods"],
    "44": ["forest_materials"], "47": ["forest_materials"], "48": ["forest_materials"], "49": ["forest_materials"],
    "71": ["consumer_durables"], "94": ["consumer_durables"], "91": ["consumer_durables"],
}
# IIP entity key (slug of type/category/sub-category) -> NSE sectors, matched on keywords so both base years map
IIP_SECTOR = [
    (r"basic_metals|metallic_minerals", ["metals_mining"]),
    (r"coke_and_refined_petroleum|fuel_minerals|gas_supply", ["oil_gas_consumable_fuels"]),
    (r"chemicals_and_chemical", ["chemicals"]), (r"rubber_and_plastics", ["chemicals"]),
    (r"pharmaceutical", ["healthcare"]),
    (r"other_non_metallic_mineral", ["construction_materials"]),
    (r"motor_vehicles", ["automobile_and_auto_components"]), (r"other_transport_equipment", ["automobile_and_auto_components", "capital_goods"]),
    (r"electrical_equipment|machinery_and_equipment|fabricated_metal", ["capital_goods"]),
    (r"computer_electronic", ["consumer_durables", "capital_goods"]),
    (r"food_products|beverages|tobacco", ["fast_moving_consumer_goods"]),
    (r"textiles|wearing_apparel|leather", ["textiles"]),
    (r"paper_and_paper|wood_and_products", ["forest_materials"]),
    (r"electricity$|renewable_electricity", ["power"]),
    (r"^use_based_capital_goods", ["capital_goods"]), (r"^use_based_consumer_durables", ["consumer_durables"]),
    (r"^use_based_consumer_non_durables", ["fast_moving_consumer_goods"]),
    (r"^use_based_infrastructure_construction_goods", ["construction", "construction_materials"]),
    (r"furniture", ["consumer_durables"]),
]


def iip_sectors(entity_key: str):
    out = []
    for pat, secs in IIP_SECTOR:
        if re.search(pat, entity_key):
            out += [s for s in secs if s not in out]
    return out


def _fy(y):  # 2025 -> ('2025-04-01', '2026-03-31')
    return f"{y}-04-01", f"{y + 1}-03-31"


def _cells(row):
    return [html.unescape(re.sub(r"<[^>]+>|\s+", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def _label(con, source_id, prefix, entity_type, key, text):
    """Human label for a code (HS chapter, IIP industry) kept as a valueless observation row, so no schema change is needed."""
    con.execute("INSERT OR REPLACE INTO observations(obs_id, source_id, metric, entity_type, entity_id, period_end, value, unit, evidence_label) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"{prefix}_{key}", source_id, f"{prefix}:" + text[:200], entity_type, key, "2000-01-01", None, None, "VERIFIED FACT"))


# ---------------------------------------------------------------- TradeStat (Ministry of Commerce)
TS = "https://tradestat.commerce.gov.in/eidb/commodity_wise_{kind}"
TS_FIELDS = {"export": {"comType": "all", "EidbYearCwe": None, "EidbComLevelCwe": "2", "Eidb_ReportCwe": "2"},
             "import": {"commodityType": "all", "Eidb_YearCwi": None, "Eidb_ComLevelCwi": "2", "Eidb_ReportCwi": "2"}}


def tradestat_table(h, kind, year):
    url = TS.format(kind=kind)
    page = h.get(url, timeout=60).text
    tok = re.search(r'name="_token" value="([^"]+)"', page).group(1)
    data = {"_token": tok}
    for k, v in TS_FIELDS[kind].items():
        data[k] = str(year) if v is None else v
    r = h.s.post(url, data=data, timeout=120)
    r.raise_for_status()
    rows = [_cells(x) for x in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S)]
    head = next((x for x in rows if x and x[0] == "S.No."), None)
    if not head:
        raise ValueError(f"TradeStat {kind} {year}: no table")
    yrs = [int(c[:4]) for c in head if re.match(r"^\d{4} - \d{4}$", c)]
    out = []
    for x in rows:
        if len(x) >= 8 and re.match(r"^\d{2}$", x[1] or ""):
            out.append({"hs": x[1], "name": x[2].rstrip(".").capitalize(), yrs[0]: num(x[3]), yrs[1]: num(x[5])})
    return out, yrs, url


def job_tradestat(con, years=(2025, 2023, 2021, 2019)):
    h = Http()
    n = 0; latest = None; names = {}
    for kind in ("export", "import"):
        for y in years:
            rows, yrs, url = tradestat_table(h, kind, y)
            for fy in yrs:
                lab = f"FY{fy}-{(fy + 1) % 100:02d}"
                d = doc(con, "tradestat_eidb", f"{url}?year={fy}&level=2&unit=usd_mn", f"TradeStat {kind}s by HS chapter, {lab} (US$ million)", data_period=lab)
                for r in rows:
                    if r.get(fy) is None:
                        continue
                    s, e = _fy(fy)
                    obs(con, "tradestat_eidb", f"trade_{kind}_usd_mn", "hs_chapter", r["hs"], e, r[fy], "US$ mn", period_start=s, doc_id=d)
                    names[r["hs"]] = r["name"]; n += 1
                    latest = max(latest or e, e)
            time.sleep(2)
    for hs, nm in names.items():
        _label(con, "tradestat_eidb", "hs_name", "hs_chapter", hs, nm)
    con.commit()
    if not n:
        raise ValueError("TradeStat returned no rows")
    return {"rows_in": len(years) * 2, "rows_new": n, "period": latest}


# ---------------------------------------------------------------- UN Comtrade (free public preview)
CT = "https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=699&period={y}&cmdCode=AG2&flowCode={f}&partnerCode=0"


def job_comtrade(con, years=None):
    h = Http()
    years = years or [today().year - 1, today().year - 2]
    n = 0; latest = None
    for y in years:
        for f, kind in (("M", "import"), ("X", "export")):
            u = CT.format(y=y, f=f)
            try:
                j = h.get(u, tries=2, timeout=60).json()
            except Exception as e:  # noqa: BLE001
                print("comtrade", y, f, e); continue
            data = j.get("data") or []
            if not data:
                continue
            d = doc(con, "un_comtrade", u, f"UN Comtrade India {kind}s {y}, HS 2-digit, world", data_period=str(y))
            for r in data:
                cc = str(r.get("cmdCode") or "")
                if not re.match(r"^\d{2}$", cc) or r.get("primaryValue") is None:
                    continue
                obs(con, "un_comtrade", f"comtrade_{kind}_usd_mn", "hs_chapter", cc, f"{y}-12-31", round(r["primaryValue"] / 1e6, 2), "US$ mn",
                    period_start=f"{y}-01-01", doc_id=d); n += 1
                latest = max(latest or str(y), str(y))
            time.sleep(1.5)
    con.commit()
    if not n:
        raise ValueError("Comtrade preview returned no rows")
    return {"rows_in": len(years) * 2, "rows_new": n, "period": latest}


# ---------------------------------------------------------------- MoSPI IIP
IIP = "https://api.mospi.gov.in/api/iip/getIipData?base_year={b}&frequency=Monthly&year={y}&type=All&Format=JSON&limit=200&page={p}"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


def _month_end(y, m):
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def iip_key(r):
    cat = r.get("category") or ""; sub = r.get("sub_category") or ""; typ = r.get("type") or ""
    if typ == "General":
        return "general"
    if typ.lower().startswith("use"):
        return slug("use-based " + cat)
    return slug(cat + (" " + sub if sub else ""))


def job_iip(con, plan=None):
    h = Http()
    y0 = today().year
    plan = plan or [("2022-23", y) for y in range(2023, y0 + 1)] + [("2011-12", y) for y in range(2019, 2026)]
    n = 0; latest = None; labels = {}
    for base, y in plan:
        p = 1
        while True:
            u = IIP.format(b=base, y=y, p=p)
            try:
                j = h.get(u, tries=2, timeout=60).json()
            except Exception as e:  # noqa: BLE001
                print("iip", base, y, p, e); break
            data = j.get("data") or []
            if not data:
                break
            d = doc(con, "mospi_iip", u.split("&page")[0], f"MoSPI IIP monthly {y} (base {base})", data_period=f"{y} base {base}")
            for r in data:
                m = MONTHS.get(r.get("month"))
                if not m:
                    continue
                k = iip_key(r); pe = _month_end(int(r["year"]), m); b = base[:4]
                labels[k] = " | ".join(x for x in (r.get("type"), r.get("category"), r.get("sub_category")) if x)
                if num(r.get("index")) is not None:
                    obs(con, "mospi_iip", f"iip_index_b{b}", "iip_industry", k, pe, num(r["index"]), "index", doc_id=d); n += 1
                if num(r.get("growth_rate")) is not None:
                    obs(con, "mospi_iip", f"iip_yoy_pct_b{b}", "iip_industry", k, pe, num(r["growth_rate"]), "%", doc_id=d); n += 1
                latest = max(latest or pe, pe)
            tp = (j.get("meta_data") or {}).get("totalPages") or 1
            if p >= tp:
                break
            p += 1
            time.sleep(0.8)
    for k, lab in labels.items():
        _label(con, "mospi_iip", "iip_label", "iip_industry", k, lab)
    con.commit()
    if not n:
        raise ValueError("MoSPI IIP returned no rows")
    return {"rows_in": len(plan), "rows_new": n, "period": latest}


# ---------------------------------------------------------------- RBI OBICUS
OB_LIST = "https://www.rbi.org.in/scripts/QuarterlyPublications.aspx?head=Quarterly+Order+Books%2C+Inventories+and+Capacity+Utilisation+Survey"


def _q_end(lab):  # 'Q1:2026-27' -> 2026-06-30
    m = re.match(r"Q([1-4]):(\d{4})-\d{2}", lab)
    q, fy = int(m.group(1)), int(m.group(2))
    return {1: f"{fy}-06-30", 2: f"{fy}-09-30", 3: f"{fy}-12-31", 4: f"{fy + 1}-03-31"}[q]


def job_obicus(con, releases=3):
    h = Http()
    lst = h.get(OB_LIST, timeout=60).text
    ids = list(dict.fromkeys(re.findall(r"PublicationsView\.aspx\?id=(\d+)", lst)))[:releases]
    n = 0; latest = None
    for pid in reversed(ids):  # oldest first so the newest release's (revised) figures win
        u = f"https://www.rbi.org.in/Scripts/PublicationsView.aspx?id={pid}"
        t = h.get(u, timeout=60).text
        i = t.find("Table 1: Capacity")
        if i < 0:
            continue
        title = re.search(r"Order Books, Inventories and Capacity Utilisation Survey[^<]{0,80}", t)
        pub = re.search(r"Date\s*:\s*([A-Z][a-z]{2} \d{2}, \d{4})", t)
        d = doc(con, "rbi_obicus", u, title.group(0).strip() if title else "RBI OBICUS", publication_date=pub.group(1) if pub else None)
        j = t.find("Table 2A", i)
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t[i:j if j > i else i + 5000], re.S):
            c = _cells(row)
            if len(c) >= 4 and re.match(r"^Q[1-4]:\d{4}-\d{2}$", c[0]):
                pe = _q_end(c[0])
                obs(con, "rbi_obicus", "obicus_cu_pct", "market", "india_manufacturing", pe, num(c[2]), "%", doc_id=d)
                obs(con, "rbi_obicus", "obicus_cu_sa_pct", "market", "india_manufacturing", pe, num(c[3]), "%", doc_id=d)
                n += 2; latest = max(latest or pe, pe)
        for row in (re.findall(r"<tr[^>]*>(.*?)</tr>", t[j:j + 5000], re.S) if j > 0 else []):
            c = _cells(row)
            if len(c) >= 8 and re.match(r"^Q[1-4]:\d{4}-\d{2}$", c[0]):
                obs(con, "rbi_obicus", "obicus_new_orders_yoy_pct", "market", "india_manufacturing", _q_end(c[0]), num(c[6]), "%", doc_id=d); n += 1
        time.sleep(1)
    con.commit()
    if not n:
        raise ValueError("OBICUS tables not found")
    return {"rows_in": len(ids), "rows_new": n, "period": latest}


# ---------------------------------------------------------------- NSE bhavcopy (close prices for the Nifty 500)
BHAV = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"


def job_bhavcopy(con, lookback=7):
    import csv
    h = Http()
    syms = {r[0]: r[1] for r in con.execute("SELECT symbol, company_id FROM companies WHERE index_membership LIKE 'NIFTY 500%' AND symbol IS NOT NULL")}
    for k in range(lookback):
        dt = today() - timedelta(days=k)
        if dt.weekday() >= 5:
            continue
        u = BHAV.format(d=dt.strftime("%Y%m%d"))
        try:
            r = h.get(u, tries=1, timeout=60)
        except Exception:  # noqa: BLE001
            continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        rows = list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), "utf-8")))
        d = doc(con, "nse_bhavcopy", u, f"NSE CM bhavcopy {dt.isoformat()}", publication_date=dt.isoformat(), data_period=dt.isoformat())
        n = 0
        for x in rows:
            if x.get("SctySrs") in ("EQ", "BE") and x.get("TckrSymb") in syms and num(x.get("ClsPric")):
                obs(con, "nse_bhavcopy", "close_inr", "company", syms[x["TckrSymb"]], x["TradDt"], num(x["ClsPric"]), "INR", doc_id=d); n += 1
        con.commit()
        if n:
            return {"rows_in": len(rows), "rows_new": n, "period": dt.isoformat()}
    raise ValueError("no bhavcopy in the last week")


JOBS = {"tradestat_eidb": job_tradestat, "un_comtrade": job_comtrade, "mospi_iip": job_iip, "rbi_obicus": job_obicus, "nse_bhavcopy": job_bhavcopy}

if __name__ == "__main__":
    import sys
    from common import run
    for sid in sys.argv[1:] or list(JOBS):
        run(sid, JOBS[sid])
