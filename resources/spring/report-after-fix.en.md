# catchme report — after · 2026-11-11T14:28:52+00:00

Breaking point not measured (run `catchme breakpoint`).

> Results are a production **approximation** in local Docker — see Limitations.

## Summary

- 🟡 medium app CPU pinned at its limit on `orders-list`: avg 99% / max 102% of 0.5 vCPU
- 🟡 medium p95 512 ms on `orders-list` exceeds target 500 ms
- 🟡 medium app CPU pinned at its limit on `product-detail`: avg 95% / max 107% of 0.5 vCPU
- 🟡 medium Lock contention on `order-race`: up to 9 sessions waiting on locks (11 samples), deadlocks 0
- 🟡 medium Lock contention on `order-race-low-stock`: up to 8 sessions waiting on locks (1 samples), deadlocks 0

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
| orders-list | 30 VUs × 30s (+20s warm-up) | 206.6 | **511.7** | 796.6 | 115.7 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+20s warm-up) | 15.3 | **88.2** | 98.1 | 1,126.5 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 3,235.5 | **3,980.2** | 4,011.1 | 24.8 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 435.6 | **628.6** | 721.6 | 134.1 | 0.00% | 1.6 |

**Auth cost**: 50 logins, p50 1,393.8 ms, p95 3,720.9 ms

## Bottleneck candidates

### 1. 🟡 medium app CPU pinned at its limit on `orders-list`: avg 99% / max 102% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 2. 🟡 medium p95 512 ms on `orders-list` exceeds target 500 ms

### 3. 🟡 medium app CPU pinned at its limit on `product-detail`: avg 95% / max 107% of 0.5 vCPU
- Fix direction: profile the hot path (serialization, hashing, N+1 overhead) or size up

### 4. 🟡 medium Lock contention on `order-race`: up to 9 sessions waiting on locks (11 samples), deadlocks 0
- Evidence: 18 lock waits of 100 ms or longer logged by PostgreSQL during the run
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

### 5. 🟡 medium Lock contention on `order-race-low-stock`: up to 8 sessions waiting on locks (1 samples), deadlocks 0
- Fix direction: shorter transactions, consistent lock order, atomic updates instead of read-modify-write

## Analysis

_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._

## Heaviest statements

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 3,484 | 1.0 | 0.363 | 1263.581 | `select oi1_0.id,oi1_0.order_id,p1_0.id,p1_0.name,p1_0.price,p1_0.stock,oi1_0.product_id,oi1_0.quantity,oi1_0.unit_price…` |
| 3,484 | 1.0 | 0.077 | 266.759 | `select o1_0.id,o1_0.created_at,o1_0.status,o1_0.user_id from orders o1_0 where o1_0.user_id=$1 order by o1_0.created_at…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 22,544 | 1.0 | 0.01 | 221.034 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 251.869 | 25186.947 | `update products p1_0 set stock=(p1_0.stock-$1) where p1_0.id=$2 and p1_0.stock>=$3` |
| 100 | 1.0 | 0.154 | 15.386 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 100 | 1.0 | 0.099 | 9.886 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 100 | 1.0 | 0.012 | 1.161 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 20.549 | 2054.911 | `update products p1_0 set stock=(p1_0.stock-$1) where p1_0.id=$2 and p1_0.stock>=$3` |
| 10 | 0.1 | 0.104 | 1.043 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 10 | 0.1 | 0.056 | 0.559 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 10 | 0.1 | 0.019 | 0.193 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

## Resources

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 99 / 102 | 354 / 1,024 |  |  |
| orders-list | db | 10 / 13 | 347 / 1,024 | 10 (3) | 0 |
| product-detail | app | 95 / 107 | 377 / 1,024 |  |  |
| product-detail | db | 10 / 16 | 347 / 1,024 | 10 (2) | 0 |
| order-race | app | 63 / 95 | 441 / 1,024 |  |  |
| order-race | db | 7 / 8 | 350 / 1,024 | 10 (9) | 9 |

## Race verdicts

| Run | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ holds | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ holds | stock_after=0, stock_before=10, sold_during_run=10 |

## Before / after fix

| Run | Metric | Before | After | Change |
|---|---|---:|---:|---:|
| orders-list | queries/request | 62.1 | 2.0 | -97% |
| orders-list | p95 (ms) | 1,174.8 | 511.7 | -56% |
| orders-list | error rate | 0.00% | 0.00% |  |
| orders-list | req/s | 32.8 | 115.7 | +253% |
| product-detail | queries/request | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 45.5 | 88.2 | +94% |
| product-detail | error rate | 0.00% | 0.00% |  |
| product-detail | req/s | 1,548.8 | 1,126.5 | -27% |
| order-race | queries/request | 7.0 | 7.0 | +0% |
| order-race | p95 (ms) | 3,864.7 | 3,980.2 | +3% |
| order-race | error rate | 0.00% | 0.00% |  |
| order-race | req/s | 25.7 | 24.8 | -3% |
| order-race | invariant: stock_consistency | ❌ violated | ✅ ok | |
| order-race-low-stock | queries/request | 6.8 | 1.6 | -77% |
| order-race-low-stock | p95 (ms) | 1,546.7 | 628.6 | -59% |
| order-race-low-stock | error rate | 0.00% | 0.00% |  |
| order-race-low-stock | req/s | 63.5 | 134.1 | +111% |
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
