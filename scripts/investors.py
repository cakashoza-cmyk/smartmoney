"""Deterministic investor-name -> parent-group resolution (no ML, no LLM)."""
import re
from common import hid, upsert, slug
from registry import GROUPS, INST_HINTS

_RX = [(g[0], re.compile(g[6])) for g in GROUPS]
INDIVIDUAL_RX = re.compile(r"^[A-Z]+( [A-Z]\.?)?( [A-Z]+){0,3}$")


def classify_name(name):
    """Returns (group_id or None, category, rule). Passive first so an SBI ETF is passive, not SBI active."""
    u = re.sub(r"\s+", " ", (name or "").upper()).strip()
    order = ["trading_firms", "odi_desks", "passive_vehicles", "brokers_prop"]
    for gid, rx in _RX:
        if gid in order and rx.search(u):
            return gid, None, f"group rule {gid}"
    for gid, rx in _RX:
        if gid not in order and rx.search(u):
            return gid, None, f"group rule {gid}"
    for rx, cat in INST_HINTS:
        if re.search(rx, u):
            return None, cat, f"suffix rule -> {cat}"
    return None, "individual_or_unknown", "no institutional marker"


def resolve(con, name, group_cat=None):
    """Ensure investor (+ self-group when no parent) exists. Returns (investor_id, group_id, category)."""
    gid, cat, rule = classify_name(name)
    iid = "inv_" + hid(re.sub(r"\s+", " ", name.upper()).strip())
    if gid:
        g = con.execute("SELECT category FROM investor_groups WHERE group_id=?", (gid,)).fetchone()
        cat = g["category"] if g else cat
    else:
        gid = "self_" + slug(name)[:60]
        upsert(con, "investor_groups", dict(group_id=gid, name=name.title(), category=cat, country=None, aum_disclosed=None, passive_flag=0,
                                            trading_flag=0, notes="no known parent; entity is its own group (" + rule + ")", source_url=None), "group_id")
    upsert(con, "investors", dict(investor_id=iid, name=name, group_id=gid, category=group_cat or cat, match_rule=rule), "investor_id")
    return iid, gid, cat
