from argparse import ArgumentParser
from pathlib import Path

from sqlalchemy import create_engine

from resolveops.observability.scale_benchmark import run_scale_benchmark, save_scale_report


def main() -> int:
    parser = ArgumentParser(description="Run an isolated PostgreSQL scale benchmark.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--sizes", default="100,1000,10000")
    parser.add_argument("--it-ratio", type=float, default=0.25)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/scale-latest.json"))
    args = parser.parse_args()
    sizes = [int(value.strip()) for value in args.sizes.split(",") if value.strip()]
    engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        report = run_scale_benchmark(
            engine,
            customer_case_sizes=sizes,
            it_ratio=args.it_ratio,
            samples=args.samples,
            seed=args.seed,
            repository_root=Path.cwd(),
        )
    finally:
        engine.dispose()
    save_scale_report(report, args.output)
    print(f"Recorded {len(report['results'])} measured scale points in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
