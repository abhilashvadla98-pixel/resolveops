import argparse
import subprocess

from resolveops.operations.backup_restore import DrillTarget


def docker_exec(target: DrillTarget, *command: str) -> str:
    completed = subprocess.run(
        ["docker", "exec", target.container, *command],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def sql(target: DrillTarget, statement: str) -> str:
    return docker_exec(
        target,
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        target.user,
        "-d",
        target.database,
        "-Atc",
        statement,
    )


def run_drill(target: DrillTarget) -> None:
    target.validate()
    dump_path = "/tmp/resolveops-backup-restore-drill.dump"
    original_title = sql(
        target,
        "SELECT title FROM demo_scenarios WHERE scenario_id = 'A';",
    )
    if not original_title:
        raise RuntimeError("scenario A is missing; migrate and seed the drill database first")
    original_revision = sql(target, "SELECT version_num FROM alembic_version;")
    durable_tables = (
        "agent_runs",
        "agent_tool_calls",
        "reviewed_resolution_memory",
        "agent_workflow_jobs",
        "agent_job_events",
    )
    table_query = " UNION ALL ".join(
        f"SELECT to_regclass('public.{table}') IS NOT NULL" for table in durable_tables
    )
    if sql(target, table_query).splitlines() != ["t"] * len(durable_tables):
        raise RuntimeError("agent durability tables are missing before backup")
    try:
        docker_exec(
            target,
            "pg_dump",
            "-U",
            target.user,
            "-d",
            target.database,
            "--format=custom",
            f"--file={dump_path}",
        )
        sql(
            target,
            "UPDATE demo_scenarios SET title = 'BACKUP DRILL MUTATION' WHERE scenario_id = 'A';",
        )
        if sql(target, "SELECT title FROM demo_scenarios WHERE scenario_id = 'A';") != (
            "BACKUP DRILL MUTATION"
        ):
            raise RuntimeError("drill mutation was not persisted")

        docker_exec(
            target,
            "dropdb",
            "-U",
            target.user,
            "--force",
            target.database,
        )
        docker_exec(target, "createdb", "-U", target.user, target.database)
        docker_exec(
            target,
            "pg_restore",
            "-U",
            target.user,
            "-d",
            target.database,
            "--exit-on-error",
            dump_path,
        )

        restored_title = sql(
            target,
            "SELECT title FROM demo_scenarios WHERE scenario_id = 'A';",
        )
        restored_case_count = sql(
            target,
            "SELECT count(*) FROM cases WHERE case_id = 'CASE-1001';",
        )
        restored_revision = sql(target, "SELECT version_num FROM alembic_version;")
        restored_tables = sql(target, table_query).splitlines()
        if (
            restored_title != original_title
            or restored_case_count != "1"
            or restored_revision != original_revision
            or restored_tables != ["t"] * len(durable_tables)
        ):
            raise RuntimeError("restored database did not match the known pre-backup state")
        print(
            "Backup/restore drill passed: business records, migration revision, and agent "
            "durability tables were restored."
        )
    finally:
        docker_exec(target, "rm", "-f", dump_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Destructive backup/restore drill for an isolated ResolveOps test database"
    )
    parser.add_argument("--container", required=True, help="PostgreSQL Docker container name")
    parser.add_argument("--database", required=True, help="Database name containing test or drill")
    parser.add_argument("--user", default="resolveops", help="PostgreSQL role inside the container")
    arguments = parser.parse_args()
    run_drill(DrillTarget(arguments.container, arguments.database, arguments.user))


if __name__ == "__main__":
    main()
