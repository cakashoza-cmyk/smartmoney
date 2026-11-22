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
| Emergence | Validation, plus a company-level supporting signal, a confirmation condition, and demand or execution evidence (not available from Sprint 1 sources) |
| Investable review | Emergence, plus a complete scenario set (probabilities total 100%) and an analyst valuation for a linked company |
| Invalidated / Archived | analyst decision |

When the criteria for a later stage are met, the screens say so. The stage changes only when an analyst records a thesis update. The history shows the date each change was actually recorded (`recorded_at`).

### Six assessment dimensions

The six dimensions are structural demand, industry economics, competitive position, capital allocation, company execution and valuation. Each is shown separately as covered or not covered by linked evidence.

- No dimension score is computed in Sprint 1.
- There is no composite score.
- Coverage mapping: capital-flow and credit signals count toward capital allocation; rating-balance signals count toward industry economics; an analyst valuation counts toward valuation.

## Valuation Lab

- **Reported data** (left panel, VERIFIED FACT):
  - month-end price derived from fund-house files (market value ÷ shares held);
  - sector index P/E with its 10-year percentile;
  - institutional and promoter holding.
- **Not ingested in Sprint 1**, and shown as "insufficient data": company financial statements (revenue, margins, capex, working capital, tax, ROIC), shares outstanding and net debt.
- **Analyst assumptions** (right panel, ANALYST ASSUMPTION): blank until entered, never prefilled. Base revenue, net debt and market value need a source note before an entry can be downloaded for review.
- **Arithmetic:**
  - free cash flow = revenue × EBIT margin × (1 − tax) − reinvestment;
  - reinvestment comes either from the return on new capital (growth ÷ ROIC × NOPAT) or from explicit net capex plus working capital;
  - value = discounted cash flows + terminal value at (cost of capital − terminal growth);
  - year-N equity = terminal value − (net debt − cumulative free cash flow).
- **Reverse DCF:** for 15%, 20% and 25% annual compounding, the revenue growth (or, alternatively, the EBIT margin) that would be needed with every other assumption held. If no value in the searched range reaches the hurdle, it says so.
- Results are labelled SCENARIO. There is no per-share value and no price objective.

## Sprint 1 limitations

- Industry economics, capacity, trade, technology, company financials and global developments are not ingested yet. The dossier shows those sections as insufficient data.
- Signals cover capital flows and credit only, so no hypothesis can meet the Emergence criteria yet.
- Hypotheses are stored in a JSON file and published by pull request. There is no multi-user authentication; admin mode is a browser-local convenience.
- Fund-house signals cover 5 of the 10 largest fund houses (the others are blocked or not built; see Fund houses).

## Next sprints (from the spec)

1. Industry economics and capacity intelligence (`industry_capacity`, `industry_trade`).
2. Company financials and segments (`company_financials`, `company_segments`), which feed reported data in the Valuation Lab.
3. Historical prediction measurement (`historical_snapshots`) and source licensing (`source_licensing`).
4. Commercial launch: authentication, server-side customer isolation, backups.
