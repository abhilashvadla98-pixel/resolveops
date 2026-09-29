from pathlib import Path

from resolveops.security.repository import publication_files, scan_file

ROOT = Path(__file__).resolve().parents[1]


def test_publication_files_exclude_local_environment() -> None:
    relative_paths = {path.relative_to(ROOT).as_posix() for path in publication_files(ROOT)}

    assert ".env" not in relative_paths
    assert ".env.example" in relative_paths


def test_credential_patterns_detect_secret_without_returning_value(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("token=AQ." + "A" * 36 + "\n", encoding="utf-8")

    assert scan_file(candidate) == [("Google generated key", 1)]
