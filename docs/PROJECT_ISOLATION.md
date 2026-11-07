# Project-scoped operator access — Phase 6 milestone 2

Organizations own projects. Each operator token authorizes exactly one project,
with its existing reader/runner/admin role. Targets belong to one project; protected
values, runs, results, jobs and baselines inherit that ownership through the target.
There is no organization-wide token or role that bypasses project checks. Two
projects in the same organization are just as isolated at the API as projects in
different organizations.

This is an application authorization boundary for trusted local installations.
Human accounts, memberships, OIDC, provider credential management, outbound destination
policy, per-project quotas and a full security review remain unfinished. Phase 6
is not complete and public deployment remains blocked.

## Upgrade and provision

Back up and stop both API and workers before upgrading to current head `0007_encrypted_credentials` using
[MIGRATIONS.md](MIGRATIONS.md). The migration creates `organizations`, `projects`,
`target_projects` and `token_projects`. The latter two tables give each target/token
one binding, with foreign keys and a project index. This additive approach avoids
rebuilding SQLite parent tables that have cascading children.

The migration adopts **all existing targets and tokens into project 1**, named
`Legacy project`, inside `Legacy installation`. Existing holders retain access to
existing data only. A newly created project starts empty; its tokens cannot read
the legacy project. Review this adoption before running the migration. If legacy
data already represents different customers, stop and plan a reviewed data split;
this migration cannot infer customer ownership. It does not move or reclassify data.

Pending private job payloads gain the legacy project binding and project cache
namespace; target settings, credentials, deadlines, results and baseline references
are retained. Cached judgments from before this migration are not reused. Do not
mix old and new API/worker binaries. Downgrade refuses an installation with more
than one project or organization, because older code would expose all their data
to every token. A reviewed backup is the recovery path for that situation.

From `backend`, with the intended API database settings:

```sh
../.venv/bin/python -m app.auth.cli organization-create --name 'Example team'
# Use the returned organization ID:
../.venv/bin/python -m app.auth.cli project-create --organization-id 2 --name 'Support bot'
../.venv/bin/python -m app.auth.cli projects
# Use the returned project ID; it is required, never inferred by the CLI:
../.venv/bin/python -m app.auth.cli issue --project-id 2 \
  --name 'Support operator' --role admin --days 7 --output /tmp/support-token
```

Compose uses the same arguments with `docker compose exec -T backend python -m
app.auth.cli`. Issuance still writes only to a new private 0600 file. Rotation means
issuing another token for the same project, validating it, switching clients and
revoking the old token. Names are operator labels, not verified human identities.
The CLI trusts local database access and lists all projects. It is not exposed as
an HTTP administration API. There is no transfer, project deletion, membership or
scope-edit API. API tokens cannot provision tokens or organizations/projects.

Enable `AUTH_MODE=token` and sign in with the project's token. The browser banner
shows the organization and project. Switching projects requires sign-out and a new
token; the existing memory-only credential and late-response protections clear the
prior application's state. Local development mode is always limited to legacy
project 1, even if other projects exist. It remains unauthenticated and local only.

## Where authorization happens

1. Middleware authenticates the token and applies the existing route/role policy
   before parsing the body. It loads the token's binding from the database on every
   request; missing bindings fail closed.
2. The HTTP database dependency puts the authenticated project ID in the request's
   session. A header, query parameter or JSON field cannot select a different scope.
   Services filter lists and individual resource lookups using target ownership.
   Foreign and nonexistent IDs return the same 404 response for each resource path.
3. Indirect paths also verify ownership: protected-value deletion, result reports,
   baseline creation/comparison, analytics, cancellation and idempotent submission.
   Authorization occurs before an idempotency-key lookup can reveal a foreign job.
4. Submission freezes target ID and project ID into the private job. Trusted workers
   can consume all projects, but check target/run/frozen ownership consistency before
   dispatch, while checking the lease and before saving a checkpoint. An inconsistent
   job is failed and its private payload removed when claimed. Case children receive
   only their job configuration and have no main-database access.
5. Every project has a random persistent cache namespace. Evaluation preparation
   inserts it into the private frozen judge runtime; that runtime is part of the
   judgment-cache key. Identical prompts/settings in different projects cannot reuse
   cached judgments. Namespace changes do not alter public comparison fingerprints.

Ownership is immutable through supported application interfaces. Database/host
operators remain trusted: SQL can alter bindings or evidence, and this is not
PostgreSQL row-level security. Missing bindings deny access rather than implicitly
assigning data at read time. ORM construction defaults to the legacy project for
internal compatibility; HTTP creation always supplies authenticated scope, and the
CLI requires an explicit project. Future resource paths must use the scoped session
and an ownership predicate, with negative tests.

The coordinator, worker pool, database, provider credentials and cache file remain
shared infrastructure. Project cache keys prevent cross-project cache hits, but do
not create separate encryption keys, capacity budgets or process/host isolation.
One project can still contend for global queue/cache capacity. Accepted jobs remain
authorized work after operator token revocation; revocation blocks new admission.
No artifact/export feature exists yet; future implementations need the same scope.

## Verification

`test_projects.py` covers same-organization and cross-organization isolation on
SQLite and PostgreSQL, every current resource path, indirect references, idempotency,
missing bindings, local-mode scope, private CLI provisioning, migration preservation,
downgrade refusal, mismatched job scope and actual isolated target/judge children
against owned HTTP fixtures. A separate test holds prompt/target/settings constant
and verifies distinct project namespaces produce separate fresh judgments and only
same-project cache hits. All credentials and data in these tests are synthetic.

The fifth authenticated Chromium workflow creates another project's target, runs a
real queued evaluation, signs in to its report, changes tokens, and verifies report
and target data are no longer accessible. Standard local workflows remain covered.
The Compose smoke validates migration and the existing full demo/restart/outage/
revocation/deletion paths. See the roadmap and PR for measured check results.
