# Operator access control — Phase 6 milestones 1–2

Token authentication and reader/runner/admin permissions now apply to one project
per token. Organizations own projects; all readers **within a project** see that
project's targets and evidence. See [project isolation](PROJECT_ISOLATION.md) for
provisioning, legacy adoption, query/worker/cache enforcement and remaining limits.
Human accounts, memberships and public registration are not implemented. Phase 6
is not complete; public deployment remains blocked.

## Modes and migration

`AUTH_MODE=local` is the compatible default, permitted only when
`APP_ENVIRONMENT=development`. It preserves the existing unauthenticated local
demo. It is not a network security boundary. Keep all services loopback-bound and
do not share that mode with untrusted users. Invalid mode names and local mode in
non-development environments prevent startup rather than silently disabling auth.

`AUTH_MODE=token` requires a valid bearer token on application endpoints. It uses
the same database as the API. CORS remains an independent browser policy; an
allowed origin does not authenticate a request. Health, readiness and access-mode
discovery remain public and contain no application records.

Back up and stop API/workers before applying Alembic revision
`0008_provider_credentials`, following [MIGRATIONS.md](MIGRATIONS.md). Revision 0005 adds token hashes/lifecycle records; 0006 binds existing targets
and tokens to the legacy project and adds scope to pending private jobs. Startup
still never creates tables. No new token is created or granted access. Operator provisioning is an explicit local CLI action.

## Provision and use a token

Use the intended API database settings when running the CLI. For native setup,
from `backend` after upgrading the schema:

```sh
../.venv/bin/python -m app.auth.cli issue \
  --project-id 1 --name 'Local operator' --role admin --days 7 \
  --output /tmp/sentinel-operator-token
```

The command generates 32 random bytes, encoded as an opaque `snt_…` bearer token.
It writes the credential to a **new file with mode 0600**, refuses existing files
and symlinks, and prints only the token ID and a generic success message. No token
value belongs in command arguments, logs, screenshots, source control or a URL.
Use a private temporary directory on shared hosts. Keep the file only as long as
needed; deletion is not secure erasure from storage/backups. CLI commands require
local database access and are an operator boundary, not an administrative web API.

Set `AUTH_MODE=token` in the backend environment and restart the API. Compose
reads it from the root `.env`; native commands read `backend/.env` or the process
environment. The frontend discovers the mode through `/auth/status` and asks for
the token. Paste it into the password input using your local secure workflow.
The value stays in JavaScript memory; reload, tab close or **Sign out** clears it.
It is not placed in cookies, localStorage or sessionStorage. An expired/revoked
credential returns 401 and clears the displayed application. Permission failures
return 403 without signing out. The UI currently leaves actions visible; the API
is the enforcement point and reports denied operations.

For a Compose installation, provision in the backend container after migration:

```sh
docker compose exec -T backend python -m app.auth.cli issue \
  --project-id 1 --name 'Local operator' --role admin --days 7 \
  --output /tmp/sentinel-operator-token
```

The file is inside that container and disappears when the container is replaced.
Retrieve/store it through your approved local secret-handling workflow before
replacement. Do not put real credentials in `docker compose exec … echo …` or
paste them into issue/PR text. Enable token mode and recreate the API with
`docker compose up -d --no-deps --force-recreate backend`. Use an existing token or
provision a new one from the CLI if an operator loses the credential.

For API clients, send `Authorization: Bearer <token>` over loopback HTTP during
local development, or over a separately reviewed TLS channel. Never use bearer
credentials over untrusted plaintext networks. Query parameters and cookies are
not accepted as credentials. Duplicate/malformed authorization headers are denied.
Interactive `/docs` and `/redoc` are disabled in token mode; authorized clients can
fetch `/openapi.json`, which declares the bearer scheme.

## Permissions

| Operation | reader | runner | admin |
| --- | --- | --- | --- |
| Read targets, masked canaries, packs, reports, results, baselines, comparisons, analytics and OpenAPI | Yes | Yes | Yes |
| Submit queued evaluations, cancel runs, create baselines | No | Yes | Yes |
| Create/edit/delete targets; create/delete protected values | No | No | Yes |
| Deprecated synchronous evaluation | No | No | No |
| Issue/revoke/list tokens and lifecycle audit | Local CLI only | Local CLI only | Local CLI only |

Every token has one fixed role and a required expiry: default 7 days, configurable
1–90 days. Names are operator labels, not verified human identities. Reader access
includes potentially sensitive saved evidence; do not issue it to users who are
not trusted with the entire project. Runner access can incur target/provider
requests and cost. Admin access can change outbound targets and therefore is
especially privileged while destination policy is still pending.

The default-deny route table classifies each path and HTTP method. Tests require
all registered application routes to have an explicit policy. Unclassified routes
are denied even to admins; WebSockets are disabled in token mode. Authentication
runs before request-body parsing. The synchronous evaluator stays available in
local mode for compatibility, but token mode disables it because it bypasses queue
limits/recovery. Authorized application responses and access errors use
`Cache-Control: no-store`. Failed database verification returns a generic 503;
it never falls back to local access.

## Rotation, revocation and audit

```sh
# Native backend commands; use the same python -m invocation in Compose exec.
../.venv/bin/python -m app.auth.cli list
../.venv/bin/python -m app.auth.cli revoke 1
../.venv/bin/python -m app.auth.cli audit
```

`list` reports IDs, names, roles, expiry and revocation status, never token values
or hashes. `audit` lists issue/revoke event IDs, token IDs and timestamps. Issuance
and its audit row commit atomically; revocation is idempotent and records one event.
This is credential lifecycle evidence, not a complete request/actor audit trail,
immutable external audit sink or attributed human action history. Database admins
can alter it. No per-request database write is needed for authentication.

Rotate by issuing a new token, validating it with `/auth/me`, switching clients,
then revoking the old token ID. The API checks hash, expiry and revocation on every
request without a positive authentication cache, so no API restart is needed.
SHA-256 is appropriate here for random 256-bit tokens; this is not a password
hashing scheme and must not be repurposed for human passwords.

Revocation applies at request admission. It does **not** abort an in-flight HTTP
request, cancel already accepted jobs, undo target side effects or revoke copied
target/provider credentials. Use a remaining runner/admin token to cancel queued
work separately. Browser sign-out only removes the local credential; it does not
revoke the token for other clients. Late responses from a previous sign-in cannot
populate the next session or clear its credentials.

## Security boundaries still open

Project ownership now scopes API data, jobs and judgment-cache keys. Infrastructure
remains shared. Target keys and private job payloads are encrypted at rest, while
token-mode provider access requires the project's provisioned key (see
[PROVIDER_CREDENTIALS.md](PROVIDER_CREDENTIALS.md)).
Arbitrary accepted outbound target URLs remain reachable, and global
submission/body/storage quotas are incomplete. In-memory browser tokens reduce
persistence but cannot withstand active same-origin script execution or a
compromised browser/host. API clients and browser tooling can still record their
own headers; never collect real tokens in test traces or logs.

No new dependency was added. Read the staged identity/ownership design in
[ADR-017](DECISIONS.md#adr-017--operator-access-first-with-an-explicit-path-to-tenant-identity).
Project ownership is implemented in [P6-2](PROJECT_ISOLATION.md). Human identity and
memberships, secure target/provider secret storage, and network/resource policy
remain open Phase 6 work.

## Verification

`test_access.py` covers the route inventory, anonymous reads, denied writes before
validation, roles, queue admission/cancellation, disabled synchronous execution,
invalid headers, expiry, rotation/revocation, database outage, CORS, metadata,
private CLI output and credential lifecycle. Operator bearer tokens are not copied
into queued target configuration. Migration tests exercise preservation and
upgrade/downgrade on SQLite/PostgreSQL.

The authenticated Chromium suite uses a fresh loopback-only SQLite installation
with public synthetic tokens. It covers sign-in failure/success, an actual queued
run, reader denial, 401 cleanup, memory-only storage, reload/sign-out, mode-discovery
failure/retry and a late old-session response. A separate normal suite preserves
the existing local workflow. Compose exercises real issuance, authenticated queued
execution, restart and revocation in PostgreSQL, alongside the existing full smoke.
See [DEVELOPMENT.md](DEVELOPMENT.md) and the roadmap for commands and results.
