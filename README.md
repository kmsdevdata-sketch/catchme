<p align="center">
  <img src="assets/hero.svg" alt="catchme — an agent with a net chasing a race condition, an N+1 query, a lock wait and a p95 spike" width="100%">
</p>

<p align="center">
  <b>Production-parity load &amp; race testing, run by your coding agent.</b><br>
  Your laptop has 50 rows, no CPU limit and zero latency. Production doesn't.
</p>

<p align="center">
  <a href="https://github.com/kmsdevdata-sketch/catchme/actions/workflows/e2e.yml"><img src="https://github.com/kmsdevdata-sketch/catchme/actions/workflows/e2e.yml/badge.svg" alt="e2e"></a>
  <img src="https://img.shields.io/badge/Claude_Code-plugin-E5794E" alt="Claude Code plugin">
  <img src="https://img.shields.io/badge/any_stack-HTTP_%2B_PostgreSQL-5C6BB0" alt="any stack on PostgreSQL">
  <img src="https://img.shields.io/badge/needs-Docker-2496ED" alt="needs Docker">
  <img src="https://img.shields.io/badge/license-MIT-8E9BD6" alt="MIT">
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#what-it-catches">What it catches</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#demos">Demos</a> ·
  <a href="#safety">Safety</a> ·
  <a href="#limitations">Limitations</a>
</p>

---

N+1 queries, exhausted connection pools, lock contention, missing indexes and races all hide on a
laptop and show up in production. **catchme** is a skill for coding agents that rebuilds your production
specs in local Docker — 0.5 vCPU, a `db.t3.micro`, a millisecond per DB round trip, a million rows — puts
real load on your API, tells you what broke and why with evidence, then fixes it on a branch and
measures again.

> **You:** test this with production specs
>
> **Agent:** No IaC found — which specs? *(Fargate 0.5 vCPU / 1 GB + RDS t3.micro)* … 100 orders went
> through but stock dropped by 10; a product with stock 10 sold 95. `GET /orders` runs 80 queries per
> request and scans 500k rows — no index on `orders.user_id`. Fix them on a branch and re-measure?

<p align="center">
  <img src="resources/prisma/02-load-report.gif" alt="catchme load and report in a terminal" width="88%">
</p>

## What it catches

| | Problem | How catchme sees it | Evidence in the report |
|---|---|---|---|
| 🔀 | **Races** — lost updates, overselling | 100 simultaneous writes, then SQL invariants you define | `100 sold, stock 100000 → 99998` |
| 🔁 | **N+1 queries** | `pg_stat_statements` per request, under 1 ms of injected latency | `62.9 queries/request; one statement runs 41.9× per request` |
| 🐢 | **Missing indexes** | `EXPLAIN` of the heaviest statements against millions of seeded rows | `Seq Scan on orders (1M rows), Filter user_id = $1` |
| 🚰 | **Pool exhaustion · connection churn** | connections sampled every 0.25 s vs pool size, new DB sessions per request | `1.00 new sessions per request` (Django default) |
| 🔒 | **Lock contention** | lock waits ≥ 100 ms from the PostgreSQL log, deadlocks | `18 lock waits of 100 ms or longer` |
| 📉 | **Capacity** | breaking-point search on your target | `This spec holds up to 13 concurrent requests` |

## How it works

<p align="center">
  <img src="assets/how-it-works.svg" alt="repo and specs → local Docker with k6, your app (0.5 vCPU), Toxiproxy (+1 ms), Postgres (db.t3.micro, 3M rows) → report → fix on a branch and re-measure" width="100%">
</p>

1. **Analyze** the project — stack, port, endpoints, auth, Dockerfile. Anything with a Dockerfile that speaks HTTP works.
2. **Profile** production from Terraform / CDK / ECS task definitions / k8s manifests, a read-only AWS lookup, or presets.
3. **Build** the environment: CPU and memory limits, RDS-like Postgres settings, Toxiproxy latency, plus whatever else
   your app needs (Redis, queues, mocks) through `compose.override.yml`.
4. **Seed** millions of FK-consistent rows from your migrated schema, deterministically.
5. **Load** with k6 — warm-up, steady load, ramps, and 100-at-once races — logged in through your real login API.
6. **Report** findings with evidence, the code that causes them, stack-specific fixes, and what the numbers can't tell you.
7. **Fix & verify** in a git worktree branch with the same profile, seed and scenarios → before/after table.

The scripts make the environment and the numbers reproducible; the agent does the judgment — what to test,
how much data, what an invariant is, what the numbers mean and what to change.

## Install

```bash
/plugin install catchme --marketplace kmsdevdata-sketch/catchme
```

Then just ask: **"test this with production specs"** — or **"운영 사양으로 테스트해줘"**, or run `/catchme:catchme`.

Needs Docker with Compose v2 (macOS, Linux; Windows via WSL). Python 3 and curl are used when present —
without Python the scripts run in a container. Other agents: see [AGENTS.md](AGENTS.md).

## Demos

Six demo shops with the same planted bugs. Every one was taken from "bugs in" to "fixed and re-measured"
by catchme; the Go one was set up from scratch by an agent that had only the skill.

| Stack | Queries/request | Order list p95 | Races (lost update / oversell) |
|---|---:|---:|---|
| [Node.js + Prisma](examples/demo-shop-prisma) | 61 → 3 | 1,677 → 110 ms | ❌❌ → ✅✅ |
| [NestJS + TypeORM](examples/demo-shop-nest-typeorm) | 63 → 2 | 1,232 → 111 ms | ❌❌ → ✅✅ |
| [Spring Boot + JPA](examples/demo-shop-spring) | 62 → 2 | 1,175 → 512 ms | ❌❌ → ✅✅ |
| [Django](examples/demo-shop-django) | 64 → 3 | 2,728 → 309 ms | ❌❌ → ✅✅ |
| [FastAPI + SQLAlchemy](examples/demo-shop-fastapi) | 62 → 2 | 2,050 → 497 ms | ❌❌ → ✅✅ |
| [Go net/http + pgx + Redis](examples/demo-shop-go) | 81 → 2 | 1,966 → 47 ms | ❌❌ → ✅✅ |

ECS Fargate 0.5 vCPU / 1 GB, RDS `db.t3.micro`, 1 ms app↔DB, 1M orders. GIFs, screenshots and raw reports
for each: [resources/](resources/README.md).

```bash
cd examples/demo-shop-prisma
CM=../../skills/catchme/scripts/catchme
$CM init
$CM profile --app-preset ecs-fargate:0.5vcpu-1gb --db-preset rds:db.t3.micro
$CM all          # gen → up → seed (1M orders) → load → report, ~5 min
$CM teardown
```

## Safety

- **Local Docker only.** It refuses when `.env`, app settings or the load target point at a non-local host,
  and won't bake an `.env` with real endpoints into the test image.
- **Read-only AWS.** Spec lookup uses `describe-*` / `list-*` only and never prints credentials.
- **Test accounts and test secrets only.**
- **Your branch stays untouched.** Fixes go to a git worktree branch you review.

Everything it generates lives in `.prod-parity/` in your project — readable and editable.

## Limitations

Results are a **production approximation**, not a reproduction. CPU generation, disk IOPS, RDS burst-credit
depletion, cross-AZ variance and real data distributions aren't modeled, and every report says so. Run-to-run
noise is real — the breaking point moves by about ±3 concurrent requests between identical runs, and a JVM at
0.5 vCPU swings more — so trust differences that repeat. PostgreSQL only for now (MySQL is planned).

## License

MIT
