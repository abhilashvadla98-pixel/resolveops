import argparse
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class DrillTarget:
    container: str
    database: str
    user: str

    def validate(self) -> None:
        if "test" not in self.database.lower() and "drill" not in self.database.lower():
            raise ValueError("refusing to recreate a database without 'test' or 'drill' in its name")
        if not self.container.strip() or not self.user.strip():
            raise ValueError("container and user are required")


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
        if restored_title != original_title or restored_case_count != "1":
            raise RuntimeError("restored database did not match the known pre-backup state")
        print("Backup/restore drill passed: scenario A and CASE-1001 were restored.")
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
