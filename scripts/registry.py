"""Source registry, taxonomy and investor-group seed. Loaded into the DB by seed(); edit here to expand."""
from common import connect, upsert, slug

# reliability: A official primary | B official secondary/aggregated | C announcement (reported, not verified deployment) | D unofficial | X not connected
SOURCES = [
 # id, name, category, url, publisher, official, reliability, schedule, max_age_days, status, credentials, limitations
 ("nse_universe", "Nifty 500 constituents + NSE sector index constituents", "public_equity", "https://archives.nseindia.com/content/indices/ind_nifty500list.csv", "NSE Indices", 1, "A", "monthly", 45, "not_built", None,
  "Listed universe = Nifty 500 (about 92% of NSE free-float market cap). Smaller listed and all unlisted companies only appear when they show up in deals or announcements. Sub-industry = NSE sectoral index membership where one exists."),
 ("nse_shp", "NSE quarterly shareholding patterns (XBRL)", "public_equity", "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern", "NSE / listed companies", 1, "A", "quarterly", 140, "not_built", None,
  "Holder categories and named holders above 1% only. A fund below 1% is invisible. Quarter-end snapshots: a change shows net position change, not trades; price moves do not change share %. Covers the Nifty 500."),
 ("nse_shp_master", "NSE shareholding summary history (promoter / public %)", "public_equity", "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern", "NSE", 1, "A", "quarterly", 140, "not_built", None,
  "Promoter and public % only, about 6 years of quarters."),
 ("nsdl_fpi_sector", "NSDL fortnightly sector-wise FPI investment", "public_equity", "https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx", "NSDL (depository, for SEBI)", 1, "A", "fortnightly", 25, "not_built", None,
  "Aggregate of all FPIs (no investor names). Net investment includes primary market and secondary trades. Assets under custody move with prices, so AUC change is not a flow."),
 ("nse_fiidii", "NSE provisional FII/DII cash-market flows", "public_equity", "https://www.nseindia.com/reports/fii-dii", "NSE", 1, "B", "daily", 5, "not_built", None,
  "Provisional, cash market only, one day at a time (history builds up from the first run on 22 Nov 2026). NSDL figures are final."),
 ("nse_deals", "NSE bulk and block deals", "public_equity", "https://www.nseindia.com/report-detail/display-bulk-and-block-deals", "NSE", 1, "A", "daily", 5, "not_built", None,
  "Only trades above 0.5% of a company's shares (bulk) or block-window trades. Many names are brokers, arbitrage or proprietary trading desks: these are flagged and excluded from conviction counts. ODI / P-note desks are not end-investors."),
 ("nse_announcements", "NSE corporate announcements (acquisitions, preferential issues, QIPs, capex, JVs)", "corporate", "https://www.nseindia.com/companies-listing/corporate-filings-announcements", "NSE / listed companies", 1, "C", "daily", 5, "not_built", None,
  "Company self-disclosures. Classified by NSE subject line with keyword rules; amounts are only taken when stated in the summary text, otherwise 'undisclosed'. Announced is not completed."),
 ("sebi_aif", "SEBI AIF commitments, funds raised and investments made", "private_markets", "https://www.sebi.gov.in/statistics/1392982252002.html", "SEBI", 1, "A", "quarterly", 140, "not_built", None,
  "Cumulative, by AIF category only (no fund or company names). Shows commitment vs raised vs invested separately."),
 ("sebi_pms", "SEBI portfolio managers monthly report (industry totals)", "private_markets", "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doPmr=yes", "SEBI", 1, "A", "monthly", 75, "not_built", None,
  "Industry totals only. Not built in v1 (form-driven page)."),
 ("amfi_monthly", "AMFI monthly mutual fund industry data", "public_equity", "https://www.amfiindia.com/research-information/amfi-monthly", "AMFI", 1, "A", "monthly", 45, "not_built", None,
  "Scheme-category net flows. Company-level MF changes come from shareholding patterns (MF % per company)."),
 ("amc_portfolios", "AMC monthly scheme portfolio files (umbrella)", "public_equity", "https://www.amfiindia.com/online-center/portfolio-disclosure", "Each AMC", 1, "A", "monthly", 45, "not_built", None,
  "Umbrella entry: each fund house is tracked as its own source (amc_<name>) below, so a blocked site shows as blocked rather than as zero holdings."),
 ('amc_sbi', 'SBI Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.sbimf.com/portfolios', 'SBI Mutual Fund', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. Files found by their fixed public naming pattern (the page builds links with a token-protected script); probed by HEAD request.'),
 ('amc_nippon', 'Nippon India Mutual Fund monthly scheme portfolios', "public_equity", 'https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures', 'Nippon India Mutual Fund', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades.'),
 ('amc_dsp', 'DSP Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.dspim.com/mandatory-disclosures/portfolio-disclosures', 'DSP Mutual Fund', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades.'),
 ('amc_ppfas', 'PPFAS Mutual Fund (Parag Parikh) monthly scheme portfolios', "public_equity", 'https://amc.ppfas.com/downloads/portfolio-disclosure/', 'PPFAS Mutual Fund (Parag Parikh)', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. One file per scheme. Foreign stocks in the Flexi Cap fund are not Indian ISINs and are left out.'),
 ('amc_absl', 'Aditya Birla Sun Life Mutual Fund monthly scheme portfolios', "public_equity", 'https://mutualfund.adityabirlacapital.com/forms-and-downloads/portfolio', 'Aditya Birla Sun Life Mutual Fund', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. Links appear only after the public page runs its script; read with a headless browser, files downloaded directly.'),
 ('amc_hdfc', 'HDFC Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio', 'HDFC Mutual Fund', 1, "A", "monthly", 45, 'blocked', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. Site returns HTTP 403 to automated requests; not bypassed.'),
 ('amc_icici', 'ICICI Prudential Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.icicipruamc.com/downloads/others/monthly-portfolio-disclosures', 'ICICI Prudential Mutual Fund', 1, "A", "monthly", 45, 'blocked', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. Site redirects/closes automated connections (HTTP 307 loop, connection closed in a headless browser); not bypassed.'),
 ('amc_kotak', 'Kotak Mahindra Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.kotakmf.com/Information/statutory-disclosure/portfolios', 'Kotak Mahindra Mutual Fund', 1, "A", "monthly", 45, 'blocked', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. Page is behind an hCaptcha challenge; not bypassed.'),
 ('amc_axis', 'Axis Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.axismf.com/statutory-disclosures', 'Axis Mutual Fund', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. No portfolio file links on the public page, even after its script runs (content served by a CMS API). Not built.'),
 ('amc_uti', 'UTI Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.utimf.com/downloads/consolidate-all-portfolio-disclosure', 'UTI Mutual Fund', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. No portfolio file links on the rendered public page. Not built.'),
 ('amc_mirae', 'Mirae Asset Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.miraeassetmf.co.in/downloads/portfolio', 'Mirae Asset Mutual Fund', 1, "A", "monthly", 45, 'not_built', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. One file per scheme behind a paged script listing; only fund-of-fund files appear on the first page. Not built yet.'),
 ('amc_tata', 'Tata Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.tatamutualfund.com/schemes-related/portfolio', 'Tata Mutual Fund', 1, "A", "monthly", 45, 'blocked', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. CDN returns HTTP 403 to automated requests; not bypassed.'),
 ('amc_edelweiss', 'Edelweiss Mutual Fund monthly scheme portfolios', "public_equity", 'https://www.edelweissmf.com/statutory/portfolio-of-schemes', 'Edelweiss Mutual Fund', 1, "A", "monthly", 45, 'blocked', None,
  'Scheme-level month-end holdings (SEBI-mandated monthly disclosure). Listed Indian equity rows only (ISIN INE...01). Index funds/ETFs flagged passive and arbitrage funds flagged arbitrage; both are left out of adds/exits and convergence. A change is the net change in shares held between two month-end files, not individual trades. Site returns HTTP 403 to automated requests; not bypassed.'),
 ("rbi_sibc", "RBI sectoral deployment of bank credit", "credit", "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx", "Reserve Bank of India", 1, "A", "monthly", 75, "not_built", None,
  "Outstanding credit (stock), not sanctions or disbursements. Cannot split new productive lending from refinancing or working capital."),
 ("dpiit_fdi", "DPIIT FDI factsheet (sector and state equity inflows)", "foreign_strategic", "https://dpiit.gov.in/publications/fdi-statistics", "DPIIT, Ministry of Commerce", 1, "A", "quarterly", 140, "not_built", None,
  "Equity inflows by DPIIT sector and state; cumulative since April 2000 and current FY. No investor or company names."),
 ("crisil_ratings", "CRISIL Ratings rating-rationale listing", "credit", "https://www.crisilratings.com/en/home/our-business/ratings/rating-rationale.html", "CRISIL Ratings (SEBI-registered CRA)", 1, "B", "daily", 10, "not_built", None,
  "Headline-level classification. ICRA, CARE and India Ratings are separate sources. Mostly MSME issuers; many 'Issuer Not Cooperating' moves (recorded, not scored)."),
 ("icra_ratings", "ICRA rating rationales (directional actions)", "credit", "https://www.icra.in/Rating/AllRatingRationales", "ICRA Limited (SEBI-registered CRA)", 1, "B", "weekly", 14, "not_built", None,
  "Headline from each public rationale page; the rationale PDF is read only for upgrades, downgrades, outlook and watch changes and defaults (for date and sector). Reaffirmations and new ratings are not stored. Sector is keyword-classified from the 'About the company' paragraph. Up to 450 rationale ids per weekly run."),
 ("care_ratings", "CARE Ratings (CareEdge) press releases", "credit", "https://www.careratings.com/", "CARE Ratings Limited (SEBI-registered CRA)", 1, "B", "weekly", 14, "not_built", None,
  "Latest press releases from the home page's public feed (about one month); each press-release PDF is read for the rating-action column and CARE's own industry classification. Many releases are 'Issuer Not Cooperating' continuations (recorded, not counted)."),
 ("indra_ratings", "India Ratings & Research rating-action commentaries", "credit", "https://www.indiaratings.co.in/raclisting/rac/all", "India Ratings & Research (Fitch group; SEBI-registered CRA)", 1, "B", "weekly", 14, "not_built", None,
  "Headline and the agency's own industry field from the public rating-action list. Headline-level classification."),
 ("pib_cabinet", "PIB press releases (Cabinet approvals, PLI, investment announcements)", "government_global", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3", "Press Information Bureau, GoI", 1, "C", "daily", 10, "not_built", None,
  "Government announcements: approved outlays are commitments, not money spent. Amount and sector are rule-extracted from the release text and link to it."),
 ("worldbank", "World Bank World Development Indicators (India)", "government_global", "https://api.worldbank.org/v2/country/IND/indicator", "World Bank", 1, "B", "annual", 500, "not_built", None,
  "Annual, 1-2 year lag."),
 ("fred", "FRED (US Federal Reserve Bank of St. Louis): US rates, dollar, Brent, IMF primary commodity prices, US industrial production", "government_global", "https://fred.stlouisfed.org/", "FRED", 1, "B", "daily", 10, "not_built", None, "Global backdrop only."),
 ("nse_sector_pe", "NSE Indices sector index P/E history", "public_equity", "https://www.niftyindices.com/reports/historical-data", "NSE Indices", 1, "A", "daily", 7, "not_built", None,
  "Sector-level valuation context only (index P/E vs its own history). Not a view on any company."),
 ("imf_datamapper", "IMF DataMapper API", "government_global", "https://www.imf.org/external/datamapper/api/v1/", "IMF", 1, "B", "annual", 400, "blocked", None,
  "Returns 'Access Denied' to automated requests from this server (checked 22 Nov 2026)."),
 ("bse_deals", "BSE bulk/block deals API", "public_equity", "https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx", "BSE", 1, "A", "daily", 5, "blocked", None,
  "BSE API returns 'Access Denied' to automated requests (checked 22 Nov 2026). NSE deals are used."),
 # paid / credentialed private-market sources: connector stubs
 ("tracxn", "Tracxn private company and funding database", "private_markets", "https://tracxn.com/", "Tracxn (paid)", 0, "X", "weekly", None, "needs_credentials", "TRACXN_API_KEY (paid enterprise API)", "Paid. Connector interface built (scripts/connectors_paid.py); not connected."),
 ("venture_intelligence", "Venture Intelligence PE/VC deal database", "private_markets", "https://www.ventureintelligence.com/", "TSJ Media (paid)", 0, "X", "weekly", None, "needs_credentials", "VI_USERNAME + VI_PASSWORD or API token (paid subscription)", "Paid. Connector interface built; not connected."),
 ("vccedge", "VCCEdge deal database", "private_markets", "https://www.vccedge.com/", "VCCircle (paid)", 0, "X", "weekly", None, "needs_credentials", "VCCEDGE_API_KEY (paid)", "Paid. Connector interface built; not connected."),
 ("mca21", "MCA21 company filings (allotments, charges, financials)", "private_markets", "https://www.mca.gov.in/", "Ministry of Corporate Affairs", 1, "X", "weekly", None, "needs_credentials", "MCA21 V3 user login; document downloads are paid per company", "Login and per-document fees. Bulk access is not permitted for free; not connected."),
 ("ivca_ey", "IVCA-EY PE/VC monthly roundups", "private_markets", "https://www.ivca.in/", "IVCA / EY", 0, "D", "monthly", None, "not_built", None, "PDF reports; aggregates reported by an industry body. Not ingested in v1."),
 ("swf_disclosures", "Sovereign wealth / pension fund portfolio disclosures (GIC, Norges, CPPIB, ADIA)", "foreign_strategic", "https://www.nbim.no/en/investments/all-investments/", "Each fund", 1, "B", "annual", None, "not_built", None, "Not ingested in v1. Named SWF/pension holdings above 1% in Nifty 500 companies already appear via shareholding patterns."),
 # ---- Sprint 2: fundamentals, trade, production / capacity, global developments
 ("nse_financials", "NSE integrated filing - financial results (XBRL), Nifty 500", "corporate", "https://www.nseindia.com/companies-listing/corporate-integrated-filing", "NSE / listed companies", 1, "A", "weekly", 120, "not_built", None,
  "Quarterly results as tagged in the company's XBRL (consolidated when filed, else standalone). SEBI integrated filing starts with the quarter ended Mar-2025, so about 7 quarters of history. Balance sheet and cash flow only in half-year (Sep/Mar) filings. EBITDA, EBIT, shares and net debt are derived with stated formulas; operating-profit formulas are not applied to banks, NBFCs or insurers. Lease liabilities are not included in net debt."),
 ("nse_bhavcopy", "NSE daily bhavcopy (closing prices)", "public_equity", "https://nsearchives.nseindia.com/content/cm/", "NSE", 1, "A", "daily", 7, "not_built", None,
  "Closing price used only to estimate market capitalisation = shares (paid-up capital / face value from the latest filing) x close. Labelled as an estimate."),
 ("tradestat_eidb", "Ministry of Commerce TradeStat (Export-Import Data Bank), HS 2-digit", "government_global", "https://tradestat.commerce.gov.in/eidb/commodity_wise_export", "Department of Commerce (DGCI&S data)", 1, "A", "annual", 400, "not_built", None,
  "Financial-year totals by HS chapter in US$ million (fiscal years 2017-18 onwards). The current year in progress is not in the annual tables. HS chapters are mapped to NSE sectors with a fixed table; one chapter can feed several sectors."),
 ("un_comtrade", "UN Comtrade public preview API (India, HS 2-digit, world partner)", "government_global", "https://comtradeapi.un.org/public/v1/preview/C/A/HS", "United Nations Statistics Division", 1, "B", "annual", 500, "not_built", None,
  "Free preview tier: annual data, 500 records per call, no key. Used as a cross-check on TradeStat and for the latest calendar year India reported to the UN."),
 ("mospi_iip", "MoSPI Index of Industrial Production (monthly, sectoral, NIC 2-digit and use-based)", "government_global", "https://api.mospi.gov.in/api/iip/getIipData", "MoSPI (NSO)", 1, "A", "monthly", 75, "not_built", None,
  "Quick estimates are revised in later months. Base 2022-23 from 2023 onwards; base 2011-12 for older months (indices are not comparable across bases, growth rates are). Industry-to-sector mapping is a fixed table."),
 ("rbi_obicus", "RBI Order Books, Inventories and Capacity Utilisation Survey (OBICUS)", "government_global", "https://www.rbi.org.in/scripts/QuarterlyPublications.aspx?head=Quarterly+Order+Books%2C+Inventories+and+Capacity+Utilisation+Survey", "Reserve Bank of India", 1, "A", "quarterly", 150, "not_built", None,
  "Aggregate manufacturing capacity utilisation (and seasonally adjusted), about 1,000 responding companies; no sector split is published in the release. Survey responses, not audited data."),
 ("oea_core8", "Office of Economic Adviser - Index of Eight Core Industries", "government_global", "https://eaindustry.nic.in/", "DPIIT Office of Economic Adviser", 1, "A", "monthly", 60, "blocked", None,
  "eaindustry.nic.in did not answer from the pipeline network (connection timeouts). Not bypassed. IIP sectoral data covers electricity, mining and the manufacturing industries in the meantime."),
 ("jpc_steel", "Joint Plant Committee steel production and consumption", "government_global", "https://jpcindia.nic.in/", "Ministry of Steel (JPC)", 1, "A", "monthly", 60, "blocked", None,
  "Site did not answer from the pipeline network. Not bypassed. IIP 'Manufacture of Basic Metals' is used as the production proxy."),
 ("cea_power", "Central Electricity Authority generation / installed capacity reports", "government_global", "https://cea.nic.in/", "Ministry of Power (CEA)", 1, "A", "monthly", 60, "not_built", None,
  "Reachable, but published as PDF/Excel report pages that change layout; not built in Sprint 2. IIP electricity indices are used instead."),
 ("coal_ministry", "Ministry of Coal production and despatch", "government_global", "https://coal.gov.in/", "Ministry of Coal", 1, "A", "monthly", 60, "not_built", None,
  "Reachable, but monthly figures are in PDF notes; not built. IIP 'Fuel Minerals' is used as the coal/lignite production proxy."),
 ("fert_production", "Department of Fertilizers production statistics", "government_global", "https://www.fert.nic.in/", "Ministry of Chemicals & Fertilizers", 1, "A", "monthly", 60, "blocked", None,
  "Site did not answer from the pipeline network. Not bypassed."),
 ("wto_timeseries", "WTO Timeseries API (tariffs, trade)", "government_global", "https://apiportal.wto.org/", "World Trade Organization", 1, "A", "annual", 400, "needs_credentials", "Free WTO API subscription key",
  "Returns 401 without a key. Not used until a key is added as a repository secret."),
 ("eia_api", "US EIA Open Data API (energy)", "government_global", "https://www.eia.gov/opendata/", "US Energy Information Administration", 1, "A", "monthly", 60, "needs_credentials", "Free EIA API key",
  "Returns 403 without a key. Brent and global energy prices come from FRED / IMF primary commodity series instead."),
 ("iea_data", "IEA data and statistics", "government_global", "https://www.iea.org/data-and-statistics", "International Energy Agency", 1, "A", "annual", 400, "not_built", None,
  "Most IEA datasets need a paid licence; not used."),
]

INDUSTRIES = ["Automobile and Auto Components", "Capital Goods", "Chemicals", "Construction", "Construction Materials", "Consumer Durables",
              "Consumer Services", "Diversified", "Fast Moving Consumer Goods", "Financial Services", "Forest Materials", "Healthcare",
              "Information Technology", "Media, Entertainment & Publication", "Metals & Mining", "Oil, Gas & Consumable Fuels", "Power",
              "Realty", "Services", "Telecommunication", "Textiles", "Utilities",
              # outside the NSE listed taxonomy (credit / FDI / government streams)
              "Agriculture and Allied", "Infrastructure (cross-sector)", "Trade (wholesale and retail)", "Personal / Retail Loans", "Sovereign", "Others"]

SUB_INDUSTRIES = {  # NSE sectoral / thematic index -> (industry, label)
    "niftybank": ("Financial Services", "Banks (Nifty Bank)"), "niftypsubank": ("Financial Services", "Public sector banks (Nifty PSU Bank)"),
    "niftyfinance": ("Financial Services", "Financial services ex-banks and banks (Nifty Financial Services)"),
    "niftyit": ("Information Technology", "IT services (Nifty IT)"), "niftypharma": ("Healthcare", "Pharmaceuticals (Nifty Pharma)"),
    "niftyhealthcare": ("Healthcare", "Healthcare (Nifty Healthcare)"), "niftyauto": ("Automobile and Auto Components", "Automobiles (Nifty Auto)"),
    "niftymetal": ("Metals & Mining", "Metals (Nifty Metal)"), "niftyrealty": ("Realty", "Real estate developers (Nifty Realty)"),
    "niftyoilgas": ("Oil, Gas & Consumable Fuels", "Oil and gas (Nifty Oil & Gas)"), "niftyfmcg": ("Fast Moving Consumer Goods", "FMCG (Nifty FMCG)"),
    "niftymedia": ("Media, Entertainment & Publication", "Media (Nifty Media)"), "niftyconsumerdurables": ("Consumer Durables", "Consumer durables (Nifty Consumer Durables)"),
}

# Parent groups. 'rx' = regex on upper-case disclosed name. Order matters (first match wins).
# category per schema; passive/trading flags exclude a group from conviction / convergence counts.
GROUPS = [
 # trading / market-making / arbitrage / ODI desks (not end-investors)
 ("trading_firms", "Proprietary trading / market-making firms (combined)", "trading_firm", None, 0, 1,
  r"GRAVITON|ALPHAGREP|JUMP TRADING|TOWER RESEARCH|HRTI|QE SECURITIES|JUNOMONETA|NK SECURITIES|MATHISYS|IRAGE|SILVERLEAF|XTX|VIRTU|OPTIVER|DOLAT|PACE STOCK|MICROCURVES|SHARE INDIA|ELIXIR WEALTH|PLUTUS|QUADEYE|TRANSACT|ESPRESSO|NEXTGEN|WORLDQUANT|CITADEL SECURITIES|SUSQUEHANNA|BEACON STOCK|SPARK FINANCIAL|PARK ACCORD|DRW |MANSI SHARE|HEADSTART"),
 ("odi_desks", "Bank ODI / arbitrage desks (P-notes, derivatives hedging)", "trading_firm", None, 0, 1,
  r"\bODI\b|ARBITRAGE|SOCIETE GENERALE|COPTHALL|CITIGROUP GLOBAL MARKETS|BOFA SECURITIES|MERRILL LYNCH|MORGAN STANLEY ASIA|GOLDMAN SACHS \(SINGAPORE\)|J\.?P\.? ?MORGAN SECURITIES|BNP PARIBAS FINANCIAL MARKETS|NOMURA SINGAPORE|MACQUARIE BANK|UBS AG|CLSA"),
 ("brokers_prop", "Stock brokers / proprietary trading desks (name rule)", "trading_firm", None, 0, 1,
  r"SHARES? (AND|&) |SHARE BROK|SHARES? LTD|SHARES? PRIVATE|SECURITIES|BROKING|BROKERS|STOCK BROK|STOCKS? |COMMODIT|CAPITAL MARKETS?|TRADING|MARKETS? LLP|MARKETEDGE|QUANT RESEARCH|BLITZQUANT|QICAP|INTERMEDIAR|FINSTOCK|EQUITIES|DERIVATIVE|RESEARCH TECH|ALGO|HFT|FINVEST|FINCAP|ARBITRAGE"),
 ("passive_vehicles", "Index funds / ETFs (passive)", "mutual_fund", None, 1, 0, r"\bETF\b|INDEX FUND|\bINDEX\b|ISHARES|VANGUARD|SPDR|NIFTY 50|NIFTY50|BHARAT BOND|CPSE ETF|SENSEX"),
 ("sbi", "SBI group (SBI Funds, SBI Life, SBI General)", "mutual_fund", "India", 0, 0, r"^SBI |STATE BANK OF INDIA|SBI MUTUAL|SBI LIFE|SBI GENERAL"),
 ("icici", "ICICI group (ICICI Prudential AMC, ICICI Prudential Life, ICICI Lombard)", "mutual_fund", "India", 0, 0, r"ICICI"),
 ("hdfc", "HDFC group (HDFC AMC, HDFC Life, HDFC Ergo)", "mutual_fund", "India", 0, 0, r"\bHDFC"),
 ("kotak", "Kotak group (Kotak AMC, Kotak Life)", "mutual_fund", "India", 0, 0, r"KOTAK"),
 ("nippon", "Nippon Life India AMC", "mutual_fund", "India/Japan", 0, 0, r"NIPPON"),
 ("aditya_birla", "Aditya Birla group (ABSL AMC, ABSL Life)", "mutual_fund", "India", 0, 0, r"ADITYA BIRLA"),
 ("axis", "Axis group (Axis AMC, Axis Max Life)", "mutual_fund", "India", 0, 0, r"^AXIS |AXIS MUTUAL|AXIS MAX"),
 ("uti", "UTI AMC", "mutual_fund", "India", 0, 0, r"^UTI |UTI MUTUAL|UTI-"),
 ("mirae", "Mirae Asset", "mutual_fund", "Korea", 0, 0, r"MIRAE"),
 ("dsp", "DSP AMC", "mutual_fund", "India", 0, 0, r"^DSP |DSP MUTUAL|DSP BLACKROCK"),
 ("tata", "Tata group (Tata AMC, Tata AIA Life)", "mutual_fund", "India", 0, 0, r"^TATA (MUTUAL|AIA|ASSET|AIG)|TATA MF"),
 ("franklin", "Franklin Templeton", "mutual_fund", "USA", 0, 0, r"FRANKLIN|TEMPLETON"),
 ("motilal", "Motilal Oswal group", "mutual_fund", "India", 0, 0, r"MOTILAL OSWAL"),
 ("quant", "Quant AMC", "mutual_fund", "India", 0, 0, r"^QUANT (MUTUAL|MF)|QUANT MUTUAL"),
 ("ppfas", "PPFAS AMC (Parag Parikh)", "mutual_fund", "India", 0, 0, r"PPFAS|PARAG PARIKH"),
 ("invesco", "Invesco", "mutual_fund", "USA", 0, 0, r"INVESCO"),
 ("canara_robeco", "Canara Robeco AMC", "mutual_fund", "India", 0, 0, r"CANARA ROBECO"),
 ("edelweiss", "Edelweiss group", "mutual_fund", "India", 0, 0, r"EDELWEISS"),
 ("bandhan", "Bandhan AMC", "mutual_fund", "India", 0, 0, r"BANDHAN"),
 ("hsbc", "HSBC group", "mutual_fund", "UK", 0, 0, r"HSBC"),
 ("sundaram", "Sundaram AMC", "mutual_fund", "India", 0, 0, r"SUNDARAM"),
 ("whiteoak", "WhiteOak Capital", "mutual_fund", "India", 0, 0, r"WHITEOAK|WHITE OAK"),
 ("bajaj", "Bajaj Finserv group (AMC, Bajaj Allianz)", "mutual_fund", "India", 0, 0, r"BAJAJ (FINSERV|ALLIANZ)"),
 ("mahindra", "Mahindra Manulife AMC", "mutual_fund", "India", 0, 0, r"MAHINDRA MANULIFE"),
 ("lic", "Life Insurance Corporation of India (incl. LIC MF)", "insurance", "India", 0, 0, r"LIFE INSURANCE CORPORATION|^LIC "),
 ("gic_re", "General Insurance Corporation of India", "insurance", "India", 0, 0, r"GENERAL INSURANCE CORPORATION"),
 ("nia", "The New India Assurance", "insurance", "India", 0, 0, r"NEW INDIA ASSURANCE"),
 ("max_life", "Max Financial / Axis Max Life", "insurance", "India", 0, 0, r"MAX LIFE"),
 ("nps", "NPS Trust (National Pension System)", "pension", "India", 0, 0, r"NPS TRUST|NATIONAL PENSION"),
 ("epfo", "EPFO", "pension", "India", 0, 0, r"EMPLOYEES PROVIDENT FUND|EPFO"),
 ("gic_sg", "GIC (Government of Singapore)", "swf", "Singapore", 0, 0, r"GOVERNMENT OF SINGAPORE"),
 ("mas", "Monetary Authority of Singapore", "swf", "Singapore", 0, 0, r"MONETARY AUTHORITY OF SINGAPORE"),
 ("adia", "Abu Dhabi Investment Authority", "swf", "UAE", 0, 0, r"ABU DHABI INVESTMENT AUTHORITY"),
 ("kia", "Kuwait Investment Authority", "swf", "Kuwait", 0, 0, r"KUWAIT INVESTMENT AUTHORITY"),
 ("qia", "Qatar Investment Authority", "swf", "Qatar", 0, 0, r"QATAR INVESTMENT AUTHORITY|QIA "),
 ("mubadala", "Mubadala", "swf", "UAE", 0, 0, r"MUBADALA"),
 ("pif", "Public Investment Fund (Saudi Arabia)", "swf", "Saudi Arabia", 0, 0, r"PUBLIC INVESTMENT FUND"),
 ("norges", "Norges Bank (Government Pension Fund Global)", "swf", "Norway", 0, 0, r"GOVERNMENT PENSION FUND GLOBAL|NORGES BANK"),
 ("temasek", "Temasek", "swf", "Singapore", 0, 0, r"TEMASEK"),
 ("cppib", "Canada Pension Plan Investment Board", "global_pension", "Canada", 0, 0, r"CANADA PENSION PLAN"),
 ("cdpq", "CDPQ (Caisse de depot et placement du Quebec)", "global_pension", "Canada", 0, 0, r"CAISSE DE DEPOT|CDPQ"),
 ("otpp", "Ontario Teachers' Pension Plan", "global_pension", "Canada", 0, 0, r"ONTARIO TEACHERS"),
 ("omers", "OMERS", "global_pension", "Canada", 0, 0, r"OMERS"),
 ("blackstone", "Blackstone", "pe", "USA", 0, 0, r"BLACKSTONE|\bBCP\b"),
 ("kkr", "KKR", "pe", "USA", 0, 0, r"\bKKR\b"),
 ("brookfield", "Brookfield", "infra_fund", "Canada", 0, 0, r"BROOKFIELD"),
 ("carlyle", "Carlyle", "pe", "USA", 0, 0, r"CARLYLE|\bCA [A-Z]+ INVESTMENTS"),
 ("warburg", "Warburg Pincus", "pe", "USA", 0, 0, r"WARBURG"),
 ("tpg", "TPG", "pe", "USA", 0, 0, r"\bTPG\b"),
 ("bain", "Bain Capital", "pe", "USA", 0, 0, r"BAIN CAPITAL|\bBC ASIA"),
 ("advent", "Advent International", "pe", "USA", 0, 0, r"ADVENT"),
 ("chryscapital", "ChrysCapital", "pe", "India", 0, 0, r"CHRYS"),
 ("peakxv", "Peak XV / Sequoia India", "vc", "India", 0, 0, r"PEAK XV|SEQUOIA|\bSCI INVESTMENTS"),
 ("softbank", "SoftBank", "growth", "Japan", 0, 0, r"SOFTBANK|SVF "),
 ("tiger", "Tiger Global", "growth", "USA", 0, 0, r"TIGER GLOBAL|INTERNET FUND"),
 ("fidelity", "Fidelity (FMR / FIL)", "fpi", "USA", 0, 0, r"FIDELITY|\bFMR\b|\bFIL "),
 ("capital_group", "Capital Group", "fpi", "USA", 0, 0, r"CAPITAL GROUP|NEW WORLD FUND|SMALLCAP WORLD|EUROPACIFIC|AMERICAN FUNDS"),
 ("blackrock", "BlackRock (active)", "fpi", "USA", 0, 0, r"BLACKROCK"),
 ("goldman_am", "Goldman Sachs Asset Management", "fpi", "USA", 0, 0, r"GOLDMAN SACHS"),
 ("morgan_stanley_im", "Morgan Stanley Investment Management", "fpi", "USA", 0, 0, r"MORGAN STANLEY"),
 ("nomura", "Nomura", "fpi", "Japan", 0, 0, r"NOMURA"),
 ("abu_dhabi_fund", "Abu Dhabi entities (other)", "swf", "UAE", 0, 0, r"ABU DHABI"),
 ("ifc", "International Finance Corporation (World Bank group)", "dfi", "Global", 0, 0, r"INTERNATIONAL FINANCE CORPORATION"),
 ("adb", "Asian Development Bank", "dfi", "Global", 0, 0, r"ASIAN DEVELOPMENT BANK"),
 ("niif", "National Investment and Infrastructure Fund", "infra_fund", "India", 0, 0, r"NATIONAL INVESTMENT AND INFRASTRUCTURE|\bNIIF"),
 ("president_india", "Government of India (President of India)", "government", "India", 0, 0, r"PRESIDENT OF INDIA|GOVERNMENT OF INDIA"),
]

INST_HINTS = [  # category by name suffix for names without a known parent (group = the entity itself)
    (r"MUTUAL FUND|\bMF\b|ASSET MANAGEMENT", "mutual_fund"), (r"INSURANCE|ASSURANCE|LIFE ", "insurance"),
    (r"PENSION|PROVIDENT", "pension"), (r"\bAIF\b|ALTERNATIVE INVESTMENT|CATEGORY (I|II|III)|SCHEME|TRUST", "aif"),
    (r"PTE\.? ?LTD|LLC|\bL\.?P\.?\b|MAURITIUS|SINGAPORE|CAYMAN|LUXEMBOURG|IRELAND|OFFSHORE|FUND\b|FUNDS\b|\bPLC\b|\bINC\b|S\.A\.|SICAV|N\.V\.", "fpi"),
    (r"BANK", "bank_nbfc"), (r"PRIVATE LIMITED|PVT\.? LTD|LIMITED|\bLTD\b|LLP", "corporate"),
]


def seed():
    con = connect()
    for s in SOURCES:
        sid, name, cat, url, pub, off, rel, sch, age, status, cred, lim = s
        ex = con.execute("SELECT status,last_success FROM sources WHERE source_id=?", (sid,)).fetchone()
        if ex:  # keep runtime status, refresh descriptive fields
            con.execute("UPDATE sources SET name=?,category=?,url=?,publisher=?,official=?,reliability=?,refresh_schedule=?,max_age_days=?,credentials_needed=?,limitations=? WHERE source_id=?",
                        (name, cat, url, pub, off, rel, sch, age, cred, lim, sid))
            if status in ("blocked", "needs_credentials"):
                con.execute("UPDATE sources SET status=? WHERE source_id=? AND last_success IS NULL", (status, sid))
        else:
            upsert(con, "sources", dict(source_id=sid, name=name, category=cat, url=url, publisher=pub, official=off, reliability=rel,
                                        refresh_schedule=sch, max_age_days=age, status=status, credentials_needed=cred, limitations=lim), "source_id")
    for n in INDUSTRIES:
        upsert(con, "industries", dict(industry_id=slug(n), name=n, description=None), "industry_id")
    for k, (ind, lab) in SUB_INDUSTRIES.items():
        upsert(con, "sub_industries", dict(sub_industry_id=k, industry_id=slug(ind), name=lab, basis="NSE sectoral index constituent list"), "sub_industry_id")
    for g in GROUPS:
        gid, name, cat, country, passive, trading, rx = g
        upsert(con, "investor_groups", dict(group_id=gid, name=name, category=cat, country=country, aum_disclosed=None, passive_flag=passive,
                                            trading_flag=trading, notes="name rule: " + rx[:120], source_url=None), "group_id")
    con.commit(); con.close()


if __name__ == "__main__":
    seed(); print("seeded")
