# catchme 리포트 — prod · 2026-11-11T13:42:47+00:00

**이 사양은 `orders-list` 기준 동시 20요청까지** 버팁니다 (p95 ≤ 500 ms, 에러율 ≤ 1.0%).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 62.9개, 한 쿼리가 요청당 41.9번 실행
- 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 🟠 높음 `orders-list`에서 커넥션 풀 포화: 활성 커넥션 최대 10개, 풀 크기 10
- 🟡 중간 `orders-list`에서 db CPU가 한도에 붙음: 평균 91% / 최대 102% (한도 2 vCPU 기준)

## 실행 조건

| | |
|---|---|
| 프로필 | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| 앱 | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| 앱↔DB 지연 | 1.0 ms (jitter 0 ms) |
| DB 풀 크기 (앱 프로세스당) | 10 |
| 데이터 | users 1,000, products 1,000, orders 1,000,000, order_items 2,000,000 (시드 42) |
| 인증 | 시딩한 테스트 계정 + 실제 로그인 API (인증 비용 포함) |
| 목표 | p95 ≤ 500 ms, errors ≤ 1.0% |

## 결과

| 시나리오 | 부하 | p50 | p95 | p99 | req/s | 에러율 | 요청당 쿼리 |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 734.9 | **1,232.2** | 1,640.5 | 37.4 | 0.00% | 62.9 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 7.3 | **46.8** | 73.3 | 2,644.0 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 435.2 | **536.6** | 538.9 | 179.8 | 0.00% | 7.2 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 575.0 | **765.0** | 765.4 | 126.9 | 0.00% | 7.2 |

**인증 비용**: 50 logins, p50 632.0 ms, p95 894.0 ms

| VUs | p95 (ms) | 에러율 | req/s | |
|---:|---:|---:|---:|---|
| 5 | 220.7 | 0.00% | 31.6 | ✅ |
| 10 | 267.4 | 0.00% | 50.4 | ✅ |
| 20 | 489.0 | 0.00% | 50.5 | ✅ |
| 22 | 565.0 | 0.00% | 50.1 | ❌ |
| 25 | 667.9 | 0.00% | 50.6 | ❌ |
| 30 | 895.4 | 0.00% | 49.0 | ❌ |
| 40 | 1,224.2 | 0.00% | 48.6 | ❌ |

## 병목 원인 후보

### 1. 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 근거: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99993, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: QueryBuilder `update().set({ stock: () => 'stock - :q' }).where('id = :id AND stock >= :q')` and check `affected`

### 2. 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 근거: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=3, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: QueryBuilder `update().set({ stock: () => 'stock - :q' }).where('id = :id AND stock >= :q')` and check `affected`

### 3. 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 62.9개, 한 쿼리가 요청당 41.9번 실행
- 근거: `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Product"."stock" AS "Product_stock" FROM "pro…` — 47,513 calls / 1,135 requests, mean 0.01 ms
- 수정 방향: `relations: { items: { product: true } }` or QueryBuilder `leftJoinAndSelect`

### 4. 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 근거: 
    - `SELECT "Order"."id" AS "Order_id", "Order"."user_id" AS "Order_user_id", "Order"."status" AS "Order_status", "Order"."created_at" AS "Order_created_at" FROM "o…` — mean 36.51 ms × 1,135 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- 수정 방향: 필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)

### 5. 🟠 높음 `orders-list`에서 커넥션 풀 포화: 활성 커넥션 최대 10개, 풀 크기 10
- 근거: avg active 1.1, p95 1,232.2 ms, 5xx 0
- 수정 방향: 트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정

### 6. 🟡 중간 `orders-list`에서 db CPU가 한도에 붙음: 평균 91% / 최대 102% (한도 2 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 7. 🟡 중간 `orders-list` p95 1232 ms가 목표 500 ms 초과

### 8. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 91% / 최대 101% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 9. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 1개 (1회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 10. 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 2개 (1회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 11. 🟡 중간 `order-race-low-stock`에서 app CPU가 한도에 붙음: 평균 87% / 최대 87% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 1,135 | 1.0 | 36.514 | 41443.266 | `SELECT "Order"."id" AS "Order_id", "Order"."user_id" AS "Order_user_id", "Order"."status" AS "Order_status", "Order"."c…` |
| 22,700 | 20.0 | 0.022 | 502.56 | `SELECT "OrderItem"."id" AS "OrderItem_id", "OrderItem"."order_id" AS "OrderItem_order_id", "OrderItem"."product_id" AS …` |
| 47,513 | 41.9 | 0.01 | 462.079 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 52,971 | 1.0 | 0.005 | 250.146 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 25 | 0.2 | 5.857 | 146.424 | `UPDATE "products" SET "stock" = $1 WHERE "id" IN ($2)` |
| 100 | 1.0 | 0.147 | 14.738 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 100 | 1.0 | 0.129 | 12.872 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 100 | 1.0 | 0.011 | 1.11 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |
| 100 | 1.0 | 0.01 | 1.023 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 25 | 0.2 | 11.213 | 280.332 | `UPDATE "products" SET "stock" = $1 WHERE "id" IN ($2)` |
| 100 | 1.0 | 0.074 | 7.394 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 100 | 1.0 | 0.052 | 5.152 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 100 | 1.0 | 0.029 | 2.93 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |
| 100 | 1.0 | 0.01 | 1.016 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 64 / 98 | 62 / 1,024 |  |  |
| orders-list | db | 91 / 102 | 347 / 1,024 | 11 (10) | 0 |
| product-detail | app | 91 / 101 | 65 / 1,024 |  |  |
| product-detail | db | 13 / 15 | 337 / 1,024 | 10 (2) | 0 |
| order-race | app | 23 / 23 | 65 / 1,024 |  |  |
| order-race | db | 5 / 5 | 338 / 1,024 | 10 (1) | 1 |
| order-race-low-stock | app | 87 / 87 | 63 / 1,024 |  |  |
| order-race-low-stock | db | 8 / 8 | 338 / 1,024 | 10 (2) | 2 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ 위반 | stock_after=99993, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ 위반 | stock_after=3, stock_before=10, sold_during_run=100 |

## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | JVM 등 런타임 설정은 사용자가 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | MVP 미지원 (v2) | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
