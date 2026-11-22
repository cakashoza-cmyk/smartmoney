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
         "with recommendation language", "recommendation language", "recommendation-word", "Recommendation-language", "recommendation words"]


def scan(text):
    for a in ALLOW:
        text = text.replace(a, " ")
    return sorted({m.group(0).lower() for w in WORDS for m in re.finditer(w, text, re.I)})


def texts():
    for f in ["index.html", "assets/app.js", "README.md", "METHODOLOGY.md"]:
        p = ROOT / f
        if p.exists():
            yield f, p.read_text(encoding="utf-8")
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
