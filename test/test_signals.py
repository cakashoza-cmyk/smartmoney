"""SM2-004/005: signals are rule-based, deterministic, source-linked, carry observed_at vs detected_at, and re-detection keeps
the first detection date. Relationships have deterministic ids. Uses the published exports and the database when present."""
import json, os, shutil, sqlite3, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402
from intelligence.signal_detector import Detector, store, relationships, RULES  # noqa: E402

LIVE = Path(os.environ.get("SM_DB", ROOT / "data" / "smartmoney.db"))
EXP = ROOT / "data" / "export"
V2 = EXP / "v2"


class SignalsDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not LIVE.exists():
            raise unittest.SkipTest("database not present")
        cls.tmp = Path(tempfile.mkdtemp()); cls.db = cls.tmp / "s.db"
        src = sqlite3.connect(LIVE); dst = sqlite3.connect(cls.db); src.backup(dst); src.close(); dst.close()
        cls.con = sqlite3.connect(cls.db); migrate.apply_all(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_deterministic_and_known_rules(self):
        a = Detector(self.con, EXP).run(); b = Detector(self.con, EXP).run()
        self.assertEqual([s["signal_id"] for s in a], [s["signal_id"] for s in b])
        self.assertEqual(len({s["signal_id"] for s in a}), len(a), "duplicate signal ids")
        for s in a:
            self.assertIn(s["rule_id"], RULES)
            self.assertIn(s["direction"], ("positive", "negative"))
            self.assertTrue(s["doc_id"], s["title"])
            self.assertIn(s["status"], ("validated", "candidate", "rejected"))

    def test_validated_signals_trace_to_documents(self):
        for s in Detector(self.con, EXP).run():
            if s["status"] == "validated":
                url = self.con.execute("SELECT url FROM source_documents WHERE doc_id=?", (s["doc_id"],)).fetchone()
                self.assertTrue(url and url[0], s["title"])
                self.assertTrue(json.loads(s["refs_json"]))

    def test_detected_at_kept_on_redetection(self):
        sigs = Detector(self.con, EXP).run()
        self.con.execute("DELETE FROM signals")
        store(self.con, sigs, "2026-01-01 10:00")
        store(self.con, sigs, "2026-02-01 10:00")
        r = self.con.execute("SELECT detected_at, last_seen_at, observed_at FROM signals WHERE signal_id=?", (sigs[0]["signal_id"],)).fetchone()
        self.assertEqual(r[0], "2026-01-01 10:00"); self.assertEqual(r[1], "2026-02-01 10:00")
        self.assertNotEqual(r[0][:10], r[2], "observed_at must be the data period, not the detection date")

    def test_stale_data_is_not_validated(self):
        from datetime import date
        late = Detector(self.con, EXP, as_of=date(2030, 1, 1)).run()
        self.assertTrue(late)
        self.assertTrue(all(s["status"] == "rejected" for s in late))

    def test_relationship_ids_deterministic(self):
        sigs = Detector(self.con, EXP).run()
        relationships(self.con, sigs, "t1"); n1 = self.con.execute("SELECT count(*) FROM entity_relationships").fetchone()[0]
        relationships(self.con, sigs, "t2"); n2 = self.con.execute("SELECT count(*) FROM entity_relationships").fetchone()[0]
        self.assertEqual(n1, n2)
        self.assertGreaterEqual(n1, len(sigs))


class SignalsExport(unittest.TestCase):
    def test_export_shape(self):
        p = V2 / "signals.json"
        if not p.exists():
            self.skipTest("v2 export not built")
        d = json.loads(p.read_text())
        self.assertTrue(d["signals"])
        for s in d["signals"]:
            for k in ("signal_id", "observed_at", "detected_at", "evidence_label", "source_id", "status", "rule_id"):
                self.assertIn(k, s)
            self.assertIsNotNone(s["observed_at"]); self.assertIsNotNone(s["detected_at"])

    def test_agencies_never_merged(self):
        p = V2 / "signals.json"
        if not p.exists():
            self.skipTest("v2 export not built")
        for s in json.loads(p.read_text())["signals"]:
            if s["rule_id"] == "rating_balance_90d":
                self.assertIn(s["source_id"], ("crisil_ratings", "icra_ratings", "care_ratings", "indra_ratings"))


if __name__ == "__main__":
    unittest.main()
