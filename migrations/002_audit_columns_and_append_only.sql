-- migrations/002_audit_columns_and_append_only.sql
-- Additive: audit columns on the 2.0 tables only, plus database-level guards that make thesis_updates append-only.
-- No v1 table is touched.

ALTER TABLE signals ADD COLUMN rule_id TEXT;              -- which fixed detection rule produced the signal
ALTER TABLE signals ADD COLUMN refs_json TEXT;            -- JSON list of supporting doc_ids / obs_ids / debt_ids
ALTER TABLE signals ADD COLUMN validation_note TEXT;      -- why the signal is validated / candidate / rejected
ALTER TABLE signals ADD COLUMN last_seen_at TEXT;         -- last build that re-detected the same signal

ALTER TABLE opportunities ADD COLUMN starter_hypothesis INTEGER NOT NULL DEFAULT 0;  -- 1 = seeded from detected signals, not yet analyst-reviewed
ALTER TABLE opportunities ADD COLUMN next_review TEXT;
ALTER TABLE opportunities ADD COLUMN detail_json TEXT;    -- analyst-entered lists (candidate beneficiaries / pressured companies, notes)

ALTER TABLE thesis_updates ADD COLUMN recorded_at TEXT;   -- when the pipeline first stored the update (cannot be back-dated)

CREATE INDEX IF NOT EXISTS ix_signals_rule ON signals(rule_id, observed_at);

CREATE TRIGGER IF NOT EXISTS thesis_updates_no_update
BEFORE UPDATE ON thesis_updates
BEGIN
    SELECT RAISE(ABORT, 'thesis_updates is append-only: add a new update instead of editing one');
END;

CREATE TRIGGER IF NOT EXISTS thesis_updates_no_delete
BEFORE DELETE ON thesis_updates
BEGIN
    SELECT RAISE(ABORT, 'thesis_updates is append-only: history cannot be deleted');
END;
