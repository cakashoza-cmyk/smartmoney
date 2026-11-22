"""Browser check of every view, desktop + mobile: JS errors, 'Could not load' panels, rendered text saved to
shots/rendered_*.txt for test/wordcheck.py, screenshots in shots/. Usage: python3 test/verify.py <base-url> [out-dir]"""
import sys, asyncio
from playwright.async_api import async_playwright
BASE = sys.argv[1].rstrip("/") + "/"; OUT = sys.argv[2] if len(sys.argv) > 2 else "shots"
VIEWS = ["executive", "horizons/1-3y", "horizons/3-10y", "horizons/10-20y", "sectors", "sectors/capital_goods", "investors", "investors/sbi", "funds", "companies", "companies/transactions",
         "global", "credit", "radar", "quality", "sources", "watch", "admin",
         "opportunities", "opportunities/opp_telecom_capital_broadening", "signals", "industry", "industry/capital_goods", "valuation", "valuation/ITC", "investable", "thesis", "analyst"]
V2_MOBILE = ["opportunities", "opportunities/opp_power_credit_quality", "valuation/ITC", "thesis"]
EDU = "For educational and research purposes only; not investment advice; users must make their own decisions under their own registrations."
PROMINENT = ("valuation", "investable", "opportunities/")


async def run(b, label, vp, mobile, errs, views):
    ctx = await b.new_context(viewport=vp, device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile, timezone_id="Asia/Kolkata")
    pg = await ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(f"{label} pageerror: {e}"))
    pg.on("console", lambda m: m.type == "error" and errs.append(f"{label} console: {m.text}"))
    await pg.goto(BASE + "#/executive", wait_until="networkidle"); await pg.wait_for_timeout(1200)
    alltxt = []
    for v in views:
        await pg.goto(BASE + "#/" + v, wait_until="networkidle"); await pg.wait_for_timeout(900)
        txt = await pg.evaluate("document.getElementById('app').innerText")
        if "Could not load this view" in txt or "Data not built yet" in txt:
            errs.append(f"{label} {v}: {txt[:300]}")
        banner = await pg.evaluate("(()=>{const e=document.getElementById('edu');return e&&e.offsetParent!==null?e.innerText:''})()")
        if EDU not in banner:
            errs.append(f"{label} {v}: educational disclosure banner missing")
        if v.startswith(PROMINENT) and not await pg.evaluate("!!document.querySelector('#app .edu.big')"):
            errs.append(f"{label} {v}: prominent disclosure missing")
        print(f"{label} {v}: {len(txt)} chars | {txt[:160]!r}")
        alltxt.append(f"=== #/{v}\n{txt}")
        await pg.screenshot(path=f"{OUT}/{label}_{v.replace('/', '_')}.png", full_page=(v in ("executive", "sectors", "horizons/10-20y") or v.startswith(("opportunities", "thesis", "investable"))))
    # company detail from the first link on the companies page
    await pg.goto(BASE + "#/companies", wait_until="networkidle"); await pg.wait_for_timeout(800)
    href = await pg.evaluate("(document.querySelector('#app table tbody a')||{}).getAttribute ? document.querySelector('#app table tbody a').getAttribute('href') : null")
    if href:
        await pg.goto(BASE + href, wait_until="networkidle"); await pg.wait_for_timeout(900)
        txt = await pg.evaluate("document.getElementById('app').innerText"); alltxt.append("=== company\n" + txt)
        print(f"{label} company {href}: {txt[:200]!r}")
        await pg.screenshot(path=f"{OUT}/{label}_company.png")
    # Valuation Lab: analyst enters assumptions, reverse DCF renders (illustrative inputs typed by the test, never saved or published)
    await pg.goto(BASE + "#/valuation/ITC", wait_until="networkidle"); await pg.wait_for_timeout(800)
    if await pg.evaluate("document.getElementById('v_revenue0').value") != "":
        errs.append(f"{label}: valuation inputs are prefilled")
    rep = await pg.evaluate("(document.querySelector('.card.reported')||{}).innerText||''")
    if "trailing 4 quarters" not in rep.lower() or "₹" not in rep.split("railing 4 quarters")[-1][:80]:
        errs.append(f"{label}: reported panel has no TTM revenue for ITC: {rep[:300]!r}")
    print(f"{label} reported panel: {rep[:300]!r}")
    for k, val in (("revenue0", "1000"), ("growth", "12"), ("margin", "18"), ("tax", "25"), ("roic", "20"), ("wacc", "12"), ("g_term", "5"), ("years", "10"), ("net_debt", "200"), ("market_value", "3000")):
        await pg.fill(f"#v_{k}", val)
    await pg.click("text=Calculate"); await pg.wait_for_timeout(500)
    out = await pg.evaluate("document.getElementById('v_out').innerText")
    if "what must happen" not in out.lower() or "scenario" not in out.lower():
        errs.append(f"{label}: valuation lab did not render results: {out[:200]}")
    print(f"{label} valuation lab: {out[:220]!r}")
    await pg.screenshot(path=f"{OUT}/{label}_valuation_calc.png", full_page=True)
    alltxt.append("=== valuation calc\n" + out)
    # search
    await pg.fill("#q", "hdfc"); await pg.wait_for_timeout(800)
    n = await pg.evaluate("document.querySelectorAll('#qres a').length"); print(f"{label} search 'hdfc': {n} hits")
    if not n:
        errs.append(f"{label}: search returned nothing")
    open(f"{OUT}/rendered_{label}.txt", "w").write("\n".join(alltxt) + "\n" + await pg.evaluate("document.body.innerText.slice(0,4000)"))
    await ctx.close()


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        errs = []
        await run(b, "desktop", {"width": 1440, "height": 900}, False, errs, VIEWS)
        await run(b, "mobile", {"width": 390, "height": 844}, True, errs, ["executive", "horizons/1-3y", "sectors", "sectors/capital_goods", "radar", "quality"] + V2_MOBILE)
        await b.close()
        print("ERRORS:", errs or "none")
        sys.exit(1 if errs else 0)

asyncio.run(main())
