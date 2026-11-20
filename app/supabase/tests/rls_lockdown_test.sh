#!/usr/bin/env bash
# Apply the lockdown migration to a throwaway local database and check it.
# This is the stand-in for `supabase start` when Docker is not available.
# It does not connect to the hosted Supabase project.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_NAME="${RLS_TEST_DB:-scribetok_rls}"

sudo -u postgres dropdb --if-exists "$DB_NAME"
sudo -u postgres createdb "$DB_NAME"

create_role() {
  local name="$1"
  local attrs="$2"
  if ! sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$name'" | grep -q 1; then
    sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "CREATE ROLE ${name} ${attrs}"
  fi
}

create_role anon "NOLOGIN NOINHERIT"
create_role authenticated "NOLOGIN NOINHERIT"
create_role service_role "NOLOGIN NOINHERIT BYPASSRLS"
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "GRANT anon, authenticated, service_role TO postgres"

sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/tests/rls_lockdown_fixture.sql"
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/migrations/20261120150000_lock_down_public_access.sql"
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/tests/rls_lockdown_assert.sql"
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/rollbacks/20261120150000_lock_down_public_access_rollback.sql"
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/tests/rls_lockdown_assert_rollback.sql"

echo "RLS lockdown migration and rollback passed on local database ${DB_NAME}."
