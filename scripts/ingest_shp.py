"""NSE quarterly shareholding patterns for the Nifty 500.
- master API: promoter/public % for ~6 years of quarters (cheap, 1 call per company)
- XBRL filing per quarter (latest N): holder-category % (MF, AIF, insurance, pension, banks, FPI cat I/II, FDI, govt...) and
  every named holder above 1% in non-promoter categories. Incremental: a (company, quarter) already parsed is skipped."""
import re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from common import Http, connect, upsert, doc, hid, run, num
from investors import resolve

QUARTERS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
CAT = {"ShareholdingOfPromoterAndPromoterGroup": "promoter", "PublicShareholding": "public", "MutualFundsOrUTI": "mf",
       "AlternativeInvestmentFunds": "aif", "Banks": "bank", "InsuranceCompanies": "insurance", "ProvidentFundsOrPensionFunds": "pension",
       "SovereignWealthFundsDomestic": "swf_domestic", "NBFCsRegisteredWithRBI": "nbfc", "OtherFinancialInstitutions": "other_fi",
       "InstitutionsDomestic": "dii_total", "ForeignDirectInvestment": "fdi", "InstitutionsForeignPortfolioInvestorCategoryOne": "fpi1",
       "InstitutionsForeignPortfolioInvestorCategoryTwo": "fpi2", "SovereignWealthFundsForeign": "swf_foreign", "ForeignSovereignWealthFunds": "swf_foreign",
       "OtherInstitutionsForeign": "other_foreign_inst", "InstitutionsForeign": "foreign_inst_total", "GovernmentsMember": "govt", "Governments": "govt",
       "CentralGovernmentOrPresidentOfIndia": "govt_central", "StateGovernmentsOrGovernors": "govt_state", "BodiesCorporate": "bodies_corporate",
       "NonResidentIndians": "nri", "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh": "retail_small",
       "ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh": "retail_large"}
NAMED_SKIP = re.compile(r"IndividualsOrHUF|OthersIndianShareholders|^Individuals|Promoter|ResidentIndividual|Unclaimed|SignificantBeneficial|CustodianOrDR|KeyManagerial|Directors|Relatives")
PCT_RX = re.compile(r'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="([^"]+)"[^>]*>([^<]+)<')
NAME_RX = re.compile(r'<in-bse-shp:NameOfTheShareholder contextRef="D_([^"]+)"[^>]*>([^<]+)<')
lock = threading.Lock()


def parse_xbrl(x):
    pct = {c: float(v) for c, v in PCT_RX.findall(x) if num(v) is not None}
    cats = {}
    for c, v in pct.items():
        if c.endswith("_ContextI"):
            k = CAT.get(c[:-9])
            if k:
                cats[k] = round(v * 100, 4)
    named = []
    for ctx, name in NAME_RX.findall(x):
        dom = ctx.rsplit("_Context", 1)[0]
        if NAMED_SKIP.search(dom) or ctx not in pct:
            continue
        named.append((dom, name.strip(), round(pct[ctx] * 100, 4)))
    return cats, named


def qdate(s):
    return datetime.strptime(s, "%d-%b-%Y").date().isoformat()


def job(con):
    h = Http(nse=True)
    syms = [r["symbol"] for r in con.execute("SELECT symbol FROM companies WHERE index_membership LIKE 'NIFTY 500%' ORDER BY symbol")]
    done = {(r[0], r[1]) for r in con.execute("SELECT DISTINCT company_id, period_end FROM ownership WHERE holder_category='mf' OR holder_category='promoter_xbrl_done'")}
    todo, n_master, fails = [], 0, []
    for i, s in enumerate(syms):
        try:
            j = h.get(f"https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={s}", pause=0.4).json()
        except Exception as e:  # noqa: BLE001
            fails.append(s); continue
        seen = {}
        for r in j:
            try:
                q = qdate(r["date"])
            except Exception:  # noqa: BLE001
                continue
            if q not in seen:
                seen[q] = r
        cid = "NSE:" + s
        for q, r in seen.items():
            d = hid("nse_shp_master", s, q)
            for cat, key in (("promoter_summary", "pr_and_prgrp"), ("public_summary", "public_val")):
                v = num(r.get(key))
                upsert(con, "ownership", dict(ownership_id=hid(cid, q, cat, None), company_id=cid, period_end=q, holder_category=cat, holder_name=None,
                                              investor_id=None, pct=v, doc_id=None), "ownership_id")
            n_master += 1
        for q in sorted(seen, reverse=True)[:QUARTERS]:
            if (cid, q) not in done and seen[q].get("xbrl"):
                todo.append((cid, q, seen[q]["xbrl"], seen[q].get("submissionDate")))
        if i % 50 == 0:
            con.commit(); print(f"master {i}/{len(syms)} todo={len(todo)}", flush=True)
    con.commit()
    print(f"XBRL to fetch: {len(todo)}", flush=True)
    results, errs = [], []

    def fetch(t):
        cid, q, url, sub = t
        try:
            x = h.get(url, pause=0.2, timeout=60).text
            return t, parse_xbrl(x), len(x)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{cid} {q}: {e}"); return t, None, 0

    n = 0
    with ThreadPoolExecutor(4) as ex:
        for t, parsed, size in ex.map(fetch, todo):
            if not parsed:
                continue
            cid, q, url, sub = t
            cats, named = parsed
            if "promoter" not in cats and "public" not in cats:
                errs.append(f"{cid} {q}: no category totals parsed"); continue
            pub = None
            try:
                pub = datetime.strptime(sub, "%d-%b-%Y").date().isoformat() if sub else None
            except Exception:  # noqa: BLE001
                pass
            d = doc(con, "nse_shp", url, f"Shareholding pattern {cid[4:]} {q}", publication_date=pub, data_period=q)
            for k, v in cats.items():
                upsert(con, "ownership", dict(ownership_id=hid(cid, q, k, None), company_id=cid, period_end=q, holder_category=k, holder_name=None,
                                              investor_id=None, pct=v, doc_id=d), "ownership_id")
            if "mf" not in cats:  # mark as parsed even if the company reports no MF line
                upsert(con, "ownership", dict(ownership_id=hid(cid, q, "promoter_xbrl_done", None), company_id=cid, period_end=q,
                                              holder_category="promoter_xbrl_done", holder_name=None, investor_id=None, pct=None, doc_id=d), "ownership_id")
            for dom, name, v in named:
                iid, gid, gcat = resolve(con, name)
                upsert(con, "ownership", dict(ownership_id=hid(cid, q, dom, name), company_id=cid, period_end=q, holder_category="named:" + dom,
                                              holder_name=name, investor_id=iid, pct=v, doc_id=d), "ownership_id")
            n += 1
            if n % 100 == 0:
                con.commit(); print(f"xbrl {n}/{len(todo)}", flush=True)
    con.commit()
    latest = con.execute("SELECT max(period_end) FROM ownership WHERE doc_id IS NOT NULL").fetchone()[0]
    warn = (f"master failed for {len(fails)} symbols; " if fails else "") + (f"{len(errs)} XBRL errors: " + "; ".join(errs[:5]) if errs else "")
    return {"rows_in": len(todo), "rows_new": n, "period": latest, "warn": warn or None}


if __name__ == "__main__":
    run("nse_shp", job)
    con = connect(); con.execute("UPDATE sources SET last_success=(SELECT last_success FROM sources WHERE source_id='nse_shp'), status='working', latest_data_period=(SELECT max(period_end) FROM ownership WHERE holder_category='promoter_summary') WHERE source_id='nse_shp_master'"); con.commit()
