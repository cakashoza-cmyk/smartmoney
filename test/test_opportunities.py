"""SM2-006/007: analyst hypotheses load from a reviewed file, evidence links only to known signals, thesis history is
append-only and cannot be back-dated, no scores/composite are accepted, stages are never promoted by the pipeline,
and starter hypotheses are backed by validated signals."""
import json, os, shutil, sqlite3, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402
from intelligence.opportunity_graph import Loader  # noqa: E402

LIVE = Path(os.environ.get("SM_DB", ROOT / "data" / "smartmoney.db"))
OPP = ROOT / "data" / "analyst" / "opportunities.json"
VAL = ROOT / "data" / "analyst" / "valuations.json"
V2 = ROOT / "data" / "export" / "v2"


def base_db(path):
    c = sqlite3.connect(path)
    c.executescript((ROOT / "schema.sql").read_text())
    migrate.apply_all(c)
    c.execute("INSERT INTO industries (industry_id, name) VALUES ('power','Power')")
    c.execute("INSERT INTO companies (company_id, name, symbol, industry_id) VALUES ('NSE:AAA','AAA Ltd','AAA','power')")
    c.execute("INSERT INTO source_documents (doc_id, source_id, url, retrieved_at) VALUES ('d1','s1','https://example.org/a','2026-11-02')")
    c.execute("INSERT INTO source_documents (doc_id, source_id, url, retrieved_at) VALUES ('d2','s2','https://example.org/b','2026-11-02')")
    for sid, src, doc, et, ei in (("sig_a", "s1", "d1", "industry", "power"), ("sig_b", "s2", "d2", "industry", "power"), ("sig_c", "s2", "d2", "company", "NSE:AAA")):
        c.execute("""INSERT INTO signals (signal_id, signal_type, title, entity_type, entity_id, observed_at, detected_at, evidence_label, source_id, doc_id, status, created_at, direction)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (sid, "capital_flow", sid, et, ei, "2026-11-01", "2026-11-02", "VERIFIED FACT", src, doc, "validated", "2026-11-02", "positive"))
    c.commit()
    return c


def opp(**kw):
    o = {"opportunity_id": "opp_test", "title": "T", "thesis": "Hypothesis", "industry_id": "power", "horizon": "1-3y", "owner": "me", "created_at": "2026-11-01",
         "evidence": [{"signal_id": "sig_a", "role": "supporting", "materiality": 2}], "companies": [], "confirmation_conditions": ["c"], "scenarios": []}
    o.update(kw)
    return o


def upd(uid, date, prev, new):
    return {"update_id": uid, "opportunity_id": "opp_test", "update_date": date, "previous_stage": prev, "new_stage": new, "summary": "s", "author": "me"}


class LoaderRules(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.con = base_db(self.tmp / "o.db")

    def tearDown(self):
        self.con.close(); shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, opps, updates, vals=None, ts="2026-11-22 10:00"):
        (self.tmp / "o.json").write_text(json.dumps({"opportunities": opps, "thesis_updates": updates}))
        (self.tmp / "v.json").write_text(json.dumps({"valuations": vals or []}))
        L = Loader(self.con, self.tmp / "o.json", self.tmp / "v.json", ts).run(); self.con.commit()
        return L

    def test_happy_path_and_stage_from_history(self):
        L = self.load([opp()], [upd("u1", "2026-11-01", None, "discovery")])
        self.assertEqual(L.errors, [])
        self.assertEqual(self.con.execute("SELECT stage FROM opportunities").fetchone()[0], "discovery")

    def test_editing_history_is_rejected(self):
        self.load([opp()], [upd("u1", "2026-11-01", None, "discovery")])
        u = upd("u1", "2026-11-01", None, "discovery"); u["summary"] = "rewritten"
        L = self.load([opp()], [u])
        self.assertTrue(any("append-only" in e for e in L.errors))
        self.assertEqual(self.con.execute("SELECT summary FROM thesis_updates WHERE update_id='u1'").fetchone()[0], "s")

    def test_removed_history_is_kept(self):
        self.load([opp()], [upd("u1", "2026-11-01", None, "discovery"), upd("u2", "2026-11-05", "discovery", "validation")])
        self.load([opp()], [upd("u1", "2026-11-01", None, "discovery")])
        self.assertEqual(self.con.execute("SELECT count(*) FROM thesis_updates").fetchone()[0], 2)
        self.assertEqual(self.con.execute("SELECT stage FROM opportunities").fetchone()[0], "validation")

    def test_backdating_and_wrong_previous_stage_rejected(self):
        self.load([opp()], [upd("u1", "2026-11-10", None, "discovery")])
        L = self.load([opp()], [upd("u1", "2026-11-10", None, "discovery"), upd("u0", "2026-11-05", "discovery", "validation")])
        self.assertTrue(any("back-dating" in e for e in L.errors))
        L = self.load([opp()], [upd("u1", "2026-11-10", None, "discovery"), upd("u3", "2026-11-12", "emergence", "investable_review")])
        self.assertTrue(any("previous stage" in e for e in L.errors))
        self.assertEqual(self.con.execute("SELECT stage FROM opportunities").fetchone()[0], "discovery")

    def test_future_dated_update_rejected(self):
        L = self.load([opp()], [upd("u1", "2027-01-01", None, "discovery")])
        self.assertTrue(any("future" in e for e in L.errors))

    def test_no_scores_or_composite(self):
        L = self.load([opp(composite_score=80)], [upd("u1", "2026-11-01", None, "discovery")])
        self.assertTrue(any("composite_score" in e for e in L.errors))
        L = self.load([opp(valuation_score=50)], [upd("u1", "2026-11-01", None, "discovery")])
        self.assertTrue(any("valuation_score" in e for e in L.errors))

    def test_unknown_signal_rejected(self):
        L = self.load([opp(evidence=[{"signal_id": "sig_nope", "role": "supporting"}])], [upd("u1", "2026-11-01", None, "discovery")])
        self.assertTrue(any("unknown signal" in e for e in L.errors))

    def test_scenario_probabilities_must_total_100(self):
        sc = [{"scenario_name": "bull", "assumptions": {}, "probability": 50}, {"scenario_name": "bear", "assumptions": {}, "probability": 30}]
        L = self.load([opp(scenarios=sc)], [upd("u1", "2026-11-01", None, "discovery")])
        self.assertTrue(any("total" in e for e in L.errors))

    def test_criteria_reported_but_never_promoted(self):
        o = opp(evidence=[{"signal_id": "sig_a", "role": "supporting"}, {"signal_id": "sig_b", "role": "supporting"}, {"signal_id": "sig_c", "role": "supporting"}])
        L = self.load([o], [upd("u1", "2026-11-01", None, "discovery")])
        crit = L.criteria("opp_test", {"confirmation_conditions": ["c"]})
        self.assertTrue(crit["validation"]["met"])
        self.assertFalse(crit["emergence"]["met"], "emergence needs demand/execution evidence")
        self.assertEqual(self.con.execute("SELECT stage FROM opportunities").fetchone()[0], "discovery")

    def test_valuation_needs_source_notes(self):
        v = {"valuation_id": "v1", "company_id": "NSE:AAA", "as_of": "2026-11-22", "analyst": "me", "source_notes": {"revenue0": "AR FY26"},
             "assumptions": {"revenue0": 100, "growth": 0.1, "margin": 0.2, "tax": 0.25, "roic": 0.2, "wacc": 0.12, "g_term": 0.05, "years": 10, "net_debt": 0, "market_value": 300}}
        L = self.load([opp()], [upd("u1", "2026-11-01", None, "discovery")], [v])
        self.assertTrue(any("source_notes.market_value" in e for e in L.errors))


class PublishedHypotheses(unittest.TestCase):
    def test_published_file_has_no_errors_and_starters_are_backed(self):
        p = V2 / "opportunities.json"
        if not p.exists():
            self.skipTest("v2 export not built")
        d = json.loads(p.read_text())
        self.assertEqual(d["analyst_file_errors"], [])
        for o in d["opportunities"]:
            self.assertTrue(all(v is None for v in o["scores"].values()), "no scores in Sprint 1")
            self.assertNotIn("composite_score", o)
            if o["starter_hypothesis"]:
                sup = [e for e in o["evidence"] if e["role"] == "supporting" and e["signal_status"] == "validated"]
                self.assertGreaterEqual(len(sup), 2, o["opportunity_id"])
                self.assertTrue(all(e["url"] for e in sup))
                self.assertIn("Starter hypothesis", o["thesis"])
            self.assertTrue(o["history"], "every hypothesis has a recorded creation update")

    def test_no_invented_figures_in_starters(self):
        """Every number in a starter hypothesis' text must already appear in a linked signal title/description."""
        import re
        p = V2 / "opportunities.json"
        if not p.exists():
            self.skipTest("v2 export not built")
        sig = json.loads((V2 / "signals.json").read_text())["signals"]
        by = {s["signal_id"]: s for s in sig}
        src = json.loads(OPP.read_text())
        rules_nums = {"1.5", "40", "65", "35", "90"}
        for o in src["opportunities"]:
            if not o.get("starter_hypothesis"):
                continue
            txt = " ".join([o["thesis"]] + [e.get("explanation") or "" for e in o["evidence"]] + [c.get("note") or "" for c in o["companies"]] + o["confirmation_conditions"] + o["invalidation_conditions"])
            known = " ".join((by.get(e["signal_id"], {}).get("title") or "") + " " + (by.get(e["signal_id"], {}).get("description") or "") for e in o["evidence"])
            for n in re.findall(r"\d+(?:\.\d+)?", txt):
                if n in rules_nums or n in ("3", "5", "2026", "10"):
                    continue
                self.assertIn(n, known, f"{o['opportunity_id']}: number {n} not found in linked signals")


if __name__ == "__main__":
    unittest.main()
