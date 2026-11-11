# catchme report — prod · 2026-11-11T14:48:17+00:00

**This spec misses the target already at 10 concurrent requests** on `orders-list` (p95 ≤ 500 ms, errors ≤ 1.0%).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- 🟠 high Possible N+1 on `orders-list`: 81.4 queries/request; one statement runs 60.4× per request
- 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- 🟠 high Possible N+1 on `ramp-orders`: 82.4 queries/request; one statement runs 61.4× per request
- 🟡 medium p95 1966 ms on `orders-list` exceeds target 500 ms

## Conditions

| | |
|---|---|
| Profile | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| App | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| App↔DB latency | 1.0 ms (jitter 0 ms) |
| DB pool size (per app process) | None |
| Data | users 10,000, products 2,000, orders 1,000,000, order_items 3,000,000 (seed 42) |
| Auth | seeded test accounts + real login API (auth cost included) |
| Targets | p95 ≤ 500 ms, errors ≤ 1.0% |

## Results

| Run | Load | p50 | p95 | p99 | req/s | Errors | Queries/req |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 1,464.9 | **1,966.3** | 2,616.1 | 20.0 | 0.00% | 81.4 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 0.4 | **1.4** | 62.0 | 19,208.7 | 0.00% | 0.0 |
| ramp-orders | ramp 20→80→160 VUs | 2,862.8 | **6,982.0** | 7,796.7 | 19.7 | 0.00% | 82.4 |
| order-race | 100 VUs × 1 (simultaneous) | 260.3 | **294.4** | 300.2 | 319.3 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 229.7 | **246.0** | 248.5 | 380.3 | 0.00% | 7.0 |

**Auth cost**: 50 logins, p50 704.7 ms, p95 997.7 ms

| VUs | p95 (ms) | Errors | req/s | |
|---:|---:|---:|---:|---|
| 10 | 557.0 | 0.00% | 22.4 | ❌ |

## Bottleneck candidates

### 1. 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- Evidence: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99998, stock_before=100000, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0

### 2. 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- Evidence: 
    - units sold never exceed the starting stock (product 2)
    - stock_after=8, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0

### 3. 🟠 high Possible N+1 on `orders-list`: 81.4 queries/request; one statement runs 60.4× per request
- Evidence: `SELECT name FROM products WHERE id = $1` — 37,097 calls / 614 requests, mean 0.007 ms

### 4. 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- Evidence: 
    - `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` — mean 22.0 ms × 614 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- Fix direction: index on the filter columns (check the WHERE / ORDER BY of the statement)

### 5. 🟠 high Possible N+1 on `ramp-orders`: 82.4 queries/request; one statement runs 61.4× per request
- Evidence: `SELECT name FROM products WHERE id = $1` — 77,073 calls / 1,256 requests, mean 0.007 ms

### 6. 🟡 medium p95 1966 ms on `orders-list` exceeds target 500 ms

### 7. 🟡 medium p95 6982 ms on `ramp-orders` exceeds target 500 ms

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 614 | 1.0 | 22.0 | 13508.058 | `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` |
| 37,097 | 60.4 | 0.007 | 249.752 | `SELECT name FROM products WHERE id = $1` |
| 12,280 | 20.0 | 0.017 | 206.962 | `SELECT product_id, quantity, unit_price FROM order_items WHERE order_id = $1` |

**ramp-orders**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 1,256 | 1.0 | 16.241 | 20399.19 | `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` |
| 77,073 | 61.4 | 0.007 | 523.209 | `SELECT name FROM products WHERE id = $1` |
| 25,120 | 20.0 | 0.018 | 440.809 | `SELECT product_id, quantity, unit_price FROM order_items WHERE order_id = $1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.392 | 39.191 | `UPDATE products SET stock = $1 WHERE id = $2` |
| 100 | 1.0 | 0.112 | 11.165 | `INSERT INTO orders (user_id, status) VALUES ($1, $2) RETURNING id` |
| 100 | 1.0 | 0.063 | 6.345 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)` |
| 100 | 1.0 | 0.016 | 1.645 | `SELECT stock, price FROM products WHERE id = $1` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.303 | 30.329 | `UPDATE products SET stock = $1 WHERE id = $2` |
| 100 | 1.0 | 0.055 | 5.452 | `INSERT INTO orders (user_id, status) VALUES ($1, 'PAID') RETURNING id` |
| 100 | 1.0 | 0.044 | 4.358 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)` |
| 100 | 1.0 | 0.013 | 1.257 | `SELECT stock, price FROM products WHERE id = $1` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 13 / 16 | 11 / 1,024 |  |  |
| orders-list | db | 48 / 61 | 326 / 1,024 | 4 (4) | 0 |
| product-detail | app | 101 / 103 | 12 / 1,024 |  |  |
| product-detail | db | 4 / 5 | 325 / 1,024 | 4 (0) | 0 |
| ramp-orders | app | 14 / 24 | 16 / 1,024 |  |  |
| ramp-orders | db | 52 / 73 | 332 / 1,024 | 4 (4) | 0 |
| order-race | app | 1 / 1 | 16 / 1,024 |  |  |
| order-race | db | 6 / 6 | 322 / 1,024 | 4 (0) | 0 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ violated | stock_after=99998, stock_before=100000, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2) | ❌ violated | stock_after=8, stock_before=10, sold_during_run=100 |

## Limitations

| Item | Approach | Limitation |
|---|---|---|
| CPU | Docker `cpus` limit | clock/generation differences and Fargate variance not modeled |
| Memory | `mem_limit` | runtime settings (heap size, GC, thread/worker counts) must match production |
| Network latency | Toxiproxy latency/jitter | cross-AZ variance and packet loss only approximated |
| Disk I/O | not modeled | EBS/RDS storage IOPS not reflected |
| RDS burst credits | `cpu_mode` switch only | credit depletion over time not modeled |
| Data | synthetic data | real distributions and hot keys may differ |
