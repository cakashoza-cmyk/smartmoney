-- migrations/001_opportunity_foundation.sql
-- SQLite-compatible; additive migration (Smart Money Intelligence 2.0 spec, section C2). No existing table is altered or dropped.

CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    entity_type TEXT,
    entity_id TEXT,
    observed_at TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    magnitude REAL,
    unit TEXT,
    direction TEXT,
    evidence_label TEXT NOT NULL,
    confidence REAL,
    source_id TEXT,
    doc_id TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_signals_entity
ON signals(entity_type, entity_id, observed_at);

CREATE INDEX IF NOT EXISTS ix_signals_type_date
ON signals(signal_type, observed_at);

CREATE TABLE IF NOT EXISTS entity_relationships (
    relationship_id TEXT PRIMARY KEY,
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    mechanism TEXT,
    direction TEXT,
    confidence REAL,
    source_doc_id TEXT,
    valid_from TEXT,
    valid_to TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_relationship_from
ON entity_relationships(from_type, from_id);

CREATE INDEX IF NOT EXISTS ix_relationship_to
ON entity_relationships(to_type, to_id);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    thesis TEXT NOT NULL,
    industry_id TEXT,
    sub_industry_id TEXT,
    geography TEXT NOT NULL DEFAULT 'India',
    horizon TEXT NOT NULL DEFAULT '5-10y',
    stage TEXT NOT NULL DEFAULT 'discovery',
    demand_score REAL,
    economics_score REAL,
    competition_score REAL,
    capital_score REAL,
    execution_score REAL,
    valuation_score REAL,
    evidence_coverage REAL,
    owner TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_opportunities_stage
ON opportunities(stage, status);

CREATE TABLE IF NOT EXISTS opportunity_evidence (
    evidence_id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    signal_id TEXT,
    doc_id TEXT,
    evidence_role TEXT NOT NULL,
    explanation TEXT,
    materiality REAL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_opportunity_evidence
ON opportunity_evidence(opportunity_id, recorded_at);

CREATE TABLE IF NOT EXISTS opportunity_scenarios (
    scenario_id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    probability REAL,
    expected_outcome TEXT,
    confirmation_conditions TEXT,
    invalidation_conditions TEXT,
    review_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thesis_updates (
    update_id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    update_date TEXT NOT NULL,
    previous_stage TEXT,
    new_stage TEXT,
    summary TEXT NOT NULL,
    supporting_evidence TEXT,
    opposing_evidence TEXT,
    assumptions_changed TEXT,
    author TEXT
);

CREATE INDEX IF NOT EXISTS ix_thesis_updates
ON thesis_updates(opportunity_id, update_date);
