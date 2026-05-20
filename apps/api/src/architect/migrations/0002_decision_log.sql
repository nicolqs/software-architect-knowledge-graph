-- Append-only audit of every graph mutation an agent proposes.
-- Plan: agents never mutate the live graph directly. They write a row here
-- with status='proposed'; a human flips status to 'approved' (later 'applied')
-- via the UI; only then does the writer touch Neo4j. Rejected proposals stay
-- in the log for review.
CREATE TABLE IF NOT EXISTS decision_log (
    id              BIGSERIAL   PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent           TEXT        NOT NULL,         -- 'architect' | 'refactor' | ...
    thread_id       TEXT        NULL,             -- LangGraph checkpoint thread
    action          TEXT        NOT NULL,         -- 'propose_node' | 'propose_edge'
    repo            TEXT        NULL,
    target_qname    TEXT        NULL,
    props           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT        NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed', 'approved', 'rejected', 'applied')),
    reviewed_at     TIMESTAMPTZ NULL,
    reviewed_by     TEXT        NULL
);

CREATE INDEX IF NOT EXISTS decision_log_status_idx     ON decision_log (status);
CREATE INDEX IF NOT EXISTS decision_log_agent_idx      ON decision_log (agent);
CREATE INDEX IF NOT EXISTS decision_log_thread_idx     ON decision_log (thread_id);
CREATE INDEX IF NOT EXISTS decision_log_occurred_idx   ON decision_log (occurred_at DESC);
