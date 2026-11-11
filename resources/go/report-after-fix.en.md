# catchme report — after · 2026-11-11T14:52:50+00:00

Breaking point not measured (run `catchme breakpoint`).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🟡 medium Lock contention on `order-race`: up to 3 sessions waiting on locks (3 samples), deadlocks 0

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 40.1 | **46.7** | 50.6 | 743.2 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 0.4 | **1.3** | 61.7 | 20,862.4 | 0.00% | 0.0 |
| ramp-orders | ramp 20→80→160 VUs | 73.4 | **199.6** | 215.9 | 704.7 | 0.00% | 2.0 |
| order-race | 100 VUs × 1 (simultaneous) | 371.0 | **669.2** | 694.8 | 139.1 | 0.00% | 6.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 175.0 | **262.1** | 270.0 | 353.6 | 0.00% | 2.4 |

**Auth cost**: 50 logins, p50 691.8 ms, p95 965.5 ms

## Bottleneck candidates

### 1. 🟡 medium Lock contention on `order-race`: up to 3 sessions waiting on locks (3 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 22,321 | 1.0 | 0.427 | 9530.092 | `SELECT oi.order_id, p.name, oi.quantity, oi.unit_price FROM order_items oi JOIN products p ON p.id = oi.product_id WHER…` |
| 22,321 | 1.0 | 0.043 | 952.725 | `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` |

**ramp-orders**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 42,395 | 1.0 | 0.424 | 17981.091 | `SELECT oi.order_id, p.name, oi.quantity, oi.unit_price FROM order_items oi JOIN products p ON p.id = oi.product_id WHER…` |
| 42,395 | 1.0 | 0.043 | 1819.511 | `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 16.634 | 1663.433 | `UPDATE products SET stock = stock - $1 WHERE id = $2 AND stock >= $1 RETURNING price` |
| 100 | 1.0 | 0.093 | 9.316 | `INSERT INTO orders (user_id, status) VALUES ($1, $2) RETURNING id` |
| 100 | 1.0 | 0.069 | 6.884 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 1.724 | 172.404 | `UPDATE products SET stock = stock - $1 WHERE id = $2 AND stock >= $1 RETURNING price` |
| 10 | 0.1 | 0.075 | 0.75 | `INSERT INTO orders (user_id, status) VALUES ($1, 'PAID') RETURNING id` |
| 10 | 0.1 | 0.057 | 0.574 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)` |
| 90 | 0.9 | 0.006 | 0.537 | `SELECT EXISTS (SELECT $2 FROM products WHERE id = $1)` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 37 / 41 | 11 / 1,024 |  |  |
| orders-list | db | 28 / 30 | 327 / 1,024 | 4 (4) | 0 |
| product-detail | app | 101 / 104 | 12 / 1,024 |  |  |
| product-detail | db | 3 / 5 | 326 / 1,024 | 4 (0) | 0 |
| ramp-orders | app | 39 / 45 | 18 / 1,024 |  |  |
| ramp-orders | db | 28 / 34 | 328 / 1,024 | 4 (4) | 0 |
| order-race | app | 0 / 0 | 17 / 1,024 |  |  |
| order-race | db | 8 / 8 | 325 / 1,024 | 4 (3) | 3 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ holds | stock_after=99900, stock_before=100000, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2) | ✅ holds | stock_after=0, stock_before=10, sold_during_run=10 |

## Before / after fix

| Run | Metric | Before | After | Change |
|---|---|---:|---:|---:|
| orders-list | queries/request | 81.4 | 2.0 | -98% |
| orders-list | p95 (ms) | 1,966.3 | 46.7 | -98% |
| orders-list | error rate | 0.00% | 0.00% |  |
| orders-list | req/s | 20.0 | 743.2 | +3614% |
| product-detail | queries/request | 0.0 | 0.0 | — |
| product-detail | p95 (ms) | 1.4 | 1.3 | -8% |
| product-detail | error rate | 0.00% | 0.00% |  |
| product-detail | req/s | 19,208.7 | 20,862.4 | +9% |
| ramp-orders | queries/request | 82.4 | 2.0 | -98% |
| ramp-orders | p95 (ms) | 6,982.0 | 199.6 | -97% |
| ramp-orders | error rate | 0.00% | 0.00% |  |
| ramp-orders | req/s | 19.7 | 704.7 | +3474% |
| order-race | queries/request | 7.0 | 6.0 | -14% |
| order-race | p95 (ms) | 294.4 | 669.2 | +127% |
| order-race | error rate | 0.00% | 0.00% |  |
| order-race | req/s | 319.3 | 139.1 | -56% |
| order-race | invariant: stock_consistency | ❌ violated | ✅ ok | |
| order-race-low-stock | queries/request | 7.0 | 2.4 | -66% |
| order-race-low-stock | p95 (ms) | 246.0 | 262.1 | +7% |
| order-race-low-stock | error rate | 0.00% | 0.00% |  |
| order-race-low-stock | req/s | 380.3 | 353.6 | -7% |
| order-race-low-stock | invariant: no_oversell | ❌ violated | ✅ ok | |


## Limitations

| Item | Approach | Limitation |
|---|---|---|
| CPU | Docker `cpus` limit | clock/generation differences and Fargate variance not modeled |
| Memory | `mem_limit` | runtime settings (heap size, GC, thread/worker counts) must match production |
| Network latency | Toxiproxy latency/jitter | cross-AZ variance and packet loss only approximated |
| Disk I/O | not modeled | EBS/RDS storage IOPS not reflected |
| RDS burst credits | `cpu_mode` switch only | credit depletion over time not modeled |
| Data | synthetic data | real distributions and hot keys may differ |
