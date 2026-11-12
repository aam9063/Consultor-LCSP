#!/bin/sh
# Runs once, when the volume is first initialised.
#
# The integration suites truncate the corpus tables, so they need a database of
# their own: this creates `<main>_test` next to the working one so a test run
# can never destroy the ingested statute.
set -e

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -c "CREATE DATABASE \"${POSTGRES_DB}_test\" OWNER \"${POSTGRES_USER}\""
