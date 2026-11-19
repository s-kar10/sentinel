# Request and queue resource limits

P6-6 bounds two resources a caller could previously consume without limit: the
bytes the API reads for one request, and the number of unfinished queued runs a
project (or the whole installation) can hold. It also makes dispatch prefer
projects that hold fewer active leases. These are application controls for a
trusted local installation, not a complete denial-of-service defense.

## Settings

| Variable | Default | Allowed | Meaning |
| --- | --- | --- | --- |
| `MAX_REQUEST_BODY_BYTES` | 1,048,576 | 65,536–10,485,760 | Largest request body the API reads, before JSON parsing |
| `QUEUE_MAX_ACTIVE_RUNS_PER_PROJECT` | 10 | 1–1,000 | Unfinished queued runs one project may hold |
| `QUEUE_MAX_ACTIVE_RUNS` | 50 | 1–10,000 | Unfinished queued runs across all projects |

The per-project value may not exceed the installation value; startup fails if it
does. Settings are read when the API starts and apply to new requests after a
restart. Compose forwards all three with the same defaults; native development
reads them from `backend/.env`. They are installation-wide: there is no per-project
override or remote management endpoint.

## Request bodies

**Problem.** Pydantic field limits (for example the 65,536-byte normalized attack
pack) run only after Starlette has buffered and decoded the whole body. A target's
`request_template` has no field-level size bound at all. A client could therefore
make the API allocate and parse an arbitrarily large body.

**Implementation.** `RequestBodyLimitMiddleware` (`backend/app/api/body_limit.py`)
is an ASGI layer that runs inside authentication and outside routing:

1. A declared `Content-Length` larger than the limit returns **413** without
   reading any body. Conflicting duplicate, negative, non-numeric or absurdly long
   `Content-Length` values return **400**.
2. Otherwise it wraps the receive channel and counts body bytes as they arrive.
   Chunked or undeclared bodies are cut off at the chunk that crosses the limit.
   The wrapper raises a Starlette `HTTPException(413)`, which FastAPI deliberately
   re-raises during body parsing, so the route never runs.
3. 413/400 responses carry a fixed message and `Connection: close`; they never echo
   the body. In token mode, unauthenticated requests still receive 401 before any
   body byte is read; the limit protects authenticated and local-mode callers.

The default leaves ample room for the largest valid attack pack and ordinary
target templates. Raising it increases peak memory per concurrent request.

## Queued admission

**Problem.** Workers already enforce 2 global leases, 1 lease per target, a 0.5 s
dispatch interval and a 30-minute run deadline. Nothing limited how many runs
could be accepted, so one project could fill the database and the FIFO queue.

**Implementation.** `JobService.submit` counts unfinished jobs (state not `done`
and run deadline not yet passed) for the target's project and for the installation.
It does so **after** taking the existing queue coordinator lock and **before**
inserting the run, in the same transaction. Every queue mutation already holds that
lock (a row lock in PostgreSQL, a write transaction in SQLite), so concurrent
submissions cannot both observe free capacity and overshoot. A refused submission
rolls back; it creates no run, result or job rows.

- Over the project limit: **429** "This project already has N unfinished queued
  evaluations…".
- Over the installation limit: **429** "The evaluation queue is at capacity…".
- An `Idempotency-Key` replay of an already accepted request returns the existing
  run **before** quota checks, so client retries stay safe when the queue is full.
- Completion, cancellation, target deletion and deadline expiry free capacity.
  Expired runs stop counting immediately, even before a worker marks them failed.

The project count joins jobs to the immutable target-project binding, so it cannot
be influenced by request fields. The installation message reveals only that
shared capacity is exhausted, not which project holds it. No `Retry-After` value is
sent because the queue cannot predict when capacity frees up.

## Project-aware dispatch

Previously a claim took the oldest eligible case. A project with two targets and a
backlog could hold both global slots while another project waited. A claim now
picks, among eligible cases, the one whose project holds the fewest active leases,
breaking ties by the original FIFO order. Consequences:

- With one project (including local mode's legacy project), ordering is unchanged.
- It is work-conserving: a slot never stays idle while any eligible work exists.
- It is not weighted fair queuing; it balances current leases, not historical usage.
  Lease recovery, attempt limits, per-target exclusivity and token fencing are
  unchanged.

## Verification

`backend/tests/test_resource_limits.py` covers declared and streamed oversize
bodies through the real FastAPI stack, malformed and boundary lengths at the ASGI
layer, token-mode ordering, setting bounds, project versus installation quotas,
idempotent replay at the limit, cancellation/deadline release, ten concurrent
submissions against a quota of three, the 429 API contract and fair claim order.
Queue tests run on SQLite and disposable PostgreSQL. The Compose smoke sends a
declared oversized body to the real Uvicorn server and checks it is refused before
the body arrives.

## Limits

- Compressed request bodies are not accepted by the API, so decompression bombs do
  not apply to requests; target response decompression remains bounded only by the
  existing post-decode response cap.
- JSON nesting depth is not separately bounded; Python's parser recursion limit
  turns pathological nesting into a generic 400 within the byte limit.
- There is no per-request rate limit, connection limit, or slow-client timeout in
  the application; those belong to the ASGI server or a reverse proxy.
- Quotas count runs, not cases or provider spend. A run may still hold up to 50
  cases; the run deadline bounds how long it can consume worker time.
- Read endpoints, target/canary counts and stored evidence size are not quota'd.
- The deprecated synchronous route (local mode only) is subject to the body limit
  but not to queue quotas.
- Limits are installation configuration; per-project budgets would need stored
  entitlements and an admin path, which are not built.
