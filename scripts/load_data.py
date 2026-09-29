from argparse import ArgumentParser
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from resolveops.config import Settings
from resolveops.data_generation.loader import load_dataset


def main() -> int:
    parser = ArgumentParser(description="Validate and load synthetic ResolveOps data.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--database-url", help="Target database; defaults to ResolveOps settings")
    parser.add_argument("--batch-size", type=int, default=1_000)
    args = parser.parse_args()
    database_url = args.database_url or Settings().resolved_database_url()
    engine = create_engine(database_url)
    with Session(engine) as session:
        loaded = load_dataset(session, args.dataset, batch_size=args.batch_size)
    for entity, count in loaded.items():
        print(f"{entity}: {count}")
    print(f"Loaded {sum(loaded.values())} validated records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
