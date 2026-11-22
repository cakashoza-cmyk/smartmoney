# Smart Money Intelligence 2.0

> For educational and research purposes only; not investment advice; users must make their own decisions under their own registrations.

The platform does not try to predict which stock will rise. It records how the economy is changing, which businesses may be exposed, and whether new evidence keeps confirming or contradicting each analyst hypothesis. It is built for compliant, registered users acting on their own behalf.

This file is the implementation contract for the 2.0 upgrade (spec v2.0, 22 November 2026, approved by Akash) and the record of what Sprint 1 shipped.

## Preservation contract

- Existing tables and identifiers are not renamed or dropped during the first three sprints. New capability is additive.
- v1 JSON exports (`data/export/*.json`) keep their keys. `test/v1_contract.json` lists them, and `test_valuation.V1Contract` fails if a key disappears.
- 2.0 exports live in `data/export/v2/`. The v1 build (`scripts/build.py`) runs first; `scripts/build_v2.py` runs after it.
- Zero running cost is kept: GitHub Pages + GitHub Actions + SQLite. There is no server. The "API" boundaries are Python functions that write static JSON.

## Architecture (Sprint 1)

| Layer | Code | What it does |
|---|---|---|
| Migrations | `scripts/migrate.py`, `migrations/NNN_*.sql` | Versioned, additive, one transaction per file, recorded in `schema_migrations` with a SHA-256 checksum. An applied file that changes is refused. |
| Signal detector | `scripts/intelligence/signal_detector.py` | Fixed rules turn existing data into `signals` with `observed_at` (data period) and `detected_at` (first build that saw it). |
| Relationship graph | `signal_detector.relationships`, `opportunity_graph.Loader` | `entity_relationships`: signal → industry/company (`observed_in`), company → industry (`belongs_to`), hypothesis → industry (`concerns`), hypothesis → company (analyst role). |
| Hypotheses | `scripts/intelligence/opportunity_graph.py` | Loads `data/analyst/opportunities.json` into `opportunities`, `opportunity_evidence`, `opportunity_scenarios`, `thesis_updates`. Checks the stage criteria and reports them; never promotes. |
| Valuation | `scripts/intelligence/valuation_engine.py` and `assets/valuation.js` | The same arithmetic in Python and in the browser (tests check they match). Every input is analyst-entered. |
| Export | `scripts/build_v2.py` | `signals.json`, `opportunities.json`, `valuation.json`, `graph.json`, `meta_v2.json`. |
| Screens | `assets/v2.js` | Signals, Opportunity Discovery, Opportunity Dossier, Investable review, Valuation Lab, Thesis Monitor, Analyst workspace. |

Data acquisition, evidence extraction, analytical rules and presentation stay separate. No language model produces a number, a signal, a stage or a score.

## Schema

`migrations/001_opportunity_foundation.sql` is the spec's section C2 SQL unchanged: `signals`, `entity_relationships`, `opportunities`, `opportunity_evidence`, `opportunity_scenarios`, `thesis_updates`.

`migrations/002_audit_columns_and_append_only.sql` adds columns to the 2.0 tables only:

- `signals`: `rule_id`, `refs_json`, `validation_note`, `last_seen_at`
- `opportunities`: `starter_hypothesis`, `next_review`, `detail_json`
- `thesis_updates`: `recorded_at`

It also adds two triggers that make `thesis_updates` append-only at the database level (UPDATE and DELETE abort).

## Signal rules (fixed; a change is a methodology change)

| Rule | Type | Source | Condition |
|---|---|---|---|
| `fpi_sector_3m` | capital_flow | NSDL fortnightly | 3-month FPI net equity flow ≥ 1.5% of the sector's FPI holdings, either direction |
| `mf_sector_breadth` | capital_flow | Fund-house monthly files | net breadth ≥ +40% or ≤ −40%, at least 10 moves |
| `mf_stock_breadth` | capital_flow | Fund-house monthly files | 3 or more fund houses moved the same way in one stock |
| `rating_balance_90d` | credit_quality | CRISIL, ICRA, CARE, India Ratings (each separately) | (upgrades − downgrades) / (upgrades + downgrades) ≥ +0.6 or ≤ −0.6, at least 6 actions, 90 days |
| `bank_credit_yoy` | credit | RBI SIBC | outstanding credit YoY ≥ 25% or ≤ 0% |
| `inst_breadth_qoq` | capital_flow | NSE shareholding patterns | share of the sector's companies with rising institutional holding ≥ 65% or ≤ 35% (10+ companies) |
| `inst_share_company` | capital_flow | NSE shareholding patterns | Nifty 500 company's institutional holding changes by ≥ 3 pp QoQ |

**Validation.** A signal is `validated` when:

- its source document has a URL;
- its source is working;
- the data is fresh for the rule (45–200 days, depending on the rule).

Otherwise it is `candidate` (document or source problem) or `rejected` (stale). Signal ids are deterministic (`sig_` + hash of rule, entity, observed period, direction), so a re-run never duplicates a signal. Re-detection keeps the first `detected_at`.

`confidence` is measurement coverage (how complete the underlying data is). It is not a probability of any outcome.

## Research hypotheses (the `opportunities` table)

- A hypothesis is a research question about economic change. It is not a view on a security.
- Source of truth: `data/analyst/opportunities.json`, changed only by a reviewed pull request. The Analyst workspace (admin mode) drafts entries in the browser and downloads the merged file.
- The build rejects (and the tests fail on):
  - unknown signals or documents;
  - any score or composite score;
  - scenario probabilities that do not total 100%;
  - an edited or deleted thesis update;
  - a back-dated or future-dated update;
  - an update whose previous stage is not the recorded stage.
- **Starter hypotheses** were seeded in Sprint 1 only where at least two validated signals from independent sources support them. Each is marked `starter_hypothesis` and owned by "Unassigned" until an analyst reviews it. Every number in their text appears in a linked signal (tested).

### Stage criteria (checked by the pipeline, applied by an analyst)

| Stage | Criteria |
|---|---|
| Discovery | at least one validated supporting signal |
| Validation | at least two validated supporting signals from two or more independent sources |
| Emergence | Validation, plus a company-level supporting signal, a confirmation condition, and a validated *supporting* signal on structural demand or company execution (Sprint 2 data) |
| Investable review | Emergence, plus a complete scenario set (probabilities total 100%) and an analyst valuation for a linked company |
| Invalidated / Archived | analyst decision |

When the criteria for a later stage are met, the screens say so. The stage changes only when an analyst records a thesis update. The history shows the date each change was actually recorded (`recorded_at`).

### Six assessment dimensions

The six dimensions are structural demand, industry economics, competitive position, capital allocation, company execution and valuation. Each is shown separately as covered or not covered by linked evidence.

- No dimension score is computed in Sprint 1.
- There is no composite score.
- Coverage mapping: capital-flow and credit signals count toward capital allocation; rating-balance signals count toward industry economics; an analyst valuation counts toward valuation.
- Coverage mapping added in Sprint 2:
  - production, export and capacity signals count toward structural demand;
  - company results count toward company execution;
  - sector results and commodity moves count toward industry economics;
  - the import share of trade counts toward competitive position.

## Valuation Lab

- **Reported data** (left panel, VERIFIED FACT):
  - month-end price derived from fund-house files (market value ÷ shares held);
  - sector index P/E with its 10-year percentile;
  - institutional and promoter holding.
- **From Sprint 2** (VERIFIED FACT, each with a link to the XBRL filing or the NSE bhavcopy): revenue for the last four quarters, EBITDA and EBIT margins, net debt, shares outstanding, an estimated market capitalisation (labelled ESTIMATED VALUE), capex and operating cash flow for the last financial year, ROCE, ROIC and incremental ROIC. Formulas are listed under the panel.
- **Still not ingested**, shown as "insufficient data": working-capital detail, cash tax paid, segment capital employed, lease liabilities.
- **Analyst assumptions** (right panel, ANALYST ASSUMPTION): blank until entered, never prefilled. Base revenue, net debt and market value need a source note before an entry can be downloaded for review.
- **Arithmetic:**
  - free cash flow = revenue × EBIT margin × (1 − tax) − reinvestment;
  - reinvestment comes either from the return on new capital (growth ÷ ROIC × NOPAT) or from explicit net capex plus working capital;
  - value = discounted cash flows + terminal value at (cost of capital − terminal growth);
  - year-N equity = terminal value − (net debt − cumulative free cash flow).
- **Reverse DCF:** for 15%, 20% and 25% annual compounding, the revenue growth (or, alternatively, the EBIT margin) that would be needed with every other assumption held. If no value in the searched range reaches the hurdle, it says so.
- Results are labelled SCENARIO. There is no per-share value and no price objective.

## Sprint 1 limitations

- (Sprint 1) Industry economics, capacity, trade, company financials and global developments were not ingested. Sprint 2 adds them (see below); technology and market share are still not ingested.
- (Sprint 1) Signals covered capital flows and credit only. Sprint 2 adds demand, execution and global rules.
- Hypotheses are stored in a JSON file and published by pull request. There is no multi-user authentication; admin mode is a browser-local convenience.
- Fund-house signals cover 5 of the 10 largest fund houses (the others are blocked or not built; see Fund houses).

## Sprint 2: data that lets hypotheses progress

### Sources added (status is kept in the `sources` registry and shown on Sources & method / Industry data)

| Source | What | Status |
|---|---|---|
| `nse_financials` | NSE integrated filing (financial results) XBRL, Nifty 500, consolidated when filed | working (quarters from Mar-2025, when SEBI integrated filing began) |
| `nse_bhavcopy` | NSE daily closing prices, for the estimated market capitalisation | working |
| `tradestat_eidb` | Ministry of Commerce TradeStat, exports/imports by HS chapter, US$ mn, FY2018-19 onwards | working (public form, no captcha) |
| `un_comtrade` | UN Comtrade public preview, India by HS chapter vs world | working (free tier, annual) |
| `mospi_iip` | MoSPI IIP monthly: general, sectoral, NIC 2-digit manufacturing, use-based | working (api.mospi.gov.in, no key) |
| `rbi_obicus` | RBI OBICUS capacity utilisation (and SA), new-order growth | working (release tables) |
| `fred` | + IMF primary commodity prices (copper, aluminium, iron ore, coal, LNG, zinc, nickel, cotton, palm oil, rubber, sugar, wheat) and US industrial production | working |
| `oea_core8` | Eight core industries (eaindustry.nic.in) | blocked: site does not answer from the pipeline network; not bypassed |
| `jpc_steel`, `fert_production` | Steel (JPC), fertiliser production | blocked: sites do not answer; IIP basic metals / chemicals used instead |
| `cea_power`, `coal_ministry` | CEA power, coal production | not built: PDF reports; IIP electricity / fuel minerals used instead |
| `imf_datamapper` | IMF DataMapper API | blocked (HTTP 403); IMF commodity prices come through FRED |
| `wto_timeseries`, `eia_api` | WTO tariffs/trade, US EIA | needs credentials (free API keys); not used |
| `iea_data` | IEA statistics | not built: licence required |

### Tables

- `company_financials` (migration 003): one row per company, period type (Q = the quarter; YTD = financial year to date) and basis. Reported fields are stored as tagged (₹ crore = rupees ÷ 10^7). Derived fields stored next to them: EBITDA, EBIT, shares outstanding and net debt. A missing tag stays NULL.
- `company_segments` (migration 003): segment revenue and result for the latest quarter of each filing.
- Trade, IIP, OBICUS, prices and commodities are stored in `observations` (no new table needed), with `hs_chapter`, `iip_industry`, `market` and `company` entity types.

### Formulas (also exported in `v2/fundamentals.json` and shown in the Valuation Lab)

- EBITDA = PBT before exceptional items + finance costs + depreciation & amortisation − other income
- EBIT = PBT before exceptional items + finance costs − other income
- Net debt = current + non-current borrowings − (cash & equivalents + other bank balances + current investments); leases excluded
- ROCE = EBIT (financial year) ÷ average capital employed, where capital employed = equity attributable to owners + borrowings, averaged over the opening and closing balance sheets
- ROIC = NOPAT ÷ average invested capital, where NOPAT = EBIT × (1 − effective tax rate) and invested capital = equity + net debt. The tax rate is tax expense ÷ PBT for the same year. ROIC is not computed when PBT ≤ 0 or the rate is outside 0–50%.
- Incremental ROIC = ΔNOPAT ÷ Δinvested capital, year on year. It is not meaningful when invested capital did not rise.
- Market capitalisation (estimate) = paid-up equity capital ÷ face value × latest NSE close.
- None of these is computed for banks, NBFCs or insurers, where borrowings are operating funding.

### Mappings to NSE sectors (fixed tables, exported in `v2/industry.json`)

- **HS chapters:** for example, 72–76 → metals & mining; 30 → healthcare; 84, 86, 88, 89, 93 → capital goods; 87 → autos; 50–63 → textiles; 27 → oil & gas. A chapter can feed several sectors. Services have no merchandise trade.
- **IIP NIC 2-digit industries and use-based groups:** for example, basic metals → metals & mining; electrical equipment and machinery → capital goods; total electricity → power. Category totals are not mapped.
- **Commodities:** each series lists the sectors it first affects and how (realisation or input cost).

### New signal rules

| Rule | Type → dimension | Threshold |
|---|---|---|
| `fin_company_quarter` | company_execution → Company execution | Revenue +20% with the margin not lower, or revenue −10%, or margin −5 pp. Mixed cases (revenue +25% and margin −5 pp together) are not emitted. |
| `fin_sector_revenue` | industry_economics → Industry economics | Sector revenue ≥ +15% or ≤ 0% YoY (5+ companies) |
| `fin_sector_margin` | industry_economics | Aggregate EBITDA margin ± 1.5 pp YoY (5+ companies) |
| `iip_sector_3m` | structural_demand → Structural demand | 3-month average IIP YoY ≥ 8% or ≤ −2% |
| `trade_export_fy` | structural_demand | Exports +15% or −10% in the latest FY |
| `trade_import_share` | competitive_position → Competitive position | Import share of trade ± 3 pp (US$ 1 bn+ of trade) |
| `capacity_utilisation` | structural_demand (market level) | OBICUS seasonally adjusted CU ≥ 75% or ≤ 70% |
| `commodity_3m` | global → Industry economics | Commodity price ± 15% over 3 months; linked to exposed sectors as relationships |

**Emergence** now requires a *supporting*, validated signal on structural demand or company execution (Sprint 1 counted any linked evidence). Promotion is still recorded only by an analyst.

### Sprint 2 limitations

- Company results history starts with the quarter ended Mar-2025 (SEBI integrated filing). The older NSE results API stops at Dec-2024 and uses a different taxonomy, so it is not merged.
- Revenue is as reported. Duties included in revenue (for example excise on tobacco from 2026) move growth and margins. The company rule skips the mixed case, but the numbers are shown as filed.
- Balance sheet and cash flow come only from half-year filings, and ROCE/ROIC use financial-year figures only.
- Trade is by financial year and HS 2-digit only, so the current year in progress is not shown. Import share is a trade-mix measure, not import dependence of consumption, because production values are not in the data.
- Core-8, JPC, CEA, coal and fertiliser ministry data are not ingested (see the status table above). IIP sub-indices are used as production proxies.
- OBICUS is aggregate manufacturing only, with no sector split.
- Global: WTO and EIA need free API keys, which have not been added; IMF DataMapper is blocked (403).

## Next sprints (from the spec)

1. (Done in Sprint 2: trade, production, capacity and company financials; see above.)
2. Historical prediction measurement (`historical_snapshots`) and source licensing (`source_licensing`).
3. Commercial launch: authentication, server-side customer isolation, backups.
