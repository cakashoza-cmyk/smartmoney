"""AMC monthly scheme portfolio disclosures (SEBI-mandated, published on each AMC's own website).
Generic parser: every sheet = one scheme; the header row holds ISIN / quantity / market value / % to net assets.
Only listed Indian equity rows (ISIN INE.......01...) are kept. Rows go into `ownership` with holder_category='mf_portfolio'
(holder = scheme, investor -> AMC parent group). Index funds/ETFs are flagged passive, arbitrage funds flagged arbitrage.
Each AMC is its own registry source (amc_<id>) so blocked sites show as blocked, never as zero holdings."""
from __future__ import annotations
import io, re, zipfile, csv
from datetime import date, datetime
import pandas as pd
from common import Http, connect, doc, hid, upsert, run, num, slug
from investors import resolve

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
EQUITY_L = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"


def month_end(y, m):
    import calendar
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def date_from_text(t):
    d = _date_from_text(t)
    if d and not ("2000-01-01" <= d <= date.today().isoformat()):
        return None  # never accept a future or implausible period
    return d


def _date_from_text(t):
    t = t.lower()
    m = re.search(r"(\d{1,2})[\s_-]*([a-z]{3})[a-z]*[\s_,-]*(\d{2,4})", t) or None
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        if m.group(2)[:3] in MONTHS:
            return month_end(y, MONTHS[m.group(2)[:3]])
    m = re.search(r"([a-z]{3})[a-z]*[\s_,-]*(\d{1,2})(?:st|nd|rd|th)?[\s_,-]+(\d{4})", t)
    if m and m.group(1)[:3] in MONTHS:
        return month_end(int(m.group(3)), MONTHS[m.group(1)[:3]])
    m = re.search(r"([a-z]{3})[a-z]*[\s_,-]*(\d{4})", t)
    if m and m.group(1)[:3] in MONTHS:
        return month_end(int(m.group(2)), MONTHS[m.group(1)[:3]])
    m = re.search(r"([a-z]{3})[a-z]*[\s_-]+(\d{2})(?:\D|$)", t)
    if m and m.group(1)[:3] in MONTHS:
        return month_end(2000 + int(m.group(2)), MONTHS[m.group(1)[:3]])
    return None


def scheme_flag(name):
    n = name.lower()
    if "arbitrage" in n:
        return "arbitrage"
    if re.search(r"\b(etf|index|bees|nifty|sensex)\b", n) and "fund of fund" not in n:
        return "passive"
    return "active"


def _find(cols, *keys, exclude=()):
    for i, c in enumerate(cols):
        if all(k in c for k in keys) and not any(e in c for e in exclude):
            return i
    return None


def parse_sheet(df):
    """Return (scheme_name, as_of_text, rows[]) or None. rows: isin, name, industry, qty, value_cr, pct_nav."""
    if df.shape[0] < 5 or df.shape[1] < 4:
        return None
    hdr = None
    for i in range(min(15, len(df))):
        vals = [str(v).strip().lower() for v in df.iloc[i].tolist()]
        if any(v == "isin" or v.startswith("isin") for v in vals):
            hdr = i; break
    if hdr is None:
        return None
    cols = [re.sub(r"\s+", " ", str(v).strip().lower()) for v in df.iloc[hdr].tolist()]
    ci = _find(cols, "isin")
    cn = _find(cols, "instrument") or _find(cols, "name", exclude=("isin",)) or _find(cols, "security") or _find(cols, "company")
    cind = _find(cols, "industry") if _find(cols, "industry") is not None else _find(cols, "rating")
    cq = _find(cols, "quantity") if _find(cols, "quantity") is not None else _find(cols, "qty")
    cv = _find(cols, "market") if _find(cols, "market") is not None else _find(cols, "value")
    cp = _find(cols, "%") if _find(cols, "%") is not None else (_find(cols, "net assets") if _find(cols, "net assets") is not None else _find(cols, "nav"))
    if None in (ci, cq, cv):
        return None
    vh = cols[cv]
    unit = 0.01 if ("lakh" in vh or "lac" in vh) else (1.0 if "crore" in vh or "cr" in vh.split() else 0.01)
    top = " ".join(str(v) for r in range(hdr) for v in df.iloc[r].tolist() if isinstance(v, str))
    names = []
    for r in range(min(hdr, 5)):  # explicit "Scheme Name :" label wins
        vals = [str(v).strip() for v in df.iloc[r].tolist() if isinstance(v, str) and str(v).strip()]
        for i, v in enumerate(vals):
            if re.match(r"scheme\s*name\s*:?", v, re.I):
                rest = re.sub(r"^scheme\s*name\s*:?\s*", "", v, flags=re.I) or (vals[i + 1] if i + 1 < len(vals) else "")
                if rest:
                    names.append(rest)
    if not names:
        names = [str(v).strip() for r in range(min(hdr, 3)) for v in df.iloc[r].tolist() if isinstance(v, str) and len(str(v).strip()) > 6]
        names = [n for n in names if " " in n and not re.search(r"portfolio|statement|as on|^index$|back to|mutual fund$", n, re.I)]
    scheme = re.sub(r"\s*\(.*$", "", names[0]).strip() if names else None
    if not scheme:
        return None
    rows, pcts = [], []
    for r in range(hdr + 1, len(df)):
        v = df.iloc[r].tolist()
        isin = str(v[ci]).strip().upper()
        if not re.fullmatch(r"INE[A-Z0-9]{9}", isin) or isin[7:9] != "01":
            continue
        q, mv = num(v[cq]), num(v[cv])
        if not q or mv is None:
            continue
        p = num(v[cp]) if cp is not None else None
        pcts.append(p or 0)
        rows.append({"isin": isin, "name": str(v[cn]).strip() if cn is not None else None, "industry": str(v[cind]).strip() if cind is not None and isinstance(v[cind], str) else None,
                     "qty": q, "value_cr": mv * unit, "pct": p})
    if pcts and max(pcts) <= 1.5:  # fractions -> percent
        for x in rows:
            x["pct"] = x["pct"] * 100 if x["pct"] is not None else None
    return scheme, top, rows


def read_book(content, fname):
    books = []
    if fname.lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(content))
        for n in z.namelist():
            if n.lower().endswith((".xls", ".xlsx", ".xlsb")):
                books.append((n, z.read(n)))
    else:
        books.append((fname, content))
    out = []
    for n, b in books:
        eng = "pyxlsb" if n.lower().endswith(".xlsb") else None
        try:
            sheets = pd.read_excel(io.BytesIO(b), sheet_name=None, header=None, engine=eng)
        except Exception as e:  # noqa: BLE001
            print("unreadable", n, e); continue
        for sn, df in sheets.items():
            r = parse_sheet(df)
            if r:
                out.append((n, sn) + r)
    return out


# ------------------------------------------------------------------ AMC listers: return [(period_end, url)] of month-end files
def _links(html, base):
    return [(u if u.startswith("http") else base + u) for u in re.findall(r'href="([^"?]+\.(?:xlsx?|zip|xlsb))(?:\?[^"]*)?"', html, re.I)]


def list_nippon(h):
    base = "https://mf.nipponindiaim.com"
    t = h.get(base + "/investor-service/downloads/factsheet-portfolio-and-other-disclosures").text
    return [(date_from_text(u.split("PORTFOLIO-")[-1]), u) for u in _links(t, base) if "MONTHLY-PORTFOLIO" in u.upper()]


def list_dsp(h):
    t = h.get("https://www.dspim.com/mandatory-disclosures/portfolio-disclosures").text
    return [(date_from_text(u.rsplit("/", 1)[-1]), u) for u in _links(t, "https://www.dspim.com") if re.search(r"monthend-portfolio", u, re.I)]


def list_ppfas(h):
    base = "https://amc.ppfas.com"
    t = h.get(base + "/downloads/portfolio-disclosure/").text
    return [(date_from_text(u.rsplit("/", 1)[-1]), u) for u in _links(t, base) if re.search(r"monthly[_-]portfolio", u, re.I)]


def _ordinal(d):
    return f"{d}{'th' if 10 <= d % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')}"


def list_sbi(h, months=7):
    """SBI MF's portfolio page builds its links in JavaScript (token-protected XHR). The files themselves are static, public and
    follow one naming pattern (verified against the rendered page on 2026-11-22), so we probe the last few month-ends by HEAD."""
    out, d = [], date.today().replace(day=1)
    for _ in range(months):
        d = date.fromordinal(d.toordinal() - 1)  # last day of previous month
        mname = d.strftime("%B").lower()
        u = f"https://www.sbimf.com/docs/default-source/scheme-portfolios/all-schemes-monthly-portfolio---as-on-{_ordinal(d.day)}-{mname}-{d.year}.xlsx"
        try:
            r = h.s.head(u, timeout=25, allow_redirects=True)
            if r.status_code == 200:
                out.append((d.isoformat(), u))
        except Exception:  # noqa: BLE001
            pass
        d = d.replace(day=1)
    return out


def render_html(url, wait_ms=7000):
    """Public page whose links are written by its own script: load it once in headless Chrome (as a visitor's browser would)."""
    import os
    from playwright.sync_api import sync_playwright
    exe = os.environ.get("CHROME_PATH") or next((p for p in ("/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium") if os.path.exists(p)), None)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True) if exe else p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(url, timeout=90000); pg.wait_for_timeout(wait_ms)
        html = pg.content(); b.close()
    return html


def list_absl(h):
    base = "https://mutualfund.adityabirlacapital.com"
    t = render_html(base + "/forms-and-downloads/portfolio")
    out = []
    for u in _links(t, base):
        if "/monthly-portfolio/" not in u.lower():
            continue
        f = u.rsplit("/", 1)[-1].lower()
        m = re.search(r"(\d{2})(\d{2})(20\d{2})", f)  # 31102026_abslmf_...
        p = month_end(int(m.group(3)), int(m.group(2))) if m and 1 <= int(m.group(2)) <= 12 else date_from_text(f.replace("--", "-"))
        out.append((p, u))
    return out


MULTI_FILE = {"ppfas"}  # AMCs that publish one file per scheme each month

AMCS = {  # amc_id: (display name, parent group id in registry.GROUPS, lister or None, page url, status note if not built/blocked)
    "nippon": ("Nippon India Mutual Fund", "nippon", list_nippon, "https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures", None),
    "dsp": ("DSP Mutual Fund", "dsp", list_dsp, "https://www.dspim.com/mandatory-disclosures/portfolio-disclosures", None),
    "sbi": ("SBI Mutual Fund", "sbi", list_sbi, "https://www.sbimf.com/portfolios", None),
    "absl": ("Aditya Birla Sun Life Mutual Fund", "aditya_birla", list_absl, "https://mutualfund.adityabirlacapital.com/forms-and-downloads/portfolio", None),
    "ppfas": ("PPFAS Mutual Fund", "ppfas", list_ppfas, "https://amc.ppfas.com/downloads/portfolio-disclosure/", None),
}


def ensure_companies(con, h, isins):
    """Map ISIN issuer prefix -> company; add non-Nifty-500 listed companies from NSE's official equity list."""
    known = {r[0][:9]: r[1] for r in con.execute("SELECT isin, company_id FROM companies WHERE isin IS NOT NULL")}
    missing = {i[:9] for i in isins} - set(known)
    if missing:
        try:
            r = h.get(EQUITY_L)
            d = doc(con, "nse_universe", EQUITY_L, "NSE list of equity securities", data_period="current", content=r.content)
            for x in csv.DictReader(io.StringIO(r.text)):
                x = {k.strip(): (v or "").strip() for k, v in x.items()}
                isin = x.get("ISIN NUMBER", "")
                if isin[:9] in missing:
                    cid = "NSE:" + x["SYMBOL"]
                    con.execute("INSERT OR IGNORE INTO companies (company_id, name, symbol, isin, listed, source_id) VALUES (?,?,?,?,1,'nse_universe')",
                                (cid, x["NAME OF COMPANY"], x["SYMBOL"], isin))
                    known[isin[:9]] = cid
        except Exception as e:  # noqa: BLE001
            print("EQUITY_L failed", e)
    return known


def ingest_file(con, h, amc_id, period, url, known=None):
    name, gid, *_ = AMCS[amc_id]
    sid = "amc_" + amc_id
    if con.execute("SELECT 1 FROM source_documents WHERE url=? AND source_id=?", (url, sid)).fetchone():
        return 0, 0
    r = h.get(url, timeout=180)
    parsed = read_book(r.content, url.rsplit("/", 1)[-1])
    as_of = period
    if not parsed:
        raise ValueError(f"no scheme sheets parsed in {url}")
    d = doc(con, sid, url, f"{name} monthly portfolio {as_of}", data_period=as_of, content=r.content)
    known = ensure_companies(con, h, [x["isin"] for p in parsed for x in p[4]])
    n = 0; schemes = 0
    for fn, sn, scheme, top, rows in parsed:
        if not rows:
            continue
        schemes += 1
        flag = scheme_flag(scheme)
        iid = "inv_" + slug(name + " " + scheme)[:90]
        upsert(con, "investors", dict(investor_id=iid, name=scheme, group_id=gid, category="mf_scheme", match_rule=f"AMC portfolio file of {name}"), "investor_id")
        agg = {}
        for x in rows:
            if x["isin"] not in agg:
                agg[x["isin"]] = dict(x)
            else:
                a = agg[x["isin"]]
                a["qty"] += x["qty"]; a["value_cr"] += x["value_cr"]; a["pct"] = (a["pct"] or 0) + (x["pct"] or 0)
        for isin, x in agg.items():
            cid = known.get(isin[:9])
            if not cid:
                cid = "ISIN:" + isin
                con.execute("INSERT OR IGNORE INTO companies (company_id, name, isin, listed, source_id) VALUES (?,?,?,1,?)", (cid, x["name"] or isin, isin, sid))
            upsert(con, "ownership", dict(ownership_id=hid("mfp", iid, isin, as_of), company_id=cid, period_end=as_of, holder_category="mf_portfolio", holder_name=scheme,
                                          investor_id=iid, pct=None, doc_id=d, quantity=x["qty"], value_inr_cr=round(x["value_cr"], 4),
                                          pct_of_nav=round(x["pct"], 4) if x["pct"] is not None else None, scheme_flag=flag), "ownership_id")
            if x["industry"]:  # the AMC's own (AMFI) industry label, used to place non-Nifty-500 companies in a sector
                con.execute("INSERT OR REPLACE INTO company_labels (company_id, source_id, label) VALUES (?,?,?)", (cid, "amc_industry", x["industry"][:80]))
            n += 1
    con.commit()
    return n, schemes


def make_job(amc_id, months=4):
    def job(con):
        h = Http()
        lister = AMCS[amc_id][2]
        files = sorted({(p, u) for p, u in lister(h) if p}, reverse=True)
        # one file per month (first listed), newest `months`
        periods = sorted({p for p, _ in files}, reverse=True)[:months]
        if amc_id in MULTI_FILE:
            pick = [(p, u) for p, u in files if p in periods]
        else:  # one file per month (first listed)
            seen, pick = set(), []
            for p, u in files:
                if p in periods and p not in seen:
                    seen.add(p); pick.append((p, u))
        if not pick:
            raise ValueError("no month-end portfolio files found on the AMC page")
        tot = sch = 0; latest = None; errs = []
        for p, u in pick:
            try:
                n, s = ingest_file(con, h, amc_id, p, u)
                tot += n; sch = max(sch, s)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{p}: {e}"[:160])
            latest = max(latest or p, p)
        have = con.execute("SELECT max(period_end) FROM ownership o JOIN investors i ON i.investor_id=o.investor_id WHERE o.holder_category='mf_portfolio' AND i.group_id=?",
                           (AMCS[amc_id][1],)).fetchone()[0]
        if not have:
            raise ValueError("; ".join(errs) or "nothing parsed")
        return {"rows_in": len(pick), "rows_new": tot, "period": have, "warn": "; ".join(errs) or None}
    return job


if __name__ == "__main__":
    import sys
    for a in (sys.argv[1:] or list(AMCS)):
        if AMCS[a][2]:
            run("amc_" + a, make_job(a))
