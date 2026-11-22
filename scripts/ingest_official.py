"""Official structured sources other than NSE: SEBI AIF, RBI SIBC, AMFI, CRISIL, PIB, World Bank, FRED, NSE sector P/E, DPIIT."""
import io, json, re, sys, html as H
from datetime import date, datetime, timedelta
import pandas as pd
from common import Http, connect, upsert, insert_new, doc, obs, hid, run, num, slug, today

MON3 = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONF = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def dparse(s):
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", s.strip())
    mo = next(v for k, v in MONF.items() if k.startswith(m.group(1).lower()[:3]))
    return date(int(m.group(3)), mo, int(m.group(2))).isoformat()


# ---------------------------------------------------------------- SEBI AIF
AIF_SECTOR = {"real estate": "realty", "financial services": "financial_services", "nbfcs": "financial_services", "banks": "financial_services",
              "insurance": "financial_services", "it/ ites": "information_technology", "it/ites": "information_technology", "pharmaceuticals": "healthcare",
              "health care providers & services": "healthcare", "automobiles": "automobile_and_auto_components", "infrastructure": "infrastructure_cross_sector",
              "fmcg": "fast_moving_consumer_goods", "capital goods": "capital_goods", "chemicals": "chemicals", "others": None, "grand total": None}


def job_sebi_aif(con):
    url = "https://www.sebi.gov.in/statistics/1392982252002.html"
    t = re.sub(r"<!--.*?-->", "", Http().get(url).text, flags=re.S)
    pos = [m.start() for m in re.finditer(r"<table", t)]
    q, n, quarters = None, 0, set()
    for i, p in enumerate(pos):
        pre = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t[pos[i - 1] if i else 0:p]))
        m = re.findall(r"quarter ending ([A-Za-z]+ \d{1,2}, \d{4})", pre)
        if m:
            q = dparse(m[-1])
        if not q:
            continue
        cap = pre.strip()[-120:].lower()
        end = t.find("</table>", p)
        try:
            d = pd.read_html(io.StringIO(t[p:end + 8]), flavor="lxml")[0]
        except Exception:  # noqa: BLE001
            continue
        hdr = " ".join(str(x) for x in d.iloc[:3].values.flatten()).lower()
        dd = doc(con, "sebi_aif", url, f"SEBI AIF statistics, quarter ending {q}", data_period=q)
        if "commitments raised" in hdr and "investments made" in hdr:
            quarters.add(q)
            for r in range(2, d.shape[0]):
                cat = str(d.iloc[r, 0]).strip()
                if cat in ("nan", "Category of AIF"):
                    continue
                c, f, inv = num(d.iloc[r, 1]), num(d.iloc[r, 2]), num(d.iloc[r, 3])
                ent = "aif_" + slug(cat)
                obs(con, "sebi_aif", "aif_commitments_cum_inr_cr", "investor_group", ent, q, c, "INR crore", doc_id=dd)
                obs(con, "sebi_aif", "aif_funds_raised_cum_inr_cr", "investor_group", ent, q, f, "INR crore", doc_id=dd)
                obs(con, "sebi_aif", "aif_investments_cum_inr_cr", "investor_group", ent, q, inv, "INR crore", doc_id=dd)
                cid = "aifc_" + hid(ent, q)
                upsert(con, "commitments", dict(commitment_id=cid, txn_id=None, scope=f"{cat}: cumulative commitments raised", industry_id=None, period=q,
                                                amount_inr_cr=c, evidence_label="VERIFIED FACT", doc_id=dd), "commitment_id")
                upsert(con, "deployments", dict(deployment_id="aifd_" + hid(ent, q), txn_id=None, commitment_id=cid, scope=f"{cat}: cumulative investments made (net)",
                                                industry_id=None, period=q, amount_inr_cr=inv, evidence_label="VERIFIED FACT", doc_id=dd), "deployment_id")
                n += 1
        elif "top 10 sectors" in cap or ("sector" in hdr and "amount invested" in hdr):
            for r in range(2, d.shape[0]):
                lab = str(d.iloc[r, 1]).strip()
                v = num(d.iloc[r, 2])
                if lab in ("nan", "Sector") or v is None:
                    continue
                ind = AIF_SECTOR.get(lab.lower())
                obs(con, "sebi_aif", "aif_sector_invested_cum_inr_cr", "industry", "aif_sector_" + slug(lab), q, v, "INR crore", doc_id=dd)
                upsert(con, "industry_map", dict(source_id="sebi_aif", source_label=lab, industry_id=ind, sub_industry_id=None), "source_id, source_label")
                if ind:
                    upsert(con, "deployments", dict(deployment_id="aifs_" + hid(lab, q), txn_id=None, commitment_id=None, scope=f"AIF cumulative net investment: {lab}",
                                                    industry_id=ind, period=q, amount_inr_cr=v, evidence_label="VERIFIED FACT", doc_id=dd), "deployment_id")
                n += 1
    if not quarters:
        raise ValueError("AIF summary table not found")
    return {"rows_in": len(pos), "rows_new": n, "period": max(quarters)}


# ---------------------------------------------------------------- RBI SIBC
SIBC_MAP = [  # (regex on SIBC name, industry_id)
    (r"^Agriculture", "agriculture_and_allied"), (r"^Mining", "metals_mining"), (r"Rubber|Plastic", "chemicals"), (r"Glass", "construction_materials"),
    (r"Cement", "construction_materials"), (r"Basic Metal|Iron and Steel|Other Metal", "metals_mining"), (r"Engineering|Electronics", "capital_goods"),
    (r"Vehicles, Vehicle", "automobile_and_auto_components"), (r"Gems", "consumer_durables"), (r"^Construction", "construction"),
    (r"^Infrastructure|Roads|Airports|Ports|Railways|Other Infrastructure", "infrastructure_cross_sector"), (r"^Power", "power"),
    (r"Telecommunications", "telecommunication"), (r"Food Processing|Sugar|Edible|Tea|Beverage", "fast_moving_consumer_goods"),
    (r"Textiles|Leather", "textiles"), (r"Wood|Paper", "forest_materials"), (r"Petroleum", "oil_gas_consumable_fuels"),
    (r"Chemicals|Fertiliser|Petro Chemicals", "chemicals"), (r"Drugs", "healthcare"), (r"Transport Operators|Shipping|Aviation|Professional Services|Other Services", "services"),
    (r"Computer Software", "information_technology"), (r"Tourism", "consumer_services"), (r"Trade", "trade_wholesale_and_retail"),
    (r"Commercial Real Estate", "realty"), (r"NBFC|Non-Banking|Housing Finance|Public Financial", "financial_services"),
    (r"Personal Loans|Housing \(|Credit Card|Education|Vehicle Loans|gold jewellery|Advances|Consumer Durables|Other Personal", "personal_retail_loans"),
]


def parse_sibc_rows(rows):
    """Copied from Lending Radar (regime-engine/engine/lending_sources.py, unit-tested there)."""
    MON = {m: i + 1 for i, m in enumerate(MON3)}
    out, dates = {}, None
    for r in rows:
        cells = [c for c in r if c is not None]
        if not cells:
            continue
        if all(isinstance(c, str) for c in cells) and len(cells) >= 5 and re.match(r"\d{1,2}\.\w{3},\d{4}", str(cells[0])):
            dates = cells[:5]; continue
        lab = str(cells[0]).strip()
        m = re.match(r"^(\d+(?:\.\d+)*)\.\s+(.*)$", lab)
        nums = [c for c in cells[1:] if isinstance(c, (int, float))]
        if not m or len(nums) < 9 or dates is None:
            continue
        code, name = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        yago, cur, yoy, fy = float(nums[2]), float(nums[4]), float(nums[6]), float(nums[8])
        calc = (cur / yago - 1) * 100 if yago else None
        dd, mm, yy = re.match(r"(\d{1,2})\.(\w{3}),(\d{4})", dates[4]).groups()
        out[code] = {"name": re.sub(r"\d+$", "", name.replace(" of which,", "")).strip(), "outstanding_cr": round(cur), "outstanding_yago_cr": round(yago),
                     "yoy_pct": round(yoy, 2), "fy_pct": round(fy, 2), "as_of": date(int(yy), MON[mm.lower()[:3]], int(dd)).isoformat(),
                     "check_ok": calc is not None and abs(calc - yoy) < 0.1}
    return out


def sibc_industry(name, code):
    if code in ("2", "3"):
        return None
    for rx, ind in SIBC_MAP:
        if re.search(rx, name, re.I):
            return ind
    return None


def job_rbi_sibc(con, months_back=4):
    import openpyxl
    h = Http()
    have = {r[0] for r in con.execute("SELECT url FROM source_documents WHERE source_id='rbi_sibc'")}
    found, n = [], 0
    t = today()
    for k in range(months_back):
        y, m = t.year, t.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        for day in range(31, 19, -1):
            try:
                dt = date(y, m, day)
            except ValueError:
                continue
            if dt > t:
                continue
            u = f"https://rbidocs.rbi.org.in/rdocs/content/docs/SIBC{dt:%d%m%Y}E.xlsx"
            if u in have:
                found.append(u); break
            try:
                r = h.s.head(u, timeout=20)
            except Exception:  # noqa: BLE001
                continue
            if r.status_code == 200 and int(r.headers.get("Content-Length", "100000")) > 5000:
                b = h.get(u, timeout=90).content
                if b[:2] != b"PK":
                    continue
                found.append(u)
                wb = openpyxl.load_workbook(io.BytesIO(b), data_only=True, read_only=True)
                sheets = [list(ws.iter_rows(values_only=True)) for ws in wb]
                s1 = parse_sibc_rows(sheets[0]) if sheets else {}
                data = {k: v for k, v in s1.items() if not k.startswith("2.")}  # Statement 1 re-uses 2.x codes for the MSME split
                data.update(parse_sibc_rows([r for sh in sheets[1:] for r in sh]) if len(sheets) > 1 else {})
                if not data:
                    break
                per = data.get("2", next(iter(data.values())))["as_of"]
                d = doc(con, "rbi_sibc", u, f"RBI Sectoral Deployment of Bank Credit, data to {per}", publication_date=dt.isoformat(), data_period=per, content=b)
                for code, v in data.items():
                    ind = sibc_industry(v["name"], code)
                    ent = "sibc_" + code
                    upsert(con, "sub_industries", dict(sub_industry_id=ent, industry_id=ind or "others", name=f"{v['name']} (RBI SIBC {code})", basis="RBI SIBC industry code"), "sub_industry_id")
                    obs(con, "rbi_sibc", "bank_credit_outstanding_inr_cr", "industry", ent, v["as_of"], v["outstanding_cr"], "INR crore", doc_id=d)
                    obs(con, "rbi_sibc", "bank_credit_yoy_pct", "industry", ent, v["as_of"], v["yoy_pct"], "%", doc_id=d)
                    obs(con, "rbi_sibc", "bank_credit_fy_pct", "industry", ent, v["as_of"], v["fy_pct"], "%", doc_id=d)
                    upsert(con, "debt", dict(debt_id="sibc_" + hid(code, v["as_of"]), txn_id=None, industry_id=ind, borrower=v["name"], measure="outstanding_bank_credit",
                                             period=v["as_of"], amount_inr_cr=v["outstanding_cr"], yoy_pct=v["yoy_pct"],
                                             detail=f"RBI SIBC code {code}; YoY check {'ok' if v['check_ok'] else 'MISMATCH'}", doc_id=d, source_id="rbi_sibc"), "debt_id")
                    n += 1
                con.commit()
                break
    if not found:
        raise ValueError("no SIBC release found by URL pattern in the last %d months" % months_back)
    per = con.execute("SELECT max(period_end) FROM observations WHERE source_id='rbi_sibc'").fetchone()[0]
    return {"rows_in": len(found), "rows_new": n, "period": per}


# ---------------------------------------------------------------- AMFI monthly
def job_amfi(con, months=36):
    h = Http()
    t = today(); n = 0; latest = None
    have = {r[0] for r in con.execute("SELECT url FROM source_documents WHERE source_id='amfi_monthly'")}
    for k in range(1, months + 1):
        y, m = t.year, t.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        u = f"https://portal.amfiindia.com/spages/am{MON3[m - 1]}{y}repo.xls"
        if u in have and k > 2:
            continue
        try:
            b = h.get(u, tries=1, timeout=60).content
            df = pd.read_excel(io.BytesIO(b), header=None, sheet_name=0)
        except Exception:  # noqa: BLE001
            continue
        hdr_row = next((i for i in range(min(10, len(df))) if any("Net Inflow" in str(x) for x in df.iloc[i])), None)
        if hdr_row is None:
            continue
        cols = [str(x) for x in df.iloc[hdr_row]]
        ci = next(i for i, c in enumerate(cols) if "Net Inflow" in c)
        ai = next((i for i, c in enumerate(cols) if c.startswith("Net Assets Under Management as on")), None)
        per = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        d = doc(con, "amfi_monthly", u, f"AMFI monthly report {MON3[m-1].title()} {y}", data_period=per.isoformat(), content=b)
        section = ""
        for i in range(hdr_row + 1, len(df)):
            sr, name = str(df.iloc[i, 0]).strip(), str(df.iloc[i, 1]).strip()
            if name == "nan":
                continue
            v = num(df.iloc[i, ci])
            if re.match(r"^(I|II|III|IV|V|VI|VII|VIII)$", sr) and v is None:
                section = name; continue
            if v is None:
                continue
            if name.lower().startswith(("sub total", "total")) or sr.lower().startswith(("sub total", "total")):
                continue
            if "grand total" in (name + sr).lower():
                obs(con, "amfi_monthly", "mf_net_inflow_inr_cr", "investor_group", "amfi_grand_total", per.isoformat(), v, "INR crore", period_start=per.replace(day=1).isoformat(), doc_id=d)
                continue
            ent = "amfi_" + slug(section)[:30] + "__" + slug(name)[:50]
            obs(con, "amfi_monthly", "mf_net_inflow_inr_cr", "investor_group", ent, per.isoformat(), v, "INR crore", period_start=per.replace(day=1).isoformat(), doc_id=d)
            if ai is not None:
                obs(con, "amfi_monthly", "mf_aum_inr_cr", "investor_group", ent, per.isoformat(), num(df.iloc[i, ai]), "INR crore", doc_id=d)
            n += 1
        latest = max(latest or per, per)
        con.commit()
    if not latest and not have:
        raise ValueError("no AMFI monthly report parsed")
    return {"rows_in": months, "rows_new": n, "period": str(latest) if latest else None}


# ---------------------------------------------------------------- CRISIL rating actions
CRISIL_LIST = ("https://www.crisilratings.com/bin/crisil/listing/rating_sme_listing_service.json?cmd=RR&resourcePath="
               "/content/crisilratings/en/home/our-business/ratings/rating-rationale/jcr:content/wrapper_100_par/ratingresultlisting")
CRISIL_IND = [(r"textile|ginning|spinning|weaving|apparel|rmg|garment", "textiles"), (r"construction|roads|bridges|epc", "construction"),
              (r"real estate|residential|commercial property", "realty"), (r"steel|metal|aluminium|copper|mining|iron", "metals_mining"),
              (r"agri|rice|wheat|poultry|dairy|edible|food|sugar|tea|seeds|cotton", "agriculture_and_allied"), (r"trader|trading|dealer|distribut", "trade_wholesale_and_retail"),
              (r"pharma|hospital|health|medical", "healthcare"), (r"chemical|dyes|pigment|fertili|pesticide|plastic|polymer", "chemicals"),
              (r"auto|vehicle", "automobile_and_auto_components"), (r"power|solar|wind|energy", "power"), (r"hotel|resort|restaurant|education|travel", "consumer_services"),
              (r"engineering|capital goods|electrical|machinery|equipment", "capital_goods"), (r"cement|ceramic|tiles|building products", "construction_materials"),
              (r"nbfc|finance|microfinance|bank", "financial_services"), (r"software|it services|technology", "information_technology"),
              (r"logistics|transport|shipping|port|support services", "services"), (r"paper|wood|furniture|furnishing", "forest_materials"), (r"jewel|diamond|gem", "consumer_durables")]


def crisil_action(heading):
    """Copied from Lending Radar ratings_gj.classify_action (headline only)."""
    h = heading.split(":", 1)[-1].lower() if ":" in heading else heading.lower()
    inc = "not cooperating" in h
    if re.search(r"crisil d\b|crisil d[ /']|\bdefault", h): return "default", True, True
    if "downgraded" in h: return ("downgrade_inc" if inc else "downgrade"), True, True
    if "upgraded" in h: return "upgrade", True, False
    if "watch" in h and "negative" in h: return "watch_negative", True, True
    if "watch" in h and ("positive" in h or "developing" in h): return ("watch_positive" if "positive" in h else "watch_developing"), True, False
    if "outlook revised" in h:
        m = re.search(r"outlook revised to[^;]*?(negative|positive|stable)", h); dd = m.group(1) if m else ""
        return ("outlook_" + (dd or "changed")), True, dd == "negative"
    if inc and "continue" in h: return "inc_continues", False, False
    if inc and ("migrated" in h or "revised" in h): return "inc_new", False, False
    if "withdrawn" in h: return "withdrawn", False, False
    if "reaffirmed" in h: return "reaffirm", True, False
    if "assigned" in h: return "assigned", True, False
    return "other", False, False


def job_crisil(con, days=365):
    h = Http()
    last = con.execute("SELECT max(period) FROM debt WHERE source_id='crisil_ratings'").fetchone()[0]
    stop = (date.fromisoformat(last) - timedelta(days=7)) if last else today() - timedelta(days=days)
    s, n, rows_in = 0, 0, 0
    while True:
        dd = h.get(f"{CRISIL_LIST}&start={s}&limit={s + 1000}", timeout=120, pause=1.5).json().get("docs") or []
        if not dd:
            break
        for x in dd:
            rows_in += 1
            try:
                dt = datetime.strptime(x["ratingDate"], "%b %d, %Y").date()
            except Exception:  # noqa: BLE001
                continue
            act, counted, neg = crisil_action(x.get("heading", ""))
            if act == "other":
                continue
            iname = x.get("industryName") or ""
            ind = next((i for rx, i in CRISIL_IND if re.search(rx, iname, re.I)), None) if iname else None
            url = "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/" + (x.get("ratingFileName") or "")
            did = "crisil_" + hid(x.get("prId"), x.get("companyCode"))
            upsert(con, "source_documents", dict(doc_id=did, source_id="crisil_ratings", url=url, title=x.get("heading", "")[:200],
                                                 publication_date=dt.isoformat(), data_period=dt.isoformat(), retrieved_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                 content_hash=None, evidence_label="VERIFIED FACT"), "doc_id")
            ok = insert_new(con, "debt", dict(debt_id=did, txn_id=None, industry_id=ind, borrower=x.get("companyName"),
                                              measure="rating_action", period=dt.isoformat(), amount_inr_cr=None, yoy_pct=None,
                                              detail=json.dumps({"action": act, "counted": counted, "negative": neg, "crisil_industry": iname or None, "heading": x.get("heading", "")[:300]}),
                                              doc_id=did, source_id="crisil_ratings"), "debt_id")
            n += ok
        con.commit()
        if datetime.strptime(dd[-1]["ratingDate"], "%b %d, %Y").date() < stop:
            break
        s += 1000
    return {"rows_in": rows_in, "rows_new": n, "period": con.execute("SELECT max(period) FROM debt WHERE source_id='crisil_ratings'").fetchone()[0]}


# ---------------------------------------------------------------- PIB announcements
PIB_RSS = "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3"
PIB_IND = [(r"semiconductor|electronics|chip", "capital_goods", "Electronics & semiconductors"), (r"defen[cs]e", "capital_goods", "Defence"),
           (r"railway|rail |highway|road|port|airport|metro|corridor|logistics", "infrastructure_cross_sector", "Transport infrastructure"),
           (r"solar|renewable|wind|green hydrogen|nuclear|hydro|power|electricity|transmission|battery", "power", "Power & energy transition"),
           (r"pharma|health|medical|hospital", "healthcare", "Healthcare"), (r"fertili[sz]er|agricultur|farmer|food|crop|fisher|dairy", "agriculture_and_allied", "Agriculture & food"),
           (r"textile", "textiles", "Textiles"), (r"telecom|5g|broadband|digital", "telecommunication", "Telecom & digital"), (r"steel|mineral|mining|coal", "metals_mining", "Metals & mining"),
           (r"oil|gas|petroleum|refiner", "oil_gas_consumable_fuels", "Oil & gas"), (r"ship", "capital_goods", "Shipbuilding"), (r"housing|urban", "realty", "Housing & urban"),
           (r"\bAI\b|artificial intelligence|space", "information_technology", "AI / space / technology")]
AMT = re.compile(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh crore|crore|cr\b|लाख करोड़|करोड़)", re.I)
CAB = r"Cabinet approves|Cabinet approval|मंत्रिमंडल ने|मंत्रिमंडल की"


def job_pib(con):
    h = Http()
    x = h.get(PIB_RSS).content.decode("utf-8-sig", "ignore")
    items = re.findall(r"<item>(.*?)</item>", x, re.S)
    n = seen = 0
    for it in items:
        tm, lm = re.search(r"<title>(.*?)</title>", it, re.S), re.search(r"<link>(.*?)</link>", it, re.S)
        if not tm or not lm:
            continue
        title = H.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", tm.group(1))).strip(); link = lm.group(1).strip()
        if not re.search(CAB + r"|PLI|Production Linked|investment|outlay|crore|निवेश|करोड़|उत्पादन से जुड़ी", title, re.I):
            continue
        seen += 1
        if con.execute("SELECT 1 FROM source_documents WHERE url=?", (link,)).fetchone():
            continue
        try:
            body = h.get(link, timeout=60).text
        except Exception:  # noqa: BLE001
            continue
        txt = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", body)))
        m = re.search(r"Posted On:\s*(\d{1,2} [A-Za-z]{3} \d{4})", txt)
        m = m if m else None
        dt = datetime.strptime(m.group(1), "%d %b %Y").date().isoformat() if m else today().isoformat()
        start = txt.find(title[:40]) if title[:40] in txt else 0
        main = txt[start:start + 6000]
        amts = set()
        for v, u in AMT.findall(main):
            val = num(v)
            if val is not None:
                amts.add(round(val * (100000 if u.lower().startswith("lakh") or u.startswith("लाख") else 1), 2))
        cab = bool(re.search(CAB, title, re.I))
        amt = max(amts) if cab and amts else None
        blob = title + " " + main[:1500]
        ind = next(((i, lab) for rx, i, lab in PIB_IND if re.search(rx, blob, re.I)), (None, None))
        d = doc(con, "pib_cabinet", link, title[:250], publication_date=dt, data_period=dt, label="REPORTED ANNOUNCEMENT")
        tid = "pib_" + hid(link)
        ok = insert_new(con, "transactions", dict(txn_id=tid, txn_type="capital_commitment" if cab else "announced_investment", evidence_label="REPORTED ANNOUNCEMENT",
             txn_date=None, announcement_date=dt, investor_id=None, company_id=None, industry_id=ind[0], instrument="Government outlay / scheme", side="NA",
             quantity=None, price=None, amount=amt, currency="INR", amount_inr_cr=amt, related_txn_id=None,
             description=f"{title}. {('Largest Rs crore figure in the release: ' + format(amt, ',.0f') + ' crore (rule-extracted; read the release).') if amt else 'Amount not extracted.'} Theme: {ind[1] or 'unclassified'}",
             doc_id=d, source_id="pib_cabinet"), "txn_id")
        if ok and cab:
            upsert(con, "commitments", dict(commitment_id="pibc_" + hid(link), txn_id=tid, scope=f"Cabinet approval: {title[:200]}", industry_id=ind[0], period=dt,
                                            amount_inr_cr=amt, evidence_label="REPORTED ANNOUNCEMENT", doc_id=d), "commitment_id")
        n += ok
    con.commit()
    return {"rows_in": len(items), "rows_new": n, "period": today().isoformat(), "warn": None if items else "RSS returned no items"}


# ---------------------------------------------------------------- World Bank
WB = {"BX.KLT.DINV.CD.WD": ("FDI net inflows", "current US$"), "NE.GDI.TOTL.ZS": ("Gross capital formation", "% of GDP"),
      "NY.GDP.MKTP.KD.ZG": ("GDP growth", "% real"), "SP.POP.1564.TO.ZS": ("Working-age population (15-64)", "% of population"),
      "SP.POP.65UP.TO.ZS": ("Population aged 65+", "% of population"), "SP.URB.TOTL.IN.ZS": ("Urban population", "% of population"),
      "EG.FEC.RNEW.ZS": ("Renewable energy consumption", "% of final energy"), "GB.XPD.RSDV.GD.ZS": ("R&D expenditure", "% of GDP"),
      "TX.VAL.TECH.MF.ZS": ("High-technology exports", "% of manufactured exports"), "IT.NET.USER.ZS": ("Internet users", "% of population"),
      "NV.IND.MANF.ZS": ("Manufacturing value added", "% of GDP"), "FS.AST.PRVT.GD.ZS": ("Domestic credit to private sector", "% of GDP"),
      "SP.DYN.TFRT.IN": ("Fertility rate", "births per woman"), "ER.H2O.FWST.ZS": ("Freshwater withdrawal (water stress)", "% of available"),
      "SP.POP.TOTL": ("Population", "people"), "NY.GDP.PCAP.CD": ("GDP per capita", "current US$")}
WB_COUNTRIES = ["IND", "CHN", "VNM", "IDN", "MEX", "WLD"]
WB_COMPARE = ("BX.KLT.DINV.CD.WD", "NV.IND.MANF.ZS", "NE.GDI.TOTL.ZS", "SP.POP.65UP.TO.ZS", "SP.POP.1564.TO.ZS", "GB.XPD.RSDV.GD.ZS")


def job_worldbank(con):
    h = Http(); n = 0; latest = None
    for ind, (lab, unit) in WB.items():
        for c in WB_COUNTRIES:
            if c != "IND" and ind not in WB_COMPARE:
                continue
            u = f"https://api.worldbank.org/v2/country/{c}/indicator/{ind}?format=json&per_page=80&date=2000:2026"
            try:
                j = h.get(u, pause=0.3).json()
            except Exception:  # noqa: BLE001
                continue
            if len(j) < 2 or not j[1]:
                continue
            d = doc(con, "worldbank", u.replace("format=json&", ""), f"World Bank WDI {ind} {c}", publication_date=j[0].get("lastupdated"), data_period="2000-2026")
            for r in j[1]:
                if r.get("value") is None:
                    continue
                obs(con, "worldbank", "wb_" + ind, "country", c, f"{r['date']}-12-31", float(r["value"]), unit, doc_id=d)
                n += 1
                latest = max(latest or r["date"], r["date"])
    con.commit()
    if not n:
        raise ValueError("no World Bank data")
    return {"rows_in": len(WB), "rows_new": n, "period": latest}


# ---------------------------------------------------------------- FRED
FRED = {"DFF": ("US Fed funds effective rate", "%"), "DGS10": ("US 10-year Treasury yield", "%"), "DTWEXBGS": ("US dollar broad index", "index"),
        "DCOILBRENTEU": ("Brent crude", "US$/bbl"), "DEXINUS": ("INR per US$", "INR"), "DFII10": ("US 10-year real yield (TIPS)", "%")}


def job_fred(con):
    import subprocess
    n = 0; latest = None; fails = []
    for sid, (lab, unit) in FRED.items():
        u = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2010-01-01"
        txt = ""
        for _ in range(2):
            try:
                txt = subprocess.run(["curl", "-s", "-m", "90", "-A", "Mozilla/5.0", u], capture_output=True, text=True, timeout=100).stdout
            except Exception:  # noqa: BLE001
                txt = ""
            if txt.count("\n") > 10:
                break
        lines = txt.strip().splitlines()[1:]
        rows = [(a, num(b)) for a, b in (l.split(",")[:2] for l in lines if "," in l) if num(b) is not None]
        if len(rows) < 10:
            fails.append(sid); continue
        d = doc(con, "fred", f"https://fred.stlouisfed.org/series/{sid}", f"FRED {sid}: {lab}", data_period="2010-")
        keep = {}
        for a, v in rows:
            keep[a[:7]] = (a, v)  # month-end values
        for a, v in keep.values():
            obs(con, "fred", "fred_" + sid, "market", "global", a, v, unit, doc_id=d); n += 1
        latest = max(latest or rows[-1][0], rows[-1][0])
    con.commit()
    if not n:
        raise ValueError("FRED unreachable")
    return {"rows_in": len(FRED), "rows_new": n, "period": latest, "warn": ("failed: " + ",".join(fails)) if fails else None}


# ---------------------------------------------------------------- NSE sector index P/E
SECTOR_INDICES = {"NIFTY 50": None, "NIFTY 500": None, "NIFTY BANK": "financial_services", "NIFTY FINANCIAL SERVICES": "financial_services",
                  "NIFTY IT": "information_technology", "NIFTY PHARMA": "healthcare", "NIFTY HEALTHCARE INDEX": "healthcare", "NIFTY AUTO": "automobile_and_auto_components",
                  "NIFTY FMCG": "fast_moving_consumer_goods", "NIFTY METAL": "metals_mining", "NIFTY REALTY": "realty", "NIFTY ENERGY": "power",
                  "NIFTY OIL & GAS": "oil_gas_consumable_fuels", "NIFTY INFRASTRUCTURE": "construction", "NIFTY MEDIA": "media_entertainment_publication",
                  "NIFTY CONSUMER DURABLES": "consumer_durables", "NIFTY PSU BANK": "financial_services", "NIFTY CHEMICALS": "chemicals",
                  "NIFTY CAPITAL MARKETS": "financial_services", "NIFTY INDIA DEFENCE": "capital_goods"}
NI = "https://www.niftyindices.com/BackPage/getpepbHistoricaldataDBtoString"


def job_sector_pe(con):
    h = Http(); n = 0; latest = None; fails = []
    for name, ind in SECTOR_INDICES.items():
        ent = "idx_" + slug(name)
        last = con.execute("SELECT max(period_end) FROM observations WHERE metric='index_pe' AND entity_id=?", (ent,)).fetchone()[0]
        s = date.fromisoformat(last) - timedelta(days=20) if last else date(2011, 1, 1)
        got = 0
        while s <= today():
            e = min(s + timedelta(days=364), today())
            body = json.dumps({"cinfo": "{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}" % (name, s.strftime("%m/%d/%Y"), e.strftime("%m/%d/%Y"), name)})
            rows = []
            try:
                r = h.s.post(NI, data=body, headers={"Content-Type": "application/json; charset=utf-8", "Referer": "https://www.niftyindices.com/reports/historical-data",
                                                     "X-Requested-With": "XMLHttpRequest"}, timeout=60)
                rows = json.loads(r.json()["d"])
            except Exception:  # noqa: BLE001
                pass
            d = None
            for x in rows:
                try:
                    dt = datetime.strptime(x["DATE"].strip(), "%d %b %Y").date().isoformat()
                except Exception:  # noqa: BLE001
                    continue
                d = d or doc(con, "nse_sector_pe", "https://www.niftyindices.com/reports/historical-data", f"{name} P/E, P/B history", data_period=f"{s}..{e}")
                obs(con, "nse_sector_pe", "index_pe", "industry", ent, dt, num(x.get("pe")), "x", doc_id=d)
                got += 1
                latest = max(latest or dt, dt)
            s = e + timedelta(days=1)
        if not got and not last:
            fails.append(name)
        n += got
        con.commit()
    if not n and not latest:
        raise ValueError("no P/E rows")
    return {"rows_in": len(SECTOR_INDICES), "rows_new": n, "period": latest, "warn": ("no data for: " + ", ".join(fails)) if fails else None}


# ---------------------------------------------------------------- DPIIT
def job_dpiit(con):
    r = Http().s.get("https://dpiit.gov.in/publications/fdi-statistics", timeout=40)
    if "Access Denied" in r.text or r.status_code != 200 or ".pdf" not in r.text:
        con.execute("UPDATE sources SET status='blocked' WHERE source_id='dpiit_fdi'")
        con.commit()
        raise RuntimeError("DPIIT FDI page is rendered in the browser and dpiit.gov.in returns 'Access Denied' to automated/headless requests; factsheet PDF links not reachable. Not bypassed.")
    return {}


JOBS = {"sebi_aif": job_sebi_aif, "rbi_sibc": job_rbi_sibc, "amfi_monthly": job_amfi, "crisil_ratings": job_crisil, "pib_cabinet": job_pib,
        "worldbank": job_worldbank, "fred": job_fred, "nse_sector_pe": job_sector_pe, "dpiit_fdi": job_dpiit}

if __name__ == "__main__":
    for k in (sys.argv[1:] or JOBS):
        run(k, JOBS[k])
