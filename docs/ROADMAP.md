# Sentinel roadmap

Baseline: V0.1, audited 2026-09-14. **Phases 1–5 are implemented locally.**
This roadmap is sequenced by engineering need, not by a promised release date.
No later phase is complete merely because V0.1 contains one of its prerequisites.
Do not start the next major phase without the user's instruction.

Status: `[x]` means verified existing/completed work; `[ ]` means remaining work.
The initial audit and P0-1 through P0-5 are implemented and locally verified.
**Phase 0 is verified locally and through hosted CI.** Fresh-checkout installation,
browser workflows and the Docker demo smoke passed on GitHub; a separate public
clone and Compose configuration check also passed.
Phase 1 was completed, followed by Phases 2 and 3 under the user's request to
finish the next two entire phases.
Phase 4 is implemented and locally verified; live OpenAI calibration is explicitly
deferred by the user. Phase 5 is implemented and verified with controlled fixtures.
**Current implementation phase: Phase 6 — Authentication, organizations, and secure secrets.**
P6-1 operator access and P6-2 project-scoped resources/jobs/cache keys are implemented.
Human identity/memberships, secure target/provider secrets, network/resource policy
and the full security review remain unfinished. Public deployment stays blocked.
Phase 0's previously pending automated external verification is recorded below.
Repository: [s-kar10/sentinel](https://github.com/s-kar10/sentinel), public source
with `main` as the primary branch. Credentials, local databases and generated
artifacts are excluded. The initial source scan passed; hosted CI and clean-clone
verification are tracked separately below. Public application hosting is not enabled.

### Initial hosted verification — 2026-10-31

The [first GitHub Actions run](https://github.com/s-kar10/sentinel/actions/runs/41130262435)
passed frontend/browser and Compose smoke checks. Python reported 280 passes and
one failure: a JSON depth test depended on the host's parser recursion limit.
The fix enforces an explicit 100-container limit for text/document/value JSON
assertions, checks text before parsing, and records the policy in provenance and
comparison identity. Boundary, escaping and pre-parse tests cover the change.
The [follow-up hosted run](https://github.com/s-kar10/sentinel/actions/runs/41241932580)
passed all three jobs for commit `544ca9c`: 289 backend tests including PostgreSQL,
13 demo tests, 16 Chromium workflows, locked clean installs, static checks and the
full Compose smoke. A separate fresh clone of the public repository passed Compose
configuration validation and contained no local secrets/database. Temporary local
clone resources were removed. Live OpenAI calibration remains deferred; this does
not establish public-deployment readiness or independent user usability testing.

The earlier 2026-10-28 verification refresh passed the existing suites and static checks;
no Compose services were running for a live stack check (see
[ARCHITECTURE.md](ARCHITECTURE.md#verification-refresh--2026-10-28)).

## Phase overview

| Phase | Goal | Status |
| --- | --- | --- |
| 0 | Stabilize the MVP | Complete; local checks and fresh-checkout hosted CI verified |
| 1 | Evaluation Engine V2 | Complete locally; configuration, isolation, provenance, outcomes and metrics verified |
| 2 | Asynchronous evaluation infrastructure | Complete locally; transactional queue, worker, retries/limits, cancellation and recovery verified |
| 3 | Historical analytics and regression detection | Complete locally; immutable baselines, version labels, comparisons, trends and descriptive repeat policy verified |
| 4 | LLM-based evaluation | Implemented and locally verified; live OpenAI calibration deferred by user |
| 5 | Real security testing | Complete locally; versioned synthetic packs, safe/vulnerable fixtures, browser and Compose verified |
| 6 | Authentication, organizations, secure secrets | In progress; P6-1 access and P6-2 project isolation implemented, remaining security gates open |
| 7 | GitHub and CI/CD integration | Planned |
| 8 | Observability and production reliability | Planned; liveness and database readiness exist |
| 9 | Public API and SDK | Planned; unversioned REST/OpenAPI exists |
| 10 | Cloud deployment | Planned; local Docker stack exists |
| 11 | Performance and scalability | Planned; no benchmarks established |
| 12 | Product-level UX | Planned; MVP target/report/history UI exists |
| 13 | Open source and real users | Planned; setup README/demo/tests exist |

Security, tests, documentation, and the UI needed for each feature belong in every
phase. Phase 8 does not defer essential error visibility, and Phase 12 does not
defer the Phase 2 progress UI. Phase 7 is customer-facing evaluation integration;
basic CI for testing Sentinel itself belongs in Phase 0.

## Phase 0 — Stabilize the MVP

**Goal:** A reliable, understandable, tested baseline without a rewrite.

### Completed and verified

- [x] Inspect authored backend/frontend/demo source, tests, APIs, database models,
  attacks, evaluators, Docker/configuration, and README.
- [x] Inventory existing target CRUD, canary management, JSON POST mapping, nested
  object/list paths, static eight-case catalog, deterministic strategy registry,
  synchronous persistence/scoring, history, and report UI in code.
- [x] Run existing tests: 37 backend and 13 demo tests passed.
- [x] Run ESLint, TypeScript checking, and Vite build successfully.
- [x] Validate Compose configuration and check the existing four healthy services.
- [x] Verify a live API/database/demo run: eight cases, four failures, score 50%,
  with four configured fake canaries; retrieve results and clean up test records.
- [x] Populate project instructions, product vision, current/target architecture,
  security risks, decision records, and all roadmap phases.
- [x] Document bugs, debt, verification limitations, and the next five tasks.

See [ARCHITECTURE.md](ARCHITECTURE.md) for code evidence and command results.
The existing stack smoke does not establish fresh-clone setup reliability.

### Current and upcoming tasks, in recommended order

#### P0-1 — Correct evaluation preconditions and path failures (complete)

- [x] Require at least one non-blank target canary whenever the selected attacks
  use target protected values. Reject with actionable HTTP 422 before creating a
  run or target client. Fixed-string-only suites remain usable without canaries.
- [x] Normalize invalid numeric list segments into `JsonPathError` for reads and
  writes, including unconvertible Unicode digits and oversized integer strings.
  Preserve valid Unicode object keys and convertible decimal indexes.
- [x] Add tests for preflight rejection without side effects, malformed paths,
  persistence/continuation after extraction failure, and add/remove-canary behavior.
- [x] Verify the real bundled demo through an in-process backend/HTTP-adapter/demo
  integration test: eight cases, four failures, score 50%; original verdicts remain.

**Verification:** 61 backend tests and 13 demo tests passed; frontend ESLint,
TypeScript/Vite build, and Compose configuration validation passed. The new demo
integration uses SQLite and in-process HTTP, not Docker/PostgreSQL or a browser.
The existing Starlette/AnyIO deprecation warning remains. Python lint/format
configuration remains P0-3 work. No dependencies or database schema changed.

**Compatibility:** Previously, running the bundled catalog without canaries could
produce untested leakage passes. It now returns 422 with no run saved and no target
requests. Register a synthetic value that actually exists in the target's test
context before retrying. Existing stored runs/scores are not rewritten. Decision
and tradeoffs: [ADR-006](DECISIONS.md#adr-006--validate-coverage-before-starting-an-evaluation).

**Acceptance:** Missing coverage cannot silently inflate leakage scores; malformed
paths return stable validation/per-case errors instead of unexpected run failures;
the configured demo still produces the documented eight-case result.

#### P0-2 — Establish Alembic migrations (complete, 2026-10-28)

- [x] Add Alembic 1.20.1 with frozen revision `0001_v01_baseline`, retaining all
  four tables, FKs, indexes, and VARCHAR status storage using uppercase enum names.
- [x] Test fresh upgrades and populated V0.1 adoption on SQLite and PostgreSQL 16.
  Validate the baseline before stamping; reject mismatches without adoption.
- [x] Remove API startup schema mutation. Add explicit CLI commands, a one-shot
  Compose migration service, and a read-only API revision gate.
- [x] Create regular test databases through migrations; document backups, restore,
  version compatibility, and destructive baseline downgrade limitations.

**Verification:** All 99 backend tests passed with PostgreSQL configured (80 pass
and 19 skip without it); 13 demo tests, frontend lint/type/build, and Compose
configuration validation passed. A disposable Compose project built and started
from an empty volume; the live demo produced 8 results, 4 failures, score 50%.
The same isolated data survived simulated legacy adoption and API restart. A
PostgreSQL dump restored into a separate test database with all 8 result rows.
Migration tests additionally cover drift rejection, transactional DDL rollback,
orphan prevention, cascading SQL deletes, ID generation, and startup rejection.

**Scope:** Existing developer databases were not upgraded, stamped, or deleted.
No browser test, zero-downtime migration, or production backup service is claimed.
The Starlette/AnyIO deprecation warning remains. P0-4 still owns broader startup,
readiness, CORS, and onboarding coverage.

**Operations:** Follow [MIGRATIONS.md](MIGRATIONS.md) for fresh setup or backup and
adoption of an existing database. The old `CREATE_DATABASE_TABLES` flag is ignored.
See [ADR-007](DECISIONS.md#adr-007--explicit-migrations-and-guarded-legacy-adoption).

**Acceptance:** A new PostgreSQL database reaches head; a populated V0.1 database
can be adopted/upgraded without losing records; migration tests cover relationships
and cascade behavior. Startup does not silently mutate production schemas.

#### P0-3 — Make checks reproducible (implemented and locally verified, 2026-10-29)

- [x] Establish one documented Python runtime policy; reconcile package metadata,
  containers, and tested versions.
- [x] Choose a small Python lint/format toolchain with a clear reason and fixed
  check commands; keep formatting changes reviewable and separate from logic.
- [x] Verify clean Python/frontend dependency installation; reconcile duplicate
  backend dependency declarations and demo dependency version ranges.
- [x] Add repository CI for the separate Python suites and frontend checks; track
  the Starlette/AnyIO warning with a tested compatibility change if needed.

**Acceptance:** A clean environment and CI run the same documented tests, lint,
format, and type/build checks successfully. No unmeasured coverage claim is added.

**Implemented:** CPython 3.12 and Node 22 policy, pinned Ruff lint/format rules,
service metadata as the direct Python dependency source, uv-generated portable
hash locks, runtime/test dependency separation, shared check commands, and two
GitHub Actions jobs with disposable PostgreSQL 16. Four new command tests verify
service import isolation and stopping on lint/format/test failures. The Python
formatting pass is mechanical. Targeted frontend lock updates address three npm
audit findings within existing version ranges.

**Verification:** Fresh macOS Python environment: 84 backend passes, 19 explicit
PostgreSQL skips, 13 demo passes. Fresh Linux Python 3.12.16 environment with
isolated PostgreSQL 16: all 103 backend and 13 demo tests pass. Ruff lint/format,
pip consistency, lock regeneration/staleness checks, and Compose config pass.
Clean Node 22.23.4 install passes ESLint, TypeScript/Vite build, and npm audit
(zero current findings). Both Python runtime images build/import successfully
without pytest. Temporary test database/network resources were removed.

**Acceptance limitation:** Hosted GitHub Actions has not run: this workspace has
no Git metadata/remote. The workflow is configured and its commands pass locally,
but a hosted run must be recorded once the repository exists. No browser coverage
or Python/container vulnerability scan is claimed. Starlette/AnyIO and ESLint
deprecation warnings remain visible and tracked in [DEVELOPMENT.md](DEVELOPMENT.md).
Runtime patch versions and base-image tags can still move. See
[ADR-008](DECISIONS.md#adr-008--shared-checks-and-reviewed-dependency-locks).

#### P0-4 — Verify clean Compose setup and readiness (complete locally, 2026-10-29)

- [x] Add a reproducible PostgreSQL-backed demo smoke using isolated resources and
  cleanup, without deleting developer data; exercise fresh build/start and restart.
- [x] Test all eight catalog prompts against the actual demo, with explicit expected
  verdicts, stored results, and cascade deletion assertions.
- [x] Separate API liveness from DB readiness and connect container startup checks
  to the appropriate endpoint.
- [x] Align/document native backend CORS origins with Vite port 3000; verify changed
  ports, container DNS, frontend deep links, and migration startup instructions.

**Acceptance:** A developer following the README can install/build, start healthy
services, execute the expected demo, retain data across restart, and diagnose a DB
outage. Record successful fresh-setup evidence, not just existing container health.

**Implementation:** `/health` remains process liveness. `/ready` reads the
configured database's migration revision and returns a redacted 503 for database
or revision failures. Compose now probes readiness. Native CORS defaults match
port 3000. PostgreSQL connection/pool waits are limited to three seconds, and
readiness statements use a transaction-local two-second timeout.

**Verification:** `python3.12 scripts/smoke_compose.py` built the real stack on an
empty isolated volume and checked eight results (4 pass, 4 fail, 50%), response
evidence, all four table counts, changed ports, allowed/rejected CORS, the built
API URL, and nginx deep links. Full container recreation preserved the report.
Stopping PostgreSQL kept liveness at 200, changed readiness to 503 and Docker
health to unhealthy; restarting it restored readiness and report access. Target
deletion removed target/canary/run/result rows. Cleanup removed the test resources.
All 115 backend and 13 demo tests passed, including PostgreSQL migration cases;
Ruff, dependency locks, frontend lint/type/build, and Compose config passed.

**Limits:** Images/build cache are retained. Tests use HTTP/SQL, not browser
automation. The new CI smoke job still needs hosted verification once a repository
exists. Readiness checks connectivity and recorded revision, not every table,
external target, or arbitrary network failure deadline. Existing developer data
was untouched. Operational instructions are in [README.md](../README.md) and
[DEVELOPMENT.md](DEVELOPMENT.md#compose-smoke); see
[ADR-009](DECISIONS.md#adr-009--database-readiness-and-an-isolated-compose-smoke).

#### P0-5 — Test and align the core UI/API workflow — completed locally 2026-10-29

- [x] Add behavioral/browser coverage for register/edit target, canary management,
  run/report, filters, validation errors, and deletion.
- [x] Align frontend types with actual nullable/optional API fields; make key-clear
  behavior explicit and reflect cascade deletion of history in confirmation copy.
- [x] Reproduce and fix report polling recovery after a transient request failure.
- [x] Test empty/failed runs and distinguish execution errors from detected
  undesirable behavior in report wording.

**Acceptance:** The main workflow passes automated browser checks; stored keys are
not exposed, deletion consequences are clear, and transient failures offer a
working recovery path. All related backend/frontend checks remain green.

**Evidence:** Nine Chromium tests passed. The main workflow uses real API/demo
processes and a fresh migrated SQLite database, including key preservation,
replacement/removal, validation, canaries, the eight-case demo, report filters,
reload, and cascading deletion. Report-only fixtures cover transient failures,
manual retry, empty/failed runs, stale requests after navigation, and rendering
untrusted response text. Disabling retry scheduling in an isolated copy made the
polling regression test fail as expected; it passes with the fix.

All **117 backend tests**, including PostgreSQL migration cases, and **13 demo
tests** passed. Dependency locks, Python lint/format, frontend lint/type/build,
Compose configuration, and the full disposable Compose smoke passed. The existing
Starlette/AnyIO deprecation warning remains.

**Engineering changes:** Report polling reschedules after transient errors and
cancels obsolete requests. API types match nullable fields; omitted keys preserve
credentials while explicit `null` removes them. Confirmation copy names deleted
history. Reports distinguish unavailable responses (execution errors) from
responses that fail behavioral checks, and suppress headline scores for empty or
failed runs. Stored scores and backend execution semantics are unchanged.

**Limits:** Browser coverage is desktop Chromium with SQLite; rare report states
use mocked responses. PostgreSQL/Compose are checked separately. This does not
establish cross-browser compatibility, a security audit, or durable execution.
Hosted CI and clean-clone verification remain pending. See
[browser-test instructions](DEVELOPMENT.md#browser-tests) and
[ADR-010](DECISIONS.md#adr-010--isolated-browser-tests-and-explicit-report-recovery).

### Phase 0 exit criteria

A new developer can clone the eventual Git repository, follow a verified setup,
run the complete application locally, execute the demo suite, and understand its
architecture. P0-1 through P0-5 are accepted, migration adoption preserves existing
data, tests/checks run reproducibly, and remaining limitations are documented.
Public clone and hosted fresh-checkout checks were verified on 2026-10-31; see
the initial hosted verification record above. Historical pending notes in the
individual task records describe their status at that earlier time.

## Phase 1 — Evaluation Engine V2

**Goal:** An extensible evaluation framework with explicit, reproducible semantics.

Existing prerequisites:

- [x] Immutable typed definitions with IDs/categories/severity; eight built-in attacks.
- [x] Registry plus forbidden-substring, exact-match, and regex implementations.
- [x] Per-case metadata and basic category pass rates.

Phase 1 implementation checklist:

- [x] P1-1: Versioned attack definitions and reusable attack packs; validated custom attacks.
- [x] Configurable assertions and stable evaluator configuration contracts.
- [x] Regex as a supported configurable strategy with execution safeguards;
  JSON/schema, latency, and status-code evaluators.
- [x] Evolve the current text-only evaluator/target-response boundary to carry
  structured response and transport metadata without rewriting orchestration.
- [x] Persist attack/evaluator identity, configuration/version provenance, and
  evaluator evidence with a clear redaction policy.
- [x] Severity-weighted scoring, richer category metrics, and explicit outcomes for
  untested, errored, or inapplicable cases.

**Exit criteria:** A new strategy and custom versioned pack can be added through
stable contracts without orchestration conditionals; tests verify validation,
backward compatibility, evidence, scoring, and reproducible run metadata.

### P1-1 — Versioned data-only attack packs (complete locally)

- Added immutable, validated JSON pack/attack models with format and content
  revisions, unique IDs, bounded fields/collections, and an aggregate size limit.
- `GET /attack-packs` exports the versioned eight-check baseline. The existing
  evaluation POST accepts an optional custom pack; bodyless requests keep the
  baseline. Custom selection is request-local and preserves execution order.
- Custom packs support the existing substring and exact-match strategies. Unknown
  fields, empty coverage, invalid versions, and custom regex are rejected before
  persistence or target contact. Protected-value checks retain canary preflight.
- Pack validation errors redact input content. Existing reports display custom
  results; the frontend Run button continues to select the baseline.

**Scope:** No database schema, scoring, evaluator algorithm, or worker change.
Versions are author-managed labels, not immutable registered artifacts. Persisted
identity/configuration/evidence and regex safeguards remain unchecked tasks above.
The normalized size limit applies after parsing, not at the HTTP transport boundary.
See [pack format and usage](ATTACK_PACKS.md) and
[ADR-011](DECISIONS.md#adr-011--versioned-data-only-attack-packs).

**Verification:** 159 backend tests passed with PostgreSQL (140 passes and 19 skips
without it), plus 13 demo tests and ten Chromium tests. The 42 new backend cases
include rejected inputs with no side effects and the real demo using an exported
and reimported baseline. The new browser case runs a custom two-check pack against
the real demo and verifies the report. Full Compose smoke, dependency locks,
Python lint/format, frontend lint/type/build, and Compose config passed. The existing
Starlette/AnyIO warning remains. Hosted CI and other browsers remain unverified.

### Phase 1 completion — Evaluation Engine V2

Format 2 packs support 1–10 versioned assertions per attack; format 1/default
requests retain their original grading behavior. Strategy registration binds a
configuration model and evaluator callable, with no orchestration conditionals.
Supported rules cover configurable string/exact matching, bounded regex, JSON
validity, a documented non-referencing JSON Schema profile, latency, and HTTP
status. Available structured data and transport metadata survive text-extraction
errors. Regex/schema workers have enforced timeout/input limits; timed-out children
are killed and reaped, and remaining checks continue.

Alembic `0002_engine_v2` adds nullable provenance, observation, assertion evidence,
and outcome columns without fabricating historical metadata. New runs snapshot
normalized definitions, evaluator/runtime/scoring versions, target mappings,
severity weights, and a redacted-content fingerprint. Known target keys/canaries
are redacted from new stored text and metadata; matching occurs before redaction.

Planned results persist as untested before execution. Results distinguish passed,
failed, errored, untested and not applicable. Original pass-rate fields remain
compatible; additive weighted rates and coverage expose richer run/category
metrics. Browser reports display outcomes, evidence, definitions and coverage,
with filtering and honest handling of unscored/incomplete runs.

**Verification:** All **216 backend tests** passed with disposable PostgreSQL,
plus **13 demo tests** and **11 Chromium tests**. A fresh Linux Python 3.12.16
environment passed the then-current 214 backend cases with PostgreSQL and the demo
suite; two final cases (documented example and JSON depth limit) also passed in the
final 216-case macOS run. The default suite has 195 runnable cases and 21 explicit
PostgreSQL skips. Locks, pip consistency, Ruff, frontend lint/type/build, Compose
config and the full isolated Compose smoke passed. New checks cover migration
upgrade/downgrade/data preservation, real metadata transport, the sample pack,
custom strategy extension, regex timeout/child cleanup, evidence redaction,
immutable history, mixed outcomes, and a real format 2 browser report.

**Limits/tradeoffs:** Schema support is an explicit bounded subset, not all JSON
Schema. Snapshots are redacted, so secret-dependent offline replay requires the
original authorized configuration. Existing historical raw text is not scrubbed.
There is no immutable server-side pack registry, durable execution/recovery, total
run deadline, or global quota. Hosted CI, clean-clone onboarding, and other
browsers remain unverified; the Starlette/AnyIO warning remains. These limits are
documented, not counted as completed future phases. See [ENGINE_V2.md](ENGINE_V2.md)
and [ADR-012](DECISIONS.md#adr-012--versioned-assertions-provenance-and-explicit-outcomes).

## Phase 2 — Asynchronous evaluation infrastructure

**Goal:** Fast submission and durable background execution.

- [x] Select Redis and a job framework (Celery, Dramatiq, RQ, or a justified
  alternative) in an ADR based on delivery/recovery needs and operational cost.
- [x] Return a run ID promptly; define submission transaction/enqueue consistency
  and idempotency. Execute in worker processes with bounded concurrency.
- [x] Define retryable failures, capped retries, exponential backoff/jitter,
  timeout policies, per-target concurrency, and global rate limits.
- [x] Add cancellation, durable progress counters, live frontend progress, and
  recovery after worker/process crashes.
- [x] Separate planned/completed/errored totals; prevent duplicate results and
  stale-worker completion from corrupting a run.

**Exit criteria:** Tests demonstrate prompt submission, progress, cancellation,
duplicate-delivery safety, retry exhaustion, and crash recovery. A documented
workload respects target/global limits; queue delivery semantics and tradeoffs are
explained. No lost run between database commit and enqueue goes unaddressed.

### Phase 2 completion — 2026-10-30

Selected the existing relational database as the durable queue rather than adding
Redis/broker operations. Submission atomically saves the run, planned results and
job; the new 202 API accepts target-scoped idempotency keys. Workers execute isolated
cases with a parent deadline plus a child self-deadline, durable checkpoints,
lease/token fencing, bounded attempts/backoff and cancellation. Limits: two global
case leases, one per target, one dispatch admission every 0.5 seconds, three attempts,
60-second case deadline, 75-second lease and 30-minute run deadline. Copied private
execution payloads are removed on terminal state. Progress and attempt counts are
stored/derived from durable result rows; the browser polls and offers cancellation.

**Verification:** Shared Phase 2–3 final checks: **248 backend tests** (SQLite and
disposable PostgreSQL), **13 demo tests**, **13 Chromium workflows**, locks/pip/Ruff,
frontend lint/type/build and Compose config passed. The default suite has 218
passes and 30 explicit PostgreSQL skips. Queue tests cover atomic rollback,
concurrent idempotency/claims, duplicate/stale completion, retry classification and
exhaustion, crash/lease recovery, deadlines (including child self-termination
without a supervising worker), frozen configuration and partial cancellation.
A documented eight-case workload with four competing consumers verifies target/
global concurrency and admission spacing on both databases. This is a correctness
workload, not a throughput benchmark.

The full disposable Compose smoke submits with the worker stopped, restarts the
API, verifies the queued run survives, resumes the worker and obtains the expected
8/4/4/50 demo result. It exercises real PostgreSQL reports/baselines, full stack
recreation, DB outage/recovery and cascading removal of jobs/baselines. Chromium
uses a real native worker for progress/cancellation and versioned history.

**Tradeoffs/limits:** At-least-once external requests can repeat after failures;
fencing protects saved evidence, not target side effects. Admission limits do not
promise exact network-arrival spacing or strict physical concurrency through
arbitrary partitions/pauses. Queue submissions are not quota-limited. The deprecated
201 synchronous API is preserved and bypasses queue controls/recovery. Private job
payloads remain plaintext while active, and clocks must agree. No worker heartbeat,
multi-host failover, production scale or hosted CI is claimed. See
[ASYNC_HISTORY.md](ASYNC_HISTORY.md) and
[ADR-013](DECISIONS.md#adr-013--a-transactional-database-queue-with-fenced-case-leases).

## Phase 3 — Historical analytics and regression detection

**Goal:** Make repeat evaluations useful across deployments.

- [x] Persist multiple runs and expose list/detail/history views.
- [x] Immutable baseline references and application/model/prompt version tags.
- [x] Compatible run comparisons, regression detection, metric/category/security
  score trends, and latency trends.
- [x] Report sample sizes, changed test coverage, and effect sizes; use confidence
  intervals or significance tests only when the sampling design supports them.
- [x] Define minimum samples, repeated-run treatment, false-positive handling, and
  separation of target execution errors from behavioral regressions.

**Exit criteria:** Known synthetic regressions are detected and explained;
incompatible or insufficient samples are identified rather than given misleading
certainty. Comparison results are reproducible from stored versioned evidence.

### Phase 3 completion — 2026-10-30

Named baselines are append-only references to completed fully covered runs. New
runs snapshot optional application/model/prompt tags and a private compatibility
fingerprint. Compatible pairs report behavioral regressions/improvements, execution
errors, missing/changed coverage, paired weighted effect sizes, category metrics
and latency sample counts/differences. History exposes bounded, replayable terminal
windows with run IDs, category/security-check scores, coverage and latency trends.
The report UI creates/selects baselines and shows comparison/history evidence.

Repeated-regression summaries require distinct labeled versions, at least three
behavioral observations per version for a check, unanimous baseline passes and
candidate failures, and no error/missing/incomplete-run observations. Insufficient
samples and mixed outcomes are flagged for review. Retries/cases are not counted
as independent replicates. No confidence intervals, p-values, calibrated false-
positive rate, or automatic deployment gate is claimed.

**Verification:** Included in the shared 248/13/13 checks above. Synthetic tests
verify known regressions/improvements, incompatible or legacy records, errors and
coverage changes, immutable baseline conflicts, insufficient/mixed/incomplete
repeats, frozen target context, bounded windows and deterministic terminal replay.
Upgrade/downgrade tests preserve original evidence on SQLite/PostgreSQL and disclose
which new metadata is lost by downgrade. Chromium verifies named baselines,
version labels, comparison after reload and history rows against actual services.

**Tradeoffs/limits:** Compatibility is deliberately conservative, including runtime
and execution policy. Labels are supplied by users and cannot attest a deployment.
Baseline immutability applies through the API, not against DB administrators;
target deletion removes the evidence. Old records get no invented identity.
Minimum-three replication is a review convention, not statistical proof. History
is capped at 100 runs per query with explicit truncation/window bounds. See
[ASYNC_HISTORY.md](ASYNC_HISTORY.md) and
[ADR-014](DECISIONS.md#adr-014--immutable-baselines-and-conservative-descriptive-comparisons).

**Remaining verification:** Hosted CI and clean-clone onboarding still require a
Git repository. Only desktop Chromium is browser-tested. Starlette/AnyIO's existing
deprecation warning remains. Developer databases and `.env` files were not changed.
At that completion point Phase 4 had not started; its implementation is recorded below.

## Phase 4 — LLM-based evaluation

**Goal:** Optional semantic judgments where deterministic checks are insufficient.

- [x] Replaceable judge-provider abstraction; configurable prompts and rubrics,
  structured outputs, scoring, and explanations.
- [x] Bounded retries, caching with provider/model/prompt/rubric versions in keys,
  token/cost tracking, timeouts, and error semantics.
- [x] Labeled calibration data and comparisons against deterministic baselines.
- [x] Document evaluator bias, non-determinism, inconsistency, prompt sensitivity,
  self-preference, cost, latency, and prompt injection through judged content.

**Exit criteria:** Providers can be replaced without orchestration changes;
structured outputs are validated; calibration disagreements and cost/latency are
measured. Deterministic evaluation still works without judge credentials.

### Phase 4 implementation and local verification — 2026-10-30

Added optional `llm_judge` assertions with a provider-independent protocol and an
OpenAI Responses adapter selected by the user. Strict config/output validation,
rubric scoring and explanations use existing assertion snapshots/evidence; no
main-schema migration or dependency was needed. Credentials/model are operator
settings, judging is disabled by default, and queued submissions freeze private
judge configuration. Known secrets are redacted before transmission. One semantic
assertion per case, at most two transient-failure calls, total default 20-second
deadline, child self-deadline, input/output limits and explicit refusal/incomplete/
invalid-output errors bound execution.

A 24-hour/1,000-entry local derived cache keys full configuration and version
identity and saves redacted judgments/source evidence. Usage records separate
new tokens from cache hits, retain incomplete-usage flags and optionally estimate
cost from operator-supplied rates. Report UI explains scores, thresholds, errors,
cache reuse, usage and judge latency. `history-v2` excludes cached judgments from
fresh repetition counts and warns on cached pairs.

The calibration CLI compares a versioned 10-case author-labeled synthetic dataset
with the semantic evaluator and a literal baseline; it supports repeated fresh
calls and two prompt variants. Reports include sample counts, disagreements,
false passes/failures, inconsistent cases, latency, reported tokens and estimated
cost or unknown. The offline scripted fixture produced 20 observations, 2
judge/label disagreements, 4 deterministic/label disagreements and 6 between
evaluators, with no execution errors. This verifies reporting, **not LLM accuracy**.

**Verification:** **281 backend tests** passed with SQLite/disposable PostgreSQL,
**13 demo tests**, **16 Chromium tests**, dependency locks/pip/Ruff, frontend
lint/type/build and Compose configuration passed. The isolated Compose smoke
passed submission/recovery/demo/history/restart/outage/deletion checks and removed
its resources. New tests exercise real owned HTTP servers and nested worker
processes, provider replacement, output validation/refusals, retry caps/deadlines,
redaction, caching/invalidation/expiry/size, saved API evidence, repeat exclusions
and calibration calculations. The 42 judge/history tests also passed inside the
Linux Python 3.12 container. Chromium verifies fresh/cached/error report details
and safe rendering. No external model calls were used for these tests.

**Explicitly pending exit verification:** The user chose "Finish local verification;
live validation later." No real OpenAI model's calibration quality, prompt
sensitivity, token spend or latency has been measured. Run the documented live
calibration with chosen credentials/model and review disagreements before treating
the full real-model exit criterion as satisfied. Hosted CI/clean-clone onboarding
remain pending, other browsers are unverified, and the existing Starlette/AnyIO
warning remains. Developer databases and `.env` files were not changed.

**Tradeoffs:** Active private jobs still contain plaintext credentials; remote
processing/billing may outlive cancellation. Usage evidence is not a billing
ledger or spend quota. Cache is local/per-container and not tenant-aware. Models
may be biased, inconsistent or influenced by malicious evidence despite valid
JSON; scores are rubric judgments, not security guarantees. See
[LLM_EVALUATION.md](LLM_EVALUATION.md) and
[ADR-015](DECISIONS.md#adr-015--optional-openai-judgments-with-bounded-execution-and-explicit-uncertainty).

## Phase 5 — Real security testing

**Goal:** Reusable, meaningful tests for authorized AI systems.

- [x] Basic string probes for prompt injection, system prompt leakage, sensitive
  information leakage, and reliability; synthetic vulnerable fixture.
- [x] Reusable versioned packs for direct/indirect prompt injection, prompt
  extraction, sensitive information leakage, jailbreak resistance, instruction
  hierarchy violations, excessive agency, insecure tool use, exfiltration
  simulations, unsafe structured output, and context poisoning.
- [x] Controlled fixtures for tools/retrieval and synthetic data; explicit scope,
  safe simulated destinations, and expected outcomes.
- [x] Map appropriate tests to recognized AI security categories using verified
  references at implementation time; document limits of those mappings.

**Exit criteria:** Packs include known vulnerable and safe fixtures, demonstrated
detection limits, and documented authorization requirements. No functionality is
intended to attack systems without permission or exfiltrate real data.

### Phase 5 implementation and verification — 2026-11-03

Three version 1 format 2 packs add **12 adversarial cases and 3 benign controls**:
instruction boundaries (6 cases), retrieval boundaries (4) and action boundaries
(5). They cover all eleven categories above, including separate retrieved-document
and tool-result injection probes. The API exports them alongside the unchanged
baseline; the target detail page selects and submits them through the existing
queue. Reports retain category filters, assertion evidence and structured action
observations. Existing compact/default runs still select the eight-case baseline.

Independent stateless safe/vulnerable demo routes accept a bounded synthetic
protocol. Tool arguments are fixed synthetic values; actions and rendering are
inert records with no network/file/process execution. Positive schema constraints
reject missing action evidence, while the allowed lookup control catches blanket
tool denial. Known vulnerable fixtures fail all 12 attack cases; known safe
fixtures pass all 15 cases; both pass all 3 controls. OWASP 2025 mappings use primary
references verified at implementation time and explicitly limit their coverage.

**Verification:** **301 backend tests** passed with SQLite and disposable
PostgreSQL, **34 demo tests**, **23 Chromium workflows**, dependency locks, pip
consistency, Ruff lint/format, frontend lint/type/build and Compose config passed.
The isolated Compose smoke executes all six pack/mode combinations through the
real PostgreSQL queue/worker, plus baseline recovery, restart, outage and cascade
deletion; it passed and removed its resources. Backend checks verify persisted
per-case verdicts/provenance, incomplete evidence, refusal text masking an action,
and documented false-positive/false-negative examples. The browser verifies pack
selection, new category filters, structured evidence, reload and pack-list retry.
The baseline remains **8 cases / 4 passes / 4 failures / 50%**. No migration or
dependency was added; main schema remains `0004_history`.

**Limitations:** These are protocol/fixture results, not real-model security or
calibration measurements. Real applications need authorized adapters and trusted
observation of side effects. Literal detectors miss transformed leaks and exact
answers reject paraphrases; those limits have tests. No real exfiltration, tool
execution, vector store, training-data poisoning, deployment or attack against an
external target occurred. Live OpenAI calibration remains deferred. Only Chromium
is browser-tested. The existing Starlette/AnyIO warning remains; this browser run
also printed a non-failing worker `SystemExit: 0` during logging shutdown. Hosted
checks for this change are tracked by the PR; local success is not hosted evidence.

See [SECURITY_PACKS.md](SECURITY_PACKS.md) for setup, protocol, expected outcomes,
authorization requirements and mappings, and
[ADR-016](DECISIONS.md#adr-016--synthetic-security-packs-with-observable-trust-boundaries)
for alternatives and tradeoffs. **Next task:** design the Phase 6 authentication,
organization/project ownership and authorization model in an ADR before adding
multi-user paths; do not start without the user's instruction.

## Phase 6 — Authentication, organizations, and secure secrets

**Goal:** Secure multi-user operation; mandatory before public exposure.

- [ ] Select authentication approach in an ADR; implement users, organizations/
  workspaces, projects, roles, API tokens, and authorization on all resource paths.
- [ ] Tenant isolation across queries, workers, caches, artifacts, and exports.
- [ ] Encrypt target credentials or use secret-manager references; support
  rotation, revocation, least-privilege access, and audit logs.
- [ ] Enforce destination/network policy, sensitive-evidence redaction/retention,
  abuse limits, and operational secret handling.
- [ ] Perform a serious security review with tests of cross-tenant access, SSRF,
  secret leakage, malicious responses, and denial-of-service boundaries.

**Exit criteria:** Isolation and permission tests cover API/background paths;
stored secrets never appear in responses/logs; rotation works; security review
findings that block public exposure are resolved. CORS is not authorization.

### P6-1 — Operator access boundary (implemented, 2026-11-04)

- [x] Record the incremental authentication choice and planned organization/project
  ownership model in ADR-017; do not confuse installation roles with tenant isolation.
- [x] Add expiring, revocable random operator tokens with hashes at rest,
  reader/runner/admin permissions and private CLI provisioning/lifecycle evidence.
- [x] Protect application endpoints before body parsing, default-deny new routes,
  fail closed on verification outages, and disable queue-bypassing synchronous
  evaluation in token mode. Retain explicit local development compatibility.
- [x] Add memory-only browser sign-in, denied-operation messages, sign-out/401
  cleanup and protection against late responses from an earlier sign-in.
- [x] Verify expiry, role denial, rotation/revocation, migration preservation and
  authenticated background evaluation with controlled local fixtures.

**Implemented:** Migration `0005_access_tokens` adds only token hashes and
credential-lifecycle records. Tokens have 256 random bits, mandatory 1–90 day
expiry (default 7), and fixed roles. A local CLI writes new credentials to exclusive
0600 files, never stdout or argv. Verification reads the database per request;
revocation is effective for subsequent admission without an API restart. CORS
preflight and public operational endpoints do not grant access to application data.
Browser reload clears authentication rather than persisting a bearer credential.
No dependency, existing target-data rewrite or queue coordination change was needed.

**Verification:** **335 backend tests** passed with SQLite/disposable PostgreSQL,
including upgrade/downgrade from 0004 and existing queue tests; **34 demo tests**,
**23 existing plus 4 authenticated Chromium workflows**, locks/pip/Ruff, frontend
lint/type/build and Compose configuration passed. The full isolated Compose smoke
passed baseline/security packs/recovery/outage/deletion and new real token-mode
issuance, queue execution, restart and revocation, then removed its resources.
Developer databases and `.env` files were not migrated or modified. Existing
Starlette/AnyIO and non-failing browser worker-shutdown warnings remain visible.
Initial hosted Python/Compose checks passed, but the second browser suite exposed
a Linux `TIME_WAIT` preflight failure after the first suite had shut down. The
probe now uses `SO_REUSEADDR`; two additional real-socket tests verify released
ports are accepted and live listeners are rejected on macOS and Linux. The current
backend suite has **337 tests**. Final hosted results are tracked in the PR; local
results alone are not hosted verification. Only desktop Chromium is tested; live judge calibration remains deferred.

**P6-1 limitations at delivery (project scope superseded by P6-2 below):** All operator tokens share the same
installation dataset; there are no human users, organization/project memberships,
tenant-scoped workers/caches or encrypted target/provider secret storage. Network
policy, retention, abuse limits and a complete security review remain required.
Revocation does not cancel accepted jobs or undo in-flight effects. Credential
lifecycle records are not a complete request/actor audit trail. The local default
remains unauthenticated and is allowed only with the development environment setting.
Public exposure is still prohibited. See [ACCESS_CONTROL.md](ACCESS_CONTROL.md).

### P6-2 — Project-scoped operator resources and execution (2026-11-06)

- [x] Organizations/projects with one immutable application binding per target/token;
  local CLI provisioning and explicit token project selection. Human memberships
  remain planned, not implied by organization records.
- [x] Scope target CRUD, protected values, runs/results, cancellation, idempotency,
  baselines, comparisons and analytics; deny missing/foreign bindings.
- [x] Freeze target/project identity into queued work and verify ownership at dispatch,
  lease checks and checkpoint writes. Namespace semantic judgment caching by project.
- [x] Adopt existing data/tokens/pending jobs into one legacy project through additive
  revision 0006; retain evidence and refuse unsafe multi-project downgrades.
- [x] Show project identity in the browser and verify that changing tokens clears
  prior report data and blocks access to its target/report.

**Implementation:** See [PROJECT_ISOLATION.md](PROJECT_ISOLATION.md) and ADR-018.
Project scoping is derived from authenticated identity, not supplied headers or body
fields. Tokens grant one project's role; sibling projects remain isolated even in
the same organization. Unbound resources are inaccessible. Local development is
limited to legacy project 1. Organization/project creation remains a trusted local
CLI operation. No dependency, human login, public registration or transfer API added.

**Verification:** 353 backend tests (SQLite and disposable PostgreSQL), 34 demo tests,
23 existing and 5 authenticated Chromium workflows passed. Tests exercise all current
resource paths, both organization/sibling-project boundaries, direct and indirect
ID guesses, idempotency, frozen worker ownership, real owned target/provider children,
cache separation, private CLI output and upgrade/downgrade preservation/refusal.
Locks/pip/Ruff, frontend lint/type/build and Compose configuration passed. Full
Compose smoke passed demo/security-pack/restart/outage/revocation/deletion paths
and removed its disposable resources. After the final indistinguishable-404
refinement, 63 affected service/queue/project tests passed again on both databases.
Initial hosted Python/Compose checks passed. Browser runs exposed missing completion
waits in the existing eight-case extraction and main CRUD workflows. Both now wait
up to 20 seconds for the completed status before asserting unchanged verdicts/counts.
Final hosted results are tracked in the PR; local checks alone are not hosted evidence.
Developer databases and `.env` files were not changed. Existing deprecation and
browser teardown warnings remain visible; only desktop Chromium is verified.
Live model calibration remains deferred.

**Still unfinished:** Human identity/OIDC and organization/project memberships,
encrypted target/provider credentials, egress policy, evidence retention, quotas,
complete audit and security review. Infrastructure and provider credentials remain
shared; project isolation does not prevent capacity contention or a trusted host/DB
operator from accessing all data. Phase 6 is not complete; public exposure remains
blocked.

**Next task within Phase 6:** implement secure target/provider credential storage
with key management, rotation, migration and leakage tests. Human identity/membership
integration and network/resource gates remain tracked above. Do not begin Phase 7.

## Phase 7 — GitHub and CI/CD integration

**Goal:** Actionable evaluation gates on code changes.

- [ ] Design/version `sentinel.yml` before implementation: project, target, attack
  packs, thresholds, baseline, required categories, and failure conditions.
- [ ] Choose GitHub App architecture if justified; use scoped permissions and
  verified, replay-safe webhook handling.
- [ ] Track commit SHA and PR; run evaluations, publish summaries/status checks/PR
  comments, and enforce quality/security gates.
- [ ] Define fork/secret handling, duplicate events, stale commits, and failure
  behavior when infrastructure or target execution fails.

**Exit criteria:** An owned test repository demonstrates pass/fail checks against
a baseline with traceable run/commit identity. A hypothetical injection failure
rate changing from 2% to 8% is an example only; real thresholds require justified
samples and measured evidence. Integration tests cover event replay and errors.

## Phase 8 — Observability and production reliability

**Goal:** Diagnose Sentinel's own behavior and operational failures.

- [x] API/demo liveness endpoints and container health checks.
- [ ] Structured redacted logging with request/job/evaluation IDs, metrics,
  dashboards, error monitoring, and tracing where cross-process diagnosis needs it.
- [ ] Readiness, worker health, stuck-job detection, actionable alerts, runbooks,
  and service-level objectives based on actual use.
- [ ] Track evaluation throughput, queue depth, worker utilization, API/target/
  evaluator latency, failures, retries, token usage, and judge cost.

**Exit criteria:** A failed/slow run can be followed across API/queue/worker/target;
fault exercises trigger useful signals without exposing secrets. Metrics are
defined with bounded label cardinality and documented alert ownership.

## Phase 9 — Public API and SDK

**Goal:** A stable developer-facing contract.

- [x] Unversioned REST API with FastAPI-generated OpenAPI.
- [ ] Versioned API, token use, pagination, filtering, consistent errors, rate
  limits, polished OpenAPI, and compatibility/deprecation policy.
- [ ] Create Python SDK only after API stabilization; consider TypeScript later.
- [ ] Provide tested examples conceptually equivalent to
  `sentinel.evaluate(target="customer-support-bot", attack_pack="prompt-injection")`.

**Exit criteria:** Contract tests enforce API compatibility and error semantics;
the Python SDK submits, tracks, and retrieves real runs using documented auth and
pagination. Examples work against a controlled test environment.

## Phase 10 — Cloud deployment

**Goal:** Operate a reviewed public service with recoverable deployments.

- [x] Local Dockerfiles and Compose stack with isolated startup/restart smoke; not a cloud deployment.
- [ ] Choose cloud/container hosting, managed PostgreSQL/Redis, TLS/load balancing,
  network boundaries, and secret management in an ADR; AWS is an option.
- [ ] Add object storage if artifact size/retention requires it; use Terraform or
  other infrastructure as code when repeatable provisioning justifies it.
- [ ] Separate staging/production, automate deployments, plan migrations,
  backups/restores, rollback, and cost visibility.
- [ ] Keep the vulnerable demo out of public production. Avoid Kubernetes until
  measured scale or operational needs justify it.

**Exit criteria:** After the Phase 6 security gate, staging and production are
reproducibly deployable, TLS/secrets/network boundaries are verified, and backup
restore plus application/schema recovery have been exercised.

## Phase 11 — Performance and scalability

**Goal:** Improve measured bottlenecks with reproducible evidence.

- [ ] Establish load-test workloads and environment/cost records for API and
  evaluation throughput, worker concurrency, memory, and external rate limits.
- [ ] Measure database/queue pressure, query plans/indexes, N+1 queries, and caching
  opportunities before changing architecture.
- [ ] Test what happens at 100,000 evaluation cases, including storage, queueing,
  completion time, cancellation, backpressure, failure recovery, and cost.
- [ ] Document before/after results and limitations of each optimization.

**Exit criteria:** Benchmarks can be repeated; the 100,000-case analysis is backed
by measurements or clearly labeled extrapolations. Changes improve demonstrated
bottlenecks while preserving correctness and rate/tenant boundaries.

## Phase 12 — Product-level UX

**Goal:** A usable developer product shaped by complete workflows.

- [x] MVP overview, score/category report, attack details, simple history/filters,
  target configuration, and evidence display in code.
- [ ] Refine overview and failure explorer; add severity filters and searchable
  evidence, historical graphs, run comparisons, and regression highlighting.
- [ ] Project settings, target configuration, API-key/token management,
  integrations, and reliable live progress for the capabilities already delivered.
- [ ] Test accessibility, empty/error/loading states, large reports, and responsive
  layouts with real users; prioritize usability over decoration.

**Exit criteria:** Developers can configure, evaluate, diagnose, compare, and act
on regressions without undocumented steps; usability feedback and automated core
workflow tests support the result.

## Phase 13 — Open source and real users

**Goal:** Support outside developers and learn from real usage.

- [x] README setup/demo guidance, sample vulnerable application, tests, and initial
  architecture/roadmap/security/decision documentation.
- [ ] Contribution/development guides, issue templates, API docs, actionable
  vulnerability-reporting policy/contact, changelog, releases, and license decision.
- [ ] Screenshots/demo, sample applications, and safely seeded demo environment.
- [ ] Seek real users; prioritize feedback and track genuine stars, contributors,
  installations, evaluations, applications tested, and issues resolved.

**Exit criteria:** An external developer can install/use/contribute through tested
documentation; release and security-reporting processes work; real feedback
influences priorities. Adoption metrics are recorded honestly, including zero.
