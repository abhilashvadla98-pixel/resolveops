from argparse import ArgumentParser
from pathlib import Path

from resolveops.data_generation.generator import generate_dataset
from resolveops.data_generation.profiles import get_profile


def main() -> int:
    parser = ArgumentParser(description="Generate deterministic synthetic ResolveOps data.")
    parser.add_argument("--profile", choices=("demo", "small", "medium", "large"), default="demo")
    parser.add_argument("--output", type=Path, default=Path("generated-data"))
    parser.add_argument("--customer-cases", type=int)
    parser.add_argument("--it-requests", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--anomaly-rate", type=float)
    parser.add_argument("--version", default="1.0.0")
    args = parser.parse_args()
    profile = get_profile(args.profile).with_overrides(
        customer_cases=args.customer_cases,
        it_requests=args.it_requests,
        seed=args.seed,
        anomaly_rate=args.anomaly_rate,
    )
    manifest = generate_dataset(args.output, profile, version=args.version)
    print(f"Generated {manifest.total_records} records in {args.output}")
    print(f"Manifest: {args.output / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
