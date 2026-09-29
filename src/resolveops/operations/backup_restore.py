"""Safety boundaries shared by the PostgreSQL backup and restore drill."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DrillTarget:
    """An explicitly disposable PostgreSQL target used by the restore drill."""

    container: str
    database: str
    user: str

    def validate(self) -> None:
        if "test" not in self.database.lower() and "drill" not in self.database.lower():
            raise ValueError(
                "refusing to recreate a database without 'test' or 'drill' in its name"
            )
        if not self.container.strip() or not self.user.strip():
            raise ValueError("container and user are required")
