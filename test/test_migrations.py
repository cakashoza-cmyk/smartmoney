"""SM2-002/003: versioned migrations are additive, idempotent, checksum-protected, and leave every legacy table intact.
Runs against a copy of the live database when data/smartmoney.db is present (pipeline / box), else a fresh schema."""
import os, shutil, sqlite3, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402

LIVE = Path(os.environ.get("SM_DB", ROOT / "data" / "smartmoney.db"))
NEW = {"signals", "entity_relationships", "opportunities", "opportunity_evidence", "opportunity_scenarios", "thesis_updates", "schema_migrations"}


def legacy_state(con):
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") if r[0] not in NEW]
    return {t: (con.execute(f"SELECT count(*) FROM {t}").fetchone()[0], con.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0]) for t in tabs}


class Migrations(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "copy.db"
        if LIVE.exists():
            src = sqlite3.connect(LIVE); dst = sqlite3.connect(self.db); src.backup(dst); src.close(); dst.close()
        else:
            c = sqlite3.connect(self.db); c.executescript((ROOT / "schema.sql").read_text()); c.close()
        self.con = sqlite3.connect(self.db)

    def tearDown(self):
        self.con.close(); shutil.rmtree(self.tmp, ignore_errors=True)

    def fresh(self):
        """A copy without any 2.0 tables, to exercise the first run."""
        for t in ("thesis_updates", "opportunity_scenarios", "opportunity_evidence", "opportunities", "entity_relationships", "signals", "schema_migrations"):
            self.con.execute(f"DROP TRIGGER IF EXISTS thesis_updates_no_update"); self.con.execute(f"DROP TRIGGER IF EXISTS thesis_updates_no_delete")
            self.con.execute(f"DROP TABLE IF EXISTS {t}")
        self.con.commit()

    def test_legacy_tables_intact_and_new_tables_created(self):
        self.fresh()
        before = legacy_state(self.con)
        ran = migrate.apply_all(self.con)
        self.assertEqual(ran, ["001_opportunity_foundation.sql", "002_audit_columns_and_append_only.sql"])
        after = legacy_state(self.con)
        self.assertEqual(before, after, "a legacy table's rows or definition changed")
        have = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue(NEW <= have)
        self.assertEqual(sorted(migrate.applied(self.con)), ["001", "002"])

    def test_idempotent(self):
        self.fresh(); migrate.apply_all(self.con)
        self.assertEqual(migrate.apply_all(self.con), [])

    def test_edited_migration_refused(self):
        self.fresh(); migrate.apply_all(self.con)
        d = self.tmp / "mig"; d.mkdir()
        for v, n, p in migrate.files():
            (d / p.name).write_text(p.read_text() + ("\n-- edited\n" if v == "001" else ""))
        with self.assertRaises(migrate.MigrationError):
            migrate.apply_all(self.con, d)

    def test_failed_migration_rolls_back(self):
        self.fresh(); migrate.apply_all(self.con)
        d = self.tmp / "mig2"; d.mkdir()
        for v, n, p in migrate.files():
            (d / p.name).write_text(p.read_text())
        (d / "003_bad.sql").write_text("CREATE TABLE zz_tmp (a INTEGER);\nTHIS IS NOT SQL;\n")
        with self.assertRaises(migrate.MigrationError):
            migrate.apply_all(self.con, d)
        self.assertIsNone(self.con.execute("SELECT name FROM sqlite_master WHERE name='zz_tmp'").fetchone())
        self.assertNotIn("003", migrate.applied(self.con))

    def test_thesis_updates_append_only(self):
        self.fresh(); migrate.apply_all(self.con)
        self.con.execute("INSERT INTO thesis_updates (update_id, opportunity_id, update_date, summary) VALUES ('u1','o1','2026-11-22','x')"); self.con.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.con.execute("UPDATE thesis_updates SET summary='y' WHERE update_id='u1'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.con.execute("DELETE FROM thesis_updates WHERE update_id='u1'")


if __name__ == "__main__":
    unittest.main()
