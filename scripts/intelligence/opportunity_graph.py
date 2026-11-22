"""Analyst-entered research hypotheses ("opportunities" in the schema), their evidence, scenarios, relationships and the
append-only thesis history. Source of truth for hypotheses is data/analyst/opportunities.json, changed only by a reviewed
commit (pull request). The pipeline never creates, scores or promotes a hypothesis on its own: it validates the file,
stores it, and reports which stage criteria are met so an analyst can decide."""
from __future__ import annotations
import json, re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import hid, now  # noqa: E402
from intelligence import valuation_engine as ve  # noqa: E402

STAGES = ["discovery", "validation", "emergence", "investable_review"]
END_STAGES = ["invalidated", "archived"]
HORIZONS = ["1-3y", "3-10y", "5-10y", "10-15y", "10-20y"]
ROLES = ["supporting", "contradicting", "contextual"]
COMPANY_ROLES = ["candidate_beneficiary", "candidate_pressured", "context"]
DIMENSIONS = ["structural_demand", "industry_economics", "competitive_position", "capital_allocation", "company_execution", "valuation"]
SIGNAL_DIMENSION = {"capital_flow": "capital_allocation", "credit": "capital_allocation", "credit_quality": "industry_economics",
                    # Sprint 2
                    "structural_demand": "structural_demand", "industry_economics": "industry_economics", "company_execution": "company_execution",
                    "competitive_position": "competitive_position", "global": "industry_economics"}
STAGE_CRITERIA = {
    "discovery": "At least one validated supporting signal is linked.",
    "validation": "At least two validated supporting signals from two or more independent sources are linked.",
    "emergence": "Validation criteria, plus at least one validated company-level supporting signal, at least one recorded confirmation condition, and validated supporting evidence on structural demand (industrial production, exports, capacity utilisation) or company execution (reported company results).",
    "investable_review": "Emergence criteria, plus a complete analyst scenario set (probabilities total 100%) and at least one analyst valuation for a linked company.",
}


def _load(path: Path, key):
    if not path.exists():
        return []
    return json.loads(path.read_text()).get(key, [])


class Loader:
    def __init__(self, con, opp_path: Path, val_path: Path, ts=None):
        self.con, self.ts = con, ts or now()
        self.opps = _load(opp_path, "opportunities")
        self.updates = _load(opp_path, "thesis_updates")
        self.vals = _load(val_path, "valuations")
        self.errors, self.warnings = [], []

    def q(self, sql, *a):
        return self.con.execute(sql, a).fetchall()

    # ------------------------------------------------------------------ validation + storage
    def run(self):
        inds = {r[0] for r in self.q("SELECT industry_id FROM industries")}
        ids = set()
        for o in self.opps:
            oid = o.get("opportunity_id", "")
            if not re.fullmatch(r"opp_[a-z0-9_]+", oid):
                self.errors.append(f"bad opportunity_id {oid!r}"); continue
            if oid in ids:
                self.errors.append(f"duplicate opportunity_id {oid}"); continue
            ids.add(oid)
            for k in ("title", "thesis", "owner", "created_at"):
                if not o.get(k):
                    self.errors.append(f"{oid}: missing {k}")
            if o.get("industry_id") and o["industry_id"] not in inds:
                self.errors.append(f"{oid}: unknown industry_id {o['industry_id']}")
            if o.get("horizon") not in HORIZONS:
                self.errors.append(f"{oid}: horizon must be one of {HORIZONS}")
            for k in ("demand_score", "economics_score", "competition_score", "capital_score", "execution_score", "valuation_score", "composite_score"):
                if o.get(k) is not None:
                    self.errors.append(f"{oid}: {k} is not accepted in Sprint 1 (no scores; no composite)")
        self.store_updates(ids)
        for o in self.opps:
            if o.get("opportunity_id") in ids:
                self.store_opportunity(o)
        self.check_valuations(ids)
        return self

    def store_updates(self, ids):
        by = defaultdict(list)
        for u in self.updates:
            by[u.get("opportunity_id")].append(u)
        for oid, us in by.items():
            if oid not in ids:
                self.errors.append(f"thesis update for unknown hypothesis {oid}"); continue
            for u in sorted(us, key=lambda x: (x.get("update_date") or "", x.get("update_id") or "")):
                uid = u.get("update_id")
                if not uid or not u.get("summary") or not u.get("update_date"):
                    self.errors.append(f"{oid}: thesis update needs update_id, update_date, summary"); continue
                cols = ("update_id", "opportunity_id", "update_date", "previous_stage", "new_stage", "summary", "supporting_evidence", "opposing_evidence", "assumptions_changed", "author")
                vals = tuple(u.get(c) if not isinstance(u.get(c), (list, dict)) else json.dumps(u.get(c)) for c in cols)
                have = self.q(f"SELECT {','.join(cols)} FROM thesis_updates WHERE update_id=?", uid)
                if have:
                    if tuple(have[0]) != vals:
                        self.errors.append(f"{oid}: thesis update {uid} differs from the stored version; history is append-only, add a new update instead")
                    continue
                last = self.q("SELECT update_date, new_stage FROM thesis_updates WHERE opportunity_id=? ORDER BY update_date DESC, recorded_at DESC LIMIT 1", oid)
                cur_stage = last[0][1] if last else None
                if last and u["update_date"] < last[0][0]:
                    self.errors.append(f"{oid}: update {uid} is dated {u['update_date']}, before the latest stored update ({last[0][0]}); back-dating is not allowed"); continue
                if u["update_date"] > self.ts[:10]:
                    self.errors.append(f"{oid}: update {uid} is dated in the future"); continue
                if (u.get("previous_stage") or None) != cur_stage:
                    self.errors.append(f"{oid}: update {uid} says previous stage {u.get('previous_stage')!r} but the recorded stage is {cur_stage!r}"); continue
                ns = u.get("new_stage")
                if ns not in STAGES + END_STAGES:
                    self.errors.append(f"{oid}: update {uid} has unknown stage {ns!r}"); continue
                self.con.execute(f"INSERT INTO thesis_updates ({','.join(cols)}, recorded_at) VALUES ({','.join('?' * (len(cols) + 1))})", vals + (self.ts,))

    def store_opportunity(self, o):
        oid = o["opportunity_id"]
        last = self.q("SELECT new_stage FROM thesis_updates WHERE opportunity_id=? ORDER BY update_date DESC, recorded_at DESC LIMIT 1", oid)
        stage = last[0][0] if last else "discovery"
        if not last:
            self.warnings.append(f"{oid}: no thesis update recorded; stage shown as discovery")
        status = {"invalidated": "invalidated", "archived": "archived"}.get(stage, o.get("status") or "active")
        detail = {"companies": o.get("companies", []), "confirmation_conditions": o.get("confirmation_conditions", []),
                  "invalidation_conditions": o.get("invalidation_conditions", []), "open_questions": o.get("open_questions", []),
                  "notes": o.get("notes")}
        prev = self.q("SELECT created_at FROM opportunities WHERE opportunity_id=?", oid)
        self.con.execute("""INSERT INTO opportunities (opportunity_id, title, thesis, industry_id, sub_industry_id, geography, horizon, stage, owner, status,
                            created_at, updated_at, starter_hypothesis, next_review, detail_json)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET title=excluded.title, thesis=excluded.thesis,
                            industry_id=excluded.industry_id, sub_industry_id=excluded.sub_industry_id, geography=excluded.geography, horizon=excluded.horizon,
                            stage=excluded.stage, owner=excluded.owner, status=excluded.status, updated_at=excluded.updated_at,
                            starter_hypothesis=excluded.starter_hypothesis, next_review=excluded.next_review, detail_json=excluded.detail_json""",
                         (oid, o["title"], o["thesis"], o.get("industry_id"), o.get("sub_industry_id"), o.get("geography") or "India", o["horizon"], stage,
                          o["owner"], status, prev[0][0] if prev else o["created_at"], self.ts, 1 if o.get("starter_hypothesis") else 0, o.get("next_review"),
                          json.dumps(detail)))
        # evidence (editable explanation/materiality; recorded_at kept)
        for e in o.get("evidence", []):
            sid, did, role = e.get("signal_id"), e.get("doc_id"), e.get("role")
            if role not in ROLES:
                self.errors.append(f"{oid}: evidence role must be one of {ROLES}"); continue
            if sid and not self.q("SELECT 1 FROM signals WHERE signal_id=?", sid):
                self.errors.append(f"{oid}: evidence refers to unknown signal {sid}"); continue
            if did and not self.q("SELECT 1 FROM source_documents WHERE doc_id=?", did):
                self.errors.append(f"{oid}: evidence refers to unknown document {did}"); continue
            if not sid and not did:
                self.errors.append(f"{oid}: evidence needs a signal_id or doc_id"); continue
            if sid and not did:
                did = self.q("SELECT doc_id FROM signals WHERE signal_id=?", sid)[0][0]
            eid = "ev_" + hid(oid, sid, e.get("doc_id"), role)
            self.con.execute("""INSERT INTO opportunity_evidence (evidence_id, opportunity_id, signal_id, doc_id, evidence_role, explanation, materiality, recorded_at)
                                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(evidence_id) DO UPDATE SET explanation=excluded.explanation, materiality=excluded.materiality""",
                             (eid, oid, sid, did, role, e.get("explanation"), e.get("materiality"), self.ts))
        # scenarios (analyst-assigned probabilities; must total 100 when all are set)
        scs = o.get("scenarios", [])
        probs = [s.get("probability") for s in scs]
        if scs and all(p is not None for p in probs) and abs(sum(probs) - 100) > 0.01:
            self.errors.append(f"{oid}: scenario probabilities total {sum(probs)}, not 100")
        for s in scs:
            if not s.get("scenario_name") or s.get("assumptions") is None:
                self.errors.append(f"{oid}: scenario needs scenario_name and assumptions"); continue
            self.con.execute("""INSERT INTO opportunity_scenarios (scenario_id, opportunity_id, scenario_name, assumptions_json, probability, expected_outcome,
                                confirmation_conditions, invalidation_conditions, review_date, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(scenario_id) DO UPDATE SET assumptions_json=excluded.assumptions_json, probability=excluded.probability,
                                expected_outcome=excluded.expected_outcome, confirmation_conditions=excluded.confirmation_conditions,
                                invalidation_conditions=excluded.invalidation_conditions, review_date=excluded.review_date""",
                             ("sc_" + hid(oid, s["scenario_name"]), oid, s["scenario_name"], json.dumps(s["assumptions"]), s.get("probability"), s.get("expected_outcome"),
                              s.get("confirmation_conditions"), s.get("invalidation_conditions"), s.get("review_date"), self.ts))
        # relationships: hypothesis -> industry, hypothesis -> analyst-listed companies
        rels = []
        if o.get("industry_id"):
            rels.append(("opportunity", oid, "concerns", "industry", o["industry_id"], "Industry the hypothesis is about (analyst-entered)", None))
        for c in o.get("companies", []):
            if c.get("role") not in COMPANY_ROLES:
                self.errors.append(f"{oid}: company role must be one of {COMPANY_ROLES}"); continue
            if not self.q("SELECT 1 FROM companies WHERE company_id=?", c.get("company_id")):
                self.errors.append(f"{oid}: unknown company {c.get('company_id')}"); continue
            rels.append(("opportunity", oid, c["role"], "company", c["company_id"], c.get("note") or "Analyst-entered link", None))
        for ft, fi, rel, tt, ti, mech, d in rels:
            self.con.execute("""INSERT INTO entity_relationships (relationship_id, from_type, from_id, relation_type, to_type, to_id, mechanism, direction, confidence, source_doc_id, valid_from, valid_to, created_at)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(relationship_id) DO UPDATE SET mechanism=excluded.mechanism""",
                             ("rel_" + hid(ft, fi, rel, tt, ti), ft, fi, rel, tt, ti, mech, d, None, None, o["created_at"], None, self.ts))
        self.con.execute("UPDATE opportunities SET evidence_coverage=? WHERE opportunity_id=?", (self.coverage(oid)["share"], oid))

    def check_valuations(self, ids):
        seen = set()
        for v in self.vals:
            vid = v.get("valuation_id")
            if not vid or vid in seen:
                self.errors.append(f"valuation without a unique valuation_id: {vid!r}"); continue
            seen.add(vid)
            if not self.q("SELECT 1 FROM companies WHERE company_id=?", v.get("company_id")):
                self.errors.append(f"{vid}: unknown company {v.get('company_id')}")
            if v.get("opportunity_id") and v["opportunity_id"] not in ids:
                self.errors.append(f"{vid}: unknown hypothesis {v['opportunity_id']}")
            for k in ("analyst", "as_of", "assumptions", "source_notes"):
                if not v.get(k):
                    self.errors.append(f"{vid}: missing {k}")
            err = ve.check(v.get("assumptions") or {})
            if err:
                self.errors.append(f"{vid}: {err}")
            for k in ("revenue0", "net_debt", "market_value"):
                if not (v.get("source_notes") or {}).get(k):
                    self.errors.append(f"{vid}: source_notes.{k} must say where the analyst took this figure from")

    # ------------------------------------------------------------------ analysis helpers (no promotion)
    def evidence(self, oid):
        rows = self.q("""SELECT e.evidence_id, e.signal_id, e.doc_id, e.evidence_role, e.explanation, e.materiality, e.recorded_at,
                                s.signal_type, s.title, s.entity_type, s.entity_id, s.observed_at, s.detected_at, s.direction, s.status, s.source_id, s.rule_id,
                                s.magnitude, s.unit, sd.url
                         FROM opportunity_evidence e LEFT JOIN signals s ON s.signal_id=e.signal_id LEFT JOIN source_documents sd ON sd.doc_id=e.doc_id
                         WHERE e.opportunity_id=? ORDER BY e.materiality DESC, s.observed_at DESC""", oid)
        keys = ("evidence_id", "signal_id", "doc_id", "role", "explanation", "materiality", "recorded_at", "signal_type", "title", "entity_type", "entity_id",
                "observed_at", "detected_at", "direction", "signal_status", "source_id", "rule_id", "magnitude", "unit", "url")
        return [dict(zip(keys, r)) for r in rows]

    def coverage(self, oid):
        ev = [e for e in self.evidence(oid) if e["signal_status"] == "validated" or (e["signal_id"] is None and e["doc_id"])]
        cov = {d: False for d in DIMENSIONS}
        for e in ev:
            if e["signal_type"] in SIGNAL_DIMENSION:
                cov[SIGNAL_DIMENSION[e["signal_type"]]] = True
        if any(v.get("opportunity_id") == oid for v in self.vals):
            cov["valuation"] = True
        return {"dimensions": cov, "share": round(sum(cov.values()) / len(cov), 3)}

    def criteria(self, oid, detail):
        sup = [e for e in self.evidence(oid) if e["role"] == "supporting" and e["signal_status"] == "validated"]
        srcs = {e["source_id"] for e in sup}
        comp = [e for e in sup if e["entity_type"] == "company"]
        scs = self.q("SELECT probability FROM opportunity_scenarios WHERE opportunity_id=?", oid)
        full = bool(scs) and all(p[0] is not None for p in scs) and abs(sum(p[0] for p in scs) - 100) < 0.01
        has_val = any(v.get("opportunity_id") == oid for v in self.vals)
        res = {}
        res["discovery"] = {"met": len(sup) >= 1, "why": f"{len(sup)} validated supporting signal(s)"}
        res["validation"] = {"met": len(sup) >= 2 and len(srcs) >= 2, "why": f"{len(sup)} validated supporting signal(s) from {len(srcs)} source(s): {', '.join(sorted(s for s in srcs if s))}"}
        sup_dims = {SIGNAL_DIMENSION.get(e["signal_type"]) for e in sup}
        dem = bool(sup_dims & {"structural_demand", "company_execution"})
        res["emergence"] = {"met": res["validation"]["met"] and bool(comp) and bool(detail.get("confirmation_conditions")) and dem,
                            "why": f"{len(comp)} company-level supporting signal(s); {len(detail.get('confirmation_conditions') or [])} confirmation condition(s); supporting demand/execution evidence: {', '.join(sorted(d for d in sup_dims & {'structural_demand', 'company_execution'})) if dem else 'none linked'}"}
        res["investable_review"] = {"met": res["emergence"]["met"] and full and has_val,
                                    "why": f"complete scenario set: {'yes' if full else 'no'}; analyst valuation linked: {'yes' if has_val else 'no'}"}
        return res

    def related_unlinked(self, oid, industry, companies, days=120):
        linked = {r[0] for r in self.q("SELECT signal_id FROM opportunity_evidence WHERE opportunity_id=? AND signal_id IS NOT NULL", oid)}
        since = (date.fromisoformat(self.ts[:10]) - timedelta(days=days)).isoformat()
        ents = [("industry", industry)] + [("company", c) for c in companies]
        if industry:
            ents += [("company", r[0]) for r in self.q("SELECT company_id FROM companies WHERE industry_id=?", industry)]
        out = []
        for et, ei in ents:
            for r in self.q("SELECT signal_id, title, direction, observed_at, detected_at, source_id, rule_id FROM signals WHERE entity_type=? AND entity_id=? AND status='validated' AND observed_at>=?", et, ei, since):
                if r[0] not in linked:
                    out.append(dict(zip(("signal_id", "title", "direction", "observed_at", "detected_at", "source_id", "rule_id"), r)))
        seen, uniq = set(), []
        for x in sorted(out, key=lambda x: x["observed_at"], reverse=True):
            if x["signal_id"] not in seen:
                seen.add(x["signal_id"]); uniq.append(x)
        return uniq
