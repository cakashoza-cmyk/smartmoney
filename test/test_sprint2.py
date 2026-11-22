"""Sprint 2: XBRL financials parsing and derived formulas, industry parsers and mappings, new signal rules, stage criteria.
Fixtures are synthetic and small; no network access. Every derived number must follow the stated formula exactly."""
import json, shutil, sqlite3, sys, tempfile, unittest
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402
import ingest_financials as IF  # noqa: E402
import ingest_industry as II  # noqa: E402
from intelligence import fundamentals as F  # noqa: E402
from intelligence.signal_detector import Detector, RULES, COMMODITY_SECTORS  # noqa: E402
from intelligence.opportunity_graph import SIGNAL_DIMENSION, STAGE_CRITERIA  # noqa: E402

CR = 1e7


def xbrl(start, end, vals_q, vals_ytd=None, ytd_start=None, bs=None, segs=None):
    ctx = [f'<xbrli:context id="OneD"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>']
    facts = [f'<in-capmkt:{k} contextRef="OneD" unitRef="INR" decimals="-5">{v}</in-capmkt:{k}>' for k, v in vals_q.items()]
    if vals_ytd:
        ctx.append(f'<xbrli:context id="FourD"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{ytd_start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')
        facts += [f'<in-capmkt:{k} contextRef="FourD" unitRef="INR" decimals="-5">{v}</in-capmkt:{k}>' for k, v in vals_ytd.items()]
    if bs:
        ctx.append(f'<xbrli:context id="OneI"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>')
        facts += [f'<in-capmkt:{k} contextRef="OneI" unitRef="INR" decimals="-5">{v}</in-capmkt:{k}>' for k, v in bs.items()]
    for i, (name, rev, res) in enumerate(segs or [], 1):
        for cid, tag, val in ((f"R{i}", "SegmentRevenue", rev), (f"S{i}", "SegmentProfitLossBeforeTaxAndFinanceCosts", res)):
            ctx.append(f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period><xbrli:scenario><xbrldi:explicitMember dimension="a">m{i}</xbrldi:explicitMember></xbrli:scenario></xbrli:context>')
            facts.append(f'<in-capmkt:DescriptionOfReportableSegment contextRef="{cid}">{name}</in-capmkt:DescriptionOfReportableSegment>')
            facts.append(f'<in-capmkt:{tag} contextRef="{cid}" unitRef="INR" decimals="-5">{val}</in-capmkt:{tag}>')
    return ('<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-capmkt="http://x" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
            + "".join(ctx) + "".join(facts) + "</xbrli:xbrl>")


P_L = {"RevenueFromOperations": 1000 * CR, "OtherIncome": 50 * CR, "FinanceCosts": 20 * CR, "DepreciationDepletionAndAmortisationExpense": 30 * CR,
       "ProfitBeforeExceptionalItemsAndTax": 200 * CR, "ProfitBeforeTax": 200 * CR, "TaxExpense": 50 * CR, "ProfitLossForPeriod": 150 * CR,
       "PaidUpValueOfEquityShareCapital": 100 * CR, "FaceValueOfEquityShareCapital": 10}


class Xbrl(unittest.TestCase):
    def test_quarter_ytd_balance_sheet_and_formulas(self):
        x = xbrl("2026-07-01", "2026-09-30", P_L, {**P_L, "RevenueFromOperations": 1900 * CR, "CashFlowsFromUsedInOperatingActivities": 300 * CR,
                                                    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": 120 * CR}, "2026-04-01",
                 {"BorrowingsCurrent": 100 * CR, "BorrowingsNoncurrent": 400 * CR, "CashAndCashEquivalents": 60 * CR, "BankBalanceOtherThanCashAndCashEquivalents": 20 * CR,
                  "CurrentInvestments": 20 * CR, "EquityAttributableToOwnersOfParent": 2000 * CR},
                 [("Alpha", 600 * CR, 120 * CR), ("Beta", 400 * CR, 80 * CR)])
        rows, segs = IF.extract(x)
        q = next(r for r in rows if r["period_type"] == "Q"); y = next(r for r in rows if r["period_type"] == "YTD")
        self.assertEqual((q["months"], y["months"]), (3, 6))
        self.assertAlmostEqual(q["ebitda_cr"], 200 + 20 + 30 - 50)  # PBT pre-exceptional + finance + D&A - other income
        self.assertAlmostEqual(q["ebit_cr"], 200 + 20 - 50)
        self.assertAlmostEqual(q["shares_outstanding"], 100 * CR / 10)
        self.assertAlmostEqual(q["net_debt_cr"], 500 - 100)
        self.assertIsNone(q["capex_cr"], "cash flow is year-to-date only")
        self.assertAlmostEqual(y["capex_cr"], 120); self.assertAlmostEqual(y["cfo_cr"], 300)
        self.assertEqual({s["segment"]: (s["revenue_cr"], s["result_cr"]) for s in segs}, {"Alpha": (600, 120), "Beta": (400, 80)})

    def test_missing_tags_stay_null_and_bad_face_value_is_dropped(self):
        x = xbrl("2026-04-01", "2026-06-30", {"RevenueFromOperations": 10 * CR, "PaidUpValueOfEquityShareCapital": 5 * CR, "FaceValueOfEquityShareCapital": 1586949})
        rows, _ = IF.extract(x)
        q = rows[0]
        self.assertIsNone(q["ebitda_cr"]); self.assertIsNone(q["pat_cr"]); self.assertIsNone(q["net_debt_cr"])
        self.assertIsNone(q["shares_outstanding"], "a face value outside 0.01-1000 is a filing error; shares are not derived")
        self.assertEqual(len(rows), 2, "Q1: the year-to-date row equals the quarter")

    def test_pick_prefers_consolidated_and_latest_revision(self):
        f = [{"qe_Date": "30-SEP-2026", "consolidated": "Standalone", "broadcast_Date": "02-Nov-2026 18:55:40", "xbrl": "https://x/xbrl/a.xml"},
             {"qe_Date": "30-SEP-2026", "consolidated": "Consolidated", "broadcast_Date": "02-Nov-2026 18:55:59", "xbrl": "https://x/xbrl/b.xml"},
             {"qe_Date": "30-SEP-2026", "consolidated": "Consolidated", "broadcast_Date": "05-Nov-2026 10:00:00", "xbrl": "https://x/xbrl/c.xml"}]
        self.assertEqual([x["xbrl"] for x in IF.pick(f)], ["https://x/xbrl/c.xml"])
        self.assertEqual(IF.taxonomy("https://n/INTEGRATED_FILING_NBFC_INDAS_1742040_19102026075918_WEB.xml"), "NBFC_INDAS")


class Returns(unittest.TestCase):
    def test_roce_roic_incremental(self):
        fy = [{"period_end": "2025-03-31", "ebit_cr": 100.0, "pbt_cr": 90.0, "tax_cr": 22.5, "equity_cr": 400.0, "borrowings_cr": 100.0, "net_debt_cr": 50.0},
              {"period_end": "2026-03-31", "ebit_cr": 130.0, "pbt_cr": 120.0, "tax_cr": 30.0, "equity_cr": 500.0, "borrowings_cr": 100.0, "net_debt_cr": 50.0}]
        r = F.returns(fy, False)
        self.assertAlmostEqual(r["roce_pct"], round(100 * 130 / ((500 + 600) / 2), 1))
        n1 = 130 * (1 - 0.25); n0 = 100 * (1 - 0.25)
        self.assertAlmostEqual(r["roic_pct"], round(100 * n1 / ((450 + 550) / 2), 1))
        self.assertAlmostEqual(r["incremental_roic_pct"], round(100 * (n1 - n0) / (550 - 450), 1))

    def test_not_meaningful_cases(self):
        fy = [{"period_end": "2025-03-31", "ebit_cr": 100.0, "pbt_cr": 90.0, "tax_cr": 22.5, "equity_cr": 500.0, "borrowings_cr": 0.0, "net_debt_cr": 0.0},
              {"period_end": "2026-03-31", "ebit_cr": 130.0, "pbt_cr": -5.0, "tax_cr": 1.0, "equity_cr": 400.0, "borrowings_cr": 0.0, "net_debt_cr": 0.0}]
        r = F.returns(fy, False)
        self.assertIsNone(r["roic_pct"], "loss year: no tax rate, no ROIC")
        self.assertIsNone(r["incremental_roic_pct"])
        self.assertIsNotNone(r["roce_pct"])
        self.assertIsNone(F.returns(fy, True)["roce_pct"], "lenders/insurers: not computed")
        self.assertIsNone(F.returns(fy[:1], False)["roce_pct"], "one year only: insufficient data")


class Industry(unittest.TestCase):
    def test_mappings(self):
        self.assertNotIn("power", II.HS_SECTOR["27"]); self.assertNotIn("telecommunication", II.HS_SECTOR["85"])
        self.assertEqual(II.iip_sectors("manufacturing_manufacture_of_basic_metals"), ["metals_mining"])
        self.assertEqual(II.iip_sectors("electricity_gas_supply_electricity"), ["power"])
        self.assertEqual(II.iip_sectors("use_based_capital_goods"), ["capital_goods"])
        self.assertEqual(II.iip_sectors("general"), [])
        self.assertEqual(II.iip_sectors("electricity_gas_supply_gas_supply"), ["oil_gas_consumable_fuels"])
        self.assertEqual(II.iip_sectors("mining_quarrying_non_metallic_minerals_incl_minor_minerals"), [])
        self.assertEqual(II.iip_sectors("electricity_gas_supply"), [], "category totals are not mapped")
        for sid, (_, secs) in COMMODITY_SECTORS.items():
            self.assertTrue(secs and all(len(x) == 2 for x in secs), sid)

    def test_quarter_and_month_helpers(self):
        self.assertEqual(II._q_end("Q1:2026-27"), "2026-06-30"); self.assertEqual(II._q_end("Q4:2025-26"), "2026-03-31")
        self.assertEqual(II._month_end(2026, 2), "2026-02-28"); self.assertEqual(II._month_end(2025, 12), "2025-12-31")
        self.assertEqual(II.iip_key({"type": "Sectoral", "category": "Manufacturing", "sub_category": "Manufacture of Basic Metals"}), "manufacturing_manufacture_of_basic_metals")


class Rules(unittest.TestCase):
    """New rules on a fresh database seeded with a few observations."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()); cls.con = sqlite3.connect(cls.tmp / "t.db")
        cls.con.executescript((ROOT / "schema.sql").read_text()); migrate.apply_all(cls.con)
        c = cls.con
        for sid in ("rbi_obicus", "fred", "tradestat_eidb", "mospi_iip"):
            c.execute("INSERT INTO sources(source_id,name,category,reliability,status) VALUES (?,?,?,?,?)", (sid, sid, "government_global", "A", "working"))
        c.execute("INSERT INTO source_documents(doc_id,source_id,url,retrieved_at) VALUES ('d1','rbi_obicus','https://rbi/x','2026-11-01')")
        c.execute("INSERT INTO source_documents(doc_id,source_id,url,retrieved_at) VALUES ('d2','fred','https://fred/x','2026-11-01')")
        c.execute("INSERT INTO source_documents(doc_id,source_id,url,retrieved_at) VALUES ('d3','tradestat_eidb','https://ts/x','2026-11-01')")
        c.execute("INSERT INTO observations(obs_id,source_id,metric,entity_type,entity_id,period_end,value,doc_id) VALUES ('o1','rbi_obicus','obicus_cu_sa_pct','market','india_manufacturing','2026-06-30',76.3,'d1')")
        for i, (pe, v) in enumerate([("2026-06-01", 100), ("2026-07-01", 105), ("2026-08-01", 110), ("2026-09-01", 120)]):
            c.execute("INSERT INTO observations(obs_id,source_id,metric,entity_type,entity_id,period_end,value,doc_id) VALUES (?,?,?,?,?,?,?,?)", (f"c{i}", "fred", "fred_PCOPPUSDM", "market", "global", pe, v, "d2"))
        for i, (m, pe, hs, v) in enumerate([("trade_export_usd_mn", "2026-03-31", "30", 130.0), ("trade_export_usd_mn", "2025-03-31", "30", 100.0),
                                            ("trade_import_usd_mn", "2026-03-31", "30", 10.0), ("trade_import_usd_mn", "2025-03-31", "30", 10.0)]):
            c.execute("INSERT INTO observations(obs_id,source_id,metric,entity_type,entity_id,period_end,value,doc_id) VALUES (?,?,?,?,?,?,?,?)", (f"t{i}", "tradestat_eidb", m, "hs_chapter", hs, pe, v, "d3"))
        c.commit()
        cls.d = Detector(c, cls.tmp, as_of=date(2026, 11, 22))
        cls.d.capacity(); cls.d.commodities(); cls.d.trade()

    @classmethod
    def tearDownClass(cls):
        cls.con.close(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def by(self, rule):
        return [s for s in self.d.out if s["rule_id"] == rule]

    def test_capacity(self):
        s = self.by("capacity_utilisation")
        self.assertEqual(len(s), 1); self.assertEqual(s[0]["direction"], "positive"); self.assertEqual(s[0]["magnitude"], 76.3)
        self.assertEqual(s[0]["status"], "validated")

    def test_commodity_uses_month_end_and_threshold(self):
        s = self.by("commodity_3m")
        self.assertEqual(len(s), 1); self.assertEqual(s[0]["observed_at"], "2026-09-30"); self.assertEqual(s[0]["magnitude"], 20.0)

    def test_trade_export_growth(self):
        s = self.by("trade_export_fy")
        self.assertEqual({x["entity_id"] for x in s}, {"healthcare"}); self.assertEqual(s[0]["magnitude"], 30.0)
        self.assertFalse(self.by("trade_import_share"), "US$ 1 bn minimum two-way trade not met")

    def test_new_types_map_to_dimensions(self):
        for r in RULES.values():
            self.assertIn(r["type"], SIGNAL_DIMENSION, r)
        self.assertIn("structural demand", STAGE_CRITERIA["emergence"])
