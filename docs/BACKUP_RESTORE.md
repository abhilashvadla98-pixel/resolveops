# PostgreSQL backup and restore drill

The drill proves that a logical PostgreSQL backup can restore known ResolveOps records. It does not
prove a recovery-time objective, point-in-time recovery, cross-region durability, or production
disaster-recovery readiness.

## Safety boundary

The script is destructive: it drops and recreates its target database. It therefore refuses any
database name that does not contain `test` or `drill`. Use a dedicated temporary PostgreSQL container
or an isolated disposable database. Never target a development, demo, staging, or production
database.

## Reproduce

Start a disposable PostgreSQL 16 container, migrate and seed its `resolveops_drill` database, then
run:

```powershell
.\.venv\Scripts\python.exe scripts\backup_restore_drill.py `
  --container resolveops-backup-restore-test `
  --database resolveops_drill `
  --user resolveops
```

The script performs this sequence using PostgreSQL's own `pg_dump`, `dropdb`, `createdb`, and
`pg_restore` tools inside the container:

1. read the original title of demo scenario A;
2. create a custom-format logical backup;
3. replace the title with a known mutation and verify it was committed;
4. drop and recreate only the guarded drill database;
5. restore the backup;
6. verify the original scenario title and `CASE-1001` are present; and
7. remove the temporary dump from the container.

## Recorded result

On 2026-09-29 the drill passed against a fresh `postgres:16-alpine` container and the Alembic head
`0010_demo_scenarios`. The pre-backup scenario A title and `CASE-1001` were restored after the known
mutation and full database recreation. The temporary database container was then removed. This is
one local logical-restore observation, not a production recovery guarantee.
