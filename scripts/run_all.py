"""Scheduler entry point. Usage: python3 scripts/run_all.py <group> [<group> ...]
Groups: daily | fortnightly | monthly | quarterly | annual | all. Each job runs independently; a failure is logged
(extraction_logs + data-quality page) and never stops the others or wipes earlier data. build.py always runs last."""
import sys
from common import run
import registry, ingest_universe, ingest_shp, ingest_nsdl, ingest_nse, ingest_official as o, connectors_paid

GROUPS = {
    "daily": [("nse_fiidii", ingest_nse.job_fiidii), ("nse_deals", ingest_nse.job_deals), ("nse_announcements", ingest_nse.job_ann),
              ("pib_cabinet", o.job_pib), ("crisil_ratings", o.job_crisil), ("fred", o.job_fred), ("nse_sector_pe", o.job_sector_pe)],
    "fortnightly": [("nsdl_fpi_sector", ingest_nsdl.job)],
    "monthly": [("nse_universe", ingest_universe.job), ("amfi_monthly", o.job_amfi), ("rbi_sibc", o.job_rbi_sibc), ("sebi_aif", o.job_sebi_aif), ("dpiit_fdi", o.job_dpiit)],
    "quarterly": [("nse_shp", ingest_shp.job)],
    "annual": [("worldbank", o.job_worldbank)],
}

if __name__ == "__main__":
    want = sys.argv[1:] or ["daily"]
    if "all" in want:
        want = list(GROUPS)
    registry.seed()
    connectors_paid.register()
    for g in want:
        for sid, fn in GROUPS[g]:
            run(sid, fn)
    import build
    build.main()
