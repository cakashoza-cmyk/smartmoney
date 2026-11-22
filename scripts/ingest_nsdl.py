"""NSDL fortnightly sector-wise FPI investment (official, aggregate of all FPIs). History from 2017; incremental after.
Two NSDL sector taxonomies: from Apr 2022 the NSE macro-sector list (matches our industries 1:1); before that ~40 finer
sectors, which are kept as sub-sectors and mapped to the current sector by name (LEGACY_MAP, documented as approximate)."""
import io, re
from datetime import datetime, date
import pandas as pd
from common import Http, connect, upsert, doc, obs, run, slug, num
from registry import INDUSTRIES

SEL = "https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx"
BASE = "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/"
START = date(2017, 1, 1)
CUR = {slug(x): x for x in INDUSTRIES}
LEGACY_MAP = {  # old NSDL sector label -> current NSE macro-sector (approximate, by name)
    "automobiles_auto_components": "Automobile and Auto Components", "banks": "Financial Services", "other_financial_services": "Financial Services",
    "total_financial_services": None, "insurance": "Financial Services", "capital_goods": "Capital Goods", "chemicals_petrochemicals": "Chemicals",
    "coal": "Oil, Gas & Consumable Fuels", "commercial_services_supplies": "Services", "construction_materials": "Construction Materials",
    "consumer_durables": "Consumer Durables", "diversified": "Diversified", "diversified_consumer_services": "Consumer Services",
    "food_drugs_retailing": "Consumer Services", "food_beverages_tobacco": "Fast Moving Consumer Goods", "forest_materials": "Forest Materials",
    "general_industrials": "Capital Goods", "hardware_technology_equipment": "Information Technology", "healthcare_equipment_supplies": "Healthcare",
    "healthcare_services": "Healthcare", "hotels_restaurants_tourism": "Consumer Services", "household_personal_products": "Fast Moving Consumer Goods",
    "media": "Media, Entertainment & Publication", "metals_mining": "Metals & Mining", "oil_gas": "Oil, Gas & Consumable Fuels",
    "pharmaceuticals_biotechnology": "Healthcare", "real_estate_investment": "Realty", "realty": "Realty", "retailing": "Consumer Services",
    "software_services": "Information Technology", "telecom_services": "Telecommunication", "telecommunications_equipment": "Telecommunication",
    "textiles_apparels_accessories": "Textiles", "transportation": "Services", "airlines": "Services", "logistics": "Services",
    "marine_port_services": "Services", "airport_services": "Services", "surface_transportation": "Services", "roads_highways": "Construction", "shipping": "Services", "transport_related_services": "Services",
    "utilities": "Utilities", "power": "Power", "construction": "Construction", "sovereign": "Sovereign", "others": "Others",
    "grand_total": None, "total": None,
}
MON = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def parse_period(h):
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2}),\s*(\d{4})", h)
    if not m:
        return None
    mo = MON[m.group(1).lower()]; y = int(m.group(4))
    return date(y, mo, int(m.group(2))).isoformat(), date(y, mo, int(m.group(3))).isoformat()


def parse_table(t):
    d = pd.read_html(io.StringIO(t), flavor="lxml")[0]
    hdr = [[str(d.iloc[i, c]) for i in range(3)] for c in range(d.shape[1])]
    flows, auc = [], None
    for c, (h0, h1, h2) in enumerate(hdr):
        if "INR" not in h1:
            continue
        if h0.startswith("Net Investment"):
            p = parse_period(h0)
            if p and h2 == "Equity" and not any(f["period"] == p and "eq" in f for f in flows):
                flows.append({"period": p, "eq": c})
            elif p and h2 in ("nan", "Total") and flows and flows[-1]["period"] == p:
                flows[-1]["tot"] = c
        if h0.startswith("AUC") and h2 == "Equity":
            auc = (c, h0)
    out = []
    for r in range(3, d.shape[0]):
        lab = str(d.iloc[r, 1]).strip()
        if lab in ("nan", "Sectors", ""):
            continue
        lab = re.sub(r"\d+$", "", lab).strip()
        row = {"label": lab, "flows": [], "auc": None}
        for f in flows:
            row["flows"].append((f["period"], num(d.iloc[r, f["eq"]]), num(d.iloc[r, f["tot"]]) if "tot" in f else None))
        if auc:
            row["auc"] = num(d.iloc[r, auc[0]])
        out.append(row)
    auc_date = None
    if auc:
        m = re.search(r"as on ([A-Za-z]+) (\d{1,2}), (\d{4})", auc[1])
        if m:
            auc_date = date(int(m.group(3)), MON[m.group(1).lower()], int(m.group(2))).isoformat()
    return out, auc_date


def label_to_industry(lab):
    s = slug(lab)
    if s in CUR:
        return slug(CUR[s]), "current"
    if s in LEGACY_MAP:
        return (slug(LEGACY_MAP[s]) if LEGACY_MAP[s] else None), "legacy"
    return None, "unmapped"


def job(con):
    h = Http()
    t = h.get(SEL).text
    files = re.findall(r"StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/(FIIInvestSec\w*_(\w{3})(\d{2})(\d{4})\.html)", t)
    have = {r[0] for r in con.execute("SELECT url FROM source_documents WHERE source_id='nsdl_fpi_sector'")}
    picks = []
    for f, mon, dd, yy in files:
        try:
            dt = datetime.strptime(f"{mon}{dd}{yy}", "%b%d%Y").date()
        except ValueError:
            continue
        if dt < START:
            continue
        is_end = (dt.replace(day=28) == dt.replace(day=28)) and dd != "15"
        picks.append((dt, f, is_end))
    picks.sort()
    latest = picks[-1][1] if picks else None
    sel = [p for p in picks if p[2] or p[1] == latest]
    n_obs, n_files, unm = 0, 0, set()
    for dt, f, _ in sel:
        url = BASE + f
        if url in have and f != latest:
            continue
        try:
            body = h.get(url, pause=0.5).text
            rows, auc_date = parse_table(body)
        except Exception as e:  # noqa: BLE001
            print("skip", f, e); continue
        d = doc(con, "nsdl_fpi_sector", url, f"NSDL fortnightly sector FPI {dt}", publication_date=None, data_period=str(dt), content=body.encode())
        n_files += 1
        for r in rows:
            ind, kind = label_to_industry(r["label"])
            if kind == "unmapped":
                unm.add(r["label"])
            sub = "nsdl_legacy_" + slug(r["label"]) if kind == "legacy" else None
            ent = "total" if slug(r["label"]) == "grand_total" else (ind or "nsdl_" + slug(r["label"]))
            if kind == "legacy" and ent != "total":
                # store the legacy sub-sector as its own series; the sector series is summed in build (documented)
                ent = sub
                if ind:
                    upsert(con, "sub_industries", dict(sub_industry_id=sub, industry_id=ind, name=r["label"] + " (NSDL legacy sector, to Mar 2022)",
                                                       basis="NSDL pre-2022 sector, mapped to current sector by name (approximate)"), "sub_industry_id")
            upsert(con, "industry_map", dict(source_id="nsdl_fpi_sector", source_label=r["label"], industry_id=ind, sub_industry_id=sub), "source_id, source_label")
            for (ps, pe), eq, tot in r["flows"]:
                obs(con, "nsdl_fpi_sector", "fpi_net_equity_inr_cr", "industry", ent, pe, eq, "INR crore", period_start=ps, doc_id=d); n_obs += 1
                if tot is not None:
                    obs(con, "nsdl_fpi_sector", "fpi_net_total_inr_cr", "industry", ent, pe, tot, "INR crore", period_start=ps, doc_id=d)
            if r["auc"] is not None and auc_date:
                obs(con, "nsdl_fpi_sector", "fpi_auc_equity_inr_cr", "industry", ent, auc_date, r["auc"], "INR crore", doc_id=d)
        con.commit()
    last = con.execute("SELECT max(period_end) FROM observations WHERE source_id='nsdl_fpi_sector' AND metric='fpi_net_equity_inr_cr'").fetchone()[0]
    return {"rows_in": n_files, "rows_new": n_obs, "period": last, "warn": ("unmapped labels: " + ", ".join(sorted(unm))) if unm else None}


if __name__ == "__main__":
    run("nsdl_fpi_sector", job)
