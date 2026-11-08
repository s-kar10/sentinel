# Sentinel engineering instructions

Sentinel V0.1 is an existing AI application security/reliability testing MVP.
Preserve functioning behavior and evolve it incrementally; do not rebuild it.

## Start each task

1. Read the relevant code, tests, and [roadmap](docs/ROADMAP.md). Identify the
   current phase and the smallest coherent change within the user's request.
2. Explain that change briefly, implement it, and add/update behavioral tests for
   substantial features and bug fixes.
3. Run relevant existing tests and checks. Report failures and unverified areas
   honestly; a successful build is not a browser or integration test.
4. Synchronize documentation, summarize the result and tradeoffs, and identify the
   next task. Do not begin the next major phase without the user's instruction.

## Engineering rules

- Prefer simple, typed, modular boundaries. Avoid giant modules, unnecessary
  rewrites, premature microservices, and dependencies without a concrete purpose.
- Validate external inputs; treat target responses as untrusted data.
- Test only owned or explicitly authorized targets, using synthetic secrets/data.
- Never expose credentials in logs, errors, or APIs. Consider SSRF, outbound
  networking, oversized input/output, resource limits, and tenant isolation.
- Keep local development straightforward. Use Alembic revisions for schema
  evolution; never restore automatic API startup `create_all`. Back up and validate
  legacy schemas before adoption. Follow [MIGRATIONS.md](docs/MIGRATIONS.md).
- Record major decisions in [DECISIONS.md](docs/DECISIONS.md): problem,
  alternatives, decision, reasoning, tradeoffs, and future implications.
- Explain important new concepts: the problem, why needed, how implemented, and
  major tradeoffs. Every technology must solve a real engineering problem.
- Separate implemented behavior from plans. Mark tasks complete only with code or
  runtime evidence. Never invent performance, adoption, or résumé metrics.
- Protect existing user changes and data. Keep secrets and generated artifacts out
  of source control. Do not publish the vulnerable demo or local MVP publicly.

## Current verification commands

Use CPython 3.12 and Node.js 22. From the project root, with dependencies and
tools installed per [DEVELOPMENT.md](docs/DEVELOPMENT.md):

```sh
bash scripts/lock-python.sh --check
bash scripts/check-python.sh
bash scripts/check-frontend.sh
docker compose config --quiet
```

For frontend/API workflow changes, run `(cd frontend && npm run test:e2e)` after
installing Chromium with `(cd frontend && npx playwright install chromium)`.
Playwright starts fresh loopback-only API/demo/Vite processes and a temporary
migrated SQLite database; ports 18000, 18001, and 18473 must be free. It refuses to
reuse running services. See [DEVELOPMENT.md](docs/DEVELOPMENT.md#browser-tests).

For changes to startup, database connectivity, Docker, or the demo workflow, also
run `python3.12 scripts/smoke_compose.py` with Docker running. This builds an
isolated stack, checks the real demo/restart/outage/deletion paths, and cleans only
its own containers/network/volume. Images/cache are retained. It is an HTTP/SQL
integration check, not a browser test.

The Python script runs pip consistency checks, Ruff lint/format checks, and the
separate backend/demo suites (both use an `app` package). The frontend build
includes TypeScript checking. Service `pyproject.toml` files are the direct Python
dependency source; regenerate locks with `bash scripts/lock-python.sh --write`.
Do not hand-edit generated requirements or hide dependency warnings. Chromium
workflow tests cover the main UI; other browsers are not verified. Follow
[README.md](README.md) for setup and the demo. See
[ARCHITECTURE.md](docs/ARCHITECTURE.md) for verification limits and
[SECURITY.md](docs/SECURITY.md) for risks.

Backend tests create SQLite schemas through migrations. To also run PostgreSQL
migration tests, set `SENTINEL_TEST_POSTGRES_URL` to a disposable database named
with the `_migration_test` suffix; see the migration guide. PostgreSQL tests skip
explicitly when it is absent. Never point these tests at a developer's real data.

## Background execution and historical analysis

The browser submits `/evaluation-jobs`; native development also needs
`(cd backend && ../.venv/bin/python -m app.worker)` using the API database settings.
Compose includes this worker. Preserve atomic submission, lease/token fencing and
per-case checkpoints when changing execution. Run PostgreSQL queue tests as well
as SQLite tests for coordination changes. The deprecated synchronous endpoint
retains compatibility but has no queue limits/recovery.

Current schema head is `0008_provider_credentials`; stop API and workers before migrations.
Keep baseline references immutable and distinguish paired behavioral changes from
errors/missing coverage. Do not claim significance from descriptive repeat rules.
See [ASYNC_HISTORY.md](docs/ASYNC_HISTORY.md) for exact contracts and limitations.

## Optional semantic judging

Phase 4 adds `llm_judge` assertions using OpenAI; disabled by default. Preserve
pre-dispatch redaction, frozen private job configuration, bounded provider children,
explicit unknown usage/cost and exclusion of cache hits from fresh repeat samples.
The local judgment cache is disposable derived
data. Judge tests use owned HTTP fixtures and synthetic credentials. Live OpenAI
calibration was explicitly deferred by the user; do not imply it has run. Follow
[LLM_EVALUATION.md](docs/LLM_EVALUATION.md) for setup and calibration, and never paste
or log keys. No new dependency is required for the HTTP adapter.

## Synthetic security packs

Phase 5 adds three format 2 packs and independent safe/vulnerable demo routes.
Preserve the original eight-case baseline, pack/case version identity, positive
response contracts and benign controls. Tool actions and render intents are inert
fixture data: never turn them into network, filesystem or process operations.
Run both fixture modes, browser selection/report tests and the Compose smoke for
changes to these workflows. See [SECURITY_PACKS.md](docs/SECURITY_PACKS.md) for the
protocol, authorization requirements, mappings and demonstrated detector limits.

## Operator access (Phase 6 in progress)

P6-1 adds optional token-mode authentication, reader/runner/admin permissions and
private CLI provisioning. Local mode preserves development and is forbidden for
non-development environment settings. Keep route permission inventory tests in
sync; new paths must default to denied. Never copy operator bearer tokens into
target/worker payloads, logs or browser persistence. Token mode disables the legacy
synchronous evaluator. Run the additional authenticated browser suite with
`(cd frontend && SENTINEL_BROWSER_AUTH=1 npm run test:e2e)`. Follow
[ACCESS_CONTROL.md](docs/ACCESS_CONTROL.md) and the current migration head. P6-2 scopes tokens,
resources, jobs and judgment-cache namespaces to projects; follow
[PROJECT_ISOLATION.md](docs/PROJECT_ISOLATION.md). Preserve legacy adoption, scoped
request sessions, default denial for unbound resources and frozen job ownership
checks. Run project isolation tests on both SQLite and PostgreSQL.

P6-3 encrypts target API keys and entire private job payloads with a separate
private keyring; follow [SECRET_STORAGE.md](docs/SECRET_STORAGE.md). Preserve
frozen credentials, fail-closed reads, offline transactional rotation and terminal
payload cleanup. Never regenerate keys for an existing encrypted database.
P6-4 provisions project OpenAI credentials through the private local CLI and records
lifecycle/snapshot/dispatch metadata; follow [PROVIDER_CREDENTIALS.md](docs/PROVIDER_CREDENTIALS.md).
Token mode must never fall back to OPENAI_API_KEY. Local environment fallback is
limited to legacy project 1 without a credential row; revoked rows never fall back.
Preserve frozen job credentials, actor identity derived from the request principal,
transactional audit, project-lock ordering and provider-key rotation coverage.
Human identity/memberships, complete secret-access audits, egress policy and the
full security review are unfinished. Do not claim Phase 6
complete or expose the service publicly.
