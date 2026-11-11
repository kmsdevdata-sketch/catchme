# catchme report — prod · 2026-11-11T14:12:20+00:00

**This spec holds up to 10 concurrent requests** on `orders-list` (p95 ≤ 500 ms, errors ≤ 1.0%).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- 🟠 high Possible N+1 on `orders-list`: 61.7 queries/request; one statement runs 40.7× per request
- 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- 🟠 high Connection pool saturated on `orders-list`: up to 9 active connections with pool size 5
- 🟠 high Connection pool saturated on `order-race`: up to 21 active connections with pool size 5

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 1,711.7 | **2,049.9** | 2,628.4 | 19.1 | 0.00% | 61.7 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 242.5 | **490.7** | 781.3 | 113.6 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 894.7 | **1,129.2** | 1,183.5 | 83.9 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 625.1 | **836.0** | 853.2 | 114.7 | 0.00% | 7.0 |

**Auth cost**: 50 logins, p50 853.7 ms, p95 1,320.9 ms

| VUs | p95 (ms) | Errors | req/s | |
|---:|---:|---:|---:|---|
| 5 | 208.2 | 0.00% | 28.0 | ✅ |
| 10 | 487.1 | 0.00% | 27.2 | ✅ |
| 11 | 693.3 | 0.00% | 22.1 | ❌ |
| 12 | 692.9 | 0.00% | 22.2 | ❌ |
| 15 | 1,099.5 | 0.00% | 19.7 | ❌ |
| 20 | 1,703.3 | 0.00% | 17.7 | ❌ |

## Bottleneck candidates

### 1. 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- Evidence: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99990, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- Fix direction: `update(Product).where(Product.id == id, Product.stock >= q).values(stock=Product.stock - q)` and check `rowcount`

### 2. 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- Evidence: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=5, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- Fix direction: `update(Product).where(Product.id == id, Product.stock >= q).values(stock=Product.stock - q)` and check `rowcount`

### 3. 🟠 high Possible N+1 on `orders-list`: 61.7 queries/request; one statement runs 40.7× per request
- Evidence: `SELECT products.id AS products_id, products.name AS products_name, products.price AS products_price, products.stock AS products_stock FROM products WHERE produ…` — 24,148 calls / 593 requests, mean 0.007 ms
- Fix direction: `options(selectinload(Order.items).joinedload(OrderItem.product))`

### 4. 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- Evidence: 
    - `SELECT orders.id, orders.user_id, orders.status, orders.created_at FROM orders WHERE orders.user_id = $1::INTEGER ORDER BY orders.created_at DESC LIMIT $2::INT…` — mean 17.32 ms × 593 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- Fix direction: index on the filter columns (check the WHERE / ORDER BY of the statement)

### 5. 🟠 high Connection pool saturated on `orders-list`: up to 9 active connections with pool size 5
- Evidence: avg active 0.4, p95 2,049.9 ms, 5xx 0
- Fix direction: shorten transactions, remove N+1, then size the pool against `max_connections`

### 6. 🟠 high Connection pool saturated on `order-race`: up to 21 active connections with pool size 5
- Evidence: avg active 5.4, p95 1,129.2 ms, 5xx 0
- Fix direction: shorten transactions, remove N+1, then size the pool against `max_connections`

### 7. 🟠 high Connection pool saturated on `order-race-low-stock`: up to 24 active connections with pool size 5
- Evidence: avg active 8.3, p95 836.0 ms, 5xx 0
- Fix direction: shorten transactions, remove N+1, then size the pool against `max_connections`

### 8. 🟡 medium app CPU pinned at its limit on `orders-list`: avg 94% / max 104% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 9. 🟡 medium p95 2050 ms on `orders-list` exceeds target 500 ms

### 10. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 93% / max 110% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 11. 🟡 medium Lock contention on `order-race`: up to 21 sessions waiting on locks (3 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 12. 🟡 medium Lock contention on `order-race-low-stock`: up to 24 sessions waiting on locks (3 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 593 | 1.0 | 17.316 | 10268.245 | `SELECT orders.id, orders.user_id, orders.status, orders.created_at FROM orders WHERE orders.user_id = $1::INTEGER ORDER…` |
| 11,563 | 19.5 | 0.018 | 207.512 | `SELECT order_items.id AS order_items_id, order_items.order_id AS order_items_order_id, order_items.product_id AS order_…` |
| 24,148 | 40.7 | 0.007 | 160.979 | `SELECT products.id AS products_id, products.name AS products_name, products.price AS products_price, products.stock AS …` |
| 297 | 0.5 | 0.017 | 4.926 | `SELECT order_items.id AS order_items_id, order_items.order_id AS order_items_order_id, order_items.product_id AS order_…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 2,293 | 1.0 | 0.014 | 31.811 | `SELECT products.id AS products_id, products.name AS products_name, products.price AS products_price, products.stock AS …` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 133.96 | 13396.022 | `UPDATE products SET stock=$1::INTEGER WHERE products.id = $2::INTEGER` |
| 100 | 1.0 | 0.159 | 15.93 | `INSERT INTO orders (user_id, status) VALUES ($1::INTEGER, $2::VARCHAR) RETURNING orders.id, orders.created_at` |
| 100 | 1.0 | 0.155 | 15.482 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1::INTEGER, $2::INTEGER, $3::INTEGER, $4:…` |
| 100 | 1.0 | 0.018 | 1.762 | `SELECT products.id AS products_id, products.name AS products_name, products.price AS products_price, products.stock AS …` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 117.594 | 11759.441 | `UPDATE products SET stock=$1::INTEGER WHERE products.id = $2::INTEGER` |
| 100 | 1.0 | 0.101 | 10.07 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1::INTEGER, $2::INTEGER, $3::INTEGER, $4:…` |
| 100 | 1.0 | 0.096 | 9.569 | `INSERT INTO orders (user_id, status) VALUES ($1::INTEGER, $2::VARCHAR) RETURNING orders.id, orders.created_at` |
| 100 | 1.0 | 0.018 | 1.773 | `SELECT products.id AS products_id, products.name AS products_name, products.price AS products_price, products.stock AS …` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 94 / 104 | 152 / 1,024 |  |  |
| orders-list | db | 43 / 54 | 365 / 1,024 | 20 (9) | 0 |
| product-detail | app | 93 / 110 | 153 / 1,024 |  |  |
| product-detail | db | 14 / 17 | 354 / 1,024 | 28 (1) | 0 |
| order-race | app | 32 / 32 | 157 / 1,024 |  |  |
| order-race | db | 12 / 12 | 365 / 1,024 | 30 (21) | 21 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ violated | stock_after=99990, stock_before=100000, orders_created=100, sold_during_run=100 |
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
