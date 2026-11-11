# catchme 리포트 — prod · 2026-11-11T14:12:20+00:00

**이 사양은 `orders-list` 기준 동시 10요청까지** 버팁니다 (p95 ≤ 500 ms, 에러율 ≤ 1.0%).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 61.7개, 한 쿼리가 요청당 40.7번 실행
- 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 🟠 높음 `orders-list`에서 커넥션 풀 포화: 활성 커넥션 최대 9개, 풀 크기 5
- 🟠 높음 `order-race`에서 커넥션 풀 포화: 활성 커넥션 최대 21개, 풀 크기 5

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 1,711.7 | **2,049.9** | 2,628.4 | 19.1 | 0.00% | 61.7 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 242.5 | **490.7** | 781.3 | 113.6 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 894.7 | **1,129.2** | 1,183.5 | 83.9 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 625.1 | **836.0** | 853.2 | 114.7 | 0.00% | 7.0 |

**인증 비용**: 50 logins, p50 853.7 ms, p95 1,320.9 ms

| VUs | p95 (ms) | 에러율 | req/s | |
|---:|---:|---:|---:|---|
| 5 | 208.2 | 0.00% | 28.0 | ✅ |
| 10 | 487.1 | 0.00% | 27.2 | ✅ |
| 11 | 693.3 | 0.00% | 22.1 | ❌ |
| 12 | 692.9 | 0.00% | 22.2 | ❌ |
| 15 | 1,099.5 | 0.00% | 19.7 | ❌ |
| 20 | 1,703.3 | 0.00% | 17.7 | ❌ |

## 병목 원인 후보

### 1. 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 근거: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99990, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: `update(Product).where(Product.id == id, Product.stock >= q).values(stock=Product.stock - q)` and check `rowcount`

### 2. 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 근거: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=5, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: `update(Product).where(Product.id == id, Product.stock >= q).values(stock=Product.stock - q)` and check `rowcount`

### 3. 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 61.7개, 한 쿼리가 요청당 40.7번 실행
- 근거: `SELECT products.id AS products_id, products.name AS products_name, products.price AS products_price, products.stock AS products_stock FROM products WHERE produ…` — 24,148 calls / 593 requests, mean 0.007 ms
- 수정 방향: `options(selectinload(Order.items).joinedload(OrderItem.product))`

### 4. 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 근거: 
    - `SELECT orders.id, orders.user_id, orders.status, orders.created_at FROM orders WHERE orders.user_id = $1::INTEGER ORDER BY orders.created_at DESC LIMIT $2::INT…` — mean 17.32 ms × 593 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- 수정 방향: 필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)

### 5. 🟠 높음 `orders-list`에서 커넥션 풀 포화: 활성 커넥션 최대 9개, 풀 크기 5
- 근거: avg active 0.4, p95 2,049.9 ms, 5xx 0
- 수정 방향: 트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정

### 6. 🟠 높음 `order-race`에서 커넥션 풀 포화: 활성 커넥션 최대 21개, 풀 크기 5
- 근거: avg active 5.4, p95 1,129.2 ms, 5xx 0
- 수정 방향: 트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정

### 7. 🟠 높음 `order-race-low-stock`에서 커넥션 풀 포화: 활성 커넥션 최대 24개, 풀 크기 5
- 근거: avg active 8.3, p95 836.0 ms, 5xx 0
- 수정 방향: 트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정

### 8. 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 94% / 최대 104% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 9. 🟡 중간 `orders-list` p95 2050 ms가 목표 500 ms 초과

### 10. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 93% / 최대 110% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 11. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 21개 (3회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 12. 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 24개 (3회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

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

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 94 / 104 | 152 / 1,024 |  |  |
| orders-list | db | 43 / 54 | 365 / 1,024 | 20 (9) | 0 |
| product-detail | app | 93 / 110 | 153 / 1,024 |  |  |
| product-detail | db | 14 / 17 | 354 / 1,024 | 28 (1) | 0 |
| order-race | app | 32 / 32 | 157 / 1,024 |  |  |
| order-race | db | 12 / 12 | 365 / 1,024 | 30 (21) | 21 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ 위반 | stock_after=99990, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ 위반 | stock_after=5, stock_before=10, sold_during_run=100 |

## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | JVM 등 런타임 설정은 사용자가 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | MVP 미지원 (v2) | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
