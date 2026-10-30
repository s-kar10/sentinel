# Database migrations

Alembic 1.20.1 manages revisions from `0001_v01_baseline` through current head
`0004_history`. Migrations describe
the database structure at each version. They run explicitly before the API starts;
the API no longer creates tables. Existing target/run/result data is not migrated
automatically or deleted by adoption.

## Current revisions and upgrade

| Revision | Change |
| --- | --- |
| `0001_v01_baseline` | Frozen original four-table schema |
| `0002_engine_v2` | Nullable engine/provenance/outcome/evidence metadata |
| `0003_durable_jobs` | Job/coordinator tables, attempt counts; application adds CANCELLED status |
| `0004_history` | Version tags, private comparison fingerprint and named baseline references |

Back up first. Stop API and workers, build updated images, run the migration
service, then restart both with the same code. Native users stop both processes,
run `python -m app.database.migrations upgrade` in `backend`, then restart them.
Do not run mixed worker/API versions during this maintenance window. Existing
runs keep their original results and scores; new nullable columns stay null.
Old pending/running synchronous runs are not automatically turned into jobs.

Downgrading from 0004 removes baselines/version/comparison metadata. Downgrading
0003 removes jobs/attempt counts, including queued work and private payloads;
queued PENDING/RUNNING/CANCELLED runs become FAILED so older code can read them.
0002 downgrade removes V2 metadata. Original result columns remain. None of these
operations restores discarded metadata; use backups. Stop all writers before any
downgrade. A baseline downgrade drops all original data as documented below.

## The three concepts

- **Upgrade:** apply missing revisions in order. An empty database gets all seven application
  tables and their indexes/foreign keys, plus Alembic's revision-tracking table.
- **Adopt:** inspect an old, unversioned V0.1 schema and record that it already
  matches the baseline. This does not recreate its tables or rewrite its rows.
- **Startup check:** read the recorded revision and refuse to start unless it
  matches this code's migration head. This check does not alter the schema or
  perform a full drift audit on every API startup.

The frozen baseline lives in `backend/migrations/versions/0001_v01_baseline.py`.
It must never import current ORM models: otherwise changing a model later would
change what an old migration means. Future schema changes belong in new revisions.

## Fresh Docker setup

From the project root:

```sh
docker compose up --build --wait
docker compose ps -a
```

Compose waits for PostgreSQL, runs the one-shot `migrate` service, and starts the
API only if migration exits successfully. The frontend waits for the API. There
are five long-running services (including the worker); `migrate` should show **Exited (0)**.

If the database already contains unversioned tables, migration deliberately fails
with adoption instructions. Follow the next section. Do not delete your volume to
make the error disappear.

## Adopt an existing V0.1 PostgreSQL database

Use the same Compose project name and `.env` settings as the existing database.
Do not overwrite `.env`. Stop API and worker writers and make a backup before adoption.

### 1. Stop application writes and build the updated image

```sh
docker compose stop backend frontend worker
docker compose build backend migrate worker
docker compose up -d postgres
```

Also stop any other process writing to this database. Wait for PostgreSQL to be
healthy (`docker compose ps`). Adoption validation is not a substitute for a
maintenance window: its migration lock only coordinates Sentinel migration
commands, not arbitrary external DDL or application writes.

### 2. Back up the database

Run these commands in the same terminal so the backup filename variable persists:

```sh
umask 077
mkdir -p backups
sentinel_backup="backups/sentinel-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$sentinel_backup"
docker compose exec -T postgres pg_restore --list < "$sentinel_backup"
```

Require both commands to succeed before proceeding. A readable archive list is
only a basic check; a restore into a separate database is stronger verification.
Backups can contain plaintext target credentials and response evidence. Keep them
private; `backups/` is ignored by Git. Keep an independent safe copy for important
data. A Docker volume is persistence, not a backup.

### 3. Validate and adopt the baseline

```sh
docker compose run --rm --no-deps migrate python -m app.database.migrations adopt-v01
```

This checks the four tables against the frozen V0.1 definition: columns, types,
nullability, server defaults, indexes, foreign keys, primary keys, and unexpected
constraints/views. It also rejects partial/custom index options and missing
PostgreSQL SERIAL defaults. It stamps **the baseline revision**, not an arbitrary
latest revision, only after validation passes.

If validation fails, the command exits without stamping. Keep the backup and
investigate the mismatch. Do not bypass this with `alembic stamp head`.
The validator is scoped to ordinary V0.1 objects in the connection's default
schema. It is not a general audit of PostgreSQL roles, triggers, extensions,
additional schemas, or application-level validity of every stored value.

### 4. Upgrade and start

```sh
docker compose run --rm --no-deps migrate
docker compose up --build --wait
docker compose exec -T backend python -m app.database.migrations check
```

After this first adoption, normal `docker compose up --build --wait` applies any
future pending revisions through the migration service. Repeated upgrades at the
current head do nothing. Running `adopt-v01` on an already versioned database is
rejected; use `upgrade` instead.

The old `CREATE_DATABASE_TABLES` environment variable is no longer used. Leaving
it in a local `.env` cannot re-enable API startup table creation.

## Native development and SQLite

Install updated backend dependencies and run the commands from `backend` so the
default relative SQLite file and `.env` resolution stay consistent:

```sh
cd backend
../.venv/bin/python -m pip install --require-hashes -r requirements.txt
../.venv/bin/python -m app.database.migrations upgrade
../.venv/bin/python -m app.database.migrations current
```

For an existing unversioned SQLite database, stop the API and all writers, back it
up with SQLite's backup API, then run `adopt-v01` followed by `upgrade`. Do not
blindly copy a running SQLite file while it may have a WAL/journal. Example for
the default file, with a new backup destination:

```sh
../.venv/bin/python - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

backup_dir = Path('../backups')
backup_dir.mkdir(mode=0o700, exist_ok=True)
destination = backup_dir / ('sentinel-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.sqlite')
destination.touch(mode=0o600, exist_ok=False)
source = sqlite3.connect('file:sentinel.db?mode=ro', uri=True)
backup = sqlite3.connect(destination)
try:
    source.backup(backup)
finally:
    backup.close()
    source.close()
PY
../.venv/bin/python -m app.database.migrations adopt-v01
../.venv/bin/python -m app.database.migrations upgrade
```

If you configured another database path, use that exact path for backup and the
same settings for migration and API startup. PostgreSQL settings reuse the API's
safe URL construction, including passwords containing URL-reserved characters;
database URLs are not written into `alembic.ini`.

## Preserved V0.1 behavior

- All four tables and existing FK/status/category indexes are retained.
- IDs use PostgreSQL SERIAL/sequence behavior or SQLite integer primary keys.
- `evaluation_runs.status` is `VARCHAR(20)` with uppercase enum member names such
  as `COMPLETED`. It is not a native PostgreSQL enum and has no CHECK constraint.
  The API still returns lowercase values such as `completed` through the ORM.
- Counts, score, HTTP method, and status defaults are application-side defaults;
  the migration does not invent SQL server defaults for them.
- Creation timestamps have database defaults. Target update timestamps continue
  to use the existing SQLAlchemy update behavior.
- Cascade deletion and existing plaintext credential storage remain unchanged.

## Creating the next schema change

Change the models, then generate a candidate revision from a disposable database
already at head:

```sh
cd backend
../.venv/bin/alembic revision --autogenerate -m "describe the schema change"
```

Review the generated revision carefully; autogeneration is not a correctness
guarantee. Check data preservation, defaults, locking, supported databases, and
rollback implications. Add upgrade/adoption/data tests before applying it to a
database you care about. Run deployments through the explicit migration command,
with backups and a maintenance/compatibility plan.

PostgreSQL migration commands share an advisory transaction lock with a 30-second
lock timeout. SQLite commands use `BEGIN IMMEDIATE`. Both keep validation and
adoption/upgrade in one transaction; failures roll back the tested transactional
DDL. Future operations such as concurrent index creation may need different
transaction handling and must be designed explicitly.

## Recovery and downgrade limitations

The baseline downgrade drops all four tables and their data. It exists to test
reversibility of the structure on disposable databases, not to recover real data.
There is intentionally no convenience downgrade command in Sentinel's wrapper.

If adoption rejects a mismatch, no version was stamped: fix the diagnosed issue
or return to the previous application using the retained database/backup. If a
transactional upgrade fails, inspect the recorded revision and database before
retrying. Never assume every future database operation can be rolled back.

For data recovery, restore the archive into a **new, separate database** and
validate it before changing Sentinel's configuration. For example, on a dedicated
local recovery instance with a new database name:

```sh
docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" sentinel_restore'
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d sentinel_restore --exit-on-error' < "$sentinel_backup"
```

Do not use `--clean` against your working database. Confirm row counts and sample
reports in the restored database, apply adoption if its backup predates migrations,
then switch the application's database settings deliberately. Keep the original
volume/backup until recovery is confirmed. Restoring an old backup loses changes
made after that backup; a schema downgrade cannot recover those changes.

## Verification

Ordinary backend tests now create disposable SQLite databases through migrations.
Migration tests also run on PostgreSQL when configured:

```sh
cd backend
SENTINEL_TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/sentinel_migration_test' \
  ../.venv/bin/python -m pytest tests/test_migrations.py
```

Use a disposable database whose name ends in `_migration_test`. Each PostgreSQL
test creates a unique schema, then deletes only that schema. Without this variable,
PostgreSQL cases are explicitly skipped; SQLite checks still run. These tests cover
fresh upgrade, ORM/schema parity, populated adoption, repeated upgrades, drift
rejection, transactional rollback, startup gating, cascades, orphan prevention,
ID generation, enum storage, and destructive downgrade/re-upgrade on empty test data.

Design references: [Alembic's programmatic connection sharing](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands)
and [autogeneration limits](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).
