-- catchme connection sample (postgres database, as role monitor). One JSON line.
SELECT json_build_object(
  't', extract(epoch FROM now()),
  'total', count(*),
  'active', count(*) FILTER (WHERE state = 'active'),
  'idle', count(*) FILTER (WHERE state = 'idle'),
  'idle_in_tx', count(*) FILTER (WHERE state LIKE 'idle in transaction%'),
  'lock_wait', count(*) FILTER (WHERE wait_event_type = 'Lock'),
  'max_connections', current_setting('max_connections')::int
)
FROM pg_stat_activity
WHERE datname = 'app' AND usename <> 'monitor' AND backend_type = 'client backend';
