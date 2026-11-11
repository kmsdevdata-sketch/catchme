# catchme report — prod · 2026-11-11T14:23:02+00:00

**This spec holds up to 13 concurrent requests** on `orders-list` (p95 ≤ 500 ms, errors ≤ 1.0%).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- 🟠 high Possible N+1 on `orders-list`: 62.1 queries/request; one statement runs 41.1× per request
- 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- 🟡 medium p95 1175 ms on `orders-list` exceeds target 500 ms
- 🟡 medium app CPU pinned at its limit on `product-detail`: avg 94% / max 106% of 0.5 vCPU

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
| orders-list | 30 VUs × 30s (+20s warm-up) | 879.5 | **1,174.8** | 1,295.0 | 32.8 | 0.00% | 62.1 |
| product-detail | 30 VUs × 20s (+20s warm-up) | 15.1 | **45.5** | 60.8 | 1,548.8 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 3,458.1 | **3,864.7** | 3,887.4 | 25.7 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 1,139.0 | **1,546.7** | 1,552.8 | 63.5 | 0.00% | 6.8 |

**Auth cost**: 50 logins, p50 1,451.0 ms, p95 4,421.9 ms

| VUs | p95 (ms) | Errors | req/s | |
|---:|---:|---:|---:|---|
| 5 | 296.3 | 0.00% | 22.5 | ✅ |
| 10 | 321.4 | 0.00% | 39.1 | ✅ |
| 12 | 399.2 | 0.00% | 38.5 | ✅ |
| 13 | 429.0 | 0.00% | 38.2 | ✅ |
| 15 | 601.6 | 0.00% | 35.9 | ❌ |
| 20 | 629.4 | 0.00% | 38.5 | ❌ |

## Bottleneck candidates

### 1. 🔴 critical Race condition: invariant `stock_consistency` violated on `order-race`
- Evidence: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99988, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- Fix direction: atomic `UPDATE ... SET stock = stock - :q WHERE stock >= :q`, `@Version`, or `PESSIMISTIC_WRITE`

### 2. 🔴 critical Race condition: invariant `no_oversell` violated on `order-race-low-stock`
- Evidence: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=0, stock_before=10, sold_during_run=97
    - HTTP ok 97, expected 3, 4xx 0, 5xx 0
- Fix direction: atomic `UPDATE ... SET stock = stock - :q WHERE stock >= :q`, `@Version`, or `PESSIMISTIC_WRITE`

### 3. 🟠 high Possible N+1 on `orders-list`: 62.1 queries/request; one statement runs 41.1× per request
- Evidence: `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` — 41,584 calls / 1,011 requests, mean 0.007 ms
- Fix direction: fetch join / `@EntityGraph`, or `hibernate.default_batch_fetch_size`

### 4. 🟠 high Possible missing index: Seq Scan on `orders` (~1,000,000 rows) with filter `(user_id = $1)`
- Evidence: 
    - `select o1_0.id,o1_0.created_at,o1_0.status,o1_0.user_id from orders o1_0 where o1_0.user_id=$1 order by o1_0.created_at desc fetch first $2 rows only` — mean 21.66 ms × 1,011 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- Fix direction: index on the filter columns (check the WHERE / ORDER BY of the statement)

### 5. 🟡 medium p95 1175 ms on `orders-list` exceeds target 500 ms

### 6. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 94% / max 106% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 7. 🟡 medium Lock contention on `order-race`: up to 5 sessions waiting on locks (5 samples), deadlocks 0
- Evidence: 5 lock waits of 100 ms or longer logged by PostgreSQL during the run
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 8. 🟡 medium Lock contention on `order-race-low-stock`: up to 5 sessions waiting on locks (6 samples), deadlocks 0
- Evidence: 4 lock waits of 100 ms or longer logged by PostgreSQL during the run
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 9. 🟡 medium app CPU pinned at its limit on `order-race-low-stock`: avg 102% / max 102% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 1,011 | 1.0 | 21.659 | 21897.602 | `select o1_0.id,o1_0.created_at,o1_0.status,o1_0.user_id from orders o1_0 where o1_0.user_id=$1 order by o1_0.created_at…` |
| 20,220 | 20.0 | 0.02 | 396.315 | `select oi1_0.id,oi1_0.order_id,oi1_0.product_id,oi1_0.quantity,oi1_0.unit_price from order_items oi1_0 where oi1_0.orde…` |
| 41,584 | 41.1 | 0.007 | 294.655 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 31,002 | 1.0 | 0.012 | 366.85 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 61.342 | 6134.214 | `update products set name=$1,price=$2,stock=$3 where id=$4` |
| 100 | 1.0 | 0.456 | 45.577 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 100 | 1.0 | 0.259 | 25.875 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 100 | 1.0 | 0.042 | 4.242 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 97 | 1.0 | 71.779 | 6962.55 | `update products set name=$1,price=$2,stock=$3 where id=$4` |
| 97 | 1.0 | 0.23 | 22.282 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 97 | 1.0 | 0.114 | 11.013 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 100 | 1.0 | 0.033 | 3.315 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 63 / 101 | 347 / 1,024 |  |  |
| orders-list | db | 76 / 91 | 344 / 1,024 | 10 (5) | 0 |
| product-detail | app | 94 / 106 | 354 / 1,024 |  |  |
| product-detail | db | 15 / 17 | 340 / 1,024 | 10 (2) | 0 |
| order-race | app | 72 / 100 | 418 / 1,024 |  |  |
| order-race | db | 5 / 8 | 341 / 1,024 | 10 (6) | 5 |
| order-race-low-stock | app | 102 / 102 | 427 / 1,024 |  |  |
| order-race-low-stock | db | 9 / 9 | 342 / 1,024 | 10 (5) | 5 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ violated | stock_after=99988, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ violated | stock_after=0, stock_before=10, sold_during_run=97 |

## Limitations

| Item | Approach | Limitation |
|---|---|---|
| CPU | Docker `cpus` limit | clock/generation differences and Fargate variance not modeled |
| Memory | `mem_limit` | runtime settings (JVM heap etc.) must match production |
| Network latency | Toxiproxy latency/jitter | cross-AZ variance and packet loss only approximated |
| Disk I/O | not modeled (v2) | EBS/RDS storage IOPS not reflected |
| RDS burst credits | `cpu_mode` switch only | credit depletion over time not modeled |
| Data | synthetic data | real distributions and hot keys may differ |
