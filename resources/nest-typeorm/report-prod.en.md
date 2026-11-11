# catchme report — prod · 2026-11-11T13:42:47+00:00

**This spec holds up to 20 concurrent requests** on `orders-list` (p95 ≤ 500 ms, errors ≤ 1.0%).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- 🟠 high Possible N+1 on `orders-list`: 62.9 queries/request; one statement runs 41.9× per request
- 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- 🟠 high Connection pool saturated on `orders-list`: up to 10 active connections with pool size 10
- 🟡 medium db CPU pinned at its limit on `orders-list`: avg 91% / max 102% of 2 vCPU

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 734.9 | **1,232.2** | 1,640.5 | 37.4 | 0.00% | 62.9 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 7.3 | **46.8** | 73.3 | 2,644.0 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 435.2 | **536.6** | 538.9 | 179.8 | 0.00% | 7.2 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 575.0 | **765.0** | 765.4 | 126.9 | 0.00% | 7.2 |

**Auth cost**: 50 logins, p50 632.0 ms, p95 894.0 ms

| VUs | p95 (ms) | Errors | req/s | |
|---:|---:|---:|---:|---|
| 5 | 220.7 | 0.00% | 31.6 | ✅ |
| 10 | 267.4 | 0.00% | 50.4 | ✅ |
| 20 | 489.0 | 0.00% | 50.5 | ✅ |
| 22 | 565.0 | 0.00% | 50.1 | ❌ |
| 25 | 667.9 | 0.00% | 50.6 | ❌ |
| 30 | 895.4 | 0.00% | 49.0 | ❌ |
| 40 | 1,224.2 | 0.00% | 48.6 | ❌ |

## Bottleneck candidates

### 1. 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- Evidence: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99993, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- Fix direction: QueryBuilder `update().set({ stock: () => 'stock - :q' }).where('id = :id AND stock >= :q')` and check `affected`

### 2. 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- Evidence: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=3, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- Fix direction: QueryBuilder `update().set({ stock: () => 'stock - :q' }).where('id = :id AND stock >= :q')` and check `affected`

### 3. 🟠 high Possible N+1 on `orders-list`: 62.9 queries/request; one statement runs 41.9× per request
- Evidence: `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Product"."stock" AS "Product_stock" FROM "pro…` — 47,513 calls / 1,135 requests, mean 0.01 ms
- Fix direction: `relations: { items: { product: true } }` or QueryBuilder `leftJoinAndSelect`

### 4. 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- Evidence: 
    - `SELECT "Order"."id" AS "Order_id", "Order"."user_id" AS "Order_user_id", "Order"."status" AS "Order_status", "Order"."created_at" AS "Order_created_at" FROM "o…` — mean 36.51 ms × 1,135 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- Fix direction: index on the filter columns (check the WHERE / ORDER BY of the statement)

### 5. 🟠 high Connection pool saturated on `orders-list`: up to 10 active connections with pool size 10
- Evidence: avg active 1.1, p95 1,232.2 ms, 5xx 0
- Fix direction: shorten transactions, remove N+1, then size the pool against `max_connections`

### 6. 🟡 medium db CPU pinned at its limit on `orders-list`: avg 91% / max 102% of 2 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 7. 🟡 medium p95 1232 ms on `orders-list` exceeds target 500 ms

### 8. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 91% / max 101% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 9. 🟡 medium Lock contention on `order-race`: up to 1 sessions waiting on locks (1 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 10. 🟡 medium Lock contention on `order-race-low-stock`: up to 2 sessions waiting on locks (1 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 11. 🟡 medium app CPU pinned at its limit on `order-race-low-stock`: avg 87% / max 87% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 1,135 | 1.0 | 36.514 | 41443.266 | `SELECT "Order"."id" AS "Order_id", "Order"."user_id" AS "Order_user_id", "Order"."status" AS "Order_status", "Order"."c…` |
| 22,700 | 20.0 | 0.022 | 502.56 | `SELECT "OrderItem"."id" AS "OrderItem_id", "OrderItem"."order_id" AS "OrderItem_order_id", "OrderItem"."product_id" AS …` |
| 47,513 | 41.9 | 0.01 | 462.079 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 52,971 | 1.0 | 0.005 | 250.146 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 25 | 0.2 | 5.857 | 146.424 | `UPDATE "products" SET "stock" = $1 WHERE "id" IN ($2)` |
| 100 | 1.0 | 0.147 | 14.738 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 100 | 1.0 | 0.129 | 12.872 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 100 | 1.0 | 0.011 | 1.11 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |
| 100 | 1.0 | 0.01 | 1.023 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 25 | 0.2 | 11.213 | 280.332 | `UPDATE "products" SET "stock" = $1 WHERE "id" IN ($2)` |
| 100 | 1.0 | 0.074 | 7.394 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 100 | 1.0 | 0.052 | 5.152 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 100 | 1.0 | 0.029 | 2.93 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |
| 100 | 1.0 | 0.01 | 1.016 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 64 / 98 | 62 / 1,024 |  |  |
| orders-list | db | 91 / 102 | 347 / 1,024 | 11 (10) | 0 |
| product-detail | app | 91 / 101 | 65 / 1,024 |  |  |
| product-detail | db | 13 / 15 | 337 / 1,024 | 10 (2) | 0 |
| order-race | app | 23 / 23 | 65 / 1,024 |  |  |
| order-race | db | 5 / 5 | 338 / 1,024 | 10 (1) | 1 |
| order-race-low-stock | app | 87 / 87 | 63 / 1,024 |  |  |
| order-race-low-stock | db | 8 / 8 | 338 / 1,024 | 10 (2) | 2 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ violated | stock_after=99993, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ violated | stock_after=3, stock_before=10, sold_during_run=100 |

## Limitations

| Item | Approach | Limitation |
|---|---|---|
| CPU | Docker `cpus` limit | clock/generation differences and Fargate variance not modeled |
| Memory | `mem_limit` | runtime settings (JVM heap etc.) must match production |
| Network latency | Toxiproxy latency/jitter | cross-AZ variance and packet loss only approximated |
| Disk I/O | not modeled (v2) | EBS/RDS storage IOPS not reflected |
| RDS burst credits | `cpu_mode` switch only | credit depletion over time not modeled |
| Data | synthetic data | real distributions and hot keys may differ |
