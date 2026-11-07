# Encrypted credential storage (P6-3)

Target API keys and complete private evaluation-job payloads are encrypted at rest
starting at migration `0007_encrypted_credentials`. This includes frozen provider
keys and canaries copied into pending work. API shapes, target key replacement/
clearing, project ownership checks, lease fencing and terminal payload deletion
remain unchanged. Phase 6 is still unfinished; public hosting remains prohibited.

## Why the storage boundary matters

Hiding a key in an API response does not protect a database dump. Encrypting only
the target table also leaves the same key in accepted background work. SQLAlchemy
types now encrypt on every ORM/Core bind and decrypt on retrieval. The private job
JSON column contains only an encrypted envelope while active. Ordinary SQL, dumps
and backups of the new stored fields contain ciphertext. Raw SQL bypasses these
types and is reserved for reviewed migrations/maintenance; runtime reads reject
plaintext rather than silently accepting it.

The envelope uses AES-256-GCM from the pinned `cryptography` package, random
96-bit nonces, a version and key ID, and authenticated field-purpose metadata.
Ciphertext modification, a wrong key or use in the other encrypted field fails
closed. The cryptographic construction follows the
[cryptography AESGCM API](https://cryptography.io/en/50.0.1/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM).
This is one installation keyring, not per-project cryptographic isolation. Envelope
metadata is bound to field purpose, not row identity: a malicious database writer
can substitute whole same-purpose records. Database/host operators remain trusted;
existing project predicates and frozen job ownership checks protect API access.

The keyring is a bounded JSON file with an active key ID and up to 32 retained
256-bit keys. Reads reject non-regular files, final-component symlinks, oversized
files, malformed keys and group/world permissions. Keep its parent directory
private too. New files use exclusive creation with mode 0600; keys are never
accepted as command arguments or printed. The API/worker require a usable keyring
at startup. Readiness checks the keyring's validity, not every stored ciphertext;
`verify` performs that deeper check. Runtime failures return a generic 503 and
workers retry without emitting secret-bearing exception text.

## Native setup and upgrade

Install locked dependencies first. From `backend`, for a **new keyring only**:

```sh
mkdir -m 700 -p .secrets
../.venv/bin/python -m app.secrets.cli init --output .secrets/keyring.json
```

The default is `.secrets/keyring.json`, relative to the backend working directory.
Set `SECRET_KEYRING_FILE` in the environment or backend `.env` to use a different
path; use the same path for API, migrations, worker and maintenance commands.
Initialization refuses to overwrite an existing file. Never regenerate a missing
keyring to repair an existing encrypted database: restore the correct backup.

For existing data, stop API and workers, back up the database and keyring securely,
then run the [normal migration upgrade](MIGRATIONS.md). Revision 0007 encrypts every
non-null target key and private job payload in the migration transaction. Missing
keys abort without advancing the revision or partially changing records. Pending
job contents, IDs, deadlines, results and baseline references survive. No automatic
API startup migration exists. Downgrade refuses non-null target keys or active
payloads rather than restoring plaintext; use a reviewed pre-upgrade backup with
matching older code for rollback. Restore tests must include the matching keyring.

## Compose setup

For a fresh installation, before the usual `up` command:

```sh
docker compose run --rm --build --no-deps key-init
docker compose up --build --wait
```

For an existing installation, stop API/workers and back up first, then initialize
once before upgrading to 0007. The explicit `key-init` tool writes into the
`secret_keys` named volume as the non-root application user. API, migration and
worker services mount that volume read-only; PostgreSQL, frontend and demo do not
mount it. Recreating containers preserves both database and key volumes.
`docker compose down --volumes` destroys **both**. Back up the key volume separately
with restricted access; never put its contents into logs, Git or a shared artifact.
The smoke harness creates its own key volume and removes only its own resources.

## Encryption-key rotation

Stop API/workers and take protected backups. From `backend`:

```sh
../.venv/bin/python -m app.secrets.cli add-key \
  --source .secrets/keyring.json --output .secrets/keyring-next.json
SECRET_KEYRING_FILE=.secrets/keyring-next.json ../.venv/bin/python -m app.secrets.cli reencrypt
SECRET_KEYRING_FILE=.secrets/keyring-next.json ../.venv/bin/python -m app.secrets.cli verify
```

`add-key` preserves old keys and creates a new active key in a new private file.
`reencrypt` reads with retained keys and writes with the active key in one database
transaction. It locks the relevant tables (SQLite write transaction/PostgreSQL
exclusive table locks); any bad ciphertext rolls the entire operation back.
Output contains operation and record counts only. Switch **all** processes to the
new file before restarting. Keep the old backup: old database backups still need
old keys. Verify a restored copy with a keyring containing only the new key before
retiring the old key from live configuration; retain backup keys for as long as
matching backups must remain recoverable. There is no automatic key deletion.

For Compose, stop API/workers and back up first. The explicitly invoked maintenance
tool alone mounts the key volume writable:

```sh
docker compose stop backend worker
docker compose run --rm --build --no-deps key-maintenance add-key \
  --source /run/sentinel-secrets/keyring.json --output /run/sentinel-secrets/keyring-next.json
export SECRET_KEYRING_FILE=/run/sentinel-secrets/keyring-next.json
docker compose run --rm --no-deps key-maintenance reencrypt
docker compose run --rm --no-deps key-maintenance verify
docker compose up --build --wait
```

Persist that **path only** in root `.env` before later restarts; preserve existing
settings. Subsequent rotations need fresh output filenames and the current source
file. Do not edit a live keyring or make normal service mounts writable. Managed
KMS/secret-manager integration and online rotation are future work.

## Credential rotation is a different operation

Replacing or clearing a target's write-only `api_key` through the existing admin
API affects **new submissions**. Already accepted jobs retain their encrypted
frozen key. Cancel accepted jobs separately and revoke the actual credential at
the target/provider to stop future use; cancellation cannot undo in-flight effects.
Changing `OPENAI_API_KEY` and restarting API/workers similarly affects future
semantic jobs. The provider key remains an installation-level environment secret;
this change encrypts its database copies, not the environment or `.env` file.
No live OpenAI calibration was performed.

## Remaining limits

Decrypted values exist in trusted API/worker memory and private subprocess pipes
when needed. Both API and worker can decrypt all projects' data; a compromised
host/process with key access is outside this protection. Keys are not sent to
case/provider children, only the credentials their work needs. No secret-manager
service, per-project provider provisioning, full credential-access audit, human
membership system, evidence-retention policy or egress/abuse gate is implemented.

Only the dedicated target key column and private job payload are encrypted here.
Canary rows, request templates, endpoint URLs, historical report evidence and other
columns can still contain sensitive information. Do not put credentials in those
fields. Redaction is exact-match and incomplete for encoded/unknown secrets.
Migration cannot erase old plaintext from backups, WAL, SQLite free pages, snapshots
or storage media. Keep old backups restricted and retire them under a reviewed
retention plan; do not claim secure erasure from an SQL update.

Tests use synthetic keys and owned HTTP fixtures, covering raw stored values,
frozen target/provider snapshots, cancellation cleanup, tampering, wrong purpose,
unsafe key files, exclusive CLI output, missing-key API/readiness failures,
transactional rotation/rollback and legacy migration on SQLite and PostgreSQL.
Existing project/worker/provider tests exercise the encrypted path too. See the
roadmap for the actual verification results.
