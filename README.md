# SentinelOps AI

Investigate a slow checkout query, gather real database evidence, require human
approval, and verify recovery. A personal engineering portfolio project, originally built for neatHack 2026.

Read the [User and evaluator manual](docs/USER-MANUAL.md) and [Usability review](docs/USABILITY-REVIEW.md).

Start with [Demo runbook](docs/DEMO.md), [Submission](docs/SUBMISSION.md) and
[Readiness](docs/READINESS.md). The dashboard sample is illustrative; real repairs
use the local CLI. Google sign-in is integrated through Supabase; live account completion still needs verification.

An incident response prototype under continuous development. The existing FastAPI app lives in
`backend/app`; Milestone 4 adds an independent PostgreSQL checkout incident simulator.

See [Production and continuous delivery](docs/PRODUCTION.md) for Docker setup and the hardening roadmap.

## Local setup

Run from the repository root on Ubuntu/WSL with Docker Desktop integration.
Create a Python virtual environment (Python 3.12 is used in CI):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
# Only if .env does not already exist:
cp -n .env.example .env
docker compose up -d --wait postgres
```

`.env.example` contains public, nonproduction demo credentials. `.env` is ignored
by Git; never commit real credentials. The CLI reads the repository `.env` and
respects any exported environment overrides. PostgreSQL initialization credentials
apply only when the named volume is first created; changing `.env` alone does not
change an existing database user's password.

The service uses PostgreSQL 17, container `sentinelops-postgres`, a health check,
and named volume `sentinelops_postgres_data` (Compose prefixes it with `sentinelops_`).
Its only published binding is **127.0.0.1:5433:5432**. The CLI fixes the endpoint
to localhost:5433 and checks the server major version. Existing `postgres-dev`
(5432), `mongo-dev` (27017), and `redis-dev` (6379) are not involved.

The backend still runs independently:

```bash
python -m uvicorn backend.app.main:app --reload
```

## Reproduce the incident and recovery

The complete cycle is one command:

```bash
python -m simulator verify --samples 200 --output evidence/milestone4-verification.json
```

`verify` removes only the demo repair index, seeds or validates the deterministic
fixture, benchmarks the missing-index incident, creates the allowlisted index,
and benchmarks recovery. It leaves the repaired index in place. Exit status is
0 only when results match, the initial plan uses a sequential scan, the repaired
plan uses the demo index, and both measured p50 and p95 improve. Status 1 means
verification failed (inspect the JSON); status 2 means configuration or execution
failed. On failure after repair, the index can remain present; use `reset` to
restore the incident. Run one simulator/test process at a time.

Individual operations are also available:

```bash
python -m simulator reset
python -m simulator seed
python -m simulator benchmark --samples 200 --output evidence/before.json
python -m simulator repair
python -m simulator benchmark --samples 200 --output evidence/after.json
python -m simulator reset
```

Seeding creates exactly 100,000 deterministic orders in `sentinelops_demo.orders`,
with synthetic `customer_email`, `status`, `total_amount`, and UTC `created_at`
fields plus an order ID primary key. There are 10,000 synthetic customers, each
with 10 orders; addresses use the reserved `example.invalid` domain. The initial
schema has only the ID primary-key index; `customer_email` is unindexed. Repeated
seed calls validate existing data and never overwrite it. Seed refuses unexpected
data or secondary indexes; after repair, run reset before seeding again.

Checkout lookup binds email with psycopg parameters and returns all matching
orders ordered by ID. The default customer is `customer-004242@example.invalid`.
Use `--email` to select another existing synthetic customer. Each benchmark:

- Performs 10 warmups by default (`--warmup`), then 100 measured samples by default.
- Times query execution and result fetching with a monotonic nanosecond clock;
  reports milliseconds, raw samples, sample count, and nearest-rank p50/p95.
- Captures a real `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plan outside the timed samples.
- Checks every result against the baseline and records a SHA-256 result fingerprint.
  Verification compares result counts and fingerprints before and after repair.

This demonstrates a warm-cache scan versus indexed lookup, not a forced cold-cache
benchmark. PostgreSQL chooses the plans naturally; no planner options disable
sequential scans. Host load, Docker overhead, and caching affect timings. No
latencies or speedup claims are fabricated or hardcoded. If improvement is noisy,
reduce unrelated host load and rerun with more samples. The evidence includes
server version, complete plans and buffer statistics for inspection.

## Repair and reset safety

The only repair action is `create_checkout_email_index`, mapped to fixed SQL for
`orders_customer_email_demo_idx` on `sentinelops_demo.orders(customer_email)`.
There is no SQL input option or LLM-generated SQL execution path. Repair and reset
are idempotent. Before touching a same-named index, both verify its exact table,
column and index definition; conflicting objects are rejected.

Reset executes only a schema-qualified `DROP INDEX IF EXISTS` for that index.
It never drops a database, table, schema, primary key, unrelated index, or rows.
An independently created email index may keep lookups fast; reset leaves it alone,
and verification/seed refuses that altered fixture. The demo uses ordinary index
creation for this small isolated table; it is not a production online-DDL recipe.

## Tests

```bash
# Existing incident model tests plus simulator unit tests; database tests clearly skip.
python -m pytest -q -rs

# Explicitly enable the real database tests after starting the service.
SENTINELOPS_TEST_POSTGRES=1 python -m pytest -q -rs
```

The integration tests cover seeding, measured before/after performance, identical
lookup results, actual planner index use, idempotency, restoring the sequential
scan, SQL parameterization, index-name collision protection, and preservation of
rows and unrelated indexes. Most run in rollback-only transactions, restoring the
prior database state after each test. The production read-tool test instead creates
a uniquely named disposable database and commits its seed so independent read-only
connections can see it; teardown drops only that owned database. The local test
role needs CREATEDB (the Compose and CI roles already have it). When opted in but credentials or the local
test database are unavailable, they skip with a clear reason. Schema errors and
failed performance/correctness assertions fail rather than silently skipping.
These tests mutate the demo schema temporarily: use only this isolated fixture.

Entire/Codex hook settings are unchanged.

## Milestone 5: autonomous investigation with human approval

```bash
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
# Configure model variables below in .env, then:
python -m uvicorn backend.app.main:app --host 127.0.0.1 --workers 1
# In a second terminal:
python scripts/agent_demo.py
```

Start with the simulator's unindexed fixture (`python -m simulator seed` on a fresh
volume). If a previous demo left the repair index, the existing explicit
`python -m simulator reset` command removes only that demo index; then seed again.
The agent never seeds, resets, or drops anything. An already repaired database
should lead to escalation, not a fabricated missing-index incident.

Required model configuration:

- `SENTINELOPS_MODEL`: your provider's tool-capable chat model ID.
- `SENTINELOPS_MODEL_API_KEY`: provider API key, loaded only from environment or
  ignored `.env`. For a local provider requiring no authentication, set a dummy
  non-secret value such as `local`.
- `SENTINELOPS_MODEL_BASE_URL`: optional API prefix, default
  `https://api.openai.com/v1`; adapter appends `/chat/completions`. Remote providers
  require HTTPS; local HTTP is allowed on localhost/127.0.0.1. The provider must
  support function tools and `tool_choice: required` with one call per response.
- `SENTINELOPS_STATE_PATH`: optional SQLite path, default
  `.sentinelops/incidents.sqlite3` (ignored by Git).

The backend also needs the three existing `POSTGRES_*` variables. It loads `.env`
at first incident request without overriding exported variables. Missing model
configuration or provider failure escalates; there is no mock fallback. Only
bounded synthetic database summaries and recent incident IDs/statuses are sent to
the model. Costs and model availability depend on your provider.

The LLM chooses `metrics`, `explain`, `schema`, or `history` based on prior tool
observations, then emits a structured `diagnose` or `refuse` call. There is no
fixed investigative sequence. Its diagnosis records a finding, confidence,
evidence IDs, and optional repair ID. The backend checks the allowlist, observed
citations, positive measurements, sequential scan, expected columns, and absent
demo index. Confidence must be at least 0.8. Unsupported diagnoses escalate.
Confidence is the model's assessment, not a calibrated probability.

Investigation has eight model steps, a 90-second overall timeout, and at most two
retries with exponential backoff for transient provider errors. Database read
transactions are read-only and capped at 15 seconds. On cancellation a background
read can finish within that database limit; it cannot repair anything. Approval
runs a fresh before benchmark, the fixed repair, and an after benchmark in a
60-second transaction. Matching result hashes/counts, initial sequential scan,
actual repaired index use, and improved measured p50 AND p95 are all required.
Failed verification rolls back the new index. A lost connection or process crash
is reported as failed/uncertain, never silently replayed; inspect the database
before starting another incident. No automatic rollback removes preexisting data.

Endpoints (existing `/` and `/health` remain):

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/incidents` | Create a checkout incident |
| POST | `/incidents/{id}/investigate` | Run bounded autonomous investigation |
| GET | `/incidents/{id}` | Inspect state and timestamped evidence/events |
| POST | `/incidents/{id}/decision` | Explicit `{"decision":"approve"}` or `{"decision":"reject"}` |
| GET | `/incidents/{id}/report` | Retrieve diagnosis and measured recovery report |

The demo script prints evidence and asks for literal `APPROVE` before sending the
approval. States include `awaiting_approval`, `escalated`, `rejected`, `resolved`,
and `failed`. Approval before a valid proposal or repeated approval returns 409.
No endpoint accepts SQL or repair commands. SQLite persists bounded structured
summaries, fixed lifecycle events, and validated diagnoses; raw model responses,
exception messages, credentials, query rows, and arbitrary plan strings are not
stored. `Agent(..., hook=callback)` exposes safe model/tool/lifecycle metadata for
future neatlogs instrumentation without changing orchestration.

Run this unauthenticated demo only on loopback with **one backend worker**, one
simulator/test process at a time, and no concurrent external database edits.
The local approval endpoint represents the human boundary, not production RBAC.
Protect the state directory; do not serve it publicly. SQLite restart recovery
marks interrupted work failed and never automatically resumes a repair.

```bash
python -m pytest -q -rs
SENTINELOPS_TEST_POSTGRES=1 python -m pytest -q -rs
```

Agent unit tests use deterministic models, including observation-dependent tool
selection. Opt-in agent database tests use real benchmarks and rollback-only
transactions with a deterministic model; they are **not live LLM validation**.
Live provider success must be demonstrated separately using the interactive demo
with a configured provider and a genuinely degraded fixture.

## Neatlogs observability

The custom `httpx` model client is manually traced through the official
[Neatlogs OTLP/gRPC integration](https://docs.neatlogs.com/sdk/opentelemetry).
The exporter uses TLS and sends the Project API key as `x-api-key` metadata.
It does not wrap `httpx`, install automatic HTTP instrumentation, or change model
selection, retries, tool authorization, or the human approval requirement.

Why OTLP: this repository currently runs Python 3.14.4. The installed public
`neatlogs==1.1.8` lacks the newer documented SDK/Doctor API. Official PyPI now
publishes 1.4.26, but that release requires Python >=3.10,<3.14; pip correctly
refused it here. We did not override that constraint. Standard OpenTelemetry
1.45.1 supports this environment and the documented Neatlogs transport. The old
neatlogs package is not imported or required by the integration. SDK Doctor is
unavailable on this transport; mock-exporter tests and actual export evidence
are recorded separately from hosted finalization.

Sources: [hackathon setup guide](https://neatlogs.com/hackathon/neatlogs-setup-guide.html),
[documentation index](https://docs.neatlogs.com/llms.txt),
[SDK Doctor](https://docs.neatlogs.com/sdk/doctor),
[span kinds](https://docs.neatlogs.com/sdk/span-kinds), and
[sessions](https://docs.neatlogs.com/sdk/sessions).
Canonical span attributes were also checked against the official 1.4.26 wheel
without installing that incompatible SDK.

### Configuration

Install `backend/requirements.txt`. Put the **Project API key** from your
project's Settings â†’ API keys in `NEATLOGS_API_KEY` in the ignored `.env` or your
process environment. Never paste the key into code, command arguments, reports,
or chat. The existing environment key is reused; no credential is copied into
tracked files. Do not use the `nlw_` HTTP-ingest key with this integration.

`NEATLOGS_OTLP_ENDPOINT` defaults to `ingest.neatlogs.com:443`; EU projects must
set `eu.ingest.neatlogs.com:443`. Only those two destinations are accepted.
Missing keys, invalid configuration, exporter failures, or a full bounded export
queue do not interrupt incident response. Telemetry may be dropped on failure.
A private tracer provider avoids modifying another library's global provider.
FastAPI shutdown drains the queue and closes the exporter. Abrupt process kills
can lose queued spans. Export RPCs have a three-second timeout; explicit queue
flush waits at most five seconds.

### Coverage and privacy

| Trigger | Trace boundary and captured operations | Verification |
| --- | --- | --- |
| `POST /incidents` | `create` WORKFLOW and creation event | Mock exporter; real transport accepted |
| `POST /incidents/{id}/investigate` | `investigate` WORKFLOW; one LLM span per attempt; TOOL spans for executed `metrics`, `explain`, `schema`, `history`, `diagnose`, `refuse`; retry/lifecycle events | Mock model and exporter tests; live LLM blocked pending configuration |
| `POST /incidents/{id}/decision` | `decision` WORKFLOW, explicit approval/rejection, conflict/error status; approved `create_checkout_email_index` TOOL; actual `recovery.verify` TASK and returned `recovery.verification_result` TASK | Mock exporter tests; existing real PostgreSQL rollback tests |
| Health/report reads and standalone simulator CLI | No independent AI workflow; excluded | Existing application tests |

Each span has `incident_id` and `neatlogs.session.id`. Investigation and later
human decisions have separate finalized roots under the same session; the
backend does not leave a trace open while waiting for a person. Investigation
and decision trace IDs are returned and persisted under `telemetry.trace_ids` in
the incident report. Actual hierarchy follows async calls and database threads.
A model's request for a tool is captured on its LLM response; only authorized,
executed operations get TOOL spans. Token counts are recorded only when supplied
by the provider; absent usage is not converted to zero.

Payloads use a strict field/value projection: structured call names, diagnosis
fields, citations, measurements, and verification booleans survive. Ordered
message roles and structured tool observations are retained. Free-form prompt
text, model prose/refusals, unknown fields, raw database rows, URLs, headers,
exception messages/stacks, and credential values are omitted. This deliberately
limits prompt replay while preserving investigation evidence. No automatic
stdout or application-log capture is enabled. Extend the projection only after
reviewing any new field's privacy implications.

### Repeatable live verification

Configure `SENTINELOPS_MODEL` and `SENTINELOPS_MODEL_API_KEY` (and the provider URL
if needed) in `.env`. Use the existing isolated PostgreSQL fixture; do not run
arbitrary SQL. Follow the simulator setup above if the fixture is absent. An
already repaired fixture can legitimately produce an escalation.

```bash
source .venv/bin/activate
# All tests, including rollback-only isolated PostgreSQL checks:
SENTINELOPS_TEST_POSTGRES=1 python -m pytest -q -rs
# Invoke the real FastAPI routes in-process, with the real model and DB tools:
python -m scripts.verify_neatlogs
# Separately test generated, non-sensitive telemetry (no model or database call):
python -m scripts.verify_neatlogs --minimal
# Read an existing trace without exporting another one:
python -m scripts.verify_neatlogs --trace-id <trace-id>
```

The verifier performs no repair and prints only incident/session/trace IDs,
status, observed tool names, and export counters. Its preflight reports missing
variable names without values. Investigation mode exits 0 only after authenticated
readback confirms the exact finalized trace and complete span tree, including LLM
and tool spans, and a successful real provider response was observed. Exit 3 means
verification failed or remains unverified; export acceptance alone cannot pass.
Minimal mode is synthetic and does not prove a real investigation. Readback-only
mode verifies finalization but cannot compare against a locally captured tree.
`--allow-unconfigured`
is only for exercising the application's missing-model error path and cannot
serve as live LLM evidence.

Open [Neatlogs](https://app.neatlogs.com), select the project owning the configured
key, and find the exact investigation trace ID under Traces. Check that the trace
is finalized, has one investigation root, contains actual LLM responses and the
executed tools matching `observed_tools`, and has the incident's session ID.
Check error/retry status and numeric usage when available. Save the trace ID,
project, finalization state, and observed spans in the verification evidence.
Transport acceptance or an empty TOOL list is insufficient for the live gate.

For approval/recovery coverage, start the backend on loopback and run
`python scripts/agent_demo.py`; only type `APPROVE` after reviewing a valid
proposal. Inspect the linked decision trace, repair TOOL, verification TASK,
and actual recovery report. The verification helper never approves on your behalf.

The verifier uses the [SDK Doctor documented readback route](https://docs.neatlogs.com/sdk/doctor),
`GET /api/traces/v3/{trace_id}`, on the allowlisted ingest host with the same
project key in `x-api-key`. This route accepts the project key; a separate general
Public API credential is not needed for this check. Polling is bounded by
`--timeout` (30 seconds by default); redirects are disabled and response bodies
are never printed. Do not paste credentials into commands or logs.

Current verification evidence and blockers: [neatlogs verification](evidence/neatlogs-verification.md).
