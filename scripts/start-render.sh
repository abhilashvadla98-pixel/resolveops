#!/bin/sh
set -eu

alembic upgrade head
python -m resolveops.database.seed
exec uvicorn resolveops.api.main:app --host 0.0.0.0 --port "${PORT:-10000}"
