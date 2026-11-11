# catchme report — after · 2026-11-11T14:08:06+00:00

Breaking point not measured (run `catchme breakpoint`).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🟠 high New DB connection per request on `orders-list`, `product-detail`, `order-race`, `order-race-low-stock`: up to 102 sessions opened for 100 requests (no connection pooling)

## Conditions

| | |
|---|---|
| Profile | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| App | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| App↔DB latency | 1.0 ms (jitter 0 ms) |
| DB pool size (per app process) | None |
| Data | users 1,000, products 1,000, orders 1,000,000, order_items 2,000,000 (seed 42) |
| Auth | seeded test accounts + real login API (auth cost included) |
| Targets | p95 ≤ 500 ms, errors ≤ 1.0% |

## Results

| Run | Load | p50 | p95 | p99 | req/s | Errors | Queries/req |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 287.8 | **308.9** | 322.8 | 103.4 | 0.00% | 3.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 236.8 | **256.7** | 274.8 | 125.8 | 0.00% | 2.0 |
| order-race | 100 VUs × 1 (simultaneous) | 750.7 | **1,320.6** | 1,382.1 | 70.5 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 545.7 | **976.6** | 1,015.1 | 96.3 | 0.00% | 2.6 |

**Auth cost**: 50 logins, p50 1,600.5 ms, p95 1,842.3 ms

## Bottleneck candidates

### 1. 🟠 high New DB connection per request on `orders-list`, `product-detail`, `order-race`, `order-race-low-stock`: up to 102 sessions opened for 100 requests (no connection pooling)
- Evidence: 
    - 1.01 new sessions per request — each pays TCP + auth + session setup over the app↔db latency (orders-list)
    - 1.00 new sessions per request — each pays TCP + auth + session setup over the app↔db latency (product-detail)
    - 1.02 new sessions per request — each pays TCP + auth + session setup over the app↔db latency (order-race)
    - 1.02 new sessions per request — each pays TCP + auth + session setup over the app↔db latency (order-race-low-stock)
- Fix direction: `CONN_MAX_AGE = 60` (+ `CONN_HEALTH_CHECKS = True`), or the psycopg pool (`OPTIONS: {"pool": True}`, Django 5.1+)

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 3,133 | 1.0 | 0.324 | 1015.889 | `SELECT "order_items"."id", "order_items"."order_id", "order_items"."product_id", "order_items"."quantity", "order_items…` |
| 3,133 | 1.0 | 0.093 | 291.268 | `SELECT "orders"."id", "orders"."user_id", "orders"."status", "orders"."created_at" FROM "orders" WHERE "orders"."user_i…` |
| 3,133 | 1.0 | 0.033 | 102.976 | `SELECT set_config($1, $2, $3)` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 2,546 | 1.0 | 0.034 | 85.714 | `SELECT set_config($1, $2, $3)` |
| 2,546 | 1.0 | 0.016 | 40.5 | `SELECT "products"."id", "products"."name", "products"."price", "products"."stock" FROM "products" WHERE "products"."id"…` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.215 | 21.454 | `UPDATE "products" SET "stock" = ("products"."stock" - $1) WHERE ("products"."id" = $2 AND "products"."stock" >= $3)` |
| 100 | 1.0 | 0.162 | 16.248 | `INSERT INTO "orders" ("user_id", "status", "created_at") VALUES ($1, $2, $3::timestamptz) RETURNING "orders"."id"` |
| 100 | 1.0 | 0.078 | 7.843 | `INSERT INTO "order_items" ("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "order…` |
| 100 | 1.0 | 0.05 | 4.979 | `SELECT set_config($1, $2, $3)` |
| 100 | 1.0 | 0.007 | 0.697 | `SELECT "products"."price" FROM "products" WHERE "products"."id" = $1 LIMIT $2` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.066 | 6.56 | `UPDATE "products" SET "stock" = ("products"."stock" - $1) WHERE ("products"."id" = $2 AND "products"."stock" >= $3)` |
| 100 | 1.0 | 0.037 | 3.664 | `SELECT set_config($1, $2, $3)` |
| 10 | 0.1 | 0.099 | 0.99 | `INSERT INTO "orders" ("user_id", "status", "created_at") VALUES ($1, $2, $3::timestamptz) RETURNING "orders"."id"` |
| 10 | 0.1 | 0.081 | 0.813 | `INSERT INTO "order_items" ("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "order…` |
| 10 | 0.1 | 0.008 | 0.083 | `SELECT "products"."price" FROM "products" WHERE "products"."id" = $1 LIMIT $2` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 76 / 87 | 96 / 1,024 |  |  |
| orders-list | db | 18 / 23 | 324 / 1,024 | 2 (2) | 0 |
| product-detail | app | 67 / 78 | 97 / 1,024 |  |  |
| product-detail | db | 17 / 19 | 317 / 1,024 | 2 (1) | 0 |
| order-race | app | 28 / 55 | 96 / 1,024 |  |  |
| order-race | db | 12 / 17 | 317 / 1,024 | 2 (0) | 0 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ holds | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ holds | stock_after=0, stock_before=10, sold_during_run=10 |

## Before / after fix

| Run | Metric | Before | After | Change |
|---|---|---:|---:|---:|
| orders-list | queries/request | 64.3 | 3.0 | -95% |
| orders-list | p95 (ms) | 2,728.1 | 308.9 | -89% |
| orders-list | error rate | 0.00% | 0.00% |  |
| orders-list | req/s | 12.0 | 103.4 | +765% |
| product-detail | queries/request | 2.0 | 2.0 | +0% |
| product-detail | p95 (ms) | 266.8 | 256.7 | -4% |
| product-detail | error rate | 0.00% | 0.00% |  |
| product-detail | req/s | 124.5 | 125.8 | +1% |
| order-race | queries/request | 8.0 | 8.0 | +0% |
| order-race | p95 (ms) | 1,663.0 | 1,320.6 | -21% |
| order-race | error rate | 0.00% | 0.00% |  |
| order-race | req/s | 56.7 | 70.5 | +24% |
| order-race | invariant: stock_consistency | ❌ violated | ✅ ok | |
| order-race-low-stock | queries/request | 3.2 | 2.6 | -19% |
| order-race-low-stock | p95 (ms) | 817.2 | 976.6 | +19% |
| order-race-low-stock | error rate | 0.00% | 0.00% |  |
| order-race-low-stock | req/s | 114.4 | 96.3 | -16% |
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
