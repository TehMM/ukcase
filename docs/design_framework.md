UK Caselaw Scraper – Design Framework (v1)

MUST READ FIRST
Any time you (human or Codex) write, analyse, or debug code for this project, you must read this document first and ensure the implemented code matches this design.

After every major feature or refactor, update this document.

When debugging, if you discover design changes or edge cases, update this document so it remains the single source of truth.

0. Purpose & Scope
0.1 Goal

Scrape UK National Archives caselaw from:

https://caselaw.nationalarchives.gov.uk/

via Atom feeds and individual judgment pages, to:

Backfill historical cases for configured “segments”.

Incrementally ingest new cases going forward (manual or webhook-triggered).

Persist judgments (XML + metadata) into a PostgreSQL-backed catalog for later use in a separate AI / RAG pipeline.

We focus on:

XML downloads (LegalDocML) as the canonical source of truth.

Robustness, idempotency, and auditability.

Extensibility for future integration with Jina, Firecrawl, agentQL, Multion, and RAG processing.

0.2 Out of Scope (for this project)

No summarisation / embedding / RAG in this codebase (just prepare for it).

No heavy Selenium-based scraping for this specific site (architecture is pluggable but not used here).

No complex multi-tenant auth; basic single-user admin-style auth only.

1. Tech Stack
1.1 Core

Language: Python (3.11+)

Web framework: FastAPI

Templating: Jinja2

Progressive enhancement: HTMX + Alpine.js for simple interactive UI

HTTP client: httpx (async-capable, used in sync style with wrappers if needed)

Atom parsing: feedparser (or equivalent) for robustness

HTML parsing (fallback): BeautifulSoup (bs4)

Database: PostgreSQL

ORM: SQLAlchemy (2.x) or SQLModel (if chosen; but stick to one – see implementation)

Task queue: Redis + RQ (background workers)

Containerisation: Docker (for deployment on VPS via Coolify or similar)

1.2 Advanced / Pluggable (not required for v1)

These are architecturally anticipated but not hard dependencies for this site:

Jina / Firecrawl: for future large-scale or cross-site text extraction / crawling.

agentQL: for future automation of complex flows (login, forms).

Multion: for exploratory / unknown workflows.

Selenium / Playwright: for future dynamic sites; not used for this static-ish Atom-based workflow.

Architecture provides extension points where these tools can be plugged in without rewiring the core.

2. High-Level Architecture
2.1 Components

API & Web UI (FastAPI)

Exposes routes for:

Managing segments (search configs).

Triggering manual runs.

Viewing runs and judgments.

Webhook endpoints (ChangeDetection.io).

Uses Jinja2 + HTMX for a simple admin UI.

2.2 Web app and admin UI

- FastAPI app is created via `app.web.main.create_app()` and exposes:
  - `/healthz` simple JSON probe.
  - Admin HTML routes mounted from `app.web.routes_admin` (templated with Jinja2 in `app/templates`).
  - Webhook routes from `app.web.routes_webhook`.
- Admin UI security:
  - HTTP Basic authentication using `UKCASE_ADMIN_USERNAME` / `UKCASE_ADMIN_PASSWORD` (settings.admin_username/password).
  - Expected to be deployed behind HTTPS termination (e.g., Coolify / reverse proxy).
- Admin pages:
  - `/admin/segments` lists segments and provides HTMX buttons to trigger backfill or incremental runs per segment. Buttons POST to `/admin/segments/{segment_id}/run/backfill` and `/admin/segments/{segment_id}/run/incremental` and render small partials with run status/counters.
  - `/admin/runs` lists up to 50 recent runs via `crud.list_recent_runs` with links to details.
  - `/admin/runs/{run_id}` shows run metadata and associated RunItems (canonical_uri, status, error_message) fetched via `crud.get_run_with_items`; returns HTTP 404 when the run is missing.
  - Templates include HTMX + Alpine from CDNs via `app/templates/base.html`.
- Route handlers are synchronous (`def`) so FastAPI runs blocking pipeline calls in its threadpool until a queue is added.
- Webhook: ChangeDetection.io
  - Endpoint: `POST /webhook/changedetection`.
  - Query parameters: `segment_id` (int), `secret` (str).
  - Secret must match `UKCASE_CHANGEDTECTION_WEBHOOK_SECRET` (settings.changedetection_webhook_secret) or the endpoint returns HTTP 403. If the segment does not exist, the endpoint returns HTTP 404.
  - On success, triggers `pipeline.run_incremental_for_segment(segment_id)` and returns a JSON summary (run_id, segment_id, status, total_entries, new_judgments, skipped_existing, failed_items).
  - Example CD.io notification URL: `https://example.com/webhook/changedetection?segment_id=12&secret=YOUR_SECRET`.

Task Queue (RQ + Redis)

Job types:

backfill_segment(segment_id)

incremental_segment_run(segment_id)

Workers run in separate process/container.

Scraping Core

Functions to:

Build and call Atom feed URLs.

Parse Atom into normalized entries.

Derive XML URLs from canonical URIs.

Download XML.

Parse XML to extract metadata.

Persist to DB.

Persistence Layer (Postgres + SQLAlchemy)

Tables:

segments

runs

run_items

judgments

Optional: future files / attachments.

Security & Auth

Basic HTTP auth for UI.

Secret token-based webhook endpoints for ChangeDetection.io.

Configuration

Environment variables:

DB URL, Redis URL, base app URL, default rate limits, auth credentials, etc.

3. Data Model & Database Schema

Canonical schema lives here. Any ORM models must match this DDL. If you change models, update this DDL.

3.1 Entities & Relationships (Conceptual)

Segment
A reusable search definition (e.g. “EWHC (Ch, Comm, KB) with keyword ‘fiduciary’”).
A segment corresponds to a consistent feed configuration.

Run
A single execution of a scraper pipeline for a segment. Triggered by:

Manual user action

Internal scheduler

Webhook (ChangeDetection.io)

RunItem
The per-judgment outcome in a run:

New judgment downloaded

Already known (skipped)

Failed to download/parse, with error reason

Judgment
A canonical judgment record, with metadata, XML path, and RAG-related fields.

3.2 PostgreSQL DDL (Initial)
-- 1. Segments: configuration of feeds / searches
CREATE TABLE segments (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    description         TEXT,

    query               TEXT,           -- main keyword/text query
    courts              TEXT[],         -- e.g. ['ewhc/ch', 'ewhc/comm']
    decision_date_from  DATE,
    decision_date_to    DATE,

    backfill_mode       TEXT NOT NULL DEFAULT 'NEW_ONLY',
    rate_limit_seconds  NUMERIC(6, 2) NOT NULL DEFAULT 1.5, -- default ~1 request / 1.5s

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


-- 3. Runs: each execution of a scraping job for a given segment
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


NOTE: Any time we change the schema (add column, change meaning, add enum value), update this DDL and comment the version change.

7. Segment scraping pipeline

The segment-level orchestrator lives in `app/scraping/pipeline.py` and exposes two public entrypoints:

- `run_backfill_for_segment(segment_id: int, max_entries: Optional[int] = None)`
- `run_incremental_for_segment(segment_id: int)`

Both delegate to `run_segment`, which:

- Loads the `Segment` by id and creates a `Run` row immediately (status `RUNNING`, counters zeroed, `run_type` set to `BACKFILL` or `INCREMENTAL`).
- Fetches Atom entries via `build_atom_url_for_segment` and `fetch_atom_entries`.
- Filters entries:
  - Backfill: processes every entry in the feed (optionally capped by `max_entries`).
  - Incremental: processes only entries whose `canonical_uri` is not already in `Judgment`.
- Iterates entries with per-entry durability (commit after each item) and rate-limits via `respect_rate_limit` before HTTP calls.
- For each entry:
  - If the `canonical_uri` is invalid, record a failed `RunItem` and continue.
  - If a `Judgment` already exists, record a `RunItem` with status `SKIPPED_EXISTING` and increment `skipped_existing` (incremental runs still log these skips without re-downloading the XML).
  - Otherwise: download XML (`download_xml_for_canonical_uri`), persist it (`store_xml_to_disk`), parse metadata (`parse_judgment_metadata_from_xml`), create a `Judgment`, and mark the `RunItem` `SUCCESS`.
  - Parse errors (`MetadataParseError`) or other exceptions are captured on the `RunItem` (status `FAILED`, truncated `error_message`) while allowing the run to continue.
- `total_entries` counts Atom entries handled during the run (including skipped and failed items).
- When all entries are processed:
  - `SUCCESS` if `failed_items == 0`.
  - `PARTIAL_SUCCESS` if there were failures but at least one new judgment succeeded.
  - `FAILED` if failures occurred and no new judgments were created (outer errors also mark `FAILED`).

Current incremental semantics: “new” means there is no existing `Judgment` row with the same `canonical_uri`. Future iterations may refine this using timestamps or last successful run markers.

4. Configuration & Environment
4.1 Environment Variables

UKCASE_APP_ENV – dev / prod / etc.

UKCASE_DATABASE_URL – PostgreSQL connection string (tests default to SQLite fallback).

UKCASE_REDIS_URL – Redis connection for RQ.

UKCASE_APP_BASE_URL – e.g. https://caselaw-scraper.example.com.

UKCASE_ADMIN_USERNAME, UKCASE_ADMIN_PASSWORD – for basic auth on UI.

UKCASE_DEFAULT_RATE_LIMIT_SECONDS – default rate limit (e.g. 1.5).

UKCASE_REQUEST_TIMEOUT_SECONDS – e.g. 20.

UKCASE_MAX_HTTP_RETRIES – e.g. 4.

4.2 Security

UI protected with HTTP Basic auth.

Webhook secured via:

Random changedetection_token per segment, used in URL path:
/webhooks/changedetection/{token}

HTTPS enforced at reverse proxy layer (Coolify / nginx).

5. Segment & Feed Configuration
5.1 Definition

A segment is a saved search configuration for the National Archives advanced search.

Fields mirror advanced search where possible:

query – text query (can be NULL).

courts – array of court codes (e.g. ['ewhc/ch', 'ewhc/comm', 'ewhc/kb']).

decision_date_from / decision_date_to – optional bounds for decision date filters.

backfill_mode – scraper behaviour hint, default NEW_ONLY (process new items only) or FULL_HISTORY for full backfill.

rate_limit_seconds – per-segment override; default is from env (1.5s).
Stored as NUMERIC(6, 2) to bound values to sensible precision.

is_active – whether the segment participates in scheduled/surfaced lists.

5.2 Atom URL Construction (Default)

Base: https://caselaw.nationalarchives.gov.uk/atom.xml

Query params:

query = segment.query (if not null)

court = each element of segment.courts as repeated parameter

decision_date_from / decision_date_to = ISO date strings if provided.

Note: decision_date_from / decision_date_to parameter names reflect the current
understanding of the TNA Atom API. If upstream naming differs, update the code
and this document together.

Example:

https://caselaw.nationalarchives.gov.uk/atom.xml?query=fiduciary&court=ewhc%2Fch&court=ewhc%2Fcomm&court=ewhc%2Fkb

6. Scraping Pipeline Design

We support two main operations:

One-time backfill – “load everything” according to backfill_mode.

Incremental run – “since last scrape”, based on DB state.

Both share the same core pipeline but differ in filtering logic.

6.1 Canonical Identifier & URL Derivation

Canonical judgment URL from Atom:
https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/3036

canonical_uri is the path part:
/ewhc/comm/2025/3036

XML URL is derived as:
https://caselaw.nationalarchives.gov.uk{canonical_uri}/data.xml

We first try derivation. If HTTP 404 or other error:

Fallback: fetch HTML page, parse <section id="download-options"> to find XML link.

6.2 Core Steps (Pseudocode)
6.2.1 High-level run
def run_segment_scrape(segment_id: int, trigger_type: str, mode: str) -> None:
    """
    mode: 'BACKFILL' or 'INCREMENTAL'
    trigger_type: 'MANUAL' | 'WEBHOOK' | 'SCHEDULED'
    """
    segment = load_segment(segment_id)
    run = create_run(segment_id=segment.id, trigger_type=trigger_type)

    try:
        entries = fetch_atom_entries(segment)
        entries = sort_entries(entries)  # likely by decision date or feed order

        stats = {
            "total": 0,
            "new": 0,
            "skipped": 0,
            "failed": 0,
        }

        for entry in entries:
            respect_rate_limit(segment)

            canonical_uri = normalize_entry_uri(entry)
            decision_date = extract_decision_date(entry)  # from Atom or later from XML
            # Filter by backfill_mode / mode
            if not should_process(entry, segment, mode, decision_date):
                continue

            stats["total"] += 1

            try:
                result = process_single_entry(
                    segment=segment,
                    run=run,
                    canonical_uri=canonical_uri,
                    entry=entry
                )
            except Exception as exc:
                log_run_item_failure(run, canonical_uri, exc)
                stats["failed"] += 1
                continue

            if result.action == "CREATED":
                stats["new"] += 1
            elif result.action.startswith("SKIPPED"):
                stats["skipped"] += 1

        finalize_run(run, stats)
    except Exception as exc:
        mark_run_failed(run, exc)
        raise

6.2.2 process_single_entry
def process_single_entry(segment, run, canonical_uri, entry):
    # 1. Check if judgment already exists
    existing = find_judgment_by_canonical_uri(canonical_uri)
    if existing:
        # Optionally, we might still verify XML presence or update metadata
        log_run_item(run, existing.id, canonical_uri,
                     action="SKIPPED_ALREADY_EXISTS", status="SUCCESS")
        return Result(action="SKIPPED_ALREADY_EXISTS", judgment=existing)

    # 2. Derive XML URL
    xml_url = derive_xml_url(canonical_uri)

    # 3. Download XML with retry/backoff
    xml_content = fetch_with_retries(xml_url)

    # 4. Persist XML to filesystem
    xml_path = store_xml_to_disk(canonical_uri, xml_content)

    # 5. Parse XML for metadata
    meta = parse_judgment_metadata_from_xml(xml_content)
    # meta must contain:
    # - neutral_citation
    # - neutral_citation_number
    # - court_code
    # - decision_date
    # - title
    # - parties
    # - judge

    # 6. Insert judgment into DB
    judgment = create_judgment(
        canonical_uri=canonical_uri,
        neutral_citation=meta.neutral_citation,
        neutral_citation_number=meta.neutral_citation_number,
        court_code=meta.court_code,
        decision_date=meta.decision_date,
        title=meta.title,
        parties=meta.parties,
        judge=meta.judge,
        xml_path=xml_path,
        xml_downloaded_at=now(),
        status="DOWNLOADED",
        first_seen_segment_id=segment.id,
        first_seen_at=now(),
        rag_status="NOT_PROCESSED",
    )

    # 7. Log run item
    log_run_item(run, judgment.id, canonical_uri,
                 action="CREATED", status="SUCCESS")

    return Result(action="CREATED", judgment=judgment)

6.2.3 XML Metadata Parsing

We parse now from XML (not later in the AI layer):

Case ID → stored implicitly via canonical_uri and/or an explicit field if needed later.

Neutral Citation (full string).

Decision date.

Title.

Parties.

Judge.

Neutral Citation Number (integer portion, e.g. 3036).

Implementation:

Use lxml or ElementTree.

Write a dedicated parser module, e.g. parsers/national_archives_xml.py, encapsulating site-specific schema handling.

Parser must be unit-tested with sample XML fixtures.

6.3 XML download, parsing, and persistence helpers

- XML download (app.scraping.xml_download)
  - download_xml_for_canonical_uri(canonical_uri): derives the XML URL, fetches it with retry/backoff on HTTP 429, HTTP 5xx, or network-level errors, and returns (xml_url, content). Other 4xx responses raise immediately without retry. All requests send the configured User-Agent and `Accept: application/xml, text/xml;q=0.9, */*;q=0.8` and respect request_timeout_seconds / max_http_retries. “Case ID” is currently the canonical_uri from the Atom feed; we may later parse an explicit XML identifier into JudgmentMetadata once the LegalDocML headers are confirmed.
  - store_xml_to_disk(canonical_uri, xml_content): normalises canonical_uri (no query/fragment, rejects traversal) and writes XML to xml_storage_root / canonical_uri / "data.xml" using atomic replace. xml_storage_root is a Path.

- XML parsing (app.scraping.xml_parse)
  - JudgmentMetadata dataclass captures neutral_citation, neutral_citation_number, court_code, decision_date, title, parties, and judge.
  - parse_judgment_metadata_from_xml(xml_bytes): extracts mandatory metadata from LegalDocML XML and raises MetadataParseError when required fields are missing or invalid.

- Judgment CRUD helpers (app.db.crud)
  - get_judgment_by_canonical_uri(session, canonical_uri): convenience selector.
  - create_judgment_from_metadata(session, canonical_uri, metadata, xml_path, first_seen_segment_id=None): inserts a new Judgment row with timestamps and default statuses.

7. Triggers & Scheduling
7.1 Manual Triggers

Route (UI + API):
POST /segments/{segment_id}/runs/manual

Enqueues:

incremental_segment_run(segment_id) by default.

Optionally backfill_segment(segment_id) explicitly from UI.

7.2 One-time Backfill Function

Job: backfill_segment(segment_id)

Behaviour:

Ignores “last seen” logic.

Applies backfill_mode:

FULL → process all entries.

SINCE_DATE → filter by decision date ≥ backfill_since_date.

NEW_ONLY (for “backfill” this is weird; implementation choice: treat as FULL but skip existing judgments).

7.3 Incremental “Since Last Scrape”

Job: incremental_segment_run(segment_id)

Behaviour:

Determine cutoff:

E.g. most recent decision_date (or first_seen_at) for judgments linked to this segment.

Filter Atom entries to only those after the cutoff.

Idempotent: if Atom returns old items, they get SKIPPED_ALREADY_EXISTS.

7.4 ChangeDetection.io Webhook

Route:
POST /webhooks/changedetection/{token}

Steps:

Find segment by changedetection_token.

Reject if not found / inactive.

Trigger pipeline.run_incremental_for_segment synchronously (current implementation) after validating the secret and confirming the segment exists. Return a JSON summary (run_id, segment_id, status, totals).

7.5 Internal Scheduling

Provided by:

System cron hitting an API endpoint OR

RQ scheduler / APScheduler in worker process.

For each active segment:

Periodic job enqueues workers.jobs.incremental_segment_run via workers.jobs.enqueue_incremental_segment respecting global and per-segment rate limits. Admin UI and CLI continue to call the synchronous pipeline directly; queued execution is available for schedulers and future async triggers.

8. Rate Limiting, Backoff & Ethics
8.1 Defaults

Global default: 1 request every 1.5 seconds (configurable).

Segment-level override via segments.rate_limit_seconds, e.g. 10 seconds for extra politeness if desired.

8.2 Retry Policy

For network / HTTP errors:

MAX_HTTP_RETRIES (default 4).

Exponential backoff:

Sleep: base_delay * (2 ** attempt) with jitter.

base_delay default 1 second.

Request timeout: e.g. 20 seconds.

Pseudo:

def fetch_with_retries(url: str) -> bytes:
    for attempt in range(max_retries):
        try:
            resp = httpx.get(url, timeout=request_timeout, headers=DEFAULT_HEADERS)
            if 200 <= resp.status_code < 300:
                return resp.content
            elif resp.status_code in (429, 500, 502, 503, 504):
                # backoff + retry
                sleep_with_backoff(attempt)
            else:
                raise HttpError(resp.status_code, url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            sleep_with_backoff(attempt)
    raise MaxRetriesExceeded(url)

9. Web UI Design
9.1 Tech

FastAPI + Jinja2 templates.

HTMX + minimal Alpine.js for interactivity (e.g. inline run triggers, filtering, no heavy SPA).

HTTP Basic auth on all admin pages.

9.2 Pages

Dashboard (/)

Summary stats:

Total judgments

Latest decisions

Recent runs with status.

Segments List (/segments)

Table of segments:

Name, active flag, backfill_mode, rate limit, last run status.

Actions:

Edit / deactivate segment.

Trigger incremental run.

Trigger backfill run.

Copy ChangeDetection webhook URL.

Segment Detail (/segments/{id})

Configuration form.

Last N runs.

Buttons:

“Run now (incremental)”

“Run backfill”

Runs List (/runs)

Filter by segment, date, status, trigger_type.

Show counts: total/new/skipped/failed.

Run Detail (/runs/{id})

Stats summary.

Table of run_items:

canonical_uri

action

status

error_message

Export CSV of all run items.

Judgments List (/judgments)

Filter by:

segment

decision_date range

court

rag_status

Columns:

decision_date, neutral_citation, title, court_code, rag_status, link to XML file.

Judgment Detail (/judgments/{id})

Display metadata.

Link to open XML file (raw).

Show associated runs / segments.

10. Queue & Worker Design
10.1 RQ Jobs

backfill_segment(segment_id: int)

incremental_segment_run(segment_id: int)

Each job:

Creates a run row at the start.

Calls run_segment_scrape with correct mode & trigger_type.

10.2 Per-segment Locking

Use Redis key lock:segment:{segment_id} with TTL.

Before starting a run:

Acquire lock.

If lock exists, job should:

Either exit with a SKIPPED_ALREADY_RUNNING log.

Or reschedule itself later (implementation decision, but document behaviour).

11. Advanced Tools – Plugin Architecture
11.1 Design Goal

Do not hard-depend on Jina / Firecrawl / agentQL / Multion, but allow future integration.

11.2 Extension Points

Define abstract interfaces / hooks:

Post-download processors:

Called after XML is saved and metadata is parsed, but before judgment commit or right after commit.

Example interface:

class JudgmentPostProcessor(Protocol):
    def process(self, judgment: Judgment, xml_content: bytes) -> None:
        ...


A registry (list of processors) loaded from config or entrypoints.

11.3 Future Uses

Jina / Firecrawl to transform XML to richer JSON or extra metadata.

AgentQL / Multion for other sites involving login / complex flows (not this project).

RAG pipeline can use the same DB to read judgments and update rag_status fields.

12. Error Handling, Logging & Monitoring
12.1 Logging

Use Python logging with structured, contextual logs.

Include:

run_id, segment_id, canonical_uri where applicable.

Log levels:

INFO default in production.

DEBUG enabled via env for deep troubleshooting.

12.2 Persistent Error Tracking

All per-judgment failures recorded in run_items with:

action (FAILED_DOWNLOAD, FAILED_PARSE)

status (FAILED)

error_message

Runs with any failures:

status = PARTIAL_SUCCESS.

13. Testing Strategy

Codex MUST create/update tests whenever modifying scraper logic.

13.1 Unit Tests

Atom feed parsing:

Given sample Atom XML, ensure we correctly extract canonical URIs and metadata.

XML metadata parsing:

Using fixture XML files, assert we correctly extract:

neutral_citation

neutral_citation_number

court_code

decision_date

title

parties

judge

URL derivation:

Ensure canonical_uri ↔ XML URL conversion is correct.

should_process(...) logic:

For backfill_mode variations and mode (BACKFILL vs INCREMENTAL).

13.2 Integration Tests

Optional integration tests (skipped by default) that:

Hit the real Atom feed for a known segment.

Run a tiny incremental scrape.

Assert that at least one judgment is inserted.

14. Implementation Modules (Suggested Layout)
app/
  __init__.py
  main.py              # FastAPI app + routes setup
  config.py            # Pydantic settings / environment handling
  auth.py              # Basic auth dependency

  db/
    __init__.py
    base.py            # engine/session + Base
    models.py          # SQLAlchemy models matching schema
    crud.py            # data access functions
    migrations/        # alembic or similar

  scraping/
    __init__.py
    feeds.py           # Atom URL construction + fetching + parsing
    xml_download.py    # derive XML URL + download + store
    xml_parse.py       # LegalDocML metadata extraction
    pipeline.py        # run_segment_scrape, process_single_entry, etc.
    rate_limit.py      # per-segment rate limiting helpers

  workers/
    worker.py          # RQ worker entrypoint (uses rq.Worker + Connection)
    jobs.py            # RQ job wrappers (backfill_segment, incremental_segment_run) + enqueue helpers

  web/
    templates/         # Jinja2 templates
    static/            # CSS/JS
    routes_segments.py # segment pages
    routes_runs.py     # run pages
    routes_judgments.py# judgment pages
    routes_webhooks.py # ChangeDetection webhook

  plugins/
    __init__.py
    base.py            # JudgmentPostProcessor protocol
    # future: jina_processor.py, etc.

15. Codex Instructions & Checklist

Any time Codex is asked to write or modify code for this project, the prompt MUST include:
“First, read docs/design_framework.md and ensure your changes are consistent with it. If there is any conflict, propose an update to the framework.”

15.1 Codex MUST:

Read this framework and align with:

Tech stack

DB schema

Module layout

Pipelines

When changing any logic that touches:

DB schema

XML parsing

Run/segment behaviour

Rate-limiting/retry

Webhook handling
Codex must:

Update this framework to reflect the changes.

Update / add tests covering the new behaviour.

When implementing a new feature:

Define which component(s) it touches (API, UI, pipeline, DB).

Ensure idempotency and proper logging.

Respect rate limits and retry policies.

When debugging:

Reproduce the bug using logs + DB state.

Once resolved, update:

Relevant code

Tests

This framework (if root cause reveals a missing/unclear design decision).

10. CLI & Segment Management

Typer-based CLI lives in `app/cli.py` exposed via the `ukcase` console script. Commands:

* `ukcase segment list` – list configured segments.
* `ukcase segment create NAME --query ... --court ewhc/ch --court ewhc/comm --decision-date-from 2020-01-01 --decision-date-to 2020-12-31 --backfill-mode FULL_HISTORY --rate-limit-seconds 2.0 --is-active/--no-is-active` – create a segment.
* `ukcase segment show SEGMENT_ID` – show full configuration.
* `ukcase segment update SEGMENT_ID --query ... --court ... --backfill-mode ... --rate-limit-seconds ... --is-active/--no-is-active` – update an existing segment.
* `ukcase segment delete SEGMENT_ID` – remove a segment.
* `ukcase run backfill SEGMENT_ID [--max-entries N]` – trigger a backfill run for a segment.
* `ukcase run incremental SEGMENT_ID` – trigger an incremental run for a segment.

Run commands delegate to `pipeline.run_backfill_for_segment` and `pipeline.run_incremental_for_segment`, ensuring consistent run tracking semantics.

Notes:

* `backfill_mode` is validated against `NEW_ONLY` and `FULL_HISTORY`; invalid values are rejected.
* Optional fields cannot yet be cleared via `segment update`; a follow-up flag set will address reset semantics.
* `segment delete` performs an immediate deletion (no interactive confirmation) to keep automation simple.
