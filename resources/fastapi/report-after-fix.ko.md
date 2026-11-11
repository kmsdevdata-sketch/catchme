# catchme 리포트 — after · 2026-11-11T14:17:20+00:00

한계점 탐색은 실행하지 않았습니다 (`catchme breakpoint`).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🟠 높음 `order-race`에서 커넥션 풀 포화: 활성 커넥션 최대 29개, 풀 크기 5
- 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 96% / 최대 105% (한도 0.5 vCPU 기준)
- 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 93% / 최대 107% (한도 0.5 vCPU 기준)
- 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 29개 (5회 관측), 데드락 0
- 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 21개 (2회 관측), 데드락 0

## 실행 조건

| | |
|---|---|
| 프로필 | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| 앱 | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| 앱↔DB 지연 | 1.0 ms (jitter 0 ms) |
| DB 풀 크기 (앱 프로세스당) | 5 |
| 데이터 | users 1,000, products 1,000, orders 1,000,000, order_items 2,000,000 (시드 42) |
| 인증 | 시딩한 테스트 계정 + 실제 로그인 API (인증 비용 포함) |
| 목표 | p95 ≤ 500 ms, errors ≤ 1.0% |

## 결과

| 시나리오 | 부하 | p50 | p95 | p99 | req/s | 에러율 | 요청당 쿼리 |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 214.2 | **497.4** | 598.0 | 134.6 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 196.0 | **403.0** | 500.2 | 143.5 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 907.8 | **1,384.6** | 1,424.1 | 69.1 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 409.8 | **494.8** | 500.4 | 197.6 | 0.00% | 1.6 |

**인증 비용**: 50 logins, p50 900.0 ms, p95 1,118.8 ms

## 병목 원인 후보

### 1. 🟠 높음 `order-race`에서 커넥션 풀 포화: 활성 커넥션 최대 29개, 풀 크기 5
- 근거: avg active 13.8, p95 1,384.6 ms, 5xx 0
- 수정 방향: 트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정

### 2. 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 96% / 최대 105% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 3. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 93% / 최대 107% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 4. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 29개 (5회 관측), 데드락 0
- 근거: 실행 중 PostgreSQL이 기록한 100 ms 이상 락 대기 9건
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 5. 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 21개 (2회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

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

## 리소스

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

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ 유지 | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ 유지 | stock_after=0, stock_before=10, sold_during_run=10 |

## 수정 전후 비교

| 시나리오 | 지표 | 수정 전 | 수정 후 | 변화 |
|---|---|---:|---:|---:|
| orders-list | 요청당 쿼리 수 | 61.7 | 2.0 | -97% |
| orders-list | p95 (ms) | 2,049.9 | 497.4 | -76% |
| orders-list | 에러율 | 0.00% | 0.00% |  |
| orders-list | 처리량 (req/s) | 19.1 | 134.6 | +604% |
| product-detail | 요청당 쿼리 수 | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 490.7 | 403.0 | -18% |
| product-detail | 에러율 | 0.00% | 0.00% |  |
| product-detail | 처리량 (req/s) | 113.6 | 143.5 | +26% |
| order-race | 요청당 쿼리 수 | 7.0 | 7.0 | +0% |
| order-race | p95 (ms) | 1,129.2 | 1,384.6 | +23% |
| order-race | 에러율 | 0.00% | 0.00% |  |
| order-race | 처리량 (req/s) | 83.9 | 69.1 | -18% |
| order-race | 불변 조건: stock_consistency | ❌ 위반 | ✅ 유지 | |
| order-race-low-stock | 요청당 쿼리 수 | 7.0 | 1.6 | -77% |
| order-race-low-stock | p95 (ms) | 836.0 | 494.8 | -41% |
| order-race-low-stock | 에러율 | 0.00% | 0.00% |  |
| order-race-low-stock | 처리량 (req/s) | 114.7 | 197.6 | +72% |
| order-race-low-stock | 불변 조건: no_oversell | ❌ 위반 | ✅ 유지 | |


## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | JVM 등 런타임 설정은 사용자가 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | MVP 미지원 (v2) | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
