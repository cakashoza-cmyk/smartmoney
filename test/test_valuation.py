"""Valuation Lab arithmetic: Python and browser implementations give the same numbers; reverse DCF solves back to the
hurdle; inputs are never prefilled; missing inputs are refused, not defaulted."""
import json, shutil, subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from intelligence import valuation_engine as ve  # noqa: E402

CASES = [
    dict(revenue0=1000, growth=0.12, margin=0.18, tax=0.25, mode="roic", roic=0.2, wacc=0.12, g_term=0.05, years=10, net_debt=200, market_value=3000),
    dict(revenue0=5000, growth=[0.2, 0.18, 0.15, 0.12, 0.1], margin=0.1, tax=0.25, mode="explicit", capex_pct=0.03, wc_pct=0.1, wacc=0.13, g_term=0.06, years=7, net_debt=-500, market_value=9000),
]


class Valuation(unittest.TestCase):
    def test_reverse_solves_back_to_hurdle(self):
        a = CASES[0]
        for h in ve.reverse(a)["hurdles"]:
            if h["required_growth"] is not None:
                r = ve.forward(dict(a, growth=h["required_growth"]))["model_annual_return"]
                self.assertAlmostEqual(r, h["hurdle"], places=6)
            if h["required_margin"] is not None:
                r = ve.forward(dict(a, margin=h["required_margin"]))["model_annual_return"]
                self.assertAlmostEqual(r, h["hurdle"], places=6)

    def test_higher_hurdle_needs_more_growth(self):
        g = [h["required_growth"] for h in ve.reverse(CASES[0])["hurdles"]]
        self.assertTrue(all(x is not None for x in g)); self.assertLess(g[0], g[1]); self.assertLess(g[1], g[2])

    def test_missing_inputs_refused(self):
        a = dict(CASES[0]); a.pop("market_value")
        self.assertIn("missing", ve.forward(a)["error"])
        self.assertIn("terminal growth", ve.forward(dict(CASES[0], wacc=0.04))["error"])

    def test_python_and_js_match(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        js = "const V=require(%s);const C=%s;console.log(JSON.stringify(C.map(a=>[V.forward(a),V.reverse(a)])));" % (json.dumps(str(ROOT / "assets/valuation.js")), json.dumps(CASES))
        out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
        for a, (f, r) in zip(CASES, out):
            pf, pr = ve.forward(a), ve.reverse(a)
            for k in ("enterprise_value", "equity_value", "model_annual_return", "terminal_value"):
                self.assertAlmostEqual(pf[k], f[k], places=6, msg=k)
            for x, y in zip(pr["hurdles"], r["hurdles"]):
                for k in ("required_growth", "required_margin"):
                    if x[k] is None:
                        self.assertIsNone(y[k])
                    else:
                        self.assertAlmostEqual(x[k], y[k], places=6)

    def test_no_prefilled_assumptions_in_ui(self):
        src = (ROOT / "assets/v2.js").read_text()
        self.assertIn("Nothing is prefilled", src)
        self.assertNotRegex(src, r"id=\"v_\$\{k\}\"[^>]*value=\"\d")

    def test_no_price_objective_wording(self):
        txt = ((ROOT / "assets/v2.js").read_text() + (ROOT / "assets/valuation.js").read_text()).lower()
        for w in ("target price", "price target", "fair value per share", "intrinsic value per share", "buy zone", "sell zone"):
            self.assertNotIn(w, txt)


class Disclosure(unittest.TestCase):
    TEXT = "For educational and research purposes only; not investment advice; users must make their own decisions under their own registrations."

    def test_every_page_and_prominent_screens(self):
        html = (ROOT / "index.html").read_text()
        self.assertIn(self.TEXT, html)  # banner under the navigation renders on every route
        v2 = (ROOT / "assets/v2.js").read_text()
        self.assertIn(self.TEXT, v2)
        for route in ("ROUTES.valuation", "ROUTES.investable", "async function dossier"):
            i = v2.index(route); self.assertIn("eduBig()", v2[i:i + 2500], route)


class V1Contract(unittest.TestCase):
    def test_v1_exports_backward_compatible(self):
        contract = json.loads((ROOT / "test/v1_contract.json").read_text())
        exp = ROOT / "data/export"
        for name, keys in contract.items():
            p = exp / name
            self.assertTrue(p.exists(), name)
            d = json.loads(p.read_text())
            if isinstance(d, dict):
                self.assertTrue(set(keys) <= set(d), f"{name} lost keys {set(keys) - set(d)}")


if __name__ == "__main__":
    unittest.main()
