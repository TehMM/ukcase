"""
design_framework.py

This file exists solely to reference the canonical design document for the
UK Caselaw Scraper.

Before writing, analysing, or debugging any code in this repository, you
MUST read docs/design_framework.md and ensure your work is consistent with it.

If code diverges from that design, either:
- Update the code to match the design, OR
- Update docs/design_framework.md (and this file's comments) to reflect
  the new, agreed design.

Scraping modules overview:
- Atom feed utilities (app.scraping.feeds):
  - build_atom_url_for_segment(segment): constructs the Atom feed URL based on Segment fields (query, courts, decision_date_from, decision_date_to).
    The decision_date_* parameter names reflect the current understanding of the
    TNA Atom API and should be updated if upstream naming differs.
  - fetch_atom_entries(segment): fetches the Atom feed using httpx with retry/backoff and parses it via feedparser into a list of AtomEntry objects.
  - AtomEntry: dataclass with canonical_uri, link, title, updated, published, and a computed xml_url property that derives the XML download URL.

- Rate limiting helpers (app.scraping.rate_limit):
  - get_rate_limit_seconds(segment): returns segment.rate_limit_seconds when set, otherwise falls back to Settings.default_rate_limit_seconds.
  - respect_rate_limit(segment): sleeps for the configured number of seconds. This will be called by higher-level scraping loops between HTTP requests to avoid hammering the UK National Archives.

- Segment scraping pipeline (app.scraping.pipeline):
  - Public entrypoints: run_backfill_for_segment(segment_id, max_entries=None) and run_incremental_for_segment(segment_id).
  - Each invocation creates a Run row immediately (status RUNNING, counters zeroed, run_type set).
  - Entries are fetched via build_atom_url_for_segment and fetch_atom_entries. Incremental runs log SKIPPED_EXISTING items for already-known judgments but do not re-download their XML.
  - For each processed entry: invalid canonical_uri → FAILED RunItem; existing judgment → SKIPPED_EXISTING; otherwise download, store, parse, and create a Judgment then mark SUCCESS. Parse or other errors set RunItem FAILED and continue.
  - total_entries counts Atom entries handled in the run (including skipped and failed). Final status: SUCCESS if failed_items == 0; PARTIAL_SUCCESS if failures occurred alongside at least one new judgment; FAILED if failures occurred and no new judgments were created (outer errors also mark FAILED).

- Web application (app.web):
  - create_app() builds a FastAPI app with /healthz, admin routes, and webhook routes mounted.
  - Admin UI uses HTTP Basic auth (settings.admin_username/password) and Jinja2 templates (app/templates) with HTMX/Alpine for progressive enhancement.
  - Routes include /admin/segments (list + trigger backfill/incremental via pipeline entrypoints), /admin/runs (recent runs), and /admin/runs/{id} (details + items).
  - Route handlers are synchronous (def) so FastAPI executes blocking pipeline work in the threadpool until a proper job queue is added.
  - /admin/runs/{id} returns 404 when the requested run does not exist.
  - ChangeDetection.io webhook lives at POST /webhook/changedetection with query params secret + segment_id. The secret must match settings.changedetection_webhook_secret; otherwise 403 is returned. The endpoint validates the segment exists (404 when missing) before triggering run_incremental_for_segment.
"""

DATABASE_SCHEMA = r"""
-- copy the SQL DDL from docs/design_framework.md here verbatim

-- 1. Segments: configuration of feeds / searches
CREATE TABLE segments (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    description         TEXT,

    query               TEXT,
    courts              TEXT[],
    decision_date_from  DATE,
    decision_date_to    DATE,

    backfill_mode       TEXT NOT NULL DEFAULT 'NEW_ONLY',
    rate_limit_seconds  NUMERIC(6, 2) NOT NULL DEFAULT 1.5,

    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_segments_active ON segments (is_active);


-- 2. Judgments: canonical store of all judgments we know about
CREATE TABLE judgments (
    id                      BIGSERIAL PRIMARY KEY,

    -- Canonical unique identity: path-like URI from caselaw site
    canonical_uri           TEXT NOT NULL UNIQUE,
    -- e.g. '/ewhc/comm/2025/3036'

    -- Neutral citation & related metadata
    neutral_citation        TEXT NOT NULL, -- e.g. '[2025] EWHC 3036 (Comm)'
    neutral_citation_number INTEGER,       -- 3036
    court_code              TEXT NOT NULL, -- e.g. 'ewhc/comm'
    decision_date           DATE NOT NULL,
    title                   TEXT NOT NULL, -- case title
    parties                 TEXT,          -- free-text, possibly parsed from XML
    judge                   TEXT,          -- free-text field

    -- File storage (XML only for now)
    xml_path                TEXT NOT NULL, -- local filesystem path or S3 key
    xml_downloaded_at       TIMESTAMPTZ NOT NULL,

    -- Judgment lifecycle status at the scraper layer
    status                  TEXT NOT NULL DEFAULT 'DOWNLOADED',
    -- Suggested values: 'DOWNLOADED', 'PARSING_FAILED', 'MISSING', 'DELETED'

    -- RAG / AI pipeline integration (future-proofing)
    rag_status              TEXT DEFAULT 'NOT_PROCESSED',
    -- e.g. 'NOT_PROCESSED', 'QUEUED', 'EMBEDDED', 'SUMMARY_CREATED', 'FAILED'
    rag_last_processed_at   TIMESTAMPTZ,
    rag_version             INTEGER DEFAULT 1,
    rag_external_id         TEXT, -- optional reference to external vector DB id

    -- Segment linkage (judgment can be discovered by multiple segments)
    -- We store only first-seen segment here for convenience; many-to-many is via run_items
    first_seen_segment_id   INTEGER REFERENCES segments(id),
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_judgments_decision_date ON judgments (decision_date);
CREATE INDEX idx_judgments_court_code_decision_date ON judgments (court_code, decision_date);
CREATE INDEX idx_judgments_rag_status ON judgments (rag_status);


CREATE TABLE runs (
    id                  BIGSERIAL PRIMARY KEY,
    segment_id          INTEGER NOT NULL REFERENCES segments(id),

    trigger_type        TEXT NOT NULL DEFAULT 'UNKNOWN',
    -- 'MANUAL', 'WEBHOOK', 'SCHEDULED', etc.
    run_type            TEXT NOT NULL,
    -- 'BACKFILL' or 'INCREMENTAL'

    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'RUNNING',
    -- 'RUNNING', 'SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED'

    total_entries       INTEGER DEFAULT 0,
    new_judgments       INTEGER DEFAULT 0,
    skipped_existing    INTEGER DEFAULT 0,
    failed_items        INTEGER DEFAULT 0,

    -- For debugging / audit
    error_message       TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_runs_segment_started_at ON runs (segment_id, started_at);


-- 4. Run items: per-judgment outcome during a run
CREATE TABLE run_items (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    judgment_id         BIGINT REFERENCES judgments(id),
    canonical_uri       TEXT NOT NULL,
    -- canonical_uri duplicates judgments.canonical_uri to allow run logging
    -- even when the judgment insert fails

    xml_url             TEXT,
    xml_path            TEXT,

    status              TEXT NOT NULL DEFAULT 'PENDING',
    -- 'PENDING', 'SUCCESS', 'FAILED', 'SKIPPED_EXISTING'

    error_message       TEXT,

    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_run_items_run_id ON run_items (run_id);
CREATE INDEX idx_run_items_canonical_uri ON run_items (canonical_uri);
"""
