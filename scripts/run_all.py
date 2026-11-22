"""Scheduler entry point. Usage: python3 scripts/run_all.py <group> [<group> ...]
Groups: daily | fortnightly | monthly | quarterly | annual | amc | ratings | all. Each job runs independently; a failure is logged
(extraction_logs + data-quality page) and never stops the others or wipes earlier data. build.py then build_v2.py always run last."""
import sys
from common import run
import registry, ingest_universe, ingest_shp, ingest_nsdl, ingest_nse, ingest_official as o, connectors_paid, ingest_amc, ingest_ratings as rt
import ingest_financials as fin, ingest_industry as ind

GROUPS = {
    "daily": [("nse_fiidii", ingest_nse.job_fiidii), ("nse_deals", ingest_nse.job_deals), ("nse_announcements", ingest_nse.job_ann),
              ("pib_cabinet", o.job_pib), ("crisil_ratings", o.job_crisil), ("fred", o.job_fred), ("nse_sector_pe", o.job_sector_pe),
              ("nse_bhavcopy", ind.job_bhavcopy)],
    "fortnightly": [("nsdl_fpi_sector", ingest_nsdl.job)],
    "monthly": [("nse_universe", ingest_universe.job), ("amfi_monthly", o.job_amfi), ("rbi_sibc", o.job_rbi_sibc), ("sebi_aif", o.job_sebi_aif), ("dpiit_fdi", o.job_dpiit),
                ("mospi_iip", ind.job_iip), ("rbi_obicus", ind.job_obicus), ("tradestat_eidb", ind.job_tradestat), ("un_comtrade", ind.job_comtrade)],
    "quarterly": [("nse_shp", ingest_shp.job)],
    "annual": [("worldbank", o.job_worldbank)],
    # AMC monthly scheme portfolios (published by the 10th): one source per fund house; blocked sites are registered, never fetched
    "amc": [("amc_" + a, ingest_amc.make_job(a)) for a in ingest_amc.AMCS],
    # Sprint 2: company results (NSE integrated-filing XBRL); incremental, only filings not yet loaded are fetched
    "fundamentals": [("nse_financials", fin.job), ("nse_bhavcopy", ind.job_bhavcopy)],
    "ratings": [("icra_ratings", rt.job_icra), ("care_ratings", rt.job_care), ("indra_ratings", rt.job_indra)],
}

if __name__ == "__main__":
    want = sys.argv[1:] or ["daily"]
    if "all" in want:
        want = list(GROUPS)
    registry.seed()
    import migrate, common  # Sprint 2 jobs write to tables created by versioned migrations
    _c = common.connect(); migrate.apply_all(_c); _c.close()
    connectors_paid.register()
    for g in want:
        for sid, fn in GROUPS[g]:
            run(sid, fn)
    import build
    build.main()
    import build_v2  # 2.0 layer: migrations, signals, analyst hypotheses, v2 exports (v1 exports untouched)
    build_v2.main()
