import pytest

from resolveops.operations.backup_restore import DrillTarget


def test_drill_refuses_an_unguarded_database_name() -> None:
    with pytest.raises(ValueError, match="test.*drill"):
        DrillTarget("postgres", "resolveops", "resolveops").validate()


@pytest.mark.parametrize("database", ["resolveops_test", "resolveops_drill"])
def test_drill_allows_explicit_disposable_database_names(database: str) -> None:
    DrillTarget("postgres-test", database, "resolveops").validate()
