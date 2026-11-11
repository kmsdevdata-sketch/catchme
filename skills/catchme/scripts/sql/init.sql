-- catchme DB init (runs once on a fresh volume, inside the `app` database).
-- Everything catchme owns lives in schema `catchme` so ORMs managing `public` never see it.
CREATE ROLE monitor WITH LOGIN SUPERUSER PASSWORD 'monitor';
CREATE SCHEMA IF NOT EXISTS catchme;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements SCHEMA catchme;

CREATE TABLE IF NOT EXISTS catchme.snapshot (
  name text PRIMARY KEY,
  value jsonb,
  taken_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS catchme.meta (
  key text PRIMARY KEY,
  value text
);

-- EXPLAIN (GENERIC_PLAN) for the heaviest statements of the app (PostgreSQL 16+).
-- Nothing is executed: plain EXPLAIN without ANALYZE.
CREATE OR REPLACE FUNCTION catchme.explain_top(n int) RETURNS json
LANGUAGE plpgsql AS $$
DECLARE
  r record;
  p json;
  result json[] := '{}';
BEGIN
  FOR r IN
    SELECT queryid, query, calls, mean_exec_time, total_exec_time
    FROM catchme.pg_stat_statements
    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND userid <> (SELECT oid FROM pg_roles WHERE rolname = 'monitor')
      AND query ~* '^\s*(select|with|update|delete)\s'
    ORDER BY total_exec_time DESC
    LIMIT n
  LOOP
    BEGIN
      EXECUTE 'EXPLAIN (GENERIC_PLAN, FORMAT JSON) ' || r.query INTO p;
      result := result || json_build_object('queryid', r.queryid::text, 'query', left(r.query, 2000),
                                            'calls', r.calls, 'mean_ms', r.mean_exec_time, 'plan', p);
    EXCEPTION WHEN OTHERS THEN
      result := result || json_build_object('queryid', r.queryid::text, 'query', left(r.query, 2000),
                                            'calls', r.calls, 'mean_ms', r.mean_exec_time, 'error', SQLERRM);
    END;
  END LOOP;
  RETURN COALESCE(array_to_json(result), '[]'::json);
END
$$;
