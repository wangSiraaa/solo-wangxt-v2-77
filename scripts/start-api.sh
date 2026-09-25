#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres@127.0.0.1:5432/leakguard}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
