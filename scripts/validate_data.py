from argparse import ArgumentParser
from pathlib import Path

from resolveops.data_generation.validation import validate_dataset, write_quality_report


def main() -> int:
    parser = ArgumentParser(description="Validate a generated ResolveOps dataset.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate_dataset(args.dataset)
    target = args.report or args.dataset / "quality-report.json"
    write_quality_report(report, target)
    print(f"Checked {report.records_checked} records with {len(report.checks_run)} checks")
    print(f"Failures: {len(report.failures)}")
    for failure in report.failures[:25]:
        print(f"{failure.check}: {failure.entity}/{failure.record_id}: {failure.message}")
    print(f"Report: {target}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
