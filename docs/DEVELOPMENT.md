# Development checks and dependency updates

## Runtime policy

Use **CPython 3.12** and **Node.js 22**. Python package metadata, Docker images,
version files, check scripts, and CI agree on these release lines. Frontend npm
installs reject other Node majors through `engines` and `.npmrc`.

Patch releases within those lines are allowed; use maintained patches. This is a
tested compatibility policy, not a bit-for-bit operating-system/image lock. Docker
base tags and CI runner images can receive updates. Local development is supported
on macOS and Linux; Windows/WSL and other Python/Node release lines are not verified.

## Install and run checks

From the project root, with Python 3.12 and Node 22 installed:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt -r demo_target/requirements-dev.txt
.venv/bin/python -m pip install -r requirements-tools.txt
npm ci --prefix frontend

bash scripts/lock-python.sh --check
bash scripts/check-python.sh
bash scripts/check-frontend.sh
docker compose config --quiet
```

`npm ci` installs the exact frontend lock; it does not rewrite it. These commands
are the same ones in `.github/workflows/ci.yml`. No activation is required. To use
another Python environment, set `SENTINEL_PYTHON` to its **absolute interpreter
path** when invoking the scripts. The tools and service test dependencies must be
installed in that environment.

The Python script checks dependency consistency with `pip check`, lints, checks
formatting, then runs backend and demo tests in separate processes/directories.
Both services contain an `app` package; combining them in one pytest process can
import the wrong application. Four command tests exercise this isolation and
verify that a lint, formatting, or backend-test failure stops subsequent steps.

The frontend script runs ESLint and `npm run build`, which includes TypeScript
checking before Vite builds browser assets. This does not exercise a browser.
Compose configuration validation does not start any services.

### PostgreSQL tests

The default backend suite has **306 cases and 31 PostgreSQL skips**. To run all
**337 cases**, set `SENTINEL_TEST_POSTGRES_URL` to a disposable PostgreSQL 16
database whose name ends in `_migration_test`, then run the same Python script.
See [migration verification](MIGRATIONS.md#verification). CI provisions its own
PostgreSQL service with synthetic credentials and always sets this variable.
Tests create and clean their own schemas. Never use a database containing real data.

### Operator access checks

`backend/tests/test_access.py` exercises permissions, private token lifecycle,
expiry/revocation, failed verification and the route inventory. Migration tests
cover revision 0005 on SQLite and PostgreSQL. The standard 23 browser workflows run
in local mode; also run four token-mode workflows against separate fresh services:

```sh
(cd frontend && SENTINEL_BROWSER_AUTH=1 npm run test:e2e)
```

Run these suites sequentially because they use the same reserved loopback ports.
The port preflight uses `SO_REUSEADDR`, matching Uvicorn: it accepts released
`TIME_WAIT` sockets after a suite exits but still rejects live listeners. Real
socket regression tests verify both cases, including reproduction on Linux.
The helper provisions public synthetic tokens only in its temporary test database;
no developer database or credential is used. CI runs both suites. Browser traces
contain these fake credentials; never use real operator tokens in recorded tests.
Compose smoke also verifies private issuance, authenticated queued runs, restart
and revocation. No general public-deployment security certification is implied.

### Security pack checks

`backend/tests/test_security_packs.py` verifies all three exported packs against
safe and vulnerable fixture routes, saved evidence, and explicit detector limits.
`demo_target/tests/test_security.py` checks independent fixture validation, scoped
tool arguments, no tool side effects and request isolation. The demo suite now has
34 tests. Seven new Chromium tests cover six real queued pack/mode combinations
and pack-list failure/retry, bringing browser coverage to 23 workflows. The
2026-11-03 run passed but emitted a worker `SystemExit: 0` during logging shutdown;
shutdown signal handling remains a maintenance item. The Compose
smoke also executes every pack/mode through PostgreSQL and the real worker.
See [security packs](SECURITY_PACKS.md) for protocol and expected outcomes.

### Semantic evaluator checks

`backend/tests/test_judges.py` uses owned loopback HTTP servers, real provider/case
subprocesses and synthetic keys. It tests no external model and spends no API
tokens. Judge/history tests also pass in the Linux Python 3.12 runtime. Browser
coverage now includes three fixture-driven semantic report cases (fresh, cached,
errored), within the 23 local-mode Chromium workflows. Provider HTTP/worker integration is
covered by backend tests; the browser fixtures do not prove live provider access.

Run the fixture calibration CLI in [LLM_EVALUATION.md](LLM_EVALUATION.md) to verify
disagreement/usage reporting. Live calibration was explicitly deferred by the user.
It requires local server credentials, a chosen model and the explicit `--live`
flag. Keep generated reports outside source control; record reviewed measurements
and configuration in documentation when live verification is performed.

## Python formatting and linting

Ruff 0.14.14 provides both operations, configured in the root `ruff.toml`:

```sh
.venv/bin/python -m ruff check backend demo_target scripts
.venv/bin/python -m ruff format --check backend demo_target scripts
```

To apply formatting/import corrections intentionally:

```sh
.venv/bin/python -m ruff check --fix backend demo_target scripts
.venv/bin/python -m ruff format backend demo_target scripts
```

The initial rules cover basic Python errors, undefined/unused names, and import
ordering. Layout uses Ruff's formatter at 88 columns. This keeps the initial
standard small; it is not static Python type checking. Ruff is version-pinned so
upgrading the formatter cannot silently change CI's expectations. The initial
formatting pass changed layout and import ordering only; evaluation behavior and
the frozen database schema were preserved.

## Dependency sources and locks

| File | Purpose | Edit directly? |
| --- | --- | --- |
| Each service's `pyproject.toml` | Direct runtime dependencies and `test` extra | Yes |
| Each service's `requirements.txt` | Generated runtime versions, platform markers, and download hashes | No |
| Each service's `requirements-dev.txt` | Generated runtime plus test dependencies | No |
| Root `requirements-tools.txt` | Pinned Ruff and uv binaries; neither has runtime dependencies | Yes |
| `frontend/package.json` / `package-lock.json` | Frontend intent / npm-resolved versions | Use npm for updates |

uv 0.9.26 is used only to compile portable Python locks. pip still installs the
application and Docker needs no uv. Universal resolution preserves platform
markers instead of copying a macOS `pip freeze` into Linux containers. Hash checks
verify that downloaded distributions match the reviewed files; they do not prove
those packages are free of vulnerabilities.

Runtime locks exclude pytest, coverage, and development tools. Dev locks include
the runtime pins. The demo is constrained to the backend's overlapping versions
because the backend integration test also loads the real demo in-process.

After editing direct dependencies in service metadata:

```sh
bash scripts/lock-python.sh --write
```

This keeps existing compatible pins. To deliberately refresh all allowed
transitive dependencies, use `bash scripts/lock-python.sh --upgrade`. Direct exact
pins still require editing the metadata. Review all lock changes, install into a
fresh environment, and rerun the checks including PostgreSQL. Commit metadata and
generated files together. CI runs `--check`, which fails on stale locks without
changing tracked files. Lock regeneration/checking may need package-index access.

## Compose smoke

```sh
python3.12 scripts/smoke_compose.py
```

Requires Docker Compose v2 and Python 3.12's standard library; no local application
dependencies are needed. The script builds the real Dockerfiles using normal build
cache, starts an empty PostgreSQL volume, and exercises HTTP endpoints and SQL row
counts. It recreates every container with the same test volume to verify durable
reports and migration startup, then stops/restarts PostgreSQL to check readiness
and connection recovery. It checks all eight catalog verdicts, compares saved
responses to direct demo calls, and checks deletion of target/canary/run/result rows,
plus jobs and baselines. It also submits while the worker is stopped, restarts the
API, resumes the worker and checks stored baseline comparisons.

Docker assigns free host ports. The script builds the frontend with the assigned
API URL and configures CORS for the assigned frontend origin. It also checks a
rejected origin, served assets, and nginx's deep-link fallback. These are HTTP
checks; JavaScript rendering and clicks are covered separately by the browser suite.

Each run uses a generated `sentinel-smoke-*` project name, its own volume/network,
synthetic credentials, an empty explicit env file, and sanitized Compose/application
environment overrides. There is no option to target an existing project. The
backend probe interval is shortened only in the smoke override; its readiness
command remains the production Compose command. Cleanup runs on success, failure,
Ctrl-C, or SIGTERM and only removes this project's containers/network/volume.
Images and build cache are retained; the script never prunes Docker globally.
Hard kills or Docker daemon failure can prevent cleanup. The printed project name
identifies leftover resources; inspect them before any manual deletion.

## Browser tests

After the standard Python and frontend dependency setup, with Node 22:

```sh
cd frontend
npx playwright install chromium
npm run test:e2e
```

On Linux, `npx playwright install --with-deps chromium` also installs required
system libraries (used in CI). Playwright 1.64.1 is pinned in the npm lock and
brings a matching browser build. Only Chromium desktop is verified.

Playwright starts the actual Vite frontend on loopback port 18473 and invokes
`scripts/serve_browser_tests.py` to run the real backend/demo on 18000/18001 plus a queue worker. The
helper creates a fresh SQLite database through migrations, uses a temporary
working directory so developer `.env` files are not read, and overrides database,
CORS, and target timeouts. Existing listeners are rejected, not reused or stopped.
The helper terminates its children and removes the temporary database on exit;
hard kills or machine failures can prevent cleanup. Existing developer data is not
part of these tests. Fixed test ports mean concurrent suites on one host are not
supported. The ordinary Compose stack can remain running on its different ports.

Thirteen tests cover the real register/edit/key/canary/run/report/filter/delete flow,
server/client validation, real extraction errors, both deletion dialogs, and
controlled empty/failed reports, transient fetch errors, polling recovery,
client-route cancellation, escaped target HTML, and an API-submitted custom pack's
real demo results displayed in the browser. Format 2 coverage includes status,
latency, JSON schema, explicit outcomes, weighted rates and provenance. The rare report states use
intercepted responses with TypeScript-checked API shapes. Two additional real-service
workflows verify queued progress/cancellation and versioned baseline comparisons. Two backend API cases also distinguish null responses
(request/extraction failure) from valid empty-string responses.

The polling test was checked against an isolated copy with retry scheduling
disabled after failure: it failed, then passed with the fix. Polls are serialized,
rescheduled after completion/failure, and cancelled on navigation. A completed, failed or cancelled run stops polling. Manual retry is available for initial or refresh errors.

Failed runs retain partial evidence but suppress a headline score; empty runs
also show no score. New runs persist explicit outcomes; old rows retain the inferred
passed/response classification. Original scores still count errors as not passed.
Engine V2 adds weighted rates and coverage with explicit nulls when no score can
be computed. See [ENGINE_V2.md](ENGINE_V2.md).

Failure screenshots/traces are stored under `frontend/test-results/` and ignored
by source control. Inspect a trace with `npx playwright show-trace PATH/trace.zip`.
Use synthetic data only; traces can include requests and page content. No cross-
browser, mobile, full accessibility, production deployment, or coverage percentage
claim is implied by these checks.

## CI and verification limits

GitHub Actions has Python, frontend, and Compose smoke jobs on Ubuntu 24.04. It uses
version files, fresh installs, the shared commands above, and PostgreSQL 16.
Actions are pinned to commit IDs and the workflow has read-only repository
permissions. No deployment or credentials for external targets are involved.

The public repository is [s-kar10/sentinel](https://github.com/s-kar10/sentinel).
[Hosted checks](https://github.com/s-kar10/sentinel/actions/workflows/ci.yml) run
from fresh checkouts. The frontend job installs isolated Python services and
Chromium, then runs the browser suite. See the roadmap for recorded run results.
Passing CI does not establish production readiness or a coverage percentage.

Known dependency maintenance items:

- Starlette 0.46.2's `TestClient` imports the deprecated
  `anyio.abc.BlockingPortal` alias under AnyIO 4.15.1. Both suites pass, and the
  warning remains visible. A future FastAPI/Starlette compatibility update must
  rerun the behavioral/integration tests; do not suppress the warning or downgrade
  AnyIO solely to hide it.
- The clean frontend install reports an ESLint 9.39.5 support deprecation. Its
  checks still pass. A future ESLint upgrade must also verify the TypeScript and
  React plugins. The clean install also surfaced three npm audit findings; a
  targeted lock update moved Vite 6.4.3 to 6.4.5, source-map-js 1.2.1 to 1.2.2,
  and brace-expansion 1.1.18/5.0.9 to 1.1.21/5.0.12 within existing constraints.
  The subsequent clean install/checks passed and npm audit reported zero findings.
  This is a point-in-time npm result, not a complete dependency security review.

See [ADR-008](DECISIONS.md#adr-008--shared-checks-and-reviewed-dependency-locks)
for alternatives and tradeoffs.
