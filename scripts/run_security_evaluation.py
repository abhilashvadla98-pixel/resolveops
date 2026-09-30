from argparse import ArgumentParser
from pathlib import Path

from resolveops.evaluation.security import (
    evaluate_adversarial_security,
    load_adversarial_cases,
    save_security_report,
)


def main() -> int:
    parser = ArgumentParser(description="Run the offline adversarial-input security gate.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/security/adversarial.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/security/adversarial-report.json"),
    )
    arguments = parser.parse_args()
    report = evaluate_adversarial_security(
        arguments.dataset, load_adversarial_cases(arguments.dataset)
    )
    save_security_report(report, arguments.output)
    print(
        f"Adversarial security: {report.passed_count}/{report.case_count} passed; "
        f"report={arguments.output}"
    )
    return 0 if report.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
