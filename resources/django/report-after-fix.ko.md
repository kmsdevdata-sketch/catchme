# catchme 리포트 — after · 2026-11-11T14:08:06+00:00

한계점 탐색은 실행하지 않았습니다 (`catchme breakpoint`).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🟠 높음 `orders-list`, `product-detail`, `order-race`, `order-race-low-stock`에서 요청마다 DB 커넥션을 새로 엶: 요청 100건에 세션 102개 (커넥션 풀 없음)

## 실행 조건

| | |
|---|---|
| 프로필 | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| 앱 | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| 앱↔DB 지연 | 1.0 ms (jitter 0 ms) |
| DB 풀 크기 (앱 프로세스당) | None |
| 데이터 | users 1,000, products 1,000, orders 1,000,000, order_items 2,000,000 (시드 42) |
| 인증 | 시딩한 테스트 계정 + 실제 로그인 API (인증 비용 포함) |
| 목표 | p95 ≤ 500 ms, errors ≤ 1.0% |

## 결과

| 시나리오 | 부하 | p50 | p95 | p99 | req/s | 에러율 | 요청당 쿼리 |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 287.8 | **308.9** | 322.8 | 103.4 | 0.00% | 3.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 236.8 | **256.7** | 274.8 | 125.8 | 0.00% | 2.0 |
| order-race | 100 VUs × 1 (simultaneous) | 750.7 | **1,320.6** | 1,382.1 | 70.5 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 545.7 | **976.6** | 1,015.1 | 96.3 | 0.00% | 2.6 |

**인증 비용**: 50 logins, p50 1,600.5 ms, p95 1,842.3 ms

## 병목 원인 후보

### 1. 🟠 높음 `orders-list`, `product-detail`, `order-race`, `order-race-low-stock`에서 요청마다 DB 커넥션을 새로 엶: 요청 100건에 세션 102개 (커넥션 풀 없음)
- 근거: 
    - 요청당 새 세션 1.01개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (orders-list)
    - 요청당 새 세션 1.00개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (product-detail)
    - 요청당 새 세션 1.02개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (order-race)
    - 요청당 새 세션 1.02개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (order-race-low-stock)
- 수정 방향: `CONN_MAX_AGE = 60` (+ `CONN_HEALTH_CHECKS = True`), or the psycopg pool (`OPTIONS: {"pool": True}`, Django 5.1+)

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 3,133 | 1.0 | 0.324 | 1015.889 | `SELECT "order_items"."id", "order_items"."order_id", "order_items"."product_id", "order_items"."quantity", "order_items…` |
| 3,133 | 1.0 | 0.093 | 291.268 | `SELECT "orders"."id", "orders"."user_id", "orders"."status", "orders"."created_at" FROM "orders" WHERE "orders"."user_i…` |
| 3,133 | 1.0 | 0.033 | 102.976 | `SELECT set_config($1, $2, $3)` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 2,546 | 1.0 | 0.034 | 85.714 | `SELECT set_config($1, $2, $3)` |
| 2,546 | 1.0 | 0.016 | 40.5 | `SELECT "products"."id", "products"."name", "products"."price", "products"."stock" FROM "products" WHERE "products"."id"…` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.215 | 21.454 | `UPDATE "products" SET "stock" = ("products"."stock" - $1) WHERE ("products"."id" = $2 AND "products"."stock" >= $3)` |
| 100 | 1.0 | 0.162 | 16.248 | `INSERT INTO "orders" ("user_id", "status", "created_at") VALUES ($1, $2, $3::timestamptz) RETURNING "orders"."id"` |
| 100 | 1.0 | 0.078 | 7.843 | `INSERT INTO "order_items" ("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "order…` |
| 100 | 1.0 | 0.05 | 4.979 | `SELECT set_config($1, $2, $3)` |
| 100 | 1.0 | 0.007 | 0.697 | `SELECT "products"."price" FROM "products" WHERE "products"."id" = $1 LIMIT $2` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.066 | 6.56 | `UPDATE "products" SET "stock" = ("products"."stock" - $1) WHERE ("products"."id" = $2 AND "products"."stock" >= $3)` |
| 100 | 1.0 | 0.037 | 3.664 | `SELECT set_config($1, $2, $3)` |
| 10 | 0.1 | 0.099 | 0.99 | `INSERT INTO "orders" ("user_id", "status", "created_at") VALUES ($1, $2, $3::timestamptz) RETURNING "orders"."id"` |
| 10 | 0.1 | 0.081 | 0.813 | `INSERT INTO "order_items" ("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "order…` |
| 10 | 0.1 | 0.008 | 0.083 | `SELECT "products"."price" FROM "products" WHERE "products"."id" = $1 LIMIT $2` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 76 / 87 | 96 / 1,024 |  |  |
| orders-list | db | 18 / 23 | 324 / 1,024 | 2 (2) | 0 |
| product-detail | app | 67 / 78 | 97 / 1,024 |  |  |
| product-detail | db | 17 / 19 | 317 / 1,024 | 2 (1) | 0 |
| order-race | app | 28 / 55 | 96 / 1,024 |  |  |
| order-race | db | 12 / 17 | 317 / 1,024 | 2 (0) | 0 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ 유지 | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ 유지 | stock_after=0, stock_before=10, sold_during_run=10 |

## 수정 전후 비교

| 시나리오 | 지표 | 수정 전 | 수정 후 | 변화 |
|---|---|---:|---:|---:|
| orders-list | 요청당 쿼리 수 | 64.3 | 3.0 | -95% |
| orders-list | p95 (ms) | 2,728.1 | 308.9 | -89% |
| orders-list | 에러율 | 0.00% | 0.00% |  |
| orders-list | 처리량 (req/s) | 12.0 | 103.4 | +765% |
| product-detail | 요청당 쿼리 수 | 2.0 | 2.0 | +0% |
| product-detail | p95 (ms) | 266.8 | 256.7 | -4% |
| product-detail | 에러율 | 0.00% | 0.00% |  |
| product-detail | 처리량 (req/s) | 124.5 | 125.8 | +1% |
| order-race | 요청당 쿼리 수 | 8.0 | 8.0 | +0% |
| order-race | p95 (ms) | 1,663.0 | 1,320.6 | -21% |
| order-race | 에러율 | 0.00% | 0.00% |  |
| order-race | 처리량 (req/s) | 56.7 | 70.5 | +24% |
| order-race | 불변 조건: stock_consistency | ❌ 위반 | ✅ 유지 | |
| order-race-low-stock | 요청당 쿼리 수 | 3.2 | 2.6 | -19% |
| order-race-low-stock | p95 (ms) | 817.2 | 976.6 | +19% |
| order-race-low-stock | 에러율 | 0.00% | 0.00% |  |
| order-race-low-stock | 처리량 (req/s) | 114.4 | 96.3 | -16% |
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
