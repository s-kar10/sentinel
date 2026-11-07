# Background evaluations and historical comparisons

Phases 2 and 3 add a durable worker and comparisons of saved evidence. The target
adapter, attack definitions, assertion registry and existing scores are preserved.
The default browser workflow uses the queue. These are local development features;
tenant isolation, encrypted target/provider secrets and safe public deployment
remain unfinished. Optional [operator access](ACCESS_CONTROL.md) now protects API
admission; revoking that access does not cancel already accepted jobs.

## Run it

Back up an existing database and stop API/workers before upgrading; see
[MIGRATIONS.md](MIGRATIONS.md). No developer database is automatically modified by
the test suite.

```sh
# Project root: includes migrations, API, worker, frontend, demo and PostgreSQL.
docker compose up --build --wait
docker compose ps -a
```

Open `http://localhost:3000`. Use the [README demo configuration](../README.md#guided-vulnerable-demo-evaluation).
Select **Run evaluation**. You get a report immediately; its saved progress updates
about every 2.5 seconds. **Cancel evaluation** stops dispatch and retains evidence.
The default eight-case demo still produces four passes, four behavioral failures,
original score 50%, weighted score 42.31%, and coverage 100%.

For native development, start the API, demo and Vite as in the README, plus a
fourth terminal, using the **same database settings and backend directory** as the
API:

```sh
cd backend
../.venv/bin/python -m app.worker
```

One worker runs one case at a time. Start a second worker process, or use
`docker compose up -d --scale worker=2`, to use both global slots. More processes
do not increase the database-enforced limits. Workers require Unix process groups
(macOS/Linux); use Docker on Windows. Worker heartbeat monitoring is not yet built;
`/ready` checks the API database, not worker availability. Check `docker compose
logs worker` and saved progress if a run waits. Queue deadlines are enforced when
a worker next visits the queue; a stopped worker cannot update expired runs.

## Submission API

New clients should use `POST /targets/{id}/evaluation-jobs`. A body is optional;
`attack_pack` defaults to the bundled pack. Version labels are optional descriptive
strings, not proof of what model or prompt the target deployed.

```sh
curl -fsS http://localhost:8000/targets/1/evaluation-jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: release-2-attempt-1' \
  -d '{"versions":{"application":"release-2","model":"model-a","prompt":"support-v3"}}'
```

The response is **202 Accepted**, with a run ID and planned/completed/errored
counts. The API performs validation and database writes, with no target HTTP call.
Poll `GET /evaluations/{id}` and `GET /evaluations/{id}/results`.
Cancel with `POST /evaluations/{id}/cancel`. Cancellation is idempotent; a finished
run remains finished. Cancelling a legacy synchronous run returns 404 because it
has no queue job.

`Idempotency-Key` is optional, target-scoped, 1–128 characters from
`A-Z a-z 0-9 _ . : -`. Retrying the same normalized request with the same key returns
the existing run, even after completion. Reusing it for different pack/version
inputs returns 409. Use a **new key for each intentional repeat evaluation**. The
browser preserves its key after ambiguous connection failures. Deleting a target
also deletes these records. There is no idempotency retention timer yet.

The old `POST /targets/{id}/evaluations` remains synchronous, returns 201, and is
marked deprecated in OpenAPI. It preserves existing integrations. **Its execution
is outside the queue's limits, cancellation, retries and crash recovery.** Local
clients should migrate to the queued endpoint. This compatibility route is not an
abuse-resistant public API; Phase 6 must gate all execution paths.

## How the queue works

1. Validation builds normalized assertions and verifies required canaries.
2. One database transaction saves the run, one untested result per planned case,
   and its job. There is no separate broker enqueue that can be lost after commit.
3. Workers take a short coordinator-row write lock, claim an eligible case, issue
   a random lease token and commit. The lock is released before HTTP execution.
4. A separate child process with its own alarm executes the case using the frozen private target and
   pack configuration. Credentials travel through a private stdin pipe, not argv.
5. The parent accepts the result only if the job still holds its token and lease.
   It updates the existing result row and counters in one transaction. Duplicate
   or stale completions cannot add a result or overwrite newer evidence.
6. An expired lease is recovered by another queue visit. It consumes an attempt,
   uses backoff, and continues from the last durable case checkpoint.

PostgreSQL is the Compose database. SQLite uses the same protocol for native
work: the coordinator update starts a write transaction before queue reads.
This deliberately serializes short queue mutations. It is simple and tested, but
not a claim of large-scale throughput. Active jobs are scanned during dispatch;
query/index scaling belongs to measured Phase 11 work.

### Fixed queue policy, version 1

| Control | Current behavior |
| --- | --- |
| Global concurrency | At most 2 valid case leases across all workers |
| Per-target concurrency | At most 1 valid case lease per registered target ID |
| Global admission rate | At least 0.5 seconds between case claims, including retries; no accumulated burst credit |
| Case attempt deadline | 60 seconds including child startup/HTTP/assertions; process creation and OS scheduling can add delay |
| HTTP operation timeout / response cap | Frozen from API settings at submission; defaults 10 seconds / 1,000,000 bytes |
| Lease | 75 seconds, with a new token for each claim |
| Run deadline | 30 minutes from submission, including queue wait and retries |
| Attempts per case | At most 3, including crashed/expired claims |
| Retry delay | `min(2 ** attempts, 30)` seconds plus random 0–1 second jitter |
| Retry eligibility | Execution errors from transport timeout/unreachable target, HTTP 429/5xx, child failure or case deadline; behavioral failures are never retried |
| Non-retry cases | Bad mapping/JSON, oversized response, ordinary HTTP 4xx, failed assertions, evaluator errors |
| Cancellation | Fence immediately in DB; active parent notices within its 0.5-second poll plus DB/OS delay and kills/reaps its child process group |

The child has its own process-group deadline as well as the parent timer, so
a killed supervisor cannot leave an indefinitely streaming attempt behind.

The rate is a **dispatch admission limit**, not an exact spacing guarantee for
network arrival times. Clock synchronization is required for leases across hosts.
There is no quota on the number of queued submissions or tenant budget yet.

Delivery is **at least once**: a target might receive a request before the worker
dies, while Sentinel has not saved its result. Retrying can send it again. Fencing
protects database evidence, not an external target's side effects. Process pauses
or partitions can also leave old external work running past a lease. Exactly-once
external calls and a strict physical concurrency bound through arbitrary failures
would require cooperation from the target. Use authorized, repeat-safe test APIs.

Private job payloads contain copied credentials/canaries in plaintext while active,
just as target configuration currently does. They are excluded from APIs and cleared
when a run finishes, fails or is cancelled; backups may retain copies. Public
snapshots/evidence redact known target secrets. Historical raw evidence is not
retroactively scrubbed. Encryption/retention/tenant isolation remain Phase 6 work.

## Baselines, versions and comparisons

On the target page, expand **Optional version labels** before starting a run.
On a completed report with full coverage, enter a **Baseline name** and select
**Save as baseline**. Later reports can **Compare with baseline**. Baselines have
no update endpoint: a name remains attached to the original run. Choose a new name
for a new baseline. Deleting the target removes its baselines and history.

```sh
# Replace the IDs with completed runs in your local database.
curl -fsS http://localhost:8000/targets/1/baselines \
  -H 'Content-Type: application/json' -d '{"name":"release-1","run_id":1}'
curl -fsS 'http://localhost:8000/evaluations/2/comparison?baseline_id=1'
curl -fsS 'http://localhost:8000/targets/1/analytics?baseline_id=1&limit=50'
```

Compatibility uses a private, saved fingerprint of the original definitions,
pack identity/version, normalized assertions, target endpoint/mapping/template,
credential/canary context, engine/scoring/runtime and queue policy. Version labels
are deliberately excluded so deployments can be compared. Editing configuration
for a later run does not rewrite old evidence. The fingerprint is not returned in
API schemas because it includes sensitive configuration. Old runs without this
identity are marked incompatible; no provenance is invented during migration.
Synchronous and queued execution policies are treated as different configurations.

A comparison reports:

- Pass → fail: an **observed behavioral regression** on the same check.
- Fail → pass: an improvement.
- Errors, untested and not-applicable outcomes: separate coverage information.
- Added/removed checks and incompatible configuration: explicit flags, with no
  misleading regression verdict between different test configurations.
- Weighted score change in **percentage points**, calculated over matching cases
  that have behavioral verdicts on both sides. Categories use the same paired rule.
- Response latency sample counts, means/medians, and the mean paired change in ms.
  This is the final case attempt's transport duration, excluding queue wait,
  retries and assertion time; it is not end-to-end evaluation duration.

The history table shows run/category scores, security-check scores (the three
non-reliability categories), coverage, errors, versions and latency. Incomplete or
incompatible points remain labeled; they are not silently pooled into a trend.
The endpoint returns at most 100 runs (default 50), window bounds, analysis version
`history-v2`, and the contributing run IDs. Version 2 excludes cached semantic
judgments from fresh repeated observations and flags cached pairs. Repeat a terminal-history query with
its `through_run_id` and `limit` to reproduce that window. Active runs can still
change; deleting targets removes the evidence. Single-run comparisons depend only
on the two stored reports and versioned algorithm.

### Samples and false-positive handling

A single pair can show a useful change, but cannot prove a statistically significant
regression. Cases in one suite test different things; retries are recovery attempts.
Neither is counted as an independent repeat.

For a **repeated regression** label, the current conservative descriptive rule
requires distinct, nonempty version labels, at least three behavioral observations
per version for that check, all baseline observations passing and all candidate
observations failing, with no error/missing/incomplete-run observations in those version groups.
Mixed outcomes are marked for review. Too few runs or behavioral samples are
reported explicitly. Compare the same target context, rerun uncertain findings,
and inspect the responses before acting. Three is an operational review minimum,
not a calibrated false-positive rate or statistical power calculation.

There are no confidence intervals, p-values, automatic deployment gates or claims
of independent sampling. Target stochasticity, shared state and changing data may
explain variation. A sound statistical design is needed before adding those claims.
Version labels are user-supplied; Sentinel does not inspect the target's deployment.

## Verification and boundaries

Tests use synthetic targets and disposable databases. Queue tests exercise atomic
rollback, concurrent idempotency/claims, per-target/global limits, duplicate/stale
completion, retry exhaustion, cancellation, lease recovery, hard child timeout and
frozen target/transport configuration. A bounded workload runs eight 0.8-second
synthetic cases across two targets with four competing consumers on SQLite and
PostgreSQL: all eight finish with at most two active cases, no same-target overlap,
and persisted admission times (derived from lease expiry) spaced by at least the
configured 0.5-second interval. A deterministic test rejects admission at 0.499
seconds and accepts the boundary at 0.5. Executor callback starts can bunch after
OS scheduling delays and are not the admission clock. This is a correctness
workload, not a throughput benchmark.

Historical tests cover known synthetic regressions/improvements, incompatible and
legacy records, coverage changes, insufficient/mixed/error repeats, immutable
baselines and reproducible terminal windows. Chromium exercises real queued
progress/cancellation and saving/comparing versioned baselines. Compose checks
submission while the worker is stopped, survival through API restart, later worker
completion, baseline analysis, full recreation and database outage/recovery.
Hosted CI, cross-browser behavior, multi-host failover and production scale remain
unverified. See [ROADMAP.md](ROADMAP.md) for final test counts and evidence.
