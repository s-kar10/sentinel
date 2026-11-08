# Project provider credentials and admission audit (P6-4)

Migration `0008_provider_credentials` adds a separately encrypted OpenAI credential
per project and non-secret lifecycle/admission records. Provisioning remains a
trusted local CLI operation, like operator-token provisioning. No new remote
credential-management endpoint or browser key editor is added.

Token-mode semantic evaluation now requires the target project's active credential.
An installation `OPENAI_API_KEY` cannot supply another project's access. The
unauthenticated local mode preserves the environment-key fallback **only for legacy
project 1, and only if no project credential row exists**. A revoked project
credential never falls back. Deterministic evaluations remain independent of
provider credentials. `JUDGE_ENABLED`, model allowlisting, provider endpoint,
timeouts and price settings remain installation policies.

## Provision and replace

Back up, stop API/workers and migrate to the current head using
[MIGRATIONS.md](MIGRATIONS.md). Revision 0008 creates empty tables: it does not copy
the environment key into every project, contact a provider or rewrite accepted
jobs. Review the project ID using `python -m app.auth.cli projects`.

From `backend`, prepare a private file containing the intended provider credential
using your local secret tooling. Keep it under `.secrets/`, out of Git, terminal
history, logs and shared artifacts. Use mode 0600 (and a private parent directory).
Then run:

```sh
../.venv/bin/python -m app.secrets.provider_cli put \
  --project-id 1 --input-file .secrets/openai-provider.txt
../.venv/bin/python -m app.secrets.provider_cli list --project-id 1
```

The CLI reads at most 4098 bytes, permits one trailing LF/CRLF, and validates a
1–4096-character printable ASCII credential without whitespace. Non-regular,
symlinked, overly permissive or oversized input files are rejected. There is no
secret-valued CLI argument, and command output/errors never contain the key.
The input file is not deleted automatically; remove or retain it according to
your local secret-handling policy after successful provisioning.

A second `put` replaces the current credential and increments its version.
Replacement takes effect for new submissions without an API restart. `list`
returns only ID, project, provider, version and an `active` flag. That flag means a
stored value exists, not that the provider has verified it. No live credential
validation or OpenAI calibration is performed.

### Compose

The CLI runs as the backend's non-root user with the configured database/keyring.
To copy a locally prepared private file into a new exclusive container file without
putting its contents in argv or stdout:

```sh
docker compose exec -T backend python -c \
  "import os,sys; fd=os.open('/tmp/provider-input', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600); f=os.fdopen(fd,'wb'); f.write(sys.stdin.buffer.read(4099)); f.close()" \
  < .secrets/openai-provider.txt
docker compose exec -T backend python -m app.secrets.provider_cli put \
  --project-id 1 --input-file /tmp/provider-input
```

After success, remove that temporary file with
`docker compose exec -T backend rm /tmp/provider-input`. Use a new path if it
already exists. Normal backend/worker keyring mounts remain read-only. The Compose
smoke exercises this path with synthetic keys only.

## Revocation and accepted work

```sh
../.venv/bin/python -m app.secrets.provider_cli revoke --project-id 1
```

Revocation clears the current stored secret and appends an audit event in the same
transaction. Repeating it is a no-op. It blocks **new semantic submissions** for
that project; it does not revoke a credential at OpenAI, clear old backups or cancel
accepted jobs. Re-provisioning increments the version and restores new admission.

Accepted jobs keep their encrypted credential snapshot and version. Replacing or
revoking the current row cannot silently change what a worker sends. An idempotent
retry of an accepted submission still returns that run after revocation. Cancel
queued work separately, and revoke the actual key at its provider when required.
Cancellation cannot undo requests already in flight. Pre-0008 jobs keep their old
snapshots and can finish; their dispatch records identify `legacy_snapshot`.

Provisioning, replacement, revocation and credential selection all lock the project
row. Submission also holds the existing queue coordinator lock, always before the
project lock. Therefore concurrent revoke/submit has one order: either submission
captures the earlier credential and commits before revocation, or revocation wins
and the submission is rejected. Audit and data commit together; audit failure
rolls back the corresponding change or new job.

## Audit meaning and limits

```sh
../.venv/bin/python -m app.secrets.provider_cli audit \
  --project-id 1 --after-id 0 --limit 100
```

Records are ordered by ID. Page with the last returned ID; `limit` accepts 1–1000.
Only the explicitly selected project's records are returned. The CLI is a trusted
host operation with database authority across projects, not a token-role API.

| Event | What it establishes |
| --- | --- |
| `created` / `replaced` | A project credential version was committed by `host_cli` |
| `revoked` | That project's current stored secret was cleared |
| `snapshotted` | An accepted evaluation captured the version; includes run ID and authenticated operator-token ID, or local/internal origin |
| `dispatched` | The worker admitted a case attempt using the frozen version; the actor is `worker` |

Dispatch can repeat on retry/recovery. It is admission evidence, not proof of a
successful external HTTP call or provider charge. Failed preflight requests,
arbitrary decryptions, every target-key read, keyring reads, direct SQL and host
file access are **not** audited by this increment. Local CLI events do not identify
a verified human. No client body/header can choose the recorded token ID.

Audit rows contain only numeric references, provider/source, event/origin and time;
no key, digest, token value, URL, request body or user-provided labels are included.
They survive target/run deletion and credential revocation. They are append-only
through these application paths, not cryptographically tamper-proof against a
trusted database/host operator. Retention/export policy and full request/secret
access auditing remain unfinished.

## Encryption, recovery and remaining boundaries

Provider secrets use the existing keyring with a distinct authenticated
`provider-api-key` purpose. Target ciphertext cannot be read as a provider key.
The existing `app.secrets.cli reencrypt` and `verify` commands now include this
third storage location. Pause API/workers **and credential-management writers**
during offline encryption-key rotation. See [SECRET_STORAGE.md](SECRET_STORAGE.md)
for backup and key-loss recovery. Metadata listing and revocation do not need to
decrypt the previous key, allowing local cleanup of an unreadable credential.

Revision 0008 refuses downgrade if either credentials or audit rows exist, including
revoked credentials; it will not silently discard audit history. Use a reviewed
backup with matching code and keys. Database/host operators remain trusted, all
projects still share an encryption keyring and worker pool, and field-purpose
binding does not prevent same-purpose substitution by a malicious DB writer.

Private credential IDs/version/source never appear in public judge policy or
reports. Version/source enter the private runtime cache key, so replacement causes
a new cache context. Existing project namespaces, pre-provider redaction, explicit
usage/cost uncertainty and cached-sample exclusions remain intact.

No new dependencies were added. Tests cover SQLite/PostgreSQL migration and
concurrency, cross-project/role denial, missing/revoked credentials, atomic audit,
private CLI files/output, raw stored ciphertext, key rotation, legacy snapshots,
worker ownership and real owned target/provider HTTP fixtures. The roadmap records
verification results. Human memberships, egress/resource policy, comprehensive
audit/retention and the full security review remain open. Public deployment remains
blocked, and live OpenAI calibration remains deferred.
