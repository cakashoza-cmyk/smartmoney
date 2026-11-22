"""Recommendation-language check (SEBI-safe framing). Fails if UI strings, docs, exported JSON statements or the rendered
page text (saved by test/verify.py) contain buy/sell/target-style recommendation words or 'opportunity/attractive' framing
about securities. Factual words for trade direction (BUY/SELL deal side, 'net buyers', 'bought', 'sold') are allowed, as are
the exact disclaimer sentences. Usage: python3 test/wordcheck.py  (exit 1 on any hit)"""
import re, sys, glob, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
WORDS = [r"\bstrong buy\b", r"\bbuy (call|rating|signal|recommendation|now)\b", r"\bsell (call|rating|signal|recommendation|now)\b", r"\b(should|must) (buy|sell|own|hold|invest)\b",
         r"\baccumulate\b", r"\btarget price\w*", r"\bprice target\w*", r"\btargets? of\b", r"\bstop[- ]?loss\b", r"\bundervalued\b", r"\bovervalued\b", r"\bmultibagger\w*",
         r"\btop picks?\b", r"\bmust[- ]own\b", r"\boutperform\w*", r"\bupside\b", r"\battractive\w*", r"\battractiveness\b", r"\bopportunit\w*", r"\brecommend\w*",
         r"\byou should\b", r"\bgood (stock|investment|buy)\b", r"\bbest (stocks?|investments?)\b", r"\binvestment idea\w*", r"\bentry point\w*", r"\bexit point\w*"]
ALLOW = ["not a recommendation to buy, sell or hold any security", "Not a recommendation to buy, sell or hold any security", "Not investment advice",
         "not investment advice", "SEBI-registered Investment Adviser", "SEBI-registered investment adviser", "is not a recommendation", "High attention is not a recommendation",
         "'Capital attention' replaces 'opportunity' and 'attractiveness'", "replaces 'opportunity' and 'attractiveness'",
         "renamed from \"Investment Attractiveness\" and \"Opportunity Radar\"", "auditor rejects any conclusion without a traceable evidence row or with recommendation language",
         "with recommendation language", "recommendation language", "recommendation-word", "Recommendation-language", "recommendation words",
         # 2.0 product terms (Akash-approved spec t94u): screen names for research hypotheses, never used about a security
         "Opportunity Discovery", "Opportunity Dossier"]
# code identifiers / schema names for the 2.0 hypothesis tables (opportunity_id, O.opportunities, #/opportunities, 'opportunities', opportunities.json)
CODE_IDS = re.compile(r"\bopportunit\w*_\w*|[./#]opportunities\b|['\"]opportunities['\"]|\bopportunities\.json\b|[{,]\s*opportunities(?=\s*:)|`[^`\n]*`")


FUND_NAME = re.compile(r"(?:\b[A-Z][\w.&'()-]* +)*\bOpportunit\w*(?: +(?:[A-Z][\w.&'()-]*|-|&|of|and))*? +"
                       r"(?:Fund|Funds|AIF|Scheme|Trust|LLP|Ltd\.?|Limited|PLC|Portfolio|Master|Plan|Series|LP|SICAV|Pte)\b")


VEHICLE = re.compile(r"\b(?:Fund|Funds|AIF|Aif|Scheme|Trust|LLP|Llp|Ltd|Limited|PLC|Plc|SICAV|Sicav|Master)\b")


def scan(text):
    for a in ALLOW:
        text = text.replace(a, " ")
    text = CODE_IDS.sub(" ", text)
    # proper names of disclosed funds (e.g. "XYZ Opportunities Fund", "PI Opportunities AIF") are data, not our wording
    text = re.sub(r"\bself_\w+", " ", text)
    text = re.sub(r"\bOPPORTUNIT[A-Z]*\b", " ", text)  # all-caps = holder name exactly as filed with the exchange
    # Title-Case fund names are exempt ONLY when the phrase ends in a fund/vehicle word ("Hem Growth Opportunities Fund", "PI Opportunities AIF II").
    # Any other Title-Case use ("Opportunity Radar", "Sector Opportunities") is our own wording and is flagged.
    text = FUND_NAME.sub(" ", text)
    # a table cell (tab-separated rendered data) that names a fund vehicle anywhere ("Schroder ... Fund Asian Opportunities") is a filed name
    text = "\n".join("\t".join(" " if (VEHICLE.search(c) and re.search(r"\bOpportunit", c)) else c for c in ln.split("\t")) if "\t" in ln else ln
                     for ln in text.split("\n"))
    text = re.sub(r"opportunit\w*[ _]+(master[ _]+)?(fund|aif|scheme)", " ", text, flags=re.I)
    text = re.sub(r'"(Investment Attractiveness|Opportunity Radar|Industry opportunity|Company quality|Investor quality)" is renamed', " ", text, flags=re.I)
    return sorted({m.group(0).lower() for w in WORDS for m in re.finditer(w, text, re.I)})


def texts():
    for f in ["index.html", "assets/app.js", "assets/v2.js", "assets/valuation.js", "README.md", "METHODOLOGY.md"] + sorted(str(Path(x).relative_to(ROOT)) for x in glob.glob(str(ROOT / "docs/*.md"))):
        p = ROOT / f
        if p.exists():
            yield f, p.read_text(encoding="utf-8")
    for f in ("data/analyst/opportunities.json", "data/analyst/valuations.json"):
        p = ROOT / f
        if p.exists():
            yield f, p.read_text(encoding="utf-8")
    v2 = ROOT / "data/export/v2"
    for name in ("signals.json", "opportunities.json", "meta_v2.json"):
        p = v2 / name
        if p.exists():
            d = json.loads(p.read_text())
            if name == "signals.json":  # our own titles/descriptions and rule texts (entity names are filed data)
                yield "v2/" + name, json.dumps([[x.get("title"), x.get("description")] for x in d["signals"]] + [r["text"] for r in d["rules"].values()], ensure_ascii=False)
            else:
                yield "v2/" + name, json.dumps(_strip_quoted(d), ensure_ascii=False)
    for p in glob.glob(str(ROOT / "shots/rendered_*.txt")):
        yield Path(p).name, Path(p).read_text(encoding="utf-8")
    exp = ROOT / "data/export"
    for name in ("conclusions.json", "radar.json", "horizons.json", "global.json", "executive.json"):
        p = exp / name
        if p.exists():
            d = json.loads(p.read_text())
            if name == "conclusions.json":  # only the statements written by the agents; filing text from companies is quoted data
                yield name, "\n".join(c["statement"] for c in d if c.get("auditor_status") != "rejected")
            elif name == "executive.json":
                yield name, json.dumps(d.get("themes", []))
            else:
                yield name, json.dumps(_strip_quoted(d), ensure_ascii=False)


def _strip_quoted(o):
    """Drop quoted third-party text (filing descriptions 'x', PIB items) so the check targets our own wording."""
    if isinstance(o, dict):
        return {k: _strip_quoted(v) for k, v in o.items() if k not in ("x", "items", "description", "inv", "gname", "name", "cn", "entities", "groups", "new_groups")}
    if isinstance(o, list):
        return [_strip_quoted(v) for v in o]
    return o


def main():
    bad = 0
    for name, t in texts():
        hits = scan(t)
        print(f"{name}: {'OK' if not hits else 'HITS ' + ', '.join(hits)}")
        bad += bool(hits)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
