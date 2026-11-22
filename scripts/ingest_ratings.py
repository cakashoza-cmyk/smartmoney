"""Rating actions from ICRA, CARE (CareEdge) and India Ratings (Ind-Ra), alongside CRISIL (ingest_official.job_crisil).
Official agency websites only, through the same public pages and files a visitor's browser loads (no login, no captcha, no
bot-protected endpoints). Action words are classified from each agency's own headline/table with rules adapted from
Lending Radar `ratings_gj.classify_action` (CRISIL). Sector comes from the agency's own industry field where it gives one
(CARE 'Industry classification', Ind-Ra 'industryName'); for ICRA it is keyword-classified from the 'About the company'
paragraph and marked as such. Rows go to `debt` (measure='rating_action') like CRISIL."""
import json, re, subprocess, tempfile, os
from datetime import date, datetime, timedelta
from common import Http, upsert, insert_new, hid, run
from ingest_official import CRISIL_IND

UA_NOTE = "public listing"
EXTRA_IND = [(r"road|toll|annuity|highway|transmission|airport|port\b|infra", "construction"), (r"housing finance|hfc|nbfc|microfin|bank|financ|lending|insurance", "financial_services"),
             (r"renewable|solar|wind|thermal|hydro|power|electric", "power"), (r"hospital|pharma|health|diagnost", "healthcare"),
             (r"telecom|tower", "telecommunication"), (r"oil|gas|petro|refin|lpg|cng", "oil_gas_consumable_fuels"), (r"securiti[sz]ation|ptc|trust\b", None)]
SECTOR_NAMES = {  # CARE 'Sector' column (NSE/AMFI basic industry tree) -> dashboard industry id
    "capital goods": "capital_goods", "financial services": "financial_services", "construction": "construction", "construction materials": "construction_materials",
    "realty": "realty", "chemicals": "chemicals", "textiles": "textiles", "power": "power", "healthcare": "healthcare", "metals & mining": "metals_mining",
    "fast moving consumer goods": "fast_moving_consumer_goods", "consumer durables": "consumer_durables", "consumer services": "consumer_services",
    "automobile and auto components": "automobile_and_auto_components", "information technology": "information_technology", "telecommunication": "telecommunication",
    "oil, gas & consumable fuels": "oil_gas_consumable_fuels", "services": "services", "forest materials": "forest_materials", "utilities": "utilities",
    "media, entertainment & publication": "media_entertainment_publication", "diversified": "diversified", "agricultural food & other products": "agriculture_and_allied",
}
SCALE = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "C+", "C", "C-", "D"]
ST_SCALE = ["A1+", "A1", "A2+", "A2", "A3+", "A3", "A4+", "A4", "D"]


def map_industry(text):
    if not text:
        return None
    t = text.lower()
    for rx, ind in EXTRA_IND + CRISIL_IND:
        if re.search(rx, t):
            return ind
    return None


def classify(heading):
    """Headline -> (action, counted, negative). Same categories as CRISIL's crisil_action so the Credit page can sum agencies' actions consistently."""
    h = heading.lower().replace("’", "'")
    h = re.sub(r"\bupgrades\b", "upgraded", h); h = re.sub(r"\bdowngrades\b", "downgraded", h); h = re.sub(r"\baffirms\b", "reaffirmed", h)
    h = re.sub(r"\bassigns\b|\brates\b", "assigned", h); h = re.sub(r"\bwithdraws\b", "withdrawn", h)
    inc = bool(re.search(r"not cooperating|non-cooperating|noncooperating|issuer not co-?operating", h))
    if re.search(r"(\[icra\]|care|ind|crisil) ?d\b|'ind d'|\bdefault", h): return "default", True, True
    if "downgraded" in h: return ("downgrade_inc" if inc else "downgrade"), True, True
    if "upgraded" in h: return "upgrade", True, False
    if "off rating watch" in h: return ("watch_resolved"), False, False
    if "watch" in h and "negative" in h: return "watch_negative", True, True
    if "watch" in h and ("positive" in h or "developing" in h): return ("watch_positive" if "positive" in h else "watch_developing"), True, False
    if re.search(r"outlook (revised|on .{0,120}? to)|revises outlook", h):
        m = re.search(r"(?:outlook revised to|to)\s*'?(negative|positive|stable)", h); dd = m.group(1) if m else ""
        return ("outlook_" + (dd or "changed")), True, dd == "negative"
    if inc and re.search(r"continue|maintain|remain", h): return "inc_continues", False, False
    if inc: return "inc_new", False, False
    if "withdrawn" in h: return "withdrawn", False, False
    if "reaffirmed" in h: return "reaffirm", True, False
    if "assigned" in h or "provisional rating to final" in h: return "assigned", True, False
    return "other", False, False


def _store(con, sid, did, url, title, dt, borrower, ind, detail):
    upsert(con, "source_documents", dict(doc_id=did, source_id=sid, url=url, title=title[:200], publication_date=dt, data_period=dt,
                                         retrieved_at=datetime.now().strftime("%Y-%m-%d %H:%M"), content_hash=None, evidence_label="VERIFIED FACT"), "doc_id")
    return insert_new(con, "debt", dict(debt_id=did, txn_id=None, industry_id=ind, borrower=borrower, measure="rating_action", period=dt, amount_inr_cr=None,
                                        yoy_pct=None, detail=json.dumps(detail), doc_id=did, source_id=sid), "debt_id")


def _pdf_text(content, pages=None):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(content); fn = f.name
    try:
        args = ["pdftotext"] + (["-l", str(pages)] if pages else []) + [fn, "-"]
        return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    finally:
        os.unlink(fn)


# ---------------------------------------------------------------- India Ratings (Ind-Ra): public rating-action listing used by indiaratings.co.in/raclisting/rac/all
INDRA_LIST = "https://www.indiaratings.co.in/pressReleases/GetListing_RAC?type=rac&year={y}&pageNo={p}&searchText="


def job_indra(con, days=365, max_pages=400):
    h = Http(); sid = "indra_ratings"
    last = con.execute("SELECT max(period) FROM debt WHERE source_id=?", (sid,)).fetchone()[0]
    stop = (date.fromisoformat(last) - timedelta(days=10)).isoformat() if last else (date.today() - timedelta(days=days)).isoformat()
    n = rows_in = pages = 0
    for y in range(date.today().year, int(stop[:4]) - 1, -1):
        p = 1
        while pages < max_pages:
            dd = h.get(INDRA_LIST.format(y=y, p=p), headers={"Referer": "https://www.indiaratings.co.in/raclisting/rac/all"}, timeout=60, pause=1.0).json() or []
            pages += 1
            if not dd:
                break
            for x in dd:
                dt = (x.get("effectiveDate") or "")[:10]
                if not dt or dt < stop:
                    continue
                rows_in += 1
                title = x.get("pressReleaseTitle") or ""
                act, counted, neg = classify(title)
                if act == "other":
                    continue
                url = f"https://www.indiaratings.co.in/pressrelease/{x.get('urlKey')}"
                iname = x.get("industryName")
                n += _store(con, sid, "indra_" + str(x.get("pressReleaseID")), url, title, dt, x.get("issuerName"), map_industry(iname),
                            {"action": act, "counted": counted, "negative": neg, "agency_industry": iname, "industry_basis": "agency industry field", "heading": title[:300]})
            con.commit()
            if min((x.get("effectiveDate") or "9")[:10] for x in dd) < stop:
                break
            p += 1
    return {"rows_in": rows_in, "rows_new": n, "period": con.execute("SELECT max(period) FROM debt WHERE source_id=?", (sid,)).fetchone()[0]}


# ---------------------------------------------------------------- CARE (CareEdge): the home page's latest-press-release feed + each press-release PDF
CARE_FEED = "https://www.careratings.com/rrcompany?companyName=IDBI&YearID=2022&fdate=&tdate="  # exactly the call the home page makes; returns the latest ~1,000 releases
CARE_PDF = "https://www.careratings.com/upload/CompanyFiles/PR/"
_CR = r"CARE\s+(AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|C[+-]?|D|A1\+?|A2\+?|A3\+?|A4\+?)"


def _rank(r):
    r = r.replace(" ", "")
    return ("st", ST_SCALE.index(r)) if r in ST_SCALE else ("lt", SCALE.index(r)) if r in SCALE else (None, None)


def care_action(text):
    """Action from the 'Rating Action' column of the first page table (text before 'Details of instruments')."""
    top = text.split("Details of instruments")[0][:4000]
    t = re.sub(r"\s+", " ", top)
    inc = "ISSUER NOT COOPERATING" in t.upper()
    moved = re.search(r"(?i)downgraded from|revised from|upgraded from|assigned|reaffirmed", t)
    if re.search(r"CARE\s+D\b", t) and moved: return "default", True, True
    if re.search(r"(?i)downgraded from", t): return ("downgrade_inc" if inc else "downgrade"), True, True
    if re.search(r"(?i)upgraded from", t): return "upgrade", True, False
    for m in re.finditer(r"(?i)revised from\s+" + _CR, t):
        prev = re.findall(_CR, t[:m.start()])
        if prev:
            a, b = _rank(prev[-1]), _rank(m.group(1))
            if a[0] and a[0] == b[0] and a[1] != b[1]:
                return ("upgrade", True, False) if a[1] < b[1] else ("downgrade", True, True)
    if re.search(r"(?i)rating watch with negative", t): return "watch_negative", True, True
    if re.search(r"(?i)rating watch with (positive|developing)", t): return ("watch_positive" if re.search("(?i)watch with positive", t) else "watch_developing"), True, False
    if re.search(r"(?i)outlook revised|revised from .{0,40}(stable|negative|positive)", t):
        m = re.search(r"(?i);\s*(Negative|Positive)\b", t)
        return ("outlook_" + (m.group(1).lower() if m else "changed")), True, bool(m and m.group(1).lower() == "negative")
    if inc and re.search(r"(?i)continues to remain", t): return "inc_continues", False, False
    if inc: return "inc_new", False, False
    if re.search(r"(?i)\bwithdrawn\b", t): return "withdrawn", False, False
    if re.search(r"(?i)\breaffirmed\b", t): return "reaffirm", True, False
    if re.search(r"(?i)\bassigned\b", t): return "assigned", True, False
    return "other", False, False


def care_sector(text):
    m = re.search(r"Industry classification(.{0,600})", text, re.S)
    if not m:
        return None, None
    blk = [l.strip() for l in m.group(1).splitlines() if l.strip()]
    blk = [l for l in blk if l.lower() not in ("macroeconomic indicator", "sector", "industry", "basic industry")]
    for l in blk[:6]:
        if l.lower() in SECTOR_NAMES:
            return SECTOR_NAMES[l.lower()], l
    joined = " / ".join(blk[:4])
    return map_industry(joined), joined[:120]


def care_sector_kw(text):
    """Fallback when the release has no classification table (most 'issuer not cooperating' notes): keywords in 'About the company'."""
    m = re.search(r"(?i)about the (?:company|firm|entity)[^\n]*\n(.{0,600})", text, re.S)
    return map_industry(re.sub(r"\s+", " ", m.group(1))[:400]) if m else None


def job_care(con, max_pdfs=450):
    h = Http(); sid = "care_ratings"
    seen = {r[0] for r in con.execute("SELECT doc_id FROM source_documents WHERE source_id=?", (sid,))}
    items = h.get(CARE_FEED, headers={"Referer": "https://www.careratings.com/"}, timeout=90).json().get("data") or []
    items = [x for x in items if x.get("FileType") == "PR" and x.get("FileURL")]
    n = fetched = 0; errs = 0
    for x in items:
        did = "care_" + hid(x["FileURL"])
        if did in seen:
            continue
        if fetched >= max_pdfs:
            break
        url = CARE_PDF + x["FileURL"]
        try:
            txt = _pdf_text(h.get(url, timeout=90, pause=0.6).content, pages=None)
        except Exception:  # noqa: BLE001
            errs += 1; continue
        fetched += 1
        act, counted, neg = care_action(txt)
        ind, lab = care_sector(txt)
        basis = "CARE industry classification" if lab else None
        if not ind and not lab:
            ind = care_sector_kw(txt); basis = "keyword-classified from 'About the company'" if ind else None
        dt = (x.get("PublishedDate") or "")[:10]
        n += _store(con, sid, did, url, f"{x.get('CompanyName')}: CARE press release ({act})", dt, x.get("CompanyName"), ind,
                    {"action": act, "counted": counted, "negative": neg, "agency_industry": lab, "industry_basis": basis,
                     "heading": f"{x.get('CompanyName')} - {act}"})
        con.commit()
    con.commit()
    if not items:
        raise ValueError("CARE latest press-release feed returned no items")
    return {"rows_in": len(items), "rows_new": n, "period": con.execute("SELECT max(period) FROM debt WHERE source_id=?", (sid,)).fetchone()[0],
            "warn": f"{errs} PDFs failed" if errs else None}


# ---------------------------------------------------------------- ICRA: public rationale pages (headline) + rationale PDF for directional actions (date, sector)
ICRA = "https://www.icra.in"
ICRA_ABOUT = re.compile(r"About the company\s*(.{0,700})", re.S)


def job_icra(con, cap=450):
    h = Http(); sid = "icra_ratings"
    lst = h.get(ICRA + "/Rating/AllRatingRationales", timeout=60).text + h.get(ICRA + "/", timeout=60).text
    ids = [int(i) for i in re.findall(r"ShowRationaleReport\?[Ii]d=(\d+)", lst)]
    if not ids:
        raise ValueError("no rationale links on ICRA's rationale page")
    top = max(ids)
    done = con.execute("SELECT max(CAST(substr(doc_id,6) AS INTEGER)) FROM source_documents WHERE source_id=? AND doc_id LIKE 'icra_%'", (sid,)).fetchone()[0]
    lo = max((done or 0) + 1, top - cap)
    n = rows_in = 0; dir_ = 0
    for i in range(top, lo - 1, -1):
        try:
            page = h.get(f"{ICRA}/Rationale/ShowRationaleReport?Id={i}", timeout=45, pause=0.5, tries=2).text
        except Exception:  # noqa: BLE001
            continue
        m = re.search(r"<title>\s*(.*?)\s*-\s*ICRA", page, re.S)
        if not m or "Error" in m.group(1)[:8]:
            continue
        title = re.sub(r"\s+", " ", m.group(1)).replace("&amp;", "&").replace("&#39;", "'")
        rows_in += 1
        act, counted, neg = classify(title)
        if act in ("other", "reaffirm", "assigned", "withdrawn", "inc_continues"):
            continue  # non-directional: not stored (ICRA's page does not show the date without the PDF)
        pdf = f"{ICRA}/Rating/GetRationalReportFilePdf?Id={i}"
        try:
            txt = _pdf_text(h.get(pdf, timeout=90, pause=0.5).content, pages=8)
        except Exception:  # noqa: BLE001
            continue
        dm = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})", txt)
        if not dm:
            continue
        dt = datetime.strptime(f"{dm.group(1)} {dm.group(2)} {dm.group(3)}", "%B %d %Y").date().isoformat()
        am = ICRA_ABOUT.search(txt)
        about = re.sub(r"\s+", " ", am.group(1))[:400] if am else ""
        ind = map_industry(about)
        n += _store(con, sid, f"icra_{i}", f"{ICRA}/Rationale/ShowRationaleReport?Id={i}", title, dt, title.split(":")[0].strip(), ind,
                    {"action": act, "counted": counted, "negative": neg, "agency_industry": None, "industry_basis": "keyword-classified from ICRA 'About the company'" if ind else None,
                     "heading": title[:300]})
        dir_ += 1
        con.commit()
    con.commit()
    return {"rows_in": rows_in, "rows_new": n, "period": con.execute("SELECT max(period) FROM debt WHERE source_id=?", (sid,)).fetchone()[0],
            "warn": f"walked rationale ids {lo}-{top}; directional actions only"}


if __name__ == "__main__":
    import sys
    from common import connect
    for a in sys.argv[1:]:
        run(a + "_ratings", {"icra": job_icra, "care": job_care, "indra": job_indra}[a])
