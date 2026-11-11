# catchme report — after · 2026-11-11T13:38:24+00:00

Breaking point not measured (run `catchme breakpoint`).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🟡 medium app CPU pinned at its limit on `orders-list`: avg 97% / max 101% of 0.5 vCPU
- 🟡 medium app CPU pinned at its limit on `product-detail`: avg 102% / max 106% of 0.5 vCPU
- 🟡 medium Lock contention on `order-race`: up to 4 sessions waiting on locks (5 samples), deadlocks 0
- 🟡 medium Lock contention on `order-race-low-stock`: up to 4 sessions waiting on locks (1 samples), deadlocks 0

## Conditions

| | |
|---|---|
| Profile | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| App | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| App↔DB latency | 1.0 ms (jitter 0 ms) |
| DB pool size (per app process) | 5 |
| Data | User 1,000, Product 1,000, Order 1,000,000, OrderItem 2,000,000 (seed 42) |
| Auth | seeded test accounts + real login API (auth cost included) |
| Targets | p95 ≤ 500 ms, errors ≤ 1.0% |

## Results

| Run | Load | p50 | p95 | p99 | req/s | Errors | Queries/req |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 84.9 | **109.8** | 161.8 | 367.6 | 0.00% | 3.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 14.5 | **53.5** | 76.8 | 1,492.4 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 701.4 | **1,205.0** | 1,248.8 | 77.6 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 244.5 | **287.5** | 291.3 | 313.8 | 0.00% | 1.7 |

**Auth cost**: 50 logins, p50 265.4 ms, p95 412.3 ms

## Bottleneck candidates

### 1. 🟡 medium app CPU pinned at its limit on `orders-list`: avg 97% / max 101% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 2. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 102% / max 106% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 3. 🟡 medium Lock contention on `order-race`: up to 4 sessions waiting on locks (5 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 4. 🟡 medium Lock contention on `order-race-low-stock`: up to 4 sessions waiting on locks (1 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 11,051 | 1.0 | 0.12 | 1326.839 | `SELECT "public"."OrderItem"."id", "public"."OrderItem"."orderId", "public"."OrderItem"."productId", "public"."OrderItem…` |
| 11,051 | 1.0 | 0.036 | 400.59 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |
| 1,844 | 0.2 | 0.067 | 124.266 | `SELECT "public"."Product"."id", "public"."Product"."name" FROM "public"."Product" WHERE "public"."Product"."id" IN ($1,…` |
| 1,472 | 0.1 | 0.069 | 100.895 | `SELECT "public"."Product"."id", "public"."Product"."name" FROM "public"."Product" WHERE "public"."Product"."id" IN ($1,…` |
| 1,104 | 0.1 | 0.07 | 77.511 | `SELECT "public"."Product"."id", "public"."Product"."name" FROM "public"."Product" WHERE "public"."Product"."id" IN ($1,…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 29,900 | 1.0 | 0.008 | 237.299 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 5 | 0.0 | 0.003 | 0.016 | `SELECT $1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 44.596 | 4459.606 | `UPDATE "public"."Product" SET "stock" = ("public"."Product"."stock" - $1) WHERE ("public"."Product"."id" = $2 AND "publ…` |
| 100 | 1.0 | 0.119 | 11.887 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.069 | 6.913 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.011 | 1.063 | `SELECT "public"."Product"."id", "public"."Product"."price" FROM "public"."Product" WHERE ("public"."Product"."id" = $1 …` |
| 100 | 1.0 | 0.008 | 0.785 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 6.1 | 609.98 | `UPDATE "public"."Product" SET "stock" = ("public"."Product"."stock" - $1) WHERE ("public"."Product"."id" = $2 AND "publ…` |
| 10 | 0.1 | 0.087 | 0.873 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 10 | 0.1 | 0.061 | 0.612 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 10 | 0.1 | 0.013 | 0.132 | `SELECT "public"."Product"."id", "public"."Product"."price" FROM "public"."Product" WHERE ("public"."Product"."id" = $1 …` |
| 10 | 0.1 | 0.012 | 0.119 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 97 / 101 | 62 / 1,024 |  |  |
| orders-list | db | 12 / 15 | 330 / 1,024 | 5 (1) | 0 |
| product-detail | app | 102 / 106 | 63 / 1,024 |  |  |
| product-detail | db | 12 / 15 | 328 / 1,024 | 5 (2) | 0 |
| order-race | app | 41 / 41 | 63 / 1,024 |  |  |
| order-race | db | 9 / 9 | 329 / 1,024 | 5 (4) | 4 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ holds | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ holds | stock_after=0, stock_before=10, sold_during_run=10 |

## Before / after fix

| Run | Metric | Before | After | Change |
|---|---|---:|---:|---:|
| orders-list | queries/request | 61.0 | 3.0 | -95% |
| orders-list | p95 (ms) | 1,677.2 | 109.8 | -93% |
| orders-list | error rate | 0.00% | 0.00% |  |
| orders-list | req/s | 28.4 | 367.6 | +1195% |
| product-detail | queries/request | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 48.9 | 53.5 | +9% |
| product-detail | error rate | 0.00% | 0.00% |  |
| product-detail | req/s | 1,523.1 | 1,492.4 | -2% |
| order-race | queries/request | 8.0 | 8.0 | +0% |
| order-race | p95 (ms) | 488.6 | 1,205.0 | +147% |
| order-race | error rate | 0.00% | 0.00% |  |
| order-race | req/s | 193.7 | 77.6 | -60% |
| order-race | invariant: stock_consistency | ❌ violated | ✅ ok | |
| order-race-low-stock | queries/request | 8.0 | 1.7 | -79% |
| order-race-low-stock | p95 (ms) | 463.5 | 287.5 | -38% |
| order-race-low-stock | error rate | 0.00% | 0.00% |  |
| order-race-low-stock | req/s | 197.6 | 313.8 | +59% |
| order-race-low-stock | invariant: no_oversell | ❌ violated | ✅ ok | |


## Limitations

| Item | Approach | Limitation |
|---|---|---|
| CPU | Docker `cpus` limit | clock/generation differences and Fargate variance not modeled |
| Memory | `mem_limit` | runtime settings (JVM heap etc.) must match production |
| Network latency | Toxiproxy latency/jitter | cross-AZ variance and packet loss only approximated |
| Disk I/O | not modeled (v2) | EBS/RDS storage IOPS not reflected |
| RDS burst credits | `cpu_mode` switch only | credit depletion over time not modeled |
| Data | synthetic data | real distributions and hot keys may differ |
