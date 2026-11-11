# catchme report — after · 2026-11-11T14:17:20+00:00

Breaking point not measured (run `catchme breakpoint`).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🟠 high Connection pool saturated on `order-race`: up to 29 active connections with pool size 5
- 🟡 medium app CPU pinned at its limit on `orders-list`: avg 96% / max 105% of 0.5 vCPU
- 🟡 medium app CPU pinned at its limit on `product-detail`: avg 93% / max 107% of 0.5 vCPU
- 🟡 medium Lock contention on `order-race`: up to 29 sessions waiting on locks (5 samples), deadlocks 0
- 🟡 medium Lock contention on `order-race-low-stock`: up to 21 sessions waiting on locks (2 samples), deadlocks 0

## Conditions

| | |
|---|---|
| Profile | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| App | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| App↔DB latency | 1.0 ms (jitter 0 ms) |
| DB pool size (per app process) | 5 |
| Data | users 1,000, products 1,000, orders 1,000,000, order_items 2,000,000 (seed 42) |
| Auth | seeded test accounts + real login API (auth cost included) |
| Targets | p95 ≤ 500 ms, errors ≤ 1.0% |

## Results

| Run | Load | p50 | p95 | p99 | req/s | Errors | Queries/req |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 214.2 | **497.4** | 598.0 | 134.6 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 196.0 | **403.0** | 500.2 | 143.5 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 907.8 | **1,384.6** | 1,424.1 | 69.1 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 409.8 | **494.8** | 500.4 | 197.6 | 0.00% | 1.6 |

**Auth cost**: 50 logins, p50 900.0 ms, p95 1,118.8 ms

## Bottleneck candidates

### 1. 🟠 high Connection pool saturated on `order-race`: up to 29 active connections with pool size 5
- Evidence: avg active 13.8, p95 1,384.6 ms, 5xx 0
- Fix direction: shorten transactions, remove N+1, then size the pool against `max_connections`

### 2. 🟡 medium app CPU pinned at its limit on `orders-list`: avg 96% / max 105% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 3. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 93% / max 107% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 4. 🟡 medium Lock contention on `order-race`: up to 29 sessions waiting on locks (5 samples), deadlocks 0
- Evidence: 9 lock waits of 100 ms or longer logged by PostgreSQL during the run
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 5. 🟡 medium Lock contention on `order-race-low-stock`: up to 21 sessions waiting on locks (2 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 2,621 | 0.6 | 0.238 | 625.03 | `SELECT order_items.order_id AS order_items_order_id, order_items.id AS order_items_id, order_items.product_id AS order_…` |
| 4,065 | 1.0 | 0.066 | 268.23 | `SELECT orders.id, orders.user_id, orders.status, orders.created_at FROM orders WHERE orders.user_id = $1::INTEGER ORDER…` |
| 587 | 0.1 | 0.186 | 109.132 | `SELECT order_items.order_id AS order_items_order_id, order_items.id AS order_items_id, order_items.product_id AS order_…` |
| 253 | 0.1 | 0.281 | 71.16 | `SELECT order_items.order_id AS order_items_order_id, order_items.id AS order_items_id, order_items.product_id AS order_…` |
| 88 | 0.0 | 0.309 | 27.217 | `SELECT order_items.order_id AS order_items_order_id, order_items.id AS order_items_id, order_items.product_id AS order_…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 2,895 | 1.0 | 0.011 | 31.33 | `SELECT products.id AS products_id, products.name AS products_name, products.price AS products_price, products.stock AS …` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 296.48 | 29647.965 | `UPDATE products SET stock=(products.stock - $1::INTEGER) WHERE products.id = $2::INTEGER AND products.stock >= $3::INTE…` |
| 100 | 1.0 | 0.205 | 20.501 | `INSERT INTO orders (user_id, status) VALUES ($1::INTEGER, $2::VARCHAR) RETURNING orders.id, orders.created_at` |
| 100 | 1.0 | 0.139 | 13.888 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1::INTEGER, $2::INTEGER, $3::INTEGER, $4:…` |
| 100 | 1.0 | 0.009 | 0.879 | `SELECT products.price FROM products WHERE products.id = $1::INTEGER` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 59.368 | 5936.786 | `UPDATE products SET stock=(products.stock - $1::INTEGER) WHERE products.id = $2::INTEGER AND products.stock >= $3::INTE…` |
| 10 | 0.1 | 0.211 | 2.114 | `INSERT INTO orders (user_id, status) VALUES ($1::INTEGER, $2::VARCHAR) RETURNING orders.id, orders.created_at` |
| 10 | 0.1 | 0.12 | 1.199 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1::INTEGER, $2::INTEGER, $3::INTEGER, $4:…` |
| 10 | 0.1 | 0.008 | 0.084 | `SELECT products.price FROM products WHERE products.id = $1::INTEGER` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 96 / 105 | 153 / 1,024 |  |  |
| orders-list | db | 10 / 11 | 370 / 1,024 | 20 (2) | 0 |
| product-detail | app | 93 / 107 | 154 / 1,024 |  |  |
| product-detail | db | 13 / 17 | 353 / 1,024 | 24 (2) | 0 |
| order-race | app | 29 / 58 | 157 / 1,024 |  |  |
| order-race | db | 12 / 16 | 376 / 1,024 | 30 (29) | 29 |
| order-race-low-stock | app | 55 / 55 | 158 / 1,024 |  |  |
| order-race-low-stock | db | 8 / 8 | 337 / 1,024 | 26 (21) | 21 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ holds | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ holds | stock_after=0, stock_before=10, sold_during_run=10 |

## Before / after fix

| Run | Metric | Before | After | Change |
|---|---|---:|---:|---:|
| orders-list | queries/request | 61.7 | 2.0 | -97% |
| orders-list | p95 (ms) | 2,049.9 | 497.4 | -76% |
| orders-list | error rate | 0.00% | 0.00% |  |
| orders-list | req/s | 19.1 | 134.6 | +604% |
| product-detail | queries/request | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 490.7 | 403.0 | -18% |
| product-detail | error rate | 0.00% | 0.00% |  |
| product-detail | req/s | 113.6 | 143.5 | +26% |
| order-race | queries/request | 7.0 | 7.0 | +0% |
| order-race | p95 (ms) | 1,129.2 | 1,384.6 | +23% |
| order-race | error rate | 0.00% | 0.00% |  |
| order-race | req/s | 83.9 | 69.1 | -18% |
| order-race | invariant: stock_consistency | ❌ violated | ✅ ok | |
| order-race-low-stock | queries/request | 7.0 | 1.6 | -77% |
| order-race-low-stock | p95 (ms) | 836.0 | 494.8 | -41% |
| order-race-low-stock | error rate | 0.00% | 0.00% |  |
| order-race-low-stock | req/s | 114.7 | 197.6 | +72% |
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
