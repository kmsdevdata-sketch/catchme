# catchme report — prod · 2026-11-11T14:54:46+00:00

**This spec holds up to 13 concurrent requests** on `orders-list` (p95 ≤ 500 ms, errors ≤ 1.0%).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- 🟠 high Possible N+1 on `orders-list`: 61.0 queries/request; one statement runs 39.9× per request
- 🟠 high Possible missing index: Seq Scan on `Order` (~1,000,000 rows) with filter `("userId" = $1)`
- 🟡 medium p95 1287 ms on `orders-list` exceeds target 500 ms
- 🟡 medium `orders-list` is 4.0× slower at p95 under the production profile than locally (323 → 1287 ms)

## Conditions

| | |
|---|---|
| Profile | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| App | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| App↔DB latency | 1.0 ms (jitter 0 ms) |
| DB pool size (per app process) | None |
| Data | User 1,000, Product 1,000, Order 1,000,000, OrderItem 2,000,000 (seed 42) |
| Auth | seeded test accounts + real login API (auth cost included) |
| Targets | p95 ≤ 500 ms, errors ≤ 1.0% |

## Results

| Run | Load | p50 (local → prod) | p95 (local → prod) | p99 (prod) | req/s (local → prod) | Errors | Queries/req |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 255.9 → 985.3 | 322.7 → **1,287.1** | 2,169.6 | 114.6 → 29.0 | 0.00% | 61.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 1.8 → 15.9 | 3.4 → **45.1** | 62.6 | 14,275.6 → 1,573.9 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 84.8 → 384.5 | 112.6 → **486.1** | 495.7 | 804.7 → 193.9 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 68.8 → 331.5 | 92.4 → **429.6** | 438.2 | 927.5 → 217.4 | 0.00% | 8.0 |

**Auth cost**: 50 logins, p50 240.0 ms, p95 415.0 ms

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

### 2. 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- Evidence: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=6, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0

### 3. 🟠 high Possible N+1 on `orders-list`: 61.0 queries/request; one statement runs 39.9× per request
- Evidence: `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM "public"."Product" WHERE ("public"."Prod…` — 35,275 calls / 883 requests, mean 0.005 ms

### 4. 🟠 high Possible missing index: Seq Scan on `Order` (~1,000,000 rows) with filter `("userId" = $1)`
- Evidence: 
    - `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "public"."Order" WHERE "public"."Order"."…` — mean 20.99 ms × 883 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on Order
- Fix direction: index on the filter columns (check the WHERE / ORDER BY of the statement)

### 5. 🟡 medium p95 1287 ms on `orders-list` exceeds target 500 ms

### 6. 🟡 medium `orders-list` is 4.0× slower at p95 under the production profile than locally (323 → 1287 ms)

### 7. 🟡 medium `product-detail` is 13.1× slower at p95 under the production profile than locally (3 → 45 ms)

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 883 | 1.0 | 20.989 | 18532.96 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |
| 17,660 | 20.0 | 0.014 | 245.704 | `SELECT "public"."OrderItem"."id", "public"."OrderItem"."orderId", "public"."OrderItem"."productId", "public"."OrderItem…` |
| 35,275 | 39.9 | 0.005 | 172.259 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 10 | 0.0 | 0.001 | 0.015 | `SELECT $1` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 31,501 | 1.0 | 0.008 | 245.881 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 5 | 0.0 | 0.002 | 0.009 | `SELECT $1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.187 | 18.667 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND $3=$4) RETURNING "public"."Product".…` |
| 100 | 1.0 | 0.095 | 9.489 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.069 | 6.86 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.012 | 1.217 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.007 | 0.718 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.089 | 8.868 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND 1=1) RETURNING "public"."Product"."i…` |
| 100 | 1.0 | 0.05 | 4.994 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.042 | 4.195 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.01 | 0.969 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.005 | 0.543 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 58 / 70 | 61 / 1,024 |  |  |
| orders-list | db | 62 / 75 | 331 / 1,024 | 5 (4) | 0 |
| product-detail | app | 88 / 103 | 63 / 1,024 |  |  |
| product-detail | db | 13 / 15 | 324 / 1,024 | 5 (2) | 0 |
| order-race | app | 39 / 39 | 63 / 1,024 |  |  |
| order-race | db | 9 / 9 | 324 / 1,024 | 5 (0) | 0 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ violated | stock_after=99996, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ violated | stock_after=6, stock_before=10, sold_during_run=100 |

## Limitations

| Item | Approach | Limitation |
|---|---|---|
| CPU | Docker `cpus` limit | clock/generation differences and Fargate variance not modeled |
| Memory | `mem_limit` | runtime settings (heap size, GC, thread/worker counts) must match production |
| Network latency | Toxiproxy latency/jitter | cross-AZ variance and packet loss only approximated |
| Disk I/O | not modeled | EBS/RDS storage IOPS not reflected |
| RDS burst credits | `cpu_mode` switch only | credit depletion over time not modeled |
| Data | synthetic data | real distributions and hot keys may differ |
