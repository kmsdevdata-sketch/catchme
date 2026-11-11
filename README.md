# catchme

**Catch me if you can — before production does.**

Your laptop has 50 rows, no CPU limit and zero network latency. Production has a million rows,
0.5 vCPU, a `db.t3.micro` and 1 ms per round trip. That's why N+1 queries, pool exhaustion,
lock contention and missing indexes show up only in production.

catchme is an agent skill pack (Claude Code plugin + `AGENTS.md`) that approximates your production
specs in local Docker, puts load on your API, and reports what breaks and why — with evidence.

> "Test the order list API with ECS 0.5 vCPU / 1 GB, RDS t3.micro, 1M orders"

1. **Analyze** the project (Spring + JPA, Node + Prisma, Django; PostgreSQL)
2. **Profile** production from Terraform / CDK / ECS task definitions / k8s manifests, a read-only AWS lookup, or presets
3. **Environment**: app + Postgres with `cpus` / `mem_limit`, RDS-like DB settings, Toxiproxy latency
4. **Seed** millions of FK-consistent rows, deterministically
5. **Load** with k6: steady load, ramps, and simultaneous writes for race reproduction
6. **Collect** p50/p95/p99, throughput, errors, queries/request, EXPLAIN plans, CPU/memory, connections, lock waits
7. **Report** local vs production, bottleneck candidates with evidence, fixes, limitations
8. **Fix & re-measure** on a separate branch with the same profile, seed and scenario → before/after table

Plus: "this spec holds up to N concurrent requests" (breaking-point search), authenticated APIs via
seeded test accounts and the real login API, and an opt-in hook that warns when a change increases
queries per request.

## Install

```bash
/plugin install catchme --marketplace <owner>/catchme
```

(or `/plugin marketplace add <owner>/catchme` then `/plugin install catchme@catchme`)

Then ask: **"운영 사양으로 테스트해줘"** / **"test this with production specs"**, or run `/catchme:catchme`.

Other agents: see [AGENTS.md](AGENTS.md). Requirements: Docker with Compose v2.
Python 3 and curl are used when present (Python falls back to a container).

## Try the demo

[`examples/demo-shop`](examples/demo-shop-prisma) has a planted N+1, a missing index and a stock race.

```bash
cd examples/demo-shop-prisma
CM=../../skills/catchme/scripts/catchme
$CM init
$CM profile --app-preset ecs-fargate:0.5vcpu-1gb --db-preset rds:db.t3.micro
$CM all && $CM breakpoint && $CM report
$CM teardown
```

## What it never does

- Connect to anything outside local Docker. It stops and asks if config points at a non-local DB.
- Call AWS write APIs. Spec lookup uses `describe-*` / `list-*` only, and never outputs credentials.
- Use production accounts or secrets.
- Touch your current branch. Fixes go to a git worktree branch.

Everything it generates lives in `.prod-parity/` in your project — readable and editable.

## Limitations

Results are approximations: CPU clock/generation, disk IOPS, RDS burst-credit depletion, cross-AZ
variance and real data distributions are not reproduced. Every report says so.

## License

MIT
