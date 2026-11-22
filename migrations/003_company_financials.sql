-- Sprint 2: reported company financials from NSE integrated-filing XBRL (additive only).
-- All amounts in Rs crore as reported (XBRL values in rupees / 1e7). NULL = not reported in the filing ("insufficient data"), never zero.
CREATE TABLE IF NOT EXISTS company_financials (
  fin_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  period_type TEXT NOT NULL,            -- Q = the quarter | YTD = financial year to date (Q4 YTD = full financial year)
  period_start TEXT,
  period_end TEXT NOT NULL,
  months INTEGER,
  basis TEXT NOT NULL,                  -- Consolidated | Standalone
  taxonomy TEXT,                        -- INDAS | BANKING | NBFC_INDAS | LI | GI ... (from the XBRL file name)
  audited TEXT,
  revenue_cr REAL,                      -- revenue from operations (banks/insurers: total income as reported)
  other_income_cr REAL,
  total_income_cr REAL,
  finance_costs_cr REAL,
  depreciation_cr REAL,
  pbt_pre_exceptional_cr REAL,
  exceptional_cr REAL,
  pbt_cr REAL,
  tax_cr REAL,
  pat_cr REAL,
  pat_owners_cr REAL,
  ebitda_cr REAL,                       -- derived: pbt_pre_exceptional + finance_costs + depreciation - other_income
  ebit_cr REAL,                         -- derived: pbt_pre_exceptional + finance_costs - other_income
  paid_up_capital_cr REAL,
  face_value REAL,
  shares_outstanding REAL,              -- derived: paid-up equity capital / face value
  borrowings_cr REAL,                   -- balance sheet (half-year filings only): current + non-current borrowings
  cash_cr REAL,                         -- cash and equivalents + other bank balances + current investments
  equity_cr REAL,                       -- equity attributable to owners (or total equity when that is not tagged)
  total_assets_cr REAL,
  net_debt_cr REAL,                     -- derived: borrowings - cash_cr
  cfo_cr REAL,                          -- cash flow statement (half-year filings, YTD rows)
  capex_cr REAL,                        -- purchase of property, plant and equipment (+ intangibles where tagged), YTD rows
  bs_date TEXT,                         -- date of the balance sheet instant when present
  filing_date TEXT,
  xbrl_url TEXT NOT NULL,
  doc_id TEXT,
  source_id TEXT NOT NULL DEFAULT 'nse_financials',
  retrieved_at TEXT NOT NULL,
  UNIQUE (company_id, period_type, period_end, basis)
);
CREATE INDEX IF NOT EXISTS idx_company_financials_company ON company_financials(company_id, period_end);

CREATE TABLE IF NOT EXISTS company_segments (
  seg_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  period_type TEXT NOT NULL,
  period_end TEXT NOT NULL,
  basis TEXT NOT NULL,
  segment TEXT NOT NULL,
  revenue_cr REAL,
  result_cr REAL,                       -- segment result as reported (usually profit before interest and tax)
  xbrl_url TEXT NOT NULL,
  doc_id TEXT,
  retrieved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_company_segments_company ON company_segments(company_id, period_end);
