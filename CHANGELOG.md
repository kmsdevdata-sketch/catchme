# Changelog

## 0.1.0 — 2026-11-12

First public release.

### What it does

- Rebuilds production specs in local Docker: CPU/memory limits from ECS / k8s / Terraform / CDK or presets,
  Postgres configured like the RDS class, Toxiproxy latency between the app and the DB, millions of seeded rows.
- Logs in test users through your real login API, then runs k6 warm-up, steady load, ramps and 100-at-once races.
- Reports N+1 queries, missing indexes, connection-pool exhaustion and connection churn, lock waits, races
  (judged with SQL invariants on the data) and the breaking point for a p95 / error-rate target.
- Fixes on a new git worktree branch and re-measures with the same profile, data and scenarios
  (`verify`, before/after table).
- Extras: local-vs-production comparison, two-profile comparison, CPU-credit depletion, a ~20 s
  queries-per-request regression check after edits, extra services (Redis, queues, mocks) via
  `compose.override.yml`.

### Stacks

Any containerizable HTTP app on PostgreSQL. Verified end to end on Node.js + Prisma, NestJS + TypeORM,
Spring Boot + JPA, Django, FastAPI + SQLAlchemy, and Go + pgx + Redis (no stack-specific code).

### Safety

Local Docker only — refuses non-local hosts in app settings, `.env` and load targets. Read-only AWS with
consent. Never changes your current branch.

### Known limitations

PostgreSQL only. Results approximate production (no CPU generation, disk IOPS, burst-credit depletion or real
data distributions) and vary between runs, more so on a JVM at 0.5 vCPU.
