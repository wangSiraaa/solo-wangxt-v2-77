#!/usr/bin/env bash
# Start the embedded PostgreSQL 17 cluster used in this sandbox (no root needed).
# For a normal deployment, point DATABASE_URL at any PostgreSQL >= 13 instead.
set -euo pipefail

PGHOME="${PGHOME:-$HOME/pgsql}"
PGDATA="${PGDATA:-$HOME/pgdata}"
PGSOCK="${PGSOCK:-/tmp/pgsock}"
export LD_LIBRARY_PATH="$PGHOME/lib:${LD_LIBRARY_PATH:-}"

if [ ! -x "$PGHOME/bin/postgres" ]; then
  echo "PostgreSQL binaries not found at $PGHOME" >&2
  exit 1
fi

if [ ! -d "$PGDATA/base" ]; then
  "$PGHOME/bin/initdb" -D "$PGDATA" -U postgres --auth=trust --no-locale --encoding=UTF8
fi

if ! "$PGHOME/bin/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
  mkdir -p "$PGSOCK"
  "$PGHOME/bin/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" start \
    -o "-p 5432 -k $PGSOCK -c listen_addresses='127.0.0.1' -c unix_socket_directories='$PGSOCK'"
fi

python3 - <<'PY'
import time, psycopg2
for _ in range(30):
    try:
        c = psycopg2.connect(host="/tmp/pgsock", user="postgres", dbname="postgres")
        cur = c.cursor(); cur.autocommit = True
        cur.execute("SELECT 1 FROM pg_database WHERE datname='leakguard'")
        if not cur.fetchone():
            cur.execute("CREATE DATABASE leakguard")
        print("PostgreSQL ready, database leakguard present")
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("database did not become ready")
PY
