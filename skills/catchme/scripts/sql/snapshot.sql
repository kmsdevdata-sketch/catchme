-- catchme stats snapshot (app database, as role monitor). One JSON line.
SELECT json_build_object(
  't', extract(epoch FROM now()),
  'total_calls', (
    SELECT COALESCE(sum(calls), 0)
    FROM catchme.pg_stat_statements
    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND userid <> (SELECT oid FROM pg_roles WHERE rolname = 'monitor')
  ),
  'statements', (
    SELECT COALESCE(json_agg(s), '[]'::json) FROM (
      SELECT queryid::text AS queryid, left(query, 2000) AS query, calls, rows,
             round(total_exec_time::numeric, 3) AS total_ms,
             round(mean_exec_time::numeric, 3) AS mean_ms,
             round(max_exec_time::numeric, 3) AS max_ms,
             shared_blks_hit, shared_blks_read, temp_blks_written
      FROM catchme.pg_stat_statements
      WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        AND userid <> (SELECT oid FROM pg_roles WHERE rolname = 'monitor')
      ORDER BY total_exec_time DESC
      LIMIT 100
    ) s
  ),
  'db', (
    SELECT row_to_json(d) FROM (
      SELECT xact_commit, xact_rollback, deadlocks, blks_read, blks_hit, tup_returned,
             tup_fetched, temp_files, temp_bytes, conflicts, sessions
      FROM pg_stat_database WHERE datname = current_database()
    ) d
  ),
  'tables', (
    SELECT COALESCE(json_agg(t), '[]'::json) FROM (
      SELECT s.relname, s.seq_scan, s.seq_tup_read, COALESCE(s.idx_scan, 0) AS idx_scan,
             s.n_live_tup, c.reltuples::bigint AS reltuples
      FROM pg_stat_user_tables s JOIN pg_class c ON c.oid = s.relid
      WHERE s.schemaname = 'public'
    ) t
  ),
  'settings', (
    SELECT json_object_agg(name, setting) FROM pg_settings
    WHERE name IN ('max_connections', 'shared_buffers', 'work_mem', 'effective_cache_size')
  )
);
