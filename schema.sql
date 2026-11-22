-- India Smart Money Intelligence Dashboard: relational schema.
-- Portable SQL: runs unchanged on SQLite (committed data/smartmoney.db) and on PostgreSQL 13+.
-- Keys are deterministic TEXT ids (hash of natural key) so re-ingesting the same disclosure never duplicates it.
-- Money is stored in INR crore (amount_inr_cr). NULL means UNDISCLOSED / INSUFFICIENT DATA, never zero.
-- Watchlists, alerts and user preferences live in the browser (localStorage) on the free static deployment;
-- their tables are defined here for a hosted (Postgres + FastAPI) deployment.

CREATE TABLE IF NOT EXISTS sources (               -- the visible source registry
  source_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,                          -- public_equity | private_markets | foreign_strategic | corporate | credit | government_global
  url TEXT,
  publisher TEXT,
  official INTEGER NOT NULL DEFAULT 1,             -- 1 = official/regulator/exchange, 0 = unofficial (labelled)
  reliability TEXT NOT NULL,                       -- A official primary | B official secondary | C announcement | D unofficial | X not connected
  refresh_schedule TEXT,                           -- daily | weekly | monthly | quarterly | annual | manual
  max_age_days INTEGER,                            -- older than this = STALE
  status TEXT NOT NULL,                            -- working | partial | blocked | needs_credentials | not_built
  credentials_needed TEXT,
  last_attempt TEXT,
  last_success TEXT,
  latest_data_period TEXT,
  latest_publication_date TEXT,
  limitations TEXT
);

CREATE TABLE IF NOT EXISTS source_documents (
  doc_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  url TEXT NOT NULL,
  title TEXT,
  publication_date TEXT,
  data_period TEXT,
  retrieved_at TEXT NOT NULL,
  content_hash TEXT,
  evidence_label TEXT NOT NULL DEFAULT 'VERIFIED FACT'
);

CREATE TABLE IF NOT EXISTS extraction_logs (
  log_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  run_at TEXT NOT NULL,
  ok INTEGER NOT NULL,
  rows_in INTEGER,
  rows_new INTEGER,
  duplicates_skipped INTEGER,
  error TEXT
);

CREATE TABLE IF NOT EXISTS industries (
  industry_id TEXT PRIMARY KEY,                    -- e.g. capital_goods (NSE macro-sector taxonomy, shared by NSDL)
  name TEXT NOT NULL,
  description TEXT
);

CREATE TABLE IF NOT EXISTS sub_industries (
  sub_industry_id TEXT PRIMARY KEY,
  industry_id TEXT NOT NULL REFERENCES industries(industry_id),
  name TEXT NOT NULL,
  basis TEXT                                       -- e.g. 'NSE thematic index membership', 'RBI SIBC industry code 2.4'
);

CREATE TABLE IF NOT EXISTS industry_map (          -- maps each source's own sector label onto the taxonomy
  source_id TEXT NOT NULL,
  source_label TEXT NOT NULL,
  industry_id TEXT REFERENCES industries(industry_id),
  sub_industry_id TEXT REFERENCES sub_industries(sub_industry_id),
  PRIMARY KEY (source_id, source_label)
);

CREATE TABLE IF NOT EXISTS investor_groups (       -- parent group; convergence counts groups, never funds
  group_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,                          -- fpi | mutual_fund | insurance | pension | aif | pms | pe | vc | growth | infra_fund | private_credit | swf | global_pension | family_office | strategic | promoter | government | dfi | bank_nbfc | trading_firm | aggregate
  country TEXT,
  aum_disclosed TEXT,                              -- text with its source, or NULL
  passive_flag INTEGER NOT NULL DEFAULT 0,         -- 1 = mostly index/passive (excluded from conviction counts)
  trading_flag INTEGER NOT NULL DEFAULT 0,         -- 1 = market-maker / proprietary trading (excluded from conviction counts)
  notes TEXT,
  source_url TEXT
);

CREATE TABLE IF NOT EXISTS investors (             -- legal entities / fund names as they appear in disclosures
  investor_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  group_id TEXT REFERENCES investor_groups(group_id),
  category TEXT,
  match_rule TEXT                                  -- which deterministic rule mapped the name to the group
);

CREATE TABLE IF NOT EXISTS companies (
  company_id TEXT PRIMARY KEY,                     -- NSE:SYMBOL for listed; CIN:... for unlisted
  name TEXT NOT NULL,
  symbol TEXT,
  isin TEXT,
  cin TEXT,
  listed INTEGER NOT NULL DEFAULT 1,
  parent_group TEXT,
  industry_id TEXT REFERENCES industries(industry_id),
  sub_industry_id TEXT REFERENCES sub_industries(sub_industry_id),
  index_membership TEXT,
  source_id TEXT REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS ownership (             -- quarterly shareholding pattern, one row per company x quarter x holder category/name
  ownership_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES companies(company_id),
  period_end TEXT NOT NULL,
  holder_category TEXT NOT NULL,                   -- promoter | mf | aif | bank | insurance | pension | fpi1 | fpi2 | fdi | swf_domestic | govt | public | ...
  holder_name TEXT,                                -- NULL for category totals; name for >1% holders
  investor_id TEXT REFERENCES investors(investor_id),
  pct REAL,
  doc_id TEXT REFERENCES source_documents(doc_id)
);

CREATE TABLE IF NOT EXISTS transactions (          -- every investment event; one id per disclosure, linked when related
  txn_id TEXT PRIMARY KEY,
  txn_type TEXT NOT NULL,                          -- actual_investment | announced_investment | capital_commitment | capital_raised | capital_deployed | secondary_purchase | secondary_sale | primary_issuance | acquisition | divestment | merger | joint_venture | corporate_capex | project_finance | debt_refinancing | investor_exit | portfolio_reallocation
  evidence_label TEXT NOT NULL,                    -- VERIFIED FACT | REPORTED ANNOUNCEMENT | ESTIMATED VALUE | AI INTERPRETATION | SCENARIO | UNVERIFIED INFORMATION
  txn_date TEXT,
  announcement_date TEXT,
  investor_id TEXT REFERENCES investors(investor_id),
  company_id TEXT REFERENCES companies(company_id),
  industry_id TEXT REFERENCES industries(industry_id),
  instrument TEXT,
  side TEXT,                                       -- BUY | SELL | NA
  quantity REAL,
  price REAL,
  amount REAL,
  currency TEXT,
  amount_inr_cr REAL,                              -- NULL = undisclosed
  related_txn_id TEXT REFERENCES transactions(txn_id),
  description TEXT,
  doc_id TEXT REFERENCES source_documents(doc_id),
  source_id TEXT REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS commitments (           -- announced / committed money; NEVER summed with deployments
  commitment_id TEXT PRIMARY KEY,
  txn_id TEXT REFERENCES transactions(txn_id),
  scope TEXT NOT NULL,                             -- e.g. 'AIF Category II, cumulative' | 'Cabinet approval: <scheme>'
  industry_id TEXT REFERENCES industries(industry_id),
  period TEXT,
  amount_inr_cr REAL,
  evidence_label TEXT NOT NULL,
  doc_id TEXT REFERENCES source_documents(doc_id)
);

CREATE TABLE IF NOT EXISTS deployments (           -- money actually invested / disbursed / traded
  deployment_id TEXT PRIMARY KEY,
  txn_id TEXT REFERENCES transactions(txn_id),
  commitment_id TEXT REFERENCES commitments(commitment_id),   -- link to the commitment it draws on (if known)
  scope TEXT NOT NULL,
  industry_id TEXT REFERENCES industries(industry_id),
  period TEXT,
  amount_inr_cr REAL,
  evidence_label TEXT NOT NULL,
  doc_id TEXT REFERENCES source_documents(doc_id)
);

CREATE TABLE IF NOT EXISTS acquisitions (
  acquisition_id TEXT PRIMARY KEY,
  txn_id TEXT NOT NULL REFERENCES transactions(txn_id),
  acquirer_company_id TEXT REFERENCES companies(company_id),
  target_name TEXT,
  stake_pct REAL,
  amount_inr_cr REAL,
  status TEXT                                       -- announced | completed | unknown
);

CREATE TABLE IF NOT EXISTS divestments (
  divestment_id TEXT PRIMARY KEY,
  txn_id TEXT NOT NULL REFERENCES transactions(txn_id),
  seller_company_id TEXT REFERENCES companies(company_id),
  asset_name TEXT,
  amount_inr_cr REAL,
  status TEXT
);

CREATE TABLE IF NOT EXISTS capex (
  capex_id TEXT PRIMARY KEY,
  txn_id TEXT REFERENCES transactions(txn_id),
  company_id TEXT REFERENCES companies(company_id),
  industry_id TEXT REFERENCES industries(industry_id),
  description TEXT,
  amount_inr_cr REAL,
  stage TEXT NOT NULL,                             -- announced | approved | under_construction | commissioned (announced != commissioned)
  evidence_label TEXT NOT NULL,
  doc_id TEXT REFERENCES source_documents(doc_id)
);

CREATE TABLE IF NOT EXISTS debt (                  -- credit stock and debt events; sanctioned != disbursed
  debt_id TEXT PRIMARY KEY,
  txn_id TEXT REFERENCES transactions(txn_id),
  industry_id TEXT REFERENCES industries(industry_id),
  borrower TEXT,
  measure TEXT NOT NULL,                           -- outstanding_bank_credit | sanctioned | disbursed | rating_action | refinancing
  period TEXT,
  amount_inr_cr REAL,
  yoy_pct REAL,
  detail TEXT,
  doc_id TEXT REFERENCES source_documents(doc_id),
  source_id TEXT REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS observations (          -- time series: flows, stocks, indicators (sector x period x metric)
  obs_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  metric TEXT NOT NULL,                            -- e.g. fpi_net_equity_inr_cr, fpi_auc_equity_inr_cr, fii_net_cash_inr_cr, sector_pe
  entity_type TEXT NOT NULL,                       -- industry | market | country | investor_group | company
  entity_id TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT NOT NULL,
  value REAL,                                      -- NULL = not published
  unit TEXT,
  evidence_label TEXT NOT NULL DEFAULT 'VERIFIED FACT',
  doc_id TEXT REFERENCES source_documents(doc_id)
);

CREATE TABLE IF NOT EXISTS ai_conclusions (        -- outputs of the (rule-based) agents, each auditable
  conclusion_id TEXT PRIMARY KEY,
  agent TEXT NOT NULL,
  horizon TEXT,                                    -- 1-3y | 3-10y | 10-20y | all
  subject_type TEXT,
  subject_id TEXT,
  statement TEXT NOT NULL,
  evidence_label TEXT NOT NULL,
  evidence_refs TEXT,                              -- JSON list of obs_id / txn_id / doc_id
  contradicting_refs TEXT,                         -- JSON list of evidence pointing the other way
  confidence TEXT,                                 -- high | medium | low | insufficient
  auditor_status TEXT NOT NULL DEFAULT 'pending',  -- accepted | rejected | flagged
  auditor_notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scoring_history (
  score_id TEXT PRIMARY KEY,
  score_name TEXT NOT NULL,                        -- capital_flow | investor_activity | industry_evidence | company_evidence | valuation_context
  horizon TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  as_of TEXT NOT NULL,
  score REAL,                                      -- NULL = insufficient data (never 0 for missing)
  components TEXT NOT NULL,                        -- JSON: [{name, value, weight, evidence, missing}]
  confidence TEXT,
  missing TEXT
);

-- Hosted deployment only (static build keeps these in the browser):
CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, email TEXT UNIQUE, role TEXT NOT NULL DEFAULT 'viewer');
CREATE TABLE IF NOT EXISTS watchlists (watchlist_id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(user_id), entity_type TEXT, entity_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS alerts (alert_id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(user_id), rule_json TEXT, created_at TEXT, last_fired TEXT);
CREATE TABLE IF NOT EXISTS user_preferences (user_id TEXT PRIMARY KEY REFERENCES users(user_id), prefs_json TEXT);

CREATE INDEX IF NOT EXISTS ix_obs_metric ON observations(metric, entity_id, period_end);
CREATE INDEX IF NOT EXISTS ix_txn_company ON transactions(company_id, txn_date);
CREATE INDEX IF NOT EXISTS ix_txn_investor ON transactions(investor_id, txn_date);
CREATE INDEX IF NOT EXISTS ix_own_company ON ownership(company_id, period_end);
CREATE INDEX IF NOT EXISTS ix_own_investor ON ownership(investor_id, period_end);
