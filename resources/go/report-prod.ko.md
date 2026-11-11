# catchme 리포트 — prod · 2026-11-11T14:48:17+00:00

**이 사양은 `orders-list` 기준 동시 10요청에서 이미 목표를 넘깁니다** (p95 ≤ 500 ms, 에러율 ≤ 1.0%).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 81.4개, 한 쿼리가 요청당 60.4번 실행
- 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 🟠 높음 `ramp-orders`에서 N+1 의심: 요청당 쿼리 82.4개, 한 쿼리가 요청당 61.4번 실행
- 🟡 중간 `orders-list` p95 1966 ms가 목표 500 ms 초과

## 실행 조건

| | |
|---|---|
| 프로필 | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| 앱 | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| 앱↔DB 지연 | 1.0 ms (jitter 0 ms) |
| DB 풀 크기 (앱 프로세스당) | None |
| 데이터 | users 10,000, products 2,000, orders 1,000,000, order_items 3,000,000 (시드 42) |
| 인증 | 시딩한 테스트 계정 + 실제 로그인 API (인증 비용 포함) |
| 목표 | p95 ≤ 500 ms, errors ≤ 1.0% |

## 결과

| 시나리오 | 부하 | p50 | p95 | p99 | req/s | 에러율 | 요청당 쿼리 |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 1,464.9 | **1,966.3** | 2,616.1 | 20.0 | 0.00% | 81.4 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 0.4 | **1.4** | 62.0 | 19,208.7 | 0.00% | 0.0 |
| ramp-orders | ramp 20→80→160 VUs | 2,862.8 | **6,982.0** | 7,796.7 | 19.7 | 0.00% | 82.4 |
| order-race | 100 VUs × 1 (simultaneous) | 260.3 | **294.4** | 300.2 | 319.3 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 229.7 | **246.0** | 248.5 | 380.3 | 0.00% | 7.0 |

**인증 비용**: 50 logins, p50 704.7 ms, p95 997.7 ms

| VUs | p95 (ms) | 에러율 | req/s | |
|---:|---:|---:|---:|---|
| 10 | 557.0 | 0.00% | 22.4 | ❌ |

## 병목 원인 후보

### 1. 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 근거: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99998, stock_before=100000, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0

### 2. 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 근거: 
    - units sold never exceed the starting stock (product 2)
    - stock_after=8, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0

### 3. 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 81.4개, 한 쿼리가 요청당 60.4번 실행
- 근거: `SELECT name FROM products WHERE id = $1` — 37,097 calls / 614 requests, mean 0.007 ms

### 4. 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 근거: 
    - `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` — mean 22.0 ms × 614 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- 수정 방향: 필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)

### 5. 🟠 높음 `ramp-orders`에서 N+1 의심: 요청당 쿼리 82.4개, 한 쿼리가 요청당 61.4번 실행
- 근거: `SELECT name FROM products WHERE id = $1` — 77,073 calls / 1,256 requests, mean 0.007 ms

### 6. 🟡 중간 `orders-list` p95 1966 ms가 목표 500 ms 초과

### 7. 🟡 중간 `ramp-orders` p95 6982 ms가 목표 500 ms 초과

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

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

## 리소스

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

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ 위반 | stock_after=99998, stock_before=100000, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2) | ❌ 위반 | stock_after=8, stock_before=10, sold_during_run=100 |

## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | 런타임 설정(힙 크기, GC, 스레드·워커 수)은 운영과 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | 재현하지 않음 | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
