<p align="center">
  <img src="assets/hero.svg" alt="catchme — an agent with a net chasing a race condition, an N+1 query, a lock wait and a p95 spike" width="100%">
</p>

<p align="center">
  <b>Load-test your app under production specs in local Docker — and let your coding agent find,<br>
  explain and fix the N+1s, races and missing indexes that only show up in production.</b>
</p>

<p align="center">
  <b>English</b> · <a href="README.ko.md">한국어</a> · <a href="README.ja.md">日本語</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/kmsdevdata-sketch/catchme/actions/workflows/e2e.yml"><img src="https://github.com/kmsdevdata-sketch/catchme/actions/workflows/e2e.yml/badge.svg" alt="e2e"></a>
  <img src="https://img.shields.io/badge/Claude_Code-plugin-E5794E" alt="Claude Code plugin">
  <img src="https://img.shields.io/badge/any_stack-HTTP_%2B_PostgreSQL-5C6BB0" alt="any stack on PostgreSQL">
  <img src="https://img.shields.io/badge/license-MIT-8E9BD6" alt="MIT">
</p>

---

**Without catchme:** tests pass on your laptop — 50 rows, no CPU limit, no network latency. In production,
`GET /orders` runs 80 queries per request, 100 simultaneous orders lose stock, and nobody knows until it's live.

**With catchme:** you say *"test this with production specs"*. Your agent rebuilds 0.5 vCPU, a `db.t3.micro`,
+1 ms per DB round trip and a million rows in local Docker, runs real load and races against your API, and comes
back with evidence, the code that causes it, a fix on a separate branch, and a before/after table.

<p align="center">
  <img src="resources/prisma/02-load-report.gif" alt="catchme load and report in a terminal" width="88%">
</p>

## Quick start

**Prerequisites:** Docker (Compose v2) running, Claude Code, an app that builds with a Dockerfile and uses PostgreSQL.

**1. Install** — in Claude Code:

```bash
/plugin marketplace add kmsdevdata-sketch/catchme
/plugin install catchme@catchme
```

**2. Open your project and say this to Claude:**

```text
test this with production specs
```

```text
Test the order list API with ECS 0.5 vCPU / 1 GB, RDS t3.micro and 1M orders,
and check whether 100 simultaneous orders break the stock count.
```

```text
How many concurrent users can this spec handle? Compare t3.micro and t3.small.
```

**3. Answer one question** (which production specs, if your repo has no Terraform / CDK / ECS / k8s files),
wait about 10 minutes, and read `.prod-parity/reports/latest.md`. Say *yes* when the agent offers to fix
what it found on a branch and re-measure.

New to it? The **[step-by-step guide](docs/getting-started.md)** walks through every step, what you'll be
asked, how to read the report, troubleshooting and FAQ.

## What it catches

| | Problem | How catchme sees it | Example evidence from a report |
|---|---|---|---|
| 🔀 | **Races** — lost updates, overselling | 100 simultaneous writes, then SQL invariants | `100 sold, stock 100000 → 99998` |
| 🔁 | **N+1 queries** | queries per request from `pg_stat_statements`, under 1 ms latency | `62.9 queries/request; one statement runs 41.9× per request` |
| 🐢 | **Missing indexes** | `EXPLAIN` of the heaviest statements on millions of rows | `Seq Scan on orders (1M rows), Filter user_id = $1` |
| 🚰 | **Pool exhaustion, connection churn** | connections every 0.25 s vs pool size, new sessions per request | `1.00 new sessions per request` |
| 🔒 | **Lock contention** | lock waits ≥ 100 ms from the PostgreSQL log, deadlocks | `18 lock waits of 100 ms or longer` |
| 📉 | **Capacity** | breaking-point search on your p95 / error-rate target | `This spec holds up to 13 concurrent requests` |

## How it works

<p align="center">
  <img src="assets/how-it-works.svg" alt="repo and specs → local Docker with k6, your app (0.5 vCPU), Toxiproxy (+1 ms), Postgres (db.t3.micro, 3M rows) → report → fix on a branch and re-measure" width="100%">
</p>

1. **Analyze** your project — stack, port, endpoints, login, Dockerfile.
2. **Profile** production from Terraform / CDK / ECS / k8s, a read-only AWS lookup, or presets.
3. **Build** it in Docker — CPU and memory limits, RDS-like Postgres, Toxiproxy latency, plus Redis / queues / mocks your app needs.
4. **Seed** millions of consistent rows and test users into your migrated schema.
5. **Load** with k6 through your real login API — warm-up, steady load, ramps, 100-at-once races.
6. **Report** findings with evidence, code locations and fixes — and what the numbers can't tell you.
7. **Fix & verify** on a git worktree branch with the same profile, data and scenarios.

Scripts keep the environment and the numbers reproducible; the agent does the judgment.

## Works with

Any language or framework that builds with a Dockerfile and talks HTTP, on PostgreSQL. Verified end to end on:

| Stack | Queries/request | Order list p95 | Races |
|---|---:|---:|---|
| [Node.js + Prisma](examples/demo-shop-prisma) | 61 → 3 | 1,677 → 110 ms | ❌ → ✅ |
| [NestJS + TypeORM](examples/demo-shop-nest-typeorm) | 63 → 2 | 1,232 → 111 ms | ❌ → ✅ |
| [Spring Boot + JPA](examples/demo-shop-spring) | 62 → 2 | 1,175 → 512 ms | ❌ → ✅ |
| [Django](examples/demo-shop-django) | 64 → 3 | 2,728 → 309 ms | ❌ → ✅ |
| [FastAPI + SQLAlchemy](examples/demo-shop-fastapi) | 62 → 2 | 2,050 → 497 ms | ❌ → ✅ |
| [Go net/http + pgx + Redis](examples/demo-shop-go) | 81 → 2 | 1,966 → 47 ms | ❌ → ✅ |

Before → after the agent's fix, ECS Fargate 0.5 vCPU / 1 GB, RDS `db.t3.micro`, 1 ms app↔DB, 1M orders.
The Go demo had no detector or reference — an agent set it up with only the skill. Details: [resources/](resources/README.md).

## Safety

- **Local Docker only.** It refuses when `.env`, app settings or the load target point at a non-local host.
- **Read-only AWS**, only with your consent; credentials are never printed.
- **Test accounts and test secrets only.**
- **Your branch is never touched** — fixes go to a new branch in a git worktree.

## Limitations

Results are a **production approximation**, not a reproduction: CPU generation, disk IOPS, burst-credit depletion,
cross-AZ variance and real data distributions aren't modeled, and every report says so. Expect run-to-run noise
(about ±3 on the breaking point; more on a JVM at 0.5 vCPU). PostgreSQL only for now — MySQL is planned.

## Docs

- [Getting started](docs/getting-started.md) — install, first run, reading the report, fix & verify, troubleshooting, FAQ
- [Skill](skills/catchme/SKILL.md) — what the agent reads · [Stack references](skills/catchme/references/) · [AGENTS.md](AGENTS.md) for other agents
- [Demos](examples/) and [recorded results](resources/README.md)

## Contributing

Issues and PRs are welcome — especially stack references (Rails, Laravel, .NET, Rust, …) and MySQL support.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
