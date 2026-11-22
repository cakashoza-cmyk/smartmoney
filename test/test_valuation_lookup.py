"""Valuation Lab: every company with results loads a reported panel, and the company selector resolves symbols and names."""
import json, re, shutil, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; EXP = ROOT / "data" / "export"


class ValuationLookup(unittest.TestCase):
    def test_every_company_with_results_has_reported_data_and_is_selectable(self):
        f = json.loads((EXP / "v2" / "fundamentals.json").read_text()); v = json.loads((EXP / "v2" / "valuation.json").read_text())
        c = json.loads((EXP / "companies.json").read_text()); rows = [dict(zip(c["cols"], r)) for r in c["rows"]]
        ids = {r["id"] for r in rows}
        missing = [k for k in f["companies"] if k not in v["reported"]]
        self.assertFalse(missing, f"companies with results but no reported panel: {missing[:10]}")
        self.assertFalse([k for k in v["reported"] if k not in ids], "reported panel for a company the selector cannot find")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_selector_resolves_symbols_and_names(self):
        js = (ROOT / "assets" / "v2.js").read_text()
        m = re.search(r"function valFind\(rows, q\) \{.*?\n\}", js, re.S); self.assertTrue(m, "valFind not found")
        rows = [{"symbol": "NTPC", "name": "NTPC Ltd.", "nifty500": 1}, {"symbol": "NTPCGREEN", "name": "NTPC Green Energy Ltd.", "nifty500": 1},
                {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd.", "nifty500": 1}, {"symbol": "BHARTIHEXA", "name": "Bharti Hexacom Ltd.", "nifty500": 1},
                {"symbol": "M&M", "name": "Mahindra & Mahindra Ltd.", "nifty500": 1}, {"symbol": "RELIANCE", "name": "Reliance Industries Ltd.", "nifty500": 1}]
        cases = {"NTPC": "NTPC", "ntpc": "NTPC", "Bharti Airtel": "BHARTIARTL", "bharti airtel ltd.": "BHARTIARTL", "m&m": "M&M",
                 "Reliance Industries Limited": "RELIANCE", "Reliance": "RELIANCE", "Bharti": None, "ZZZ": None, "": None}
        prog = m.group(0) + f"\nconst rows={json.dumps(rows)};const cases={json.dumps(cases)};const out={{}};" \
            "for (const k in cases) { const r = valFind(rows, k); out[k] = r ? r.symbol : null; } console.log(JSON.stringify(out));"
        got = json.loads(subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(got, cases)


if __name__ == "__main__":
    unittest.main()
