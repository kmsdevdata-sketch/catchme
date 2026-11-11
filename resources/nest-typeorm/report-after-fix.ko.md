# catchme 리포트 — after · 2026-11-11T13:48:01+00:00

한계점 탐색은 실행하지 않았습니다 (`catchme breakpoint`).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🟠 높음 `order-race`에서 커넥션 풀 포화: 활성 커넥션 최대 10개, 풀 크기 10
- 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 99% / 최대 101% (한도 0.5 vCPU 기준)
- 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 90% / 최대 103% (한도 0.5 vCPU 기준)
- 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 9개 (5회 관측), 데드락 0
- 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 9개 (1회 관측), 데드락 0

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 81.5 | **111.0** | 173.1 | 420.1 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 8.0 | **42.9** | 73.5 | 2,677.8 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 692.7 | **1,169.0** | 1,208.4 | 80.8 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 352.4 | **375.3** | 376.9 | 247.3 | 0.00% | 1.6 |

**인증 비용**: 50 logins, p50 670.7 ms, p95 750.5 ms

## 병목 원인 후보

### 1. 🟠 높음 `order-race`에서 커넥션 풀 포화: 활성 커넥션 최대 10개, 풀 크기 10
- 근거: avg active 4.9, p95 1,169.0 ms, 5xx 0
- 수정 방향: 트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정

### 2. 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 99% / 최대 101% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 3. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 90% / 최대 103% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 4. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 9개 (5회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 5. 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 9개 (1회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 12,626 | 1.0 | 0.15 | 1896.682 | `SELECT DISTINCT "distinctAlias"."Order_id" AS "ids_Order_id", "distinctAlias"."Order_created_at" FROM (SELECT "Order"."…` |
| 12,626 | 1.0 | 0.147 | 1850.134 | `SELECT "Order"."id" AS "Order_id", "Order"."user_id" AS "Order_user_id", "Order"."status" AS "Order_status", "Order"."c…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 53,759 | 1.0 | 0.004 | 210.724 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 97.365 | 9736.453 | `UPDATE "products" SET "stock" = "stock" - $1 WHERE "id" = $2 AND "stock" >= $1` |
| 100 | 1.0 | 0.209 | 20.92 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 100 | 1.0 | 0.118 | 11.822 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 100 | 1.0 | 0.014 | 1.365 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 25.879 | 2587.94 | `UPDATE "products" SET "stock" = "stock" - $1 WHERE "id" = $2 AND "stock" >= $1` |
| 10 | 0.1 | 0.184 | 1.841 | `INSERT INTO "orders"("user_id", "status", "created_at") VALUES ($1, $2, DEFAULT) RETURNING "id", "created_at"` |
| 10 | 0.1 | 0.119 | 1.192 | `INSERT INTO "order_items"("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "id"` |
| 10 | 0.1 | 0.026 | 0.26 | `SELECT "Product"."id" AS "Product_id", "Product"."name" AS "Product_name", "Product"."price" AS "Product_price", "Produ…` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 99 / 101 | 65 / 1,024 |  |  |
| orders-list | db | 16 / 18 | 346 / 1,024 | 10 (3) | 0 |
| product-detail | app | 90 / 103 | 66 / 1,024 |  |  |
| product-detail | db | 13 / 17 | 345 / 1,024 | 10 (2) | 0 |
| order-race | app | 34 / 34 | 65 / 1,024 |  |  |
| order-race | db | 10 / 10 | 348 / 1,024 | 10 (10) | 9 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ 유지 | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ 유지 | stock_after=0, stock_before=10, sold_during_run=10 |

## 수정 전후 비교

| 시나리오 | 지표 | 수정 전 | 수정 후 | 변화 |
|---|---|---:|---:|---:|
| orders-list | 요청당 쿼리 수 | 62.9 | 2.0 | -97% |
| orders-list | p95 (ms) | 1,232.2 | 111.0 | -91% |
| orders-list | 에러율 | 0.00% | 0.00% |  |
| orders-list | 처리량 (req/s) | 37.4 | 420.1 | +1022% |
| product-detail | 요청당 쿼리 수 | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 46.8 | 42.9 | -8% |
| product-detail | 에러율 | 0.00% | 0.00% |  |
| product-detail | 처리량 (req/s) | 2,644.0 | 2,677.8 | +1% |
| order-race | 요청당 쿼리 수 | 7.2 | 7.0 | -3% |
| order-race | p95 (ms) | 536.6 | 1,169.0 | +118% |
| order-race | 에러율 | 0.00% | 0.00% |  |
| order-race | 처리량 (req/s) | 179.8 | 80.8 | -55% |
| order-race | 불변 조건: stock_consistency | ❌ 위반 | ✅ 유지 | |
| order-race-low-stock | 요청당 쿼리 수 | 7.2 | 1.6 | -78% |
| order-race-low-stock | p95 (ms) | 765.0 | 375.3 | -51% |
| order-race-low-stock | 에러율 | 0.00% | 0.00% |  |
| order-race-low-stock | 처리량 (req/s) | 126.9 | 247.3 | +95% |
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
