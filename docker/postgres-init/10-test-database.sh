#!/bin/sh
# Runs once, when the volume is first initialised.
#
# The integration suites truncate the corpus tables, so they need a database of
# their own: this creates `<main>_test` next to the working one so a test run
# can never destroy the ingested statute.
set -e

TEST_DB="${POSTGRES_DB}_test"

# Postgres has no CREATE DATABASE IF NOT EXISTS, and this script runs with
# set -e: an already existing database (reused volume, manual re-run) must be
# skipped, not abort the whole initialisation.
if ! psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -tAc "SELECT 1 FROM pg_database WHERE datname = '$TEST_DB'" | grep -q 1
then
  psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -c "CREATE DATABASE \"$TEST_DB\" OWNER \"$POSTGRES_USER\""
fi
