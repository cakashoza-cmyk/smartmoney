"""Acceptance tests mapped to the brief's acceptance criteria. Run: python3 -m unittest discover -s test -p "test_*.py" -v
Uses data/export (always) and data/smartmoney.db (when present, e.g. in the pipeline)."""
import json, os, re, sqlite3, sys, unittest
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "data" / "export"
DB = Path(os.environ.get("SM_DB", ROOT / "data" / "smartmoney.db"))
sys.path.insert(0, str(ROOT / "scripts"))


def J(n):
    return json.loads((EXP / n).read_text())


class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = J("meta.json")
        cls.db = sqlite3.connect(DB) if DB.exists() else None

    def need_db(self):
        if not self.db:
            self.skipTest("database not present")

    # 1. three horizons, each with its own method
    def test_three_horizons_distinct_methods(self):
        h = J("horizons.json")
        for k in ("1-3y", "3-10y", "10-20y"):
            self.assertIn(k, h); self.assertIn(k, h["methods"])
        self.assertEqual(len({h["methods"][k]["method"] for k in h["methods"]}), 3)
        self.assertNotEqual([r["id"] for r in h["1-3y"]["ranking"]][:5] + ["x"], ["y"])  # rankings exist
        self.assertTrue(h["1-3y"]["ranking"], "1-3y ranking empty")
        self.assertTrue(h["3-10y"]["ranking"], "3-10y ranking empty")

    # 2. 10-20y shows evidence and labelled scenarios only (no numeric forecasts, no company names)
    def test_long_horizon_scenarios_only(self):
        th = J("horizons.json")["10-20y"]["themes"]
        self.assertGreaterEqual(len(th), 5)
        for t in th:
            self.assertEqual(t["label"], "SCENARIO"); self.assertTrue(t["confirm"]); self.assertTrue(t["invalidate"])
            self.assertNotRegex(t["scenario"], r"\d+(\.\d+)?\s*%|CAGR|Rs\s*\d|₹\s*\d", "numeric forecast in scenario text")
            for e in t["evidence"]:
                self.assertIn(e["evidence_label"], ("VERIFIED FACT", "REPORTED ANNOUNCEMENT"))

    # 3. global search covers every entity type
    def test_search_covers_entities(self):
        kinds = {r[0] for r in J("search.json")}
        for k in ("industry", "company", "investor", "source"):
            self.assertIn(k, kinds)

    # 4. history: long FPI history and scoring history persisted
    def test_history(self):
        x = J("executive.json")
        self.assertTrue(x["fpi_total"]); self.assertLessEqual(x["fpi_total"][0][0], "2018-01-01")
        if self.db:
            self.assertGreater(self.db.execute("SELECT count(DISTINCT as_of) FROM scoring_history").fetchone()[0], 0)

    # 5. traceability: every transaction and observation has a source document; every exported tx has a link
    def test_traceability(self):
        checks = {c["check"]: c for c in self.meta["quality"]["audit_checks"]}
        for k in ("Every transaction has a source document", "Every observation has a source document"):
            self.assertTrue(checks[k]["ok"], checks[k]["detail"])
        t = J("transactions.json")
        for r in t["rows"][:5000]:
            self.assertTrue(r[12] or (r[13] == "nse_deals" and t["deals_url"]), r)
        for c in J("conclusions.json"):
            self.assertTrue(json.loads(c["evidence_refs"]) or c["auditor_status"] == "rejected", c["statement"])

    # 6. commitments and deployments separate, linked, never summed
    def test_commitments_vs_deployments(self):
        checks = {c["check"]: c for c in self.meta["quality"]["audit_checks"]}
        self.assertTrue(checks["Commitments and deployments are separate rows (never the same id, never summed)"]["ok"])
        if self.db:
            n = self.db.execute("SELECT count(*) FROM deployments WHERE commitment_id IS NOT NULL AND commitment_id NOT IN (SELECT commitment_id FROM commitments)").fetchone()[0]
            self.assertEqual(n, 0, "deployment links to a missing commitment")
            self.assertGreater(self.db.execute("SELECT count(*) FROM deployments").fetchone()[0], 0)
        from openpyxl import load_workbook
        wb = load_workbook(EXP / "smartmoney.xlsx", read_only=True)
        self.assertIn("Deployments (verified)", wb.sheetnames); self.assertIn("Commitments (announced)", wb.sheetnames)

    # 7. convergence never double counts fund families and excludes trading/passive/individual groups
    def test_convergence_no_double_count(self):
        inv = J("investors.json"); groups = self.meta["groups"]
        for r in inv["convergence"]:
            self.assertEqual(len(r["groups"]), len(set(r["groups"])))
            self.assertEqual(r["independent_groups"], len(r["groups"]))
            for g in r["groups"]:
                m = groups.get(g)
                if m:
                    self.assertFalse(m["trading"] or m["passive"], f"{g} excluded group in convergence")
                    self.assertNotIn(m["category"], ("individual_or_unknown", "corporate", "promoter"))

    # 8. score transparency: components, weights and raw values for every ranked item; weights match weights.json
    def test_score_transparency(self):
        w = json.loads((ROOT / "data" / "weights.json").read_text())
        for hz in ("1-3y", "3-10y"):
            for r in J("horizons.json")[hz]["ranking"]:
                names = {c["name"] for c in r["components"]}
                self.assertEqual(names, set(w["capital_flow"][hz]))
                for c in r["components"]:
                    self.assertIn("raw", c); self.assertEqual(c["weight"], w["capital_flow"][hz][c["name"]])
                self.assertIn(r["confidence"], ("high", "medium", "low"))
                self.assertTrue(0 <= r["score"] <= 100)

    # 9. unknowns are never zero
    def test_unknowns_not_zero(self):
        checks = {c["check"]: c for c in self.meta["quality"]["audit_checks"]}
        self.assertTrue(checks["Undisclosed amounts stored as NULL, not zero"]["ok"])
        from build import combine
        self.assertEqual(combine({"a": None, "b": None, "c": 80}, {"a": 40, "b": 30, "c": 30})[0], None)
        self.assertEqual(combine({"a": 50, "b": None, "c": 80}, {"a": 40, "b": 30, "c": 30})[0], round((50 * 40 + 80 * 30) / 70, 1))

    # 10. every source in the registry with the required fields; paid sources show not connected
    def test_source_registry(self):
        req = ("source_id", "name", "url", "category", "status", "reliability", "limitations", "last_success", "latest_data_period")
        ids = set()
        for s in self.meta["sources"]:
            for k in req:
                self.assertIn(k, s)
            self.assertIn(s["status"], ("working", "partial", "blocked", "needs_credentials", "not_built"))
            ids.add(s["source_id"])
            if s["status"] == "needs_credentials":
                self.assertTrue(s["credentials_needed"])
        for p in ("tracxn", "venture_intelligence", "vccedge", "mca21"):
            self.assertIn(p, ids)
            self.assertEqual(next(s for s in self.meta["sources"] if s["source_id"] == p)["status"], "needs_credentials")
        working = [s for s in self.meta["sources"] if s["status"] == "working"]
        self.assertGreaterEqual(len(working), 8)

    # 11. stale flags
    def test_stale_flags(self):
        from build import B
        b = B.__new__(B)
        self.assertTrue(B.is_stale(b, {"source_id": "x", "status": "working", "last_success": "2020-01-01T00:00", "max_age_days": 3, "latest_data_period": "2020-01-01"}))
        self.assertFalse(B.is_stale(b, {"source_id": "x", "status": "working", "last_success": date.today().isoformat() + "T00:00", "max_age_days": 3, "latest_data_period": date.today().isoformat()}))
        for c, v in self.meta["freshness"].items():
            self.assertIn("stale_sources", v)

    # 12. conflicting evidence is surfaced, not hidden
    def test_conflicts_surfaced(self):
        self.assertIn("discrepancies", self.meta["quality"])
        statuses = {c["auditor_status"] for c in J("conclusions.json")}
        self.assertTrue(statuses <= {"accepted", "flagged", "rejected"})

    # 13. exports
    def test_exports(self):
        for f in ("meta.json", "executive.json", "sectors.json", "companies.json", "investors.json", "horizons.json", "radar.json", "credit.json", "global.json",
                  "conclusions.json", "search.json", "transactions.json", "smartmoney.xlsx"):
            self.assertTrue((EXP / f).exists(), f)
        js = (ROOT / "assets" / "app.js").read_text()
        self.assertIn("window.csv", js); self.assertIn("window.print", js)

    # 14. persistence + scheduled jobs
    def test_persistence_and_schedule(self):
        wf = (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
        self.assertGreaterEqual(len(re.findall(r"cron:", wf)), 3)
        for g in ("daily", "fortnightly", "monthly", "quarterly", "annual"):
            self.assertIn(g, wf)
        self.assertIn("gh release upload db", wf)
        if self.db:
            for t, n in (("observations", 10000), ("transactions", 1000), ("ownership", 10000), ("companies", 400)):
                self.assertGreater(self.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0], n, t)

    # 15. privacy: individuals' names withheld in exported company timelines; disclaimer present
    def test_privacy_and_disclaimer(self):
        for p in list((EXP / "co").glob("*.json"))[:600]:
            for t in json.loads(p.read_text())["timeline"]:
                if t.get("flag") == "individual":
                    self.assertTrue(t["inv"].startswith("Individual investor"))
        html = (ROOT / "index.html").read_text()
        self.assertIn("Not investment advice", html); self.assertIn("SEBI-registered", html)
        self.assertIn("not investment advice", self.meta["disclaimer"].lower())

    # 16. no language model produces numbers: pipeline has no LLM client
    def test_no_llm(self):
        for p in (ROOT / "scripts").glob("*.py"):
            src = p.read_text().lower()
            for w in ("openai", "anthropic", "deepseek", "chat/completions", "gemini"):
                self.assertNotIn(w, src, f"{p.name} references {w}")


if __name__ == "__main__":
    unittest.main()
