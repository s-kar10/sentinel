# Architecture decision records

Record major choices with the problem, alternatives, decision, reasoning,
tradeoffs, and future implications. Distinguish observed implementation from
newly accepted direction and unselected future technology.

Date of initial records: 2026-09-14. These records explain the current code and the
user's explicit project direction; they do not claim to reconstruct unavailable
historical discussions or commits.

## ADR-001 — Preserve the modular monolith

**Status:** Accepted project direction; modular boundaries observed in V0.1.

**Problem:** Grow a working MVP without discarding functioning target, evaluation,
storage, and UI behavior or introducing operational complexity too early.

**Alternatives:** Rewrite the application; immediately split into microservices;
incrementally extend the existing API/services/evaluator/model modules.

**Decision:** Evolve the existing modular monolith. Add worker processes when
durable background execution requires them; do not assume independently deployed
microservices are needed.

**Reasoning:** Current responsibilities are already separated in code. Preserving
those boundaries and tests permits small, understandable changes.

**Tradeoffs:** Modules share a deployment and database; discipline is needed to
avoid coupling. Current synchronous work shares API process resources.

**Future implications:** Phase 2 separates execution from request handling. Further
service boundaries require measured scaling, reliability, or ownership needs.

## ADR-002 — Deterministic evaluator strategies first

**Status:** Existing implementation retained; richer framework planned in Phase 1.

**Problem:** Grade response behavior predictably without requiring paid or
non-deterministic model calls for simple assertions.

**Alternatives:** Hard-code checks in orchestration; use an LLM judge for all
cases; resolve deterministic strategies through a registry.

**Decision:** Retain the named registry and small evaluator interface. V0.1
registers forbidden-substring, absence, exact-match, and regex strategies. Only
the two substring strategy names are used by the bundled catalog.

**Reasoning:** A strategy can be tested independently and selected by the attack
definition without adding orchestration conditionals.

**Tradeoffs:** Substrings can produce false positives/negatives. P0-1 now rejects
missing required canaries in the service (ADR-006). The current `expected_values`
and text-only interface cannot
adequately describe schema/status/latency assertions. Outcome evidence is dropped
before persistence.

**Future implications:** P0-1 fixes preconditions; Phase 1 evolves configuration
and metadata boundaries. Phase 4 adds replaceable, calibrated optional judges
while retaining deterministic checks.

## ADR-003 — Relational persistence with PostgreSQL in Compose

**Status:** Existing relational design retained; P0-2 migration implementation
completed on 2026-10-28 (ADR-007).

**Problem:** Persist targets, canaries, runs, and results with explicit ownership
and deletion behavior, while keeping tests fast and isolated.

**Alternatives:** Ephemeral in-memory results; document storage; PostgreSQL with
SQLAlchemy and isolated SQLite tests.

**Decision:** Preserve the four-table SQLAlchemy model and PostgreSQL deployment.
Retain lightweight SQLite tests and add PostgreSQL integration/migration coverage.
Introduce Alembic rather than extending startup `create_all` as a schema strategy.

**Reasoning:** The data is relational and already persisted; a migration history
makes schema changes explicit and reviewable without losing existing records.

**Tradeoffs:** SQLite tests do not prove PostgreSQL behavior. Cascades currently
delete history with a target. Per-run provenance is incomplete, and dynamically
loading results for category summaries can become expensive.

**Future implications:** Baseline adoption and schema migration commands are now
implemented/tested in P0-2. Future revisions must preserve existing data and design
version snapshots and indexes from query needs.

## ADR-004 — Synchronous execution is a transitional constraint

**Status:** Existing V0.1 behavior, not a durable-execution design.

**Problem:** Complete small evaluation runs with low local operational overhead
while preserving observations if a later case fails.

**Alternatives:** One all-or-nothing transaction; synchronous execution with
per-case commits; durable queued jobs with workers.

**Decision:** Preserve synchronous execution during stabilization and document its
limits. Keep per-case commits until a tested Phase 2 lifecycle replaces them.

**Reasoning:** The current eight-case path works and already stores partial
evidence. A queue introduces delivery, idempotency, recovery, and operational
requirements that deserve a separate coherent phase.

**Tradeoffs:** Requests wait for the run; operation timeouts do not bound total
duration; process crashes can strand runs; counts do not represent live progress.
Per-case persistence does not guarantee recovery or exactly-once execution.

**Future implications:** Design submission/enqueue consistency, intended/completed
counts, retry semantics, cancellation, and crash recovery before selecting a queue.

## ADR-005 — Local-only trust model until security prerequisites are met

**Status:** Accepted boundary; current protections and gaps documented in code.

**Problem:** Sentinel intentionally makes outbound requests to configured targets
and retains potentially sensitive evidence, but V0.1 lacks access control.

**Alternatives:** Publish the MVP immediately; restrict use to trusted local
development while building and verifying multi-user controls.

**Decision:** Keep V0.1 local and use synthetic data. Require a serious security
review and the Phase 6 controls before public deployment.

**Reasoning:** Write-only API-key schemas, redacted errors, and loopback ports do
not solve SSRF, plaintext storage, evidence leakage, or authorization.

**Tradeoffs:** Outside collaboration/hosting is deferred. Local private-network
demo access must coexist with later restrictive production egress policies.

**Future implications:** Add enforceable destination policy, encrypted secrets,
tenant boundaries, and auditability. See [SECURITY.md](SECURITY.md).

## ADR-006 — Validate coverage before starting an evaluation

**Status:** Accepted and implemented in P0-1.

**Problem:** The four target-canary leakage checks could pass for any response when
no values were configured. A score then included checks with no useful coverage.
Malformed Unicode list indexes could also escape normal error handling and fail
an entire run instead of one case.

**Alternatives:** Keep the no-op passes; mark missing-canary cases failed; introduce
skipped/inapplicable outcomes and change scoring/report schemas; reject an
incomplete target configuration before starting. For path errors, catch arbitrary
exceptions in orchestration or normalize conversion failures at the path boundary.

**Decision:** When any selected attack declares that it uses target protected
values, require at least one non-blank target canary, including when the attack
also defines fixed strings. The service raises the existing
`InvalidTargetConfigurationError`, which the API maps to actionable HTTP 422,
before creating a run or target client. Suites without that declaration do not
require target canaries. Centralize list-index conversion and translate its
`ValueError` into `JsonPathError` for both reads and writes.

**Reasoning:** The service knows the suite and target, so it can reject missing
configuration without polluting run history or sending unnecessary requests.
Path helpers know how to interpret JSON indexes. Normalizing the error there
allows the existing adapter and service to record a failed case and continue.
Valid Unicode object keys and convertible decimal indexes remain supported.

**Tradeoffs:** Starting the bundled catalog without canaries now returns 422, a
deliberate compatibility change. Developers must configure a synthetic canary
that the target actually knows; Sentinel cannot prove that context exists.
Existing stored scores are unchanged. The evaluator's standalone empty-list
behavior remains a no-match pass; the service owns the suite prerequisite.
Skipped/error-specific scoring and historical correction remain separate work.

**Future implications:** Phase 1 can introduce explicit outcome types and richer
attack requirements through a deliberate contract change. No database migration,
new dependency, queue, or UI redesign was needed for P0-1.

**Validation/evidence:** Regression tests reproduced the defects before the fix.
61 backend tests pass, including no-side-effect rejection, fixed-string-only
suites, Unicode/path edge cases, persisted partial failures, and the actual
eight-case demo through in-process HTTP with SQLite (4 passes, 4 failures, 50%).
The separate 13 demo tests and frontend lint/type/build checks pass. Docker and
PostgreSQL runtime verification of the updated code remains outside this test.

## ADR-007 — Explicit migrations and guarded legacy adoption

**Date:** 2026-10-28.

**Status:** Accepted and implemented in P0-2.

**Problem:** API startup created missing tables through live ORM metadata but
could not evolve existing tables or record their version. Existing V0.1 databases
already contained useful records, so replacing tables or blindly stamping the
latest revision was unacceptable.

**Alternatives:** Continue `create_all`; run migrations in every API process;
automatically stamp any existing tables; or use a separate explicit migration
command with checked legacy adoption.

**Decision:** Pin Alembic 1.20.1 and freeze the current four-table schema in
`0001_v01_baseline`. The frozen metadata generates explicit Alembic table/index
operations and serves as the adoption comparison target; it imports no live ORM
models. Future changes use new revisions. Store migration state in
`alembic_version`. Run the upgrade command as a one-shot Compose service before
API startup; the API only reads/checks the revision.

The `adopt-v01` command requires an unversioned schema matching the frozen
baseline. It checks Alembic-detectable differences plus primary keys, unexpected
constraints, index options, views, and PostgreSQL ID defaults. Only then does it
stamp the exact baseline. It rejects empty/already-versioned/mismatched databases
without marking them adopted. Ordinary upgrade refuses unversioned populated
databases instead of guessing their history.

**Reasoning:** This preserves working data and makes schema changes reviewable.
Tests use the real migration path. A separate job avoids each API replica trying
to change schema; explicit adoption distinguishes an old installation from a new
one. PostgreSQL transaction advisory locking and SQLite `BEGIN IMMEDIATE` serialize
supported migration commands and keep checked adoption atomic.

**Tradeoffs:** Existing installations need a maintenance window, backup, and one
adoption command. Alembic adds a justified dependency. Startup version checking
does not detect every manual database edit. The validator covers V0.1 objects in
the default schema, not all triggers, permissions, extensions, or semantic data
validity. It intentionally rejects schema variations rather than guessing repairs.
Direct raw Alembic commands can bypass the wrapper's safeguards; documented
deployment/adoption workflows must use the wrapper.

The baseline preserves the old non-native status representation: VARCHAR(20)
containing uppercase enum names, with no added database enum/check constraint.
Application-side defaults remain application-side. Its downgrade drops all data
tables and is suitable only for disposable tests; real recovery uses a backup
restored into a separate database. Production backup automation and zero-downtime
schema changes remain future work.

**Future implications:** Review every generated revision for data loss, locking,
compatibility, and recovery. PostgreSQL operations requiring autocommit or
concurrent indexes need a deliberate extension of the transaction policy.
Authentication, encryption, and evaluation behavior are unchanged by this task.

**Validation/evidence:** 99 backend tests pass with PostgreSQL enabled; 13 demo
tests and frontend lint/type/build pass. An isolated Compose startup and live
eight-case demo succeed, populated legacy adoption preserves the report across
restart, and a dump restores to a separate PostgreSQL database. Existing developer
data was not modified. Commands and recovery instructions are in
[MIGRATIONS.md](MIGRATIONS.md).

## ADR-008 — Shared checks and reviewed dependency locks

**Date:** 2026-10-29

**Status:** Accepted

**Problem:** Backend metadata advertised Python 3.11+, containers used 3.12, and
the native Node runtime differed from Docker. Backend requirements duplicated
metadata while the demo used broad ranges. Existing tests could pass against a
different dependency set on another machine. Python had no formatter/linter or CI.

**Alternatives:** Keep hand-maintained pins; freeze one machine's installed
packages; adopt a full environment/build manager; or compile portable pip locks
and share small check scripts between local development and CI. For lint/layout,
separate Flake8/isort/Black tools were considered against Ruff's combined tooling.

**Decision:** Support CPython 3.12 and Node 22, allowing patch updates. Keep direct
Python requirements in each service's `pyproject.toml`, with a `test` extra. Use
uv 0.9.26 only to compile universal, hash-checked runtime and test requirements.
Keep standard pip installation in development and Docker. Constrain overlapping
demo dependencies to the backend pins for the existing in-process integration.
Runtime images exclude test tooling.

Use pinned Ruff 0.14.14 for basic errors, unused names, import order, and formatting.
Shell check commands stop on failure and run the two `app` packages separately.
GitHub Actions uses these same commands, fresh installs, read-only permissions,
pinned action commits, and a disposable PostgreSQL 16 service. npm retains its
existing lock approach; patch updates address the three audit findings discovered
by clean installation without changing direct dependency ranges.

**Reasoning:** One source of direct Python dependency intent prevents declaration
drift. Generated locks record indirect dependencies and distribution hashes, while
universal markers support macOS/Linux differences. CI can reject stale generated
files. Ruff avoids maintaining three overlapping tools. Shared commands reduce
differences between a developer's checks and CI.

**Tradeoffs:** Generated hash files are long and must be updated deliberately.
uv is an additional development-only binary with a concrete locking job. Lock
checking can need network access. Runtime/OS patches still float; this does not
make builds bit-for-bit reproducible or certify package security. Initial Python
changes are mechanical formatting/import ordering; syntax-tree comparison and
existing behavior tests guard against unintended application changes.

The Starlette 0.46.2/AnyIO 4.15.1 deprecated alias remains visible and tested;
upgrading the FastAPI/Starlette stack or downgrading AnyIO merely to remove a
warning is outside this change. ESLint's support deprecation is also tracked.

**Future implications:** Review metadata and locks together, run fresh installs
and PostgreSQL checks for dependency updates, and treat formatter/runtime upgrades
as explicit compatibility changes. Run hosted CI once a real Git repository is
available. Browser automation remains P0-5, not implied by a build.

**Validation/evidence:** See the P0-3 verification section in
[ARCHITECTURE.md](ARCHITECTURE.md) and commands in [DEVELOPMENT.md](DEVELOPMENT.md).

**References:** [uv dependency compilation](https://docs.astral.sh/uv/pip/compile/),
[Ruff configuration](https://docs.astral.sh/ruff/configuration/),
[setup-python](https://github.com/actions/setup-python), and
[setup-node](https://github.com/actions/setup-node).

## ADR-009 — Database readiness and an isolated Compose smoke

**Date:** 2026-10-29

**Status:** Accepted

**Problem:** Process liveness could report success during a database outage. The
earlier one-off Docker checks were not a reusable startup/restart test. Native
CORS defaults disagreed with the frontend port.

**Alternatives:** Change `/health` to mean readiness; add a database connectivity
query only; or retain liveness and add a separate revision-aware readiness probe.
For integration testing, reuse the developer stack or create disposable resources.

**Decision:** Preserve `/health` and add `/ready` using the configured application
engine and existing read-only migration gate. Database/revision errors produce a
generic HTTP 503 without driver details. Use this endpoint for Compose health.
Limit PostgreSQL connection/pool waits to three seconds; apply a transaction-local
two-second timeout to readiness statements only. Align native CORS with port 3000.

Add a standard-library Python smoke harness and CI job. The harness selects a
unique project, empty explicit env file, sanitized application/Compose overrides,
synthetic values, automatically assigned loopback ports, and a new volume. It
builds the actual services, exercises the catalog/storage/restart/outage/deletion
paths, then removes its own containers/network/volume in `finally`. It retains
images/build cache and never globally prunes Docker. Shorter probe intervals in
the smoke override accelerate the unhealthy-state check without changing its
probe command.

**Reasoning:** Existing clients keep their liveness contract. Revision-aware
readiness catches unversioned/stale databases in addition to disconnection. Real
container tests exercise DNS, migrations, PostgreSQL persistence, the compiled
frontend URL, and nginx routing that in-process tests cannot establish. Generated
resource names avoid resetting, adopting, or deleting developer databases.

**Tradeoffs:** Readiness consumes a small database query and can be unready when
the pool is exhausted. It does not validate every table or external target, and
timeouts do not create a complete network deadline. Docker health is diagnostic;
Compose does not restart an otherwise running unhealthy process automatically.
The smoke is slower than unit tests, requires Docker/build downloads, retains
build images/cache, and cannot guarantee cleanup after SIGKILL or daemon failure.

**Future implications:** P0-5 must test real browser interactions. Hosted CI still
requires the eventual repository. Later worker/queue dependencies need their own
readiness and operational policies rather than expanding process liveness.

**Validation/evidence:** 115 backend and 13 demo tests passed, plus frontend and
static checks. The disposable Compose smoke passed fresh startup, exact eight-case
results, persistent reports after recreation, database outage/recovery, and
cascading deletion. Tests also verify cleanup isolation after a simulated failure.

**References:** [Compose startup and health conditions](https://docs.docker.com/compose/how-tos/startup-order/)
and [SQLAlchemy connection pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html).

## ADR-010 — Isolated browser tests and explicit report recovery

**Date:** 2026-10-29

**Status:** Accepted; locally verified, hosted CI pending.

**Problem:** A passing frontend build did not verify the user workflow. UI types
drifted from API contracts, saved-key removal was unavailable, deletion copy
understated its consequences, and a failed background refresh could stop polling.
Reports also blurred execution errors and failed behavioral checks.

**Alternatives:** Component-only tests versus browser tests with real services;
reuse developer services versus isolated temporary services; change the stored
outcome schema now versus explain the existing response contract accurately.

**Decision:** Pin Playwright 1.64.1 and test desktop Chromium. Start loopback-only
API/demo/Vite processes with a temporary migrated SQLite database, refuse occupied
ports, and clean up owned resources. Exercise the main workflow against real
services; use typed intercepted responses for rare report states. Extend the
frontend CI job to install Python service dependencies and Chromium.

Put report loading/polling in a dedicated hook with serialized requests, retries
after background failures, terminal-state stopping, cancellation, and stale-result
guards. Match TypeScript fields to API schemas. Preserve omitted keys and send
explicit `null` for removal. Explain cascade deletion and separate execution
errors from failed behavioral checks using the existing nullable response field.
Keep backend execution, persisted scores, and the database schema unchanged.

**Reasoning:** Real browser interactions catch failures that server tests and
typechecking miss. Disposable services protect developer records and make setup
repeatable. Controlled report fixtures make timing/error regressions reproducible.
A single request lifecycle makes retry and cancellation behavior explicit. The
existing null-versus-string contract is sufficient for current report wording.

**Tradeoffs:** Browser downloads add setup time and a development dependency. Fixed
ports prevent concurrent runs in the same environment. Desktop Chromium/SQLite
coverage does not establish other browser or PostgreSQL browser behavior. Cleanup
cannot be guaranteed after SIGKILL. Mocked report transitions do not validate a
worker. The existing score still counts execution errors as not passed; it is not
a security certification or a pure measure of behavioral failures.

**Future implications:** Phase 1 must define richer outcome/scoring semantics
explicitly if they change. Phase 2 must test real job progress and crash recovery.
Expand browsers when product support requirements justify it. Hosted CI and
clean-clone onboarding require the eventual Git repository.

**Validation/evidence:** Nine browser tests, 117 backend tests including
PostgreSQL, and 13 demo tests passed, as did lint/type/build, dependency checks,
and the full Compose smoke. Disabling retry scheduling in an isolated test copy
made the polling regression fail as expected. Two backend cases distinguish an
unavailable response from a valid empty string. Browser tests verify response text
is displayed as text and synthetic keys are not echoed in target API responses;
this is not a general security audit.

**References:** [Playwright web servers](https://playwright.dev/docs/test-webserver),
[network mocking](https://playwright.dev/docs/mock), and
[browser/system dependencies in CI](https://playwright.dev/docs/docker).

## ADR-011 — Versioned data-only attack packs

**Status:** Accepted; P1-1 implemented and locally verified.

**Problem:** The engine accepted only a code-defined default catalog through the
API. Developers could not save a reusable custom suite, label definition revisions,
or validate external definitions before execution.

**Alternatives:** Load Python modules dynamically; add a database-backed pack
registry/editor immediately; replace the evaluation engine's definitions; or add a
validated JSON boundary that converts to the existing immutable definitions.

**Decision:** Add frozen Pydantic `PackAttack`/`AttackPack` models with tuples,
explicit integer format/content revisions, bounded fields/collections, unique
attack IDs, and forbidden extra fields. Convert accepted data to the existing
`AttackDefinition`, now carrying a version. Export the unchanged baseline through
`GET /attack-packs`; accept an optional `attack_pack` body on evaluation submission.
Keep no-body submission compatible and make selection request-local.

Expose existing substring and exact-match strategies; reject custom regex until
execution safeguards exist. Use neutral `expected_values` in JSON, translating to
the legacy internal `forbidden_values` field without changing grading algorithms.
Exact match uses explicit expectations only; substring rules may additionally use
target canaries and retain preflight. Redact pack inputs in validation errors.

**Reasoning:** JSON supports file reuse without executing supplied code. Existing
Pydantic validation provides OpenAPI schemas without a new dependency. A narrow
conversion boundary preserves orchestration and the existing UI/API response
contract. Separate schema and content revisions distinguish format changes from
changes to an author's checks. Request-local selection prevents one submission
from changing subsequent users' default tests.

**Tradeoffs:** Author-managed IDs/versions do not prove immutable content and are
not saved with historical runs yet. Custom packs are submitted in full, not
registered for lookup. Validation has an evaluator allowlist that must evolve with
the supported configuration contracts. The normalized size cap follows parsing;
it is not an HTTP request limit. Runs remain synchronous with no absolute deadline.
The UI can view custom results but cannot yet author/select packs. Existing stored
prompts/responses may contain sensitive data; input-error redaction is narrower
than evidence redaction.

**Future implications:** P1-2 will formalize evaluator configuration/assertions.
Persisted definition identity, configuration snapshots, evaluator evidence, richer
outcomes, and regex safeguards remain separate Phase 1 work. Content-addressed or
registered immutable artifacts should be considered when provenance is implemented.
Any schema evolution then requires an Alembic revision.

**Validation/evidence:** 42 added backend cases cover API rejection without target
contact or saved runs, supported evaluator behavior, canaries, versions/order/text,
immutable models, OpenAPI, and baseline export/reimport through the real demo.
All 159 backend tests (including PostgreSQL), 13 demo tests, and ten browser tests
passed. The new browser case checks a real custom two-attack run and report.
Compose smoke and static/dependency checks passed; hosted CI remains pending.

**References:** [Pydantic 2.11 field constraints and strict validation](https://pydantic.dev/docs/validation/2.11/concepts/fields/).

## ADR-012 — Versioned assertions, provenance and explicit outcomes

Date: 2026-10-30. Status: accepted; Phase 1 implemented.

**Problem:** Text-only boolean verdicts cannot express transport errors, missing
coverage, structured checks or exactly which configuration produced a result.

**Alternatives:** Add more orchestration conditionals; accept executable plugins;
replace all existing scoring/contracts. Each expands coupling or breaks history.

**Decision/reasoning:** Format 2 packs contain typed versioned assertions resolved
through a registry. Preserve format 1 and original scores. Add structured transport
observations, five outcomes, weighted scores/coverage and normalized redacted
snapshots. Regex/schema run in bounded subprocesses; schemas use a documented
non-referencing subset. Nullable migration columns preserve old records honestly.

**Tradeoffs:** Process startup costs, conservative schema support, literal known
secret redaction and no secret-dependent offline replay from public snapshots.
Original scores still count all non-passes; richer metrics must accompany them.

**Future implications:** Strategies need stable versions/configuration, behavioral
tests and resource boundaries. New replay features need authorized secret context.

**Evidence:** Phase 1: 216 backend, 13 demo, 11 Chromium tests plus Compose/static
checks. See [ENGINE_V2.md](ENGINE_V2.md). Design references:
[jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/)
and [Python subprocess management](https://docs.python.org/3.12/library/subprocess.html).

## ADR-013 — A transactional database queue with fenced case leases

Date: 2026-10-30. Status: accepted; Phase 2 implemented.

**Problem:** A synchronous API request ties progress to one process and can leave
runs unfinished after a crash. A separately committed broker enqueue risks losing
work between database commit and message publication.

**Alternatives:** Celery/Dramatiq/RQ with Redis and a transactional outbox; in-memory
background tasks; a database queue. A broker is reasonable at larger scale, but
requires another service plus delivery/outbox reconciliation. In-memory tasks do
not provide recovery.

**Decision:** Store run, planned results and job in one database transaction. A
singleton coordinator row serializes short queue mutations on PostgreSQL/SQLite.
Workers lease one case, execute outside the transaction in a child process, then
conditionally save with the lease token. Fixed admission/concurrency, attempt,
backoff/deadline and cancellation rules are recorded in [ASYNC_HISTORY.md](ASYNC_HISTORY.md).

**Reasoning:** This avoids the enqueue gap and adds no dependency/service beyond
the already-required database and worker process. Existing engine evaluation logic
is reused. Fenced writes and pre-created result rows prevent stale/duplicate
completion. Queue payloads freeze target configuration and are cleared on terminal
state. A new 202 endpoint and browser workflow preserve the deprecated 201
synchronous API without silently changing its contract.

**Tradeoffs:** Delivery is at least once; duplicate external requests are possible.
Leases require clocks to agree and do not fence external targets. The coordinator
and active-job scan favor simplicity over large-scale throughput. Plaintext
private payloads inherit the existing secrets-at-rest debt. The synchronous route
bypasses queue controls and must be gated before public exposure. No tenant quota,
broker monitoring, durable worker heartbeat or multi-host fault proof is claimed.

**Future implications:** Measure dispatch contention before adding broker/outbox
infrastructure. Phase 6 must secure every execution path and secrets; Phase 8 must
add worker health/alerts; Phase 11 owns throughput benchmarks. Deploy API/workers
at one compatible schema/code revision during maintenance.

**Evidence:** Atomic rollback, idempotent concurrent submissions, claims/limits,
lease recovery, stale completion, retries/cancellation and a multi-consumer workload
are tested on SQLite and PostgreSQL. Real child execution/deadlines and browser/
Compose queue workflows are exercised. Protocol relies on documented
[PostgreSQL row locks](https://www.postgresql.org/docs/16/explicit-locking.html) and
[SQLite write transactions](https://www.sqlite.org/lang_transaction.html).

## ADR-014 — Immutable baselines and conservative descriptive comparisons

Date: 2026-10-30. Status: accepted; Phase 3 implemented.

**Problem:** A score change may be caused by different tests or execution errors,
rather than a change in target behavior. One run cannot establish statistical
significance for a nondeterministic target.

**Alternatives:** Compare raw scores alone; mutable “latest baseline”; statistical
tests over unrelated attack cases; immutable references and explicit compatibility.

**Decision/reasoning:** A baseline name permanently references one completed fully
covered run through the API. Snapshot application/model/prompt labels. Use a private
fingerprint of actual test/target/engine/policy configuration to accept comparisons.
Pair matching behavioral observations; show errors, coverage, effect sizes, latency
and category/security-check trends separately. Return contributing IDs and bounded
history windows under analysis version `history-v1`.

A repeated-regression label requires at least three clean observations per distinct
version, all baseline passes and all candidate failures. Mixed/error/insufficient
samples need review. This is a conservative descriptive workflow, not a calibrated
statistical test. No confidence intervals or p-values are emitted.

**Tradeoffs:** Conservative fingerprints reject comparisons after runtime/config
changes even if a human considers them equivalent. Labels are user assertions;
Sentinel cannot attest deployments. A minimum of three is a review convention,
not evidence of independence or a measured false-positive rate. Bounded windows
may omit older repeats; responses explicitly disclose that. Baselines disappear
with deliberate target deletion and are not protected from database administrators.

**Future implications:** Sampling/calibration and immutable artifact retention are
needed before significance or automated release gates. A compatibility migration
must be deliberate; never fabricate old provenance. Index/query tuning follows
measured history volume.

**Evidence:** Known synthetic regressions/improvements, errors, incompatible
configurations, insufficient/mixed repeats, window replay and immutable references
have backend tests. Chromium exercises named baselines and versioned comparisons;
Compose verifies analysis over worker-produced PostgreSQL evidence.

## ADR-015 — Optional OpenAI judgments with bounded execution and explicit uncertainty

**Date:** 2026-10-30

**Status:** accepted; implemented locally; live calibration deferred by user.

**Problem:** Literal/structural assertions cannot assess every semantic behavior.
A model judge introduces uncertain judgments, external data transfer, latency,
usage cost and new failure modes. It must fit the existing engine and durable jobs.

**Alternatives:** Keep only deterministic checks; use a local Ollama adapter;
couple orchestration to a provider SDK; add a provider-independent contract and
small HTTP adapter. The user explicitly selected OpenAI as the first provider.

**Decision:** Register `llm_judge` version 1 with typed config/result contracts.
Use an adapter registry and the existing httpx dependency for OpenAI Responses.
Request strict JSON output but independently validate scores/explanations. The
[official structured-output contract](https://developers.openai.com/api/docs/guides/structured-outputs)
also requires handling refusals and incomplete output. Keep those as errors.
Keep judging opt-in, operator-configured and model-allowlisted. Freeze private
settings/credential in queued jobs and public version/policy evidence in snapshots.

Isolate each provider attempt in a subprocess with a parent deadline and child
self-deadline. Allow one semantic assertion per case and two transient-failure
attempts within a default 20-second total budget. Do not retry the target merely
because judging failed. Redact known secrets before dispatch, separate rubric
instructions from untrusted evidence, disable tools and follow no redirects.

Cache redacted judgments in a bounded, expiring, disposable local SQLite file.
Use full content/configuration/version/provider/credential identity in hashed keys.
Main schema remains unchanged. Save reported token counts, measured judge time,
optional operator-priced estimates and explicit incomplete-usage flags. Cache hits
report no new tokens and preserve source evidence. `history-v2` excludes them from
fresh repeat samples; comparisons still expose their saved verdicts with a warning.

**Reasoning:** These boundaries reuse existing queue/results/scoring and avoid a
new SDK, broker, hosted cache or schema solely for optional judging. A failure is
diagnosable without being misrepresented as a security failure or pass. A separate
calibration CLI compares an author-labeled synthetic dataset to both the judge and
a literal baseline, with repeats, prompt variants, disagreement/error counts,
latency and usage evidence. Offline fixture output is explicitly not model quality.

**Tradeoffs:** Bounded retry is at-least-once and cannot guarantee billing totals.
Unknown usage remains unknown; crash-lost usage is not reconstructed. No spend
quota, tenant-aware cache, encrypted active job credential or live accuracy claim.
SQLite caches are per container unless explicitly mounted, and concurrent misses
may duplicate calls. Redaction can remove semantic clues. Models can be biased,
inconsistent, sensitive to prompts and vulnerable to malicious grading requests;
schema correctness does not solve those issues. Version labels cannot attest a
moving alias. Target deletion does not immediately erase the disposable cache;
entries expire after 24 hours or can be removed by deleting its file.

**Future implications:** Before consequential use, run live calibration with
chosen model snapshots, review labels/disagreements with humans, evaluate prompt
sensitivity and cross-model/self-preference effects, and establish policy-specific
thresholds. Phase 6 must secure credentials, cache/evidence retention and tenant
boundaries before public access. Phase 8 can aggregate usage telemetry; a billing
ledger would require separate durable attempt accounting.

**Evidence:** Provider-swapping test, real loopback HTTP and nested worker tests,
retry/deadline/invalid/refusal/size handling, redaction, caching/TTL/capacity,
persisted reports, repeat exclusion and calibration calculations. Chromium checks
fresh/cached/error explanations and safe text rendering. Full verification and
the intentional live-validation gap are recorded in the roadmap.

## ADR-016 — Synthetic security packs with observable trust boundaries

**Date:** 2026-11-03
**Status:** Accepted

**Problem:** The eight-case baseline mostly recognizes strings. It cannot show
whether retrieved content gained instruction authority, whether a refusal masked
an unsafe tool intent, or whether a downstream consumer received an unsafe output
contract. We need reproducible examples with known outcomes before interpreting
results against an authorized real application.

**Alternatives:** Add only more free-text prompts; introduce a live agent/tool
framework and new evaluator orchestration; or reuse format 2 packs and structured
assertions with bounded, independent fixtures.

**Decision:** Add three versioned, data-only packs using existing status, schema
and substring assertions, exported by the existing pack endpoint and selectable
in the browser. Add separate safe/vulnerable demo routes with explicit user,
retrieval, tool-result and proposed-action fields. All actions are inert intent
records. Keep the baseline and queue contracts intact. Map individual cases to
verified OWASP 2025 primary references in the security-pack guide.

**Reasoning:** A tool/action trace exposes violations invisible in refusal text.
Positive envelope constraints prevent missing evidence from looking safe. Benign
controls require useful behavior, including an allowed lookup. Independent fixture
rules do not read pack IDs or expected verdicts. Reusing versioned snapshots and
evaluators avoids a second execution engine, schema migration or dependency.

**Tradeoffs:** The protocol requires an owner-provided adapter for real systems.
An untrusted target can fabricate an action trace; assertions cannot attest actual
side effects. Deterministic fixtures verify plumbing and specified boundaries,
not model quality. Literal checks miss transformed leaks; exact answers reject
paraphrases. Fixed synthetic tool arguments constrain these fixtures but do not
solve Sentinel's general SSRF, authentication or tenant-isolation gaps. No real
network transfer, file access, refund or generated HTML execution is performed.

**Future implications:** Keep pack/case versions aligned with changes. Real-system
use requires authorized adapters, trustworthy instrumentation, reviewed policies,
additional adversarial variants and appropriate calibration. Phase 6 still gates
public exposure; no additional major phase begins in this change.

**Validation/evidence:** Safe/vulnerable saved verdicts and provenance, missing/
empty evidence rejection, demonstrated detector blind spots, independent fixture
validation and no-side-effect tests, browser selection/report/filter/retry flows,
and real worker/PostgreSQL Compose runs. Counts are in the Phase 5 roadmap entry.

## ADR-017 — Operator access first with an explicit path to tenant identity

**Date:** 2026-11-04
**Status:** Accepted for P6-1; project ownership is implemented by ADR-018.
Human identity/membership direction below remains planned. P6-1 tradeoffs describe
its original delivery and are superseded where ADR-018 says so.

**Problem:** Every current API caller can read or mutate the same installation.
Phase 6 combines identity, ownership, secret storage and network security. Treating
a login form as completion would leave those boundaries unprotected. We need a
small, testable admission boundary without inventing premature human-account or
tenant infrastructure.

**Alternatives:** Build passwords, recovery and registration now; choose an external
identity vendor before the deployment/organization requirements are known; use a
single static environment key; or issue revocable, expiring operator tokens in the
existing database and keep the remaining Phase 6 gates explicit.

**Decision:** Begin with opaque, random 256-bit operator tokens, SHA-256 digests in
revision 0005, and reader/runner/admin API permissions. The local CLI provisions
credentials into exclusive 0600 files and records issue/revoke events atomically.
The API verifies each request before body parsing, uses a default-deny route policy,
and never places the incoming bearer token in worker payloads. Explicit local
mode preserves development compatibility and is forbidden outside the development
environment setting. Token mode disables the synchronous queue-bypassing endpoint.
The browser stores tokens in memory only and clears application state on 401 or
sign-out. CORS is not authentication. No dependency is needed for these primitives.

**Reasoning:** Revocation on each request is simpler to verify than a JWT denylist
or cache invalidation. Random-token hashes do not require a human-password KDF;
password support would require a separate design. A single static key would not
provide individual revocation, expiry or least-privilege roles. The separate
[OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
and [REST guidance](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html),
checked 2026-11-04, support default denial, per-request permission checks, TLS and
keeping credentials out of URLs. This implementation is not an OWASP certification.

**Planned identity and ownership model:** Human login should use an established
OIDC provider, with stable `(issuer, subject)` identity rather than email as a
primary key; vendor selection remains open. Organizations own projects, projects
own targets, and membership grants roles within an organization/project. API tokens
must eventually reference a subject and explicit scope, rather than just an
operator label. Existing data must be adopted into an explicitly chosen owner,
not silently made visible to every new user. Immutable ownership must flow through
jobs/results/baselines and cache keys before multi-user access is enabled. Resource
queries need ownership predicates as well as route permissions, with negative
cross-tenant tests. None of these future tables or relationships is implemented by
this milestone; creating unused schema would obscure rather than enforce isolation.

**Tradeoffs:** All current token holders with read permission see the same dataset.
Token names are labels, not verified human identities. CLI access trusts the host
operator and database access. Audit covers credential lifecycle only; DB admins can
rewrite it. Memory-only browser storage requires sign-in on reload and cannot
withstand active XSS. Revocation blocks new requests but not in-flight work or
accepted jobs. Local mode is intentionally unauthenticated. Authentication adds a
DB read per protected request. Target/provider secrets remain plaintext; destination
controls, submission quotas and retention still require Phase 6 work. No public
hosting or multi-user readiness is claimed.

**Validation:** All-route inventory and permission tests, expired/revoked/rotated
credentials, malformed headers and auth DB failure, private CLI output/rollback,
SQLite/PostgreSQL migration preservation, existing workflow compatibility, real
browser auth/role/session cleanup and Compose token-mode queue/restart/revocation.
The roadmap records verification counts. Next: ownership and tenant isolation,
then secure target/provider secrets, outbound policy and the full security review.

## Decisions deliberately deferred

| Decision | Trigger | Questions to resolve |
| --- | --- | --- |
| External broker / queue scaling | Measured need after ADR-013 | Coordinator contention, outbox semantics, operations |
| Statistical sampling / calibration | Before significance or release gates | Independence, minimum power, multiplicity, false-positive costs |
| Live judge calibration | After ADR-015; deferred by user | Real-model disagreements, repeated variation, prompt sensitivity, usage/cost/latency |
| Human identity and secrets provider | Phase 6 after ADR-017 | OIDC vendor, ownership/membership enforcement, encryption keys, operational ownership |
| GitHub App/configuration format | Phase 7 | Permissions, webhook verification, fork secrets, config versions, gate semantics |
| Cloud and infrastructure as code | Phase 10 | Cost, managed services, networking, backup/restore, deployment/rollback |
| Service extraction/caching | Phase 11 | Measured bottleneck, complexity cost, failure modes, correctness |

ADR-013 selects a database queue; ADR-015 selects an optional OpenAI adapter.
Authentication vendor, GitHub App design, cloud provider and Kubernetes remain unselected.

## Template for subsequent decisions

```text
ADR-NNN — Title
Date:
Status: proposed / accepted / superseded (link replacement)
Problem:
Alternatives:
Decision:
Reasoning:
Tradeoffs:
Future implications:
Validation/evidence:
```

## ADR-018 — Project-scoped operator tokens with additive ownership bindings

**Date:** 2026-11-06
**Status:** Accepted for P6-2; human identity/membership remains planned

**Problem:** P6-1 authenticates operators but lets every reader access the whole
installation. Route roles alone cannot protect individual targets, reports or
indirect historical references. Queued work and judgment caching must carry the
same ownership boundary after the originating request has ended.

**Alternatives:** Implement an OIDC provider and human membership management first;
use one database per project; introduce PostgreSQL-only row-level security; rebuild
existing parent tables to add mandatory scope columns; or use additive ownership
bindings and explicit service predicates while preserving both SQLite and PostgreSQL.

**Decision:** Organizations own projects. Each target and token has one project
binding in new foreign-key tables. New projects have no access to the legacy
project; even an admin token acts within just one project. The CLI provisions
organizations/projects and requires explicit project selection for token issuance.
HTTP sessions derive scope from authenticated identity, and service reads/mutations
filter by target ownership. Missing bindings fail closed. No transfer API exists.

Revision 0006 adopts prior targets/tokens into named legacy project 1 and extends
pending private job payloads with project/target identity. Workers verify that
frozen identity agrees with the target and run before dispatch, lease checks and
checkpoint writes. Project UUID namespaces enter frozen judge runtime/cache keys,
without changing public comparison fingerprints. The shared worker remains a
trusted process. Local unauthenticated mode addresses only legacy project 1.

**Reasoning:** One-to-one bindings add ownership without rebuilding SQLite parent
tables under existing cascading foreign keys. They also let unbound raw rows deny
access rather than silently fall into a default project. Existing report evidence,
immutable baseline references and queued transport/provider settings are preserved.
A single token scope keeps authorization understandable without inventing human
accounts before OIDC selection. Explicit predicates work in both supported databases
and are covered by negative API tests, including indirect and idempotent paths.

**Tradeoffs:** Extra joins and binding records are needed. Internal ORM creation
uses legacy project 1 as its compatibility default; HTTP creation supplies scope
and the CLI requires it. Future paths must use the scoped session and owned-resource
lookup. This is application authorization, not database RLS: host/database operators
can read or mutate all projects. Organizations are ownership containers, not login
accounts or organization-wide authorization grants. Names are unverified labels.
Shared workers, queue limits, cache capacity and provider credentials remain shared;
project namespaces prevent cache reuse, not resource contention. There is no
project transfer/delete API, human membership, per-project budget or audit trail
for every request. Credential lifecycle auditing remains as before.

**Recovery and future implications:** Operators must review legacy adoption before
migration; already mixed customer data needs a separate reviewed split. Stop all
API/workers for migration. Downgrade refuses multiple organizations/projects because
older unscoped binaries would collapse the access boundary. Use reviewed backups
instead. Later OIDC subjects/memberships can grant access to the same projects;
secret encryption and outbound/resource policy remain separate Phase 6 gates.
No public-deployment readiness is claimed.

**Validation:** SQLite/PostgreSQL migration/model parity and evidence preservation;
sibling-project and cross-organization API denial, missing bindings, idempotency,
worker dispatch/checkpoint scope, real owned target/provider child execution and
project cache-key separation; browser report isolation when changing tokens.
See [PROJECT_ISOLATION.md](PROJECT_ISOLATION.md), the roadmap and PR check evidence.

## ADR-019 — Encrypt target keys and private job payloads at the SQL boundary

**Problem:** Write-only API schemas still leave plaintext target keys in database
backups. Durable work also snapshots target/provider keys, so protecting only the
target column would leave a second recoverable copy.

**Alternatives:** External secret-manager references; a new per-project credential
service; encryption only in CRUD services; or encryption types over existing
columns. References would change frozen-job semantics and require additional
service/lifecycle policy. Service-only encryption can be bypassed by other ORM or
Core writes. Managed key infrastructure is not yet part of the local MVP.

**Decision:** Use pinned `cryptography` AES-256-GCM with versioned envelopes and
field-purpose authentication. SQLAlchemy types encrypt the target key and entire
private job JSON on binding and reject invalid/plaintext data on reading. A bounded
private keyring outside the database supplies one active and retained old keys.
Explicit CLI initialization, offline transactional re-encryption and read-only
verification support lifecycle operations without printing secrets. Revision 0007
converts legacy rows transactionally and refuses unsafe plaintext downgrade.
Compose mounts a separately initialized key volume read-only in trusted services.

**Reasoning:** This covers all existing database copies of target/provider keys
while preserving project checks, queue fencing, immutable accepted configuration,
terminal cleanup and public API contracts. AES-GCM provides confidentiality and
integrity through a maintained library; there is no handwritten cryptography.
The extra dependency solves authenticated encryption, not a speculative need.

**Tradeoffs:** API and worker still possess installation-wide decryption authority.
Field-purpose authentication does not prevent a trusted DB writer from substituting
same-purpose rows. Key-file reads add filesystem work per encrypted field. This is
appropriate for the local bounded queue, with no performance claim. Losing keys
loses access; backups need separate retained keys. Rotation requires downtime and
one transaction over existing records. Old disk pages/backups can retain plaintext.
Canary rows and general evidence/templates remain outside the encryption scope.
Environment provider configuration remains shared; replacing a credential does not
revoke frozen jobs or revoke the credential at its external issuer.

**Future implications:** Managed key storage, per-project provider credentials,
complete credential/request audits and evidence retention remain Phase 6 work.
Human memberships and egress/resource controls are separate unfinished gates.
Neither this encryption milestone nor its tests establish public readiness.
Details and operational steps: [SECRET_STORAGE.md](SECRET_STORAGE.md).
