"""Phase 2 tests: AMC monthly portfolio files (passive excluded, schemes collapsed to the fund house, no double counting,
split handling) and rating actions from ICRA / CARE / India Ratings (classification, per-agency display, sources recorded)."""
import json, os, sqlite3, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "data" / "export"
DB = Path(os.environ.get("SM_DB", ROOT / "data" / "smartmoney.db"))
sys.path.insert(0, str(ROOT / "scripts"))


def J(n):
    return json.loads((EXP / n).read_text())


class Classifiers(unittest.TestCase):
    def test_scheme_flags(self):
        from ingest_amc import scheme_flag
        for n in ["SBI Nifty 50 ETF", "Nippon India ETF Nifty BeES", "DSP Nifty Midcap 150 Index Fund", "ABSL BSE Sensex ETF", "HDFC Index Fund - Sensex Plan"]:
            self.assertEqual(scheme_flag(n), "passive", n)
        self.assertEqual(scheme_flag("SBI Arbitrage Opportunities Fund"), "arbitrage")
        for n in ["SBI Contra Fund", "Parag Parikh Flexi Cap Fund", "DSP Quant Fund", "Nippon India Small Cap Fund"]:
            self.assertEqual(scheme_flag(n), "active", n)

    def test_period_parsing(self):
        from ingest_amc import date_from_text
        self.assertEqual(date_from_text("NIMF-MONTHLY-PORTFOLIO-31-Oct-26.xls"), "2026-10-31")
        self.assertEqual(date_from_text("monthend-portfolio-july-31st-2023.zip"), "2023-07-31")
        self.assertEqual(date_from_text("NIMF-MONTHLY-PORTFOLIO-Nov-25.xls"), "2025-11-30")
        self.assertIsNone(date_from_text("x-31-dec-2099.xls"))  # never a future period

    def test_rating_headlines(self):
        from ingest_ratings import classify
        self.assertEqual(classify("India Ratings Upgrades ABC Ltd to 'IND A'")[0], "upgrade")
        self.assertEqual(classify("XYZ Private Limited: Rating downgraded to [ICRA]BB+")[0], "downgrade")
        self.assertEqual(classify("India Ratings Revises Outlook on Foo's Bank Loans to Negative; Affirms 'IND BBB'")[:3], ("outlook_negative", True, True))
        self.assertEqual(classify("India Ratings Affirms Foo at 'IND A'/Stable; Off Rating Watch with Negative Implications")[0], "watch_resolved")
        self.assertEqual(classify("India Ratings Migrates Bar to Non-Cooperating Category")[1], False)

    def test_care_table(self):
        from ingest_ratings import care_action
        t = "Long Term Bank Facilities RBI 2.45 CARE BB; Stable Rating removed from ISSUER NOT COOPERATING category and Upgraded from CARE C; Stable Details of instruments"
        self.assertEqual(care_action(t)[0], "upgrade")
        t = "Long Term Bank Facilities RBI 10.00 CARE D; ISSUER NOT COOPERATING* Rating continues to remain under ISSUER NOT COOPERATING category Details of instruments"
        self.assertEqual(care_action(t)[0], "inc_continues")  # a continuing 'D' is not a new default
        t = "Long-term bank facilities RBI 100 CARE A-; Stable Revised from CARE BBB+; Stable Details of instruments"
        self.assertEqual(care_action(t)[0], "upgrade")


@unittest.skipUnless(DB.exists(), "database not present")
class MfData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(DB); cls.db.row_factory = sqlite3.Row
        cls.mf = J("mf.json")

    def test_amc_sources_registered_with_status(self):
        src = {r["source_id"]: r["status"] for r in self.db.execute("SELECT source_id, status FROM sources WHERE source_id LIKE 'amc_%'")}
        for a in ("amc_sbi", "amc_icici", "amc_hdfc", "amc_nippon", "amc_kotak", "amc_axis", "amc_absl", "amc_uti", "amc_mirae", "amc_dsp"):
            self.assertIn(a, src)
        self.assertEqual(src["amc_hdfc"], "blocked"); self.assertEqual(src["amc_kotak"], "blocked")
        self.assertGreaterEqual(sum(1 for v in src.values() if v == "working"), 3)

    def test_scheme_investors_parented_to_fund_house(self):
        bad = self.db.execute("""SELECT count(*) FROM ownership o JOIN investors i ON i.investor_id=o.investor_id JOIN source_documents sd ON sd.doc_id=o.doc_id
                                 WHERE o.holder_category='mf_portfolio' AND i.group_id NOT IN ('sbi','nippon','dsp','aditya_birla','ppfas','icici','hdfc','kotak','axis','uti','mirae')""").fetchone()[0]
        self.assertEqual(bad, 0, "an AMC scheme was re-mapped away from its fund house")

    def test_passive_and_arbitrage_never_in_flows(self):
        # every derived flow row is the sum of ACTIVE schemes only: recompute one group-company and compare
        r = self.db.execute("SELECT t.company_id, i.group_id, t.txn_date FROM transactions t JOIN investors i ON i.investor_id=t.investor_id WHERE t.txn_id LIKE 'mff_%' LIMIT 1").fetchone()
        if not r:
            self.skipTest("no flows yet")
        n_passive = self.db.execute("""SELECT count(*) FROM ownership o JOIN investors i ON i.investor_id=o.investor_id WHERE o.holder_category='mf_portfolio' AND o.scheme_flag='passive'""").fetchone()[0]
        self.assertGreater(n_passive, 0, "passive schemes should be stored (flagged), just not counted")
        import mf_flows
        moves, _ = mf_flows.compute(self.db, write=False)
        act = {(m["group"], m["company"]) for m in moves}
        only_passive = self.db.execute("""SELECT i.group_id, o.company_id FROM ownership o JOIN investors i ON i.investor_id=o.investor_id WHERE o.holder_category='mf_portfolio'
                                          GROUP BY 1,2 HAVING sum(o.scheme_flag='active')=0""").fetchall()
        for g, c in only_passive[:200]:
            self.assertNotIn((g, c), act, f"{g}/{c} is held only by passive/arbitrage schemes but produced a flow")

    def test_one_flow_per_fund_house_company_month(self):
        dup = self.db.execute("""SELECT count(*) FROM (SELECT i.group_id, t.company_id, t.txn_date, count(*) n FROM transactions t JOIN investors i ON i.investor_id=t.investor_id
                                 WHERE t.txn_id LIKE 'mff_%' GROUP BY 1,2,3 HAVING n>1)""").fetchone()[0]
        self.assertEqual(dup, 0)

    def test_convergence_counts_fund_house_once(self):
        for r in J("investors.json")["convergence"]:
            self.assertEqual(len(r["groups"]), len(set(r["groups"])))
            self.assertEqual(r["independent_groups"], len(r["groups"]))
            for g in r.get("via_mf", []):
                self.assertIn(g, r["groups"])
                self.assertFalse(g.startswith("passive"), "passive group in convergence")

    def test_mf_summary_and_labels(self):
        self.assertTrue(self.mf["month"]); self.assertTrue(self.mf["groups_compared"])
        for s in self.mf["sectors"]:
            if s["buy_moves"] + s["sell_moves"] < 10:
                self.assertIsNone(s["net_breadth_pct"], "breadth must be 'insufficient data' below 10 moves, never 0")
        lab = {r[0] for r in self.db.execute("SELECT DISTINCT evidence_label FROM transactions WHERE txn_id LIKE 'mff_%'")}
        self.assertEqual(lab, {"ESTIMATED VALUE"})

    def test_mf_feeds_1_3y(self):
        h = J("horizons.json")["1-3y"]
        self.assertIn("mf", h)
        w = json.loads((ROOT / "data/weights.json").read_text())
        self.assertIn("mf_amc_net_breadth_1m", w["capital_flow"]["1-3y"])


@unittest.skipUnless(DB.exists(), "database not present")
class RatingData(unittest.TestCase):
    def test_agencies_present(self):
        cr = J("credit.json")
        self.assertEqual(set(cr["agencies"]), {"crisil_ratings", "icra_ratings", "care_ratings", "indra_ratings"})
        db = sqlite3.connect(DB)
        for sid in ("icra_ratings", "care_ratings", "indra_ratings"):
            st = db.execute("SELECT status FROM sources WHERE source_id=?", (sid,)).fetchone()
            self.assertIsNotNone(st, sid)
        n = db.execute("SELECT count(*) FROM debt WHERE source_id IN ('icra_ratings','care_ratings','indra_ratings')").fetchone()[0]
        self.assertGreater(n, 0)
        orphan = db.execute("SELECT count(*) FROM debt d LEFT JOIN source_documents sd ON sd.doc_id=d.doc_id WHERE d.source_id IN ('icra_ratings','care_ratings','indra_ratings') AND sd.url IS NULL").fetchone()[0]
        self.assertEqual(orphan, 0, "every rating action must link to its official page")


if __name__ == "__main__":
    unittest.main()
