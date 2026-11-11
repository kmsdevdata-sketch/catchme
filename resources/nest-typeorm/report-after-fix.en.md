# catchme report — after · 2026-11-11T13:48:01+00:00

Breaking point not measured (run `catchme breakpoint`).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🟠 high Connection pool saturated on `order-race`: up to 10 active connections with pool size 10
- 🟡 medium app CPU pinned at its limit on `orders-list`: avg 99% / max 101% of 0.5 vCPU
- 🟡 medium app CPU pinned at its limit on `product-detail`: avg 90% / max 103% of 0.5 vCPU
- 🟡 medium Lock contention on `order-race`: up to 9 sessions waiting on locks (5 samples), deadlocks 0
- 🟡 medium Lock contention on `order-race-low-stock`: up to 9 sessions waiting on locks (1 samples), deadlocks 0

## Conditions

| | |
|---|---|
| Profile | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| App | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| App↔DB latency | 1.0 ms (jitter 0 ms) |
| DB pool size (per app process) | 10 |
| Data | users 1,000, products 1,000, orders 1,000,000, order_items 2,000,000 (seed 42) |
| Auth | seeded test accounts + real login API (auth cost included) |
| Targets | p95 ≤ 500 ms, errors ≤ 1.0% |

## Results

| Run | Load | p50 | p95 | p99 | req/s | Errors | Queries/req |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 81.5 | **111.0** | 173.1 | 420.1 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 8.0 | **42.9** | 73.5 | 2,677.8 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 692.7 | **1,169.0** | 1,208.4 | 80.8 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 352.4 | **375.3** | 376.9 | 247.3 | 0.00% | 1.6 |

**Auth cost**: 50 logins, p50 670.7 ms, p95 750.5 ms

## Bottleneck candidates

### 1. 🟠 high Connection pool saturated on `order-race`: up to 10 active connections with pool size 10
- Evidence: avg active 4.9, p95 1,169.0 ms, 5xx 0
- Fix direction: shorten transactions, remove N+1, then size the pool against `max_connections`

### 2. 🟡 medium app CPU pinned at its limit on `orders-list`: avg 99% / max 101% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 3. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 90% / max 103% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 4. 🟡 medium Lock contention on `order-race`: up to 9 sessions waiting on locks (5 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 5. 🟡 medium Lock contention on `order-race-low-stock`: up to 9 sessions waiting on locks (1 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 12,626 | 1.0 | 0.15 | 1896.682 | `SELECT DISTINCT "distinctAlias"."Order_id" AS "ids_Order_id", "distinctAlias"."Order_created_at" FROM (SELECT "Order"."…` |
| 12,626 | 1.0 | 0.147 | 1850.134 | `SELECT "Order"."id" AS "Order_id", "Order"."user_id" AS "Order_user_id", "Order"."status" AS "Order_status", "Order"."c…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 53,759 | 1.0 | 0.004 | 210.724 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 97.365 | 9736.453 | `UPDATE "products" SET "stock" = "stock" - $1 WHERE "id" = $2 AND "stock" >= $1` |
| 100 | 1.0 | 0.209 | 20.92 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 100 | 1.0 | 0.118 | 11.822 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 100 | 1.0 | 0.014 | 1.365 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 25.879 | 2587.94 | `UPDATE "products" SET "stock" = "stock" - $1 WHERE "id" = $2 AND "stock" >= $1` |
| 10 | 0.1 | 0.184 | 1.841 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 10 | 0.1 | 0.119 | 1.192 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 10 | 0.1 | 0.026 | 0.26 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 99 / 101 | 65 / 1,024 |  |  |
| orders-list | db | 16 / 18 | 346 / 1,024 | 10 (3) | 0 |
| product-detail | app | 90 / 103 | 66 / 1,024 |  |  |
| product-detail | db | 13 / 17 | 345 / 1,024 | 10 (2) | 0 |
| order-race | app | 34 / 34 | 65 / 1,024 |  |  |
| order-race | db | 10 / 10 | 348 / 1,024 | 10 (10) | 9 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ holds | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ holds | stock_after=0, stock_before=10, sold_during_run=10 |

## Before / after fix

| Run | Metric | Before | After | Change |
|---|---|---:|---:|---:|
| orders-list | queries/request | 62.9 | 2.0 | -97% |
| orders-list | p95 (ms) | 1,232.2 | 111.0 | -91% |
| orders-list | error rate | 0.00% | 0.00% |  |
| orders-list | req/s | 37.4 | 420.1 | +1022% |
| product-detail | queries/request | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 46.8 | 42.9 | -8% |
| product-detail | error rate | 0.00% | 0.00% |  |
| product-detail | req/s | 2,644.0 | 2,677.8 | +1% |
| order-race | queries/request | 7.2 | 7.0 | -3% |
| order-race | p95 (ms) | 536.6 | 1,169.0 | +118% |
| order-race | error rate | 0.00% | 0.00% |  |
| order-race | req/s | 179.8 | 80.8 | -55% |
| order-race | invariant: stock_consistency | ❌ violated | ✅ ok | |
| order-race-low-stock | queries/request | 7.2 | 1.6 | -78% |
| order-race-low-stock | p95 (ms) | 765.0 | 375.3 | -51% |
| order-race-low-stock | error rate | 0.00% | 0.00% |  |
| order-race-low-stock | req/s | 126.9 | 247.3 | +95% |
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
