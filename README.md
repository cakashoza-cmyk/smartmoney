# India Smart Money Intelligence Dashboard

**Live:** https://cakashoza-cmyk.github.io/smartmoney/ · **Code:** this repository

A capital-allocation intelligence terminal for India: where disclosed institutional, private-market, corporate, credit and policy money is moving, across three horizons (1-3 years, 3-10 years, 10-20 years). It is built only from official or structured public sources. Every number links to its source document and date.

> **Not investment advice.** This is educational research on public capital-flow disclosures. It is not a recommendation to buy, sell or hold any security, and the author is not a SEBI-registered investment adviser or research analyst. "Capital attention" measures where disclosed money moved. It is not a view on returns.

## Architecture (zero running cost)

| Layer | What it is |
|---|---|
| Ingestion | Python jobs in `scripts/ingest_*.py`, one per source. Each run is logged in `extraction_logs`. A failure is recorded and never wipes earlier data. |
| Database | SQLite (`schema.sql`; the same DDL runs on PostgreSQL). It persists between runs as the release asset `db/smartmoney.db.gz`, with weekly dated backups attached to the same release. |
| Intelligence | `scripts/build.py` holds 8 rule-based agents, the investor convergence logic, five scores × three horizons, the Research Auditor, and the JSON/Excel export. |
| Scheduler | GitHub Actions `.github/workflows/refresh.yml`, with cron jobs for the daily, fortnightly, monthly, quarterly and annual groups. |
| Frontend | A static SPA (`index.html`, `assets/app.js`) on GitHub Pages that reads `data/export/*.json`. It has no build step and no server. |
| User state | Watchlists, alerts, theme, filters and admin weight overrides live in the browser's localStorage. |

**Changes from the brief, and why:**
- The brief asks for Next.js, FastAPI, Postgres and cloud auth. A hosted backend would cost money, so the same relational model runs on SQLite and is published as static JSON.
- `users`, `watchlists`, `alerts` and `user_preferences` tables exist in the schema for a future hosted deployment.
- **Authentication and role-based access are not implemented.** The Admin page is a client-side mode that only changes weights in your own browser. Changing the published weights means editing `data/weights.json` in the repository. Real role-based access needs a hosted backend.
- **No language model is used anywhere.** No free LLM key was available, and the brief forbids LLM-produced numbers. The "AI agents" are deterministic Python rules. Their text is labelled AI INTERPRETATION, and every one of their conclusions is checked by the deterministic Research Auditor.
- **SEBI compliance:**
  - "Investment Attractiveness" is renamed **Valuation context**, and "Opportunity Radar" is renamed **Capital attention radar**.
  - "Investor quality" is renamed **Investor activity**, because track record and returns are not disclosed in structured form.
  - "Company quality" is renamed **Company evidence**.
  - "Industry opportunity" is renamed **Industry evidence**.
  - The platform never names a security as worth owning. `test/wordcheck.py` enforces this.

## Database schema (`schema.sql`)

| Table | Contents |
|---|---|
| `sources` | The visible registry: status, reliability, last success, latest data period, limitations, credentials needed |
| `source_documents` | Every fetched file or page: URL, publication date, data period, retrieval time, content hash |
| `extraction_logs` | One row per job run: ok/error, rows in/new, duplicates skipped |
| `industries`, `sub_industries`, `industry_map` | NSE macro-sector taxonomy (22 sectors plus credit-only categories). Sub-industries come from NSE sector index lists and RBI codes. `industry_map` maps each source's own labels onto the taxonomy. |
| `investor_groups`, `investors` | Parent group vs legal entity, with passive and trading flags and the name rule that matched |
| `companies`, `ownership` | Listed universe, plus quarterly shareholding by category and by named holder above 1% |
| `transactions` | Every investment event: type, dates, amount (NULL when undisclosed), side, investor, evidence label, `related_txn_id` |
| `commitments`, `deployments` | Kept separate with a `commitment_id` link, and **never summed** |
| `acquisitions`, `divestments`, `capex`, `debt` | Event detail tables. `debt` covers sanctioned vs disbursed stock and rating actions. |
| `observations` | Time series (metric × entity × period), each with a `doc_id` |
| `ai_conclusions`, `scoring_history` | Agent outputs with auditor status, and every score with components, missing data and confidence |
| `users`, `watchlists`, `alerts`, `user_preferences` | For a hosted deployment only. The static site uses localStorage. |

## Sources

The live status of each source is on the **Sources & method** page.

| Source | What it supplies | Status |
|---|---|---|
| NSE Nifty 500 list + sector index lists | Company universe, sector, sub-industry | working |
| NSE shareholding patterns (XBRL, 5 quarters) | Category %, named holders above 1% | working (a few filers fail to parse) |
| NSDL fortnightly FPI by sector (2017→) | Sector FPI flows and holdings | working |
| NSE FII/DII provisional | Daily cash flows. NSE publishes only the latest day, so history builds from the pipeline start. | working |
| NSE bulk + block deals (CSV) | Named large trades | working |
| NSE corporate announcements | Acquisitions, capex, JVs, QIPs, allotments, NCD/CP | working (amount only if exactly one figure appears in the summary) |
| SEBI AIF statistics | Commitments, raised and invested by category, plus sector table | working |
| RBI sectoral deployment of bank credit (SIBC) | Outstanding credit by industry code | working |
| AMFI monthly | MF net inflows by category | working |
| CRISIL rating actions | Upgrades, downgrades, defaults, non-cooperation | working |
| India Ratings rating-action list | Headline action + the agency's industry field | working (weekly) |
| CARE (CareEdge) press releases | Rating-action column + CARE's own industry classification, from each PDF | working (weekly; the public feed holds about one month) |
| ICRA rating rationales | Upgrades, downgrades, outlook/watch changes, defaults (PDF read only for these) | working (weekly; sector keyword-classified) |
| AMC monthly scheme portfolios: SBI, Nippon India, Aditya Birla Sun Life, DSP, PPFAS | Every scheme's listed Indian equity holdings, month-end | working (monthly, 10th-12th) |
| AMC monthly portfolios: HDFC, ICICI Prudential, Kotak, Tata, Edelweiss | n/a | **blocked** (403 / connection refused / hCaptcha; not bypassed) |
| AMC monthly portfolios: Axis, UTI, Mirae Asset | n/a | not built (no file links on the public page, or per-scheme paged listing) |
| PIB Cabinet releases | Approved outlays (announcements) | working (RSS comes in Hindi to some networks; parsed both ways) |
| World Bank WDI | Structural indicators, FDI, peers | working |
| FRED | US rates, real yield, dollar, Brent, INR | partial (intermittent timeouts) |
| Nifty sector P/E (niftyindices) | Valuation context, 10-year percentile | working |
| DPIIT FDI factsheets | Sector FDI | **blocked** (site refuses automated access; not bypassed) |
| IMF DataMapper, BSE deals API | n/a | **blocked** |
| Tracxn, Venture Intelligence, VCCEdge, MCA21 | PE/VC rounds, unlisted companies | **needs paid credentials** (connector stubs in `scripts/connectors_paid.py`) |
| SEBI PMS, IVCA/EY, SWF disclosures | n/a | not built yet |

## Scores

There are five scores. Each one is computed separately for each of the three horizons.

**How a score is built:**
- Each component is a percentile rank (0-100) across sectors, groups or companies.
- The score is the weighted mean of the components that have data.
- If less than 50% of the weight has data, the score is **insufficient data**. It is never set to zero.
- Confidence is high when at least 85% of the weight is covered, medium at 65% or more, and low at 50% or more.
- Weights are in `data/weights.json`.

**Inputs the brief asks for that are not available.** No free structured source supplies these, so they are listed as *not assessed*:
- ROIC, management quality, track record, competitive intensity and expected returns.

**Method by horizon:**
- **1-3y:** FPI flow over the last 6 fortnights (% of holdings), median institutional stake change QoQ, breadth, non-trading institutional net deals over 90 days, new independent holders above 1%, bank credit FYTD, and fund-house breadth (share of fund-house x stock moves in the sector that were adds or new positions rather than trims or exits, latest month, active schemes only).
- **3-10y:** FPI persistence over 36 months, FPI flow over 12 months, institutional stake change YoY, bank credit YoY, AIF sector investment growth, and corporate capital events over 180 days.
- **10-20y:** no forecasts. Eight authored SCENARIOS, each with confirm and invalidate conditions. Each scenario is checked against World Bank structural series, credit, AIF, FPI since 2017 and Cabinet approvals.

## Investor convergence

A company counts when several distinct **parent groups** are adding to it, through either of these routes:
- the group became a new holder above 1% in the latest quarter (shareholding patterns), or
- the group was a net buyer in bulk/block deals over 90 days, or
- (fund houses) the group opened a new position in its active schemes in the latest monthly portfolio file.

What is excluded or collapsed:
- Fund families collapse to their parent when a name rule exists (for example, every SBI scheme counts as SBI Funds Management). Foreign funds with no rule yet count as their own group, so two unmapped funds of one family could still be counted twice; the rule list grows over time.
- Trading firms, broker desks, ODI/P-note desks, index funds and ETFs, individuals and corporates are all excluded.
- Holdings below 1% are invisible, because companies do not disclose them.

## Operating and maintenance

- **Run locally:**
  ```
  pip install requests pandas lxml openpyxl xlrd
  cd scripts && python3 run_all.py all
  python3 -m http.server
  ```
  Then open http://localhost:8000.
- **Run one group:** `python3 scripts/run_all.py daily` (or `fortnightly`, `monthly`, `quarterly`, `annual`).
- **Run in GitHub Actions:** open Actions → refresh → Run workflow, and enter the groups to run.
- **Schedules (IST):**
  - Mon-Fri 19:00: daily group plus the NSDL check
  - Sunday 06:00: monthly group plus shareholding patterns (incremental)
  - 5th of the month 07:30: World Bank
- **Tests:**
  ```
  python3 -m unittest discover -s test -p "test_*.py" -v
  python3 test/wordcheck.py
  python3 test/verify.py <url>
  ```
  `test/verify.py` is the browser check. It needs Playwright and Chrome.
- **Add an investor parent rule:** add a regex to `GROUPS` in `scripts/registry.py`. The rules are re-applied to all stored names on the next build.
- **Connect a paid source:** set the environment variables named in `scripts/connectors_paid.py` as repository secrets, then implement `fetch()`.
- **Stale data:** a source whose latest data period is older than its `max_age_days` plus the normal publication lag is marked stale in the header bar and on the Data quality page.

## Known limitations

- **Coverage of holdings:** only holdings above 1% are named, and only for Nifty 500 companies, over 5 quarters. Mutual fund scheme-level portfolios are not ingested yet.
- **PE/VC and unlisted companies:** no rounds, valuations or unlisted funding without paid databases.
- **Credit:** stock data only, with no sanction vs disbursement split. NBFC on-lending by sector is not available.
- **Announcement amounts:** taken only when the filing summary states one unambiguous figure. Everything else stays *undisclosed*.
- **Sector history before Apr 2022:** NSDL used about 40 legacy sectors, which are mapped by name to today's sectors. This mapping is approximate.
- **Global data:** FRED and World Bank only. There is no tariff or trade-policy feed yet (WTO and UNCTAD are planned).
- **NSE access from cloud IPs:** NSE may block GitHub Actions IP ranges. If it does, the affected sources are flagged stale and the last good data stays visible.

## Fund houses (AMC monthly portfolio files)

- Each fund house publishes every scheme's month-end holdings (SEBI requirement, by the 10th). Files are downloaded from the fund house's own site; the scheduler runs on the 10th-12th and skips files already loaded.
- Only listed Indian equity rows (ISIN `INE...01...`) are kept. Holdings are stored in `ownership` with `holder_category='mf_portfolio'`, with quantity, market value and % of scheme NAV.
- Every scheme is parented to the fund house that published the file (never by a name rule), so all schemes of one house count once.
- Index funds and ETFs are flagged **passive**, arbitrage funds **arbitrage**. Both are stored but left out of adds/exits, convergence and the 1-3y component.
- Month-on-month: shares held by a house's active schemes are summed per stock. new = not held last month; exit = no longer held; add / trim = shares up / down 10% or more; smaller changes are 'held' (inflows move every holding a little). Splits and bonuses are detected from the files (share count up, price down) and the earlier quantity is adjusted.
- Each change is written to `transactions` (`txn_id` `mff_...`, label ESTIMATED VALUE: the quantity change is a fact from two files, the rupee value is change x month-end price).
- Sector for stocks outside the Nifty 500 = the sector most Nifty 500 stocks with the same AMC industry label belong to.

## Rating actions (four agencies)

CRISIL, ICRA, CARE and India Ratings are separate sources and are never summed: they rate different issuers and publish in different forms. The Credit page shows upgrades, downgrades, defaults and outlook/watch changes by sector for each agency. The 1-3y industry-evidence score keeps using CRISIL only, because it is the one source with the full 12-month action history including reaffirmations.

## Smart Money Intelligence 2.0 (Sprint 1)

> For educational and research purposes only; not investment advice; users must make their own decisions under their own registrations.

New screens:
- **Signals:** rule-based changes, each with an observed date and a detected date.
- **Opportunity Discovery:** analyst research hypotheses with linked evidence.
- **Opportunity Dossier**
- **Investable review**
- **Valuation Lab:** reported data kept separate from analyst assumptions, plus a reverse DCF at 15%, 20% and 25%.
- **Thesis Monitor:** append-only stage history.
- **Analyst workspace**

How it works:
- Schema changes are versioned migrations in `migrations/`, recorded in `schema_migrations`.
- Hypotheses live in `data/analyst/opportunities.json` and change only through a reviewed pull request. The pipeline never creates, scores or promotes one.
- There is no composite score.

Sprint 2 adds:
- **Company results:** from NSE integrated-filing XBRL for the Nifty 500. Covers TTM revenue, EBITDA, net debt, capex, ROCE, ROIC and incremental ROIC, with formulas shown.
- **Trade:** TradeStat and UN Comtrade data by HS chapter.
- **Production and capacity:** MoSPI IIP and RBI OBICUS capacity utilisation.
- **Global Radar:** IMF commodity prices via FRED.
- **New signal rules** that feed structural demand and company execution.
- **Industry data page,** plus a prefilled reported panel in the Valuation Lab. Analyst assumptions stay blank.

Design, rules, stage criteria and limitations: [docs/SMART_MONEY_INTELLIGENCE_2.0.md](docs/SMART_MONEY_INTELLIGENCE_2.0.md).
