# catchme report — prod · 2026-11-11T13:33:33+00:00

**This spec holds up to 13 concurrent requests** on `orders-list` (p95 ≤ 500 ms, errors ≤ 1.0%).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- 🟠 high Possible N+1 on `orders-list`: 61.0 queries/request; one statement runs 40.0× per request
- 🟠 high Possible missing index: Seq Scan on `Order` (~1,000,000 rows) with filter `("userId" = $1)`
- 🟠 high Connection pool saturated on `orders-list`: up to 5 active connections with pool size 5
- 🟡 medium p95 1677 ms on `orders-list` exceeds target 500 ms

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 965.8 | **1,677.2** | 2,469.9 | 28.4 | 0.00% | 61.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 14.8 | **48.9** | 71.2 | 1,523.1 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 394.1 | **488.6** | 492.1 | 193.7 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 371.5 | **463.5** | 470.3 | 197.6 | 0.00% | 8.0 |

**Auth cost**: 50 logins, p50 272.4 ms, p95 430.8 ms

| VUs | p95 (ms) | Errors | req/s | |
|---:|---:|---:|---:|---|
| 5 | 178.1 | 0.00% | 34.0 | ✅ |
| 10 | 349.3 | 0.00% | 35.2 | ✅ |
| 12 | 443.3 | 0.00% | 35.4 | ✅ |
| 13 | 443.9 | 0.00% | 36.3 | ✅ |
| 15 | 579.6 | 0.00% | 35.3 | ❌ |
| 20 | 824.9 | 0.00% | 33.0 | ❌ |

## Bottleneck candidates

### 1. 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- Evidence: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99996, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- Fix direction: `updateMany({ where: { id, stock: { gte: q } }, data: { stock: { decrement: q } } })` and check `count`

### 2. 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- Evidence: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=5, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- Fix direction: `updateMany({ where: { id, stock: { gte: q } }, data: { stock: { decrement: q } } })` and check `count`

### 3. 🟠 high Possible N+1 on `orders-list`: 61.0 queries/request; one statement runs 40.0× per request
- Evidence: `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM "public"."Product" WHERE ("public"."Prod…` — 34,604 calls / 866 requests, mean 0.006 ms
- Fix direction: `include` / nested `select`, or one `findMany({ where: { id: { in: ids } } })`

### 4. 🟠 high Possible missing index: Seq Scan on `Order` (~1,000,000 rows) with filter `("userId" = $1)`
- Evidence: 
    - `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "public"."Order" WHERE "public"."Order"."…` — mean 25.06 ms × 866 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on Order
- Fix direction: index on the filter columns (check the WHERE / ORDER BY of the statement)

### 5. 🟠 high Connection pool saturated on `orders-list`: up to 5 active connections with pool size 5
- Evidence: avg active 0.7, p95 1,677.2 ms, 5xx 0
- Fix direction: shorten transactions, remove N+1, then size the pool against `max_connections`

### 6. 🟡 medium p95 1677 ms on `orders-list` exceeds target 500 ms

### 7. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 104% / max 110% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 866 | 1.0 | 25.061 | 21703.206 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |
| 17,320 | 20.0 | 0.023 | 404.153 | `SELECT "public"."OrderItem"."id", "public"."OrderItem"."orderId", "public"."OrderItem"."productId", "public"."OrderItem…` |
| 34,604 | 40.0 | 0.006 | 206.584 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 10 | 0.0 | 0.003 | 0.033 | `SELECT $1` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 30,500 | 1.0 | 0.008 | 258.945 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 5 | 0.0 | 0.003 | 0.015 | `SELECT $1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.253 | 25.264 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND $3=$4) RETURNING "public"."Product".…` |
| 100 | 1.0 | 0.126 | 12.644 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.077 | 7.669 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.013 | 1.294 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.006 | 0.635 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.173 | 17.27 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND 1=1) RETURNING "public"."Product"."i…` |
| 100 | 1.0 | 0.073 | 7.303 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.05 | 4.978 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.012 | 1.203 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.007 | 0.739 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 70 / 98 | 62 / 1,024 |  |  |
| orders-list | db | 68 / 83 | 331 / 1,024 | 5 (5) | 0 |
| product-detail | app | 104 / 110 | 64 / 1,024 |  |  |
| product-detail | db | 13 / 14 | 327 / 1,024 | 5 (2) | 0 |
| order-race | app | 0 / 0 | 64 / 1,024 |  |  |
| order-race | db | 9 / 9 | 326 / 1,024 | 5 (0) | 0 |
| order-race-low-stock | app | 44 / 44 | 64 / 1,024 |  |  |
| order-race-low-stock | db | 10 / 10 | 326 / 1,024 | 5 (0) | 0 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ violated | stock_after=99996, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ violated | stock_after=5, stock_before=10, sold_during_run=100 |

## Limitations

| Item | Approach | Limitation |
|---|---|---|
| CPU | Docker `cpus` limit | clock/generation differences and Fargate variance not modeled |
| Memory | `mem_limit` | runtime settings (JVM heap etc.) must match production |
| Network latency | Toxiproxy latency/jitter | cross-AZ variance and packet loss only approximated |
| Disk I/O | not modeled (v2) | EBS/RDS storage IOPS not reflected |
| RDS burst credits | `cpu_mode` switch only | credit depletion over time not modeled |
| Data | synthetic data | real distributions and hot keys may differ |
