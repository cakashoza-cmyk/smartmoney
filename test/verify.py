"""Browser check of every view, desktop + mobile: JS errors, 'Could not load' panels, rendered text saved to
shots/rendered_*.txt for test/wordcheck.py, screenshots in shots/. Usage: python3 test/verify.py <base-url> [out-dir]"""
import sys, asyncio
from playwright.async_api import async_playwright
BASE = sys.argv[1].rstrip("/") + "/"; OUT = sys.argv[2] if len(sys.argv) > 2 else "shots"
VIEWS = ["executive", "horizons/1-3y", "horizons/3-10y", "horizons/10-20y", "sectors", "sectors/capital_goods", "investors", "companies", "companies/transactions",
         "global", "credit", "radar", "quality", "sources", "watch", "admin"]


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
        print(f"{label} {v}: {len(txt)} chars | {txt[:160]!r}")
        alltxt.append(f"=== {v}\n{txt}")
        await pg.screenshot(path=f"{OUT}/{label}_{v.replace('/', '_')}.png", full_page=(v in ("executive", "sectors", "horizons/10-20y")))
    # company detail from the first link on the companies page
    await pg.goto(BASE + "#/companies", wait_until="networkidle"); await pg.wait_for_timeout(800)
    href = await pg.evaluate("(document.querySelector('#app table tbody a')||{}).getAttribute ? document.querySelector('#app table tbody a').getAttribute('href') : null")
    if href:
        await pg.goto(BASE + href, wait_until="networkidle"); await pg.wait_for_timeout(900)
        txt = await pg.evaluate("document.getElementById('app').innerText"); alltxt.append("=== company\n" + txt)
        print(f"{label} company {href}: {txt[:200]!r}")
        await pg.screenshot(path=f"{OUT}/{label}_company.png")
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
        await run(b, "mobile", {"width": 390, "height": 844}, True, errs, ["executive", "horizons/1-3y", "sectors", "sectors/capital_goods", "radar", "quality"])
        await b.close()
        print("ERRORS:", errs or "none")
        sys.exit(1 if errs else 0)

asyncio.run(main())
