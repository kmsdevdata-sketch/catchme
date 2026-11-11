# catchme 리포트 — prod · 2026-11-11T14:03:43+00:00

**이 사양은 `orders-list` 기준 동시 6요청까지** 버팁니다 (p95 ≤ 500 ms, 에러율 ≤ 1.0%).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 64.3개, 한 쿼리가 요청당 42.3번 실행
- 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 🟠 높음 `orders-list`, `product-detail`, `order-race`, `order-race-low-stock`에서 요청마다 DB 커넥션을 새로 엶: 요청 388건에 세션 405개 (커넥션 풀 없음)
- 🟡 중간 `orders-list` p95 2728 ms가 목표 500 ms 초과

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 2,490.6 | **2,728.1** | 2,816.3 | 12.0 | 0.00% | 64.3 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 237.8 | **266.8** | 289.6 | 124.5 | 0.00% | 2.0 |
| order-race | 100 VUs × 1 (simultaneous) | 675.9 | **1,663.0** | 1,713.8 | 56.7 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 492.4 | **817.2** | 845.3 | 114.4 | 0.00% | 3.2 |

**인증 비용**: 50 logins, p50 1,813.2 ms, p95 2,103.4 ms

| VUs | p95 (ms) | 에러율 | req/s | |
|---:|---:|---:|---:|---|
| 5 | 448.8 | 0.00% | 13.4 | ✅ |
| 6 | 472.5 | 0.00% | 13.4 | ✅ |
| 7 | 609.9 | 0.00% | 13.3 | ❌ |
| 10 | 795.7 | 0.00% | 13.2 | ❌ |

## 병목 원인 후보

### 1. 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 근거: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99902, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: `filter(stock__gte=q).update(stock=F('stock') - q)` or `select_for_update()` in `atomic()`

### 2. 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 근거: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=0, stock_before=10, sold_during_run=20
    - HTTP ok 20, expected 80, 4xx 0, 5xx 0
- 수정 방향: `filter(stock__gte=q).update(stock=F('stock') - q)` or `select_for_update()` in `atomic()`

### 3. 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 64.3개, 한 쿼리가 요청당 42.3번 실행
- 근거: `SELECT "products"."id", "products"."name", "products"."price", "products"."stock" FROM "products" WHERE "products"."id" = $1 LIMIT $2` — 16,410 calls / 388 requests, mean 0.005 ms
- 수정 방향: `select_related` (FK) / `prefetch_related` (reverse FK, M2M)

### 4. 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 근거: 
    - `SELECT "orders"."id", "orders"."user_id", "orders"."status", "orders"."created_at" FROM "orders" WHERE "orders"."user_id" = $1 ORDER BY "orders"."created_at" D…` — mean 16.34 ms × 388 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- 수정 방향: 필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)

### 5. 🟠 높음 `orders-list`, `product-detail`, `order-race`, `order-race-low-stock`에서 요청마다 DB 커넥션을 새로 엶: 요청 388건에 세션 405개 (커넥션 풀 없음)
- 근거: 
    - 요청당 새 세션 1.04개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (orders-list)
    - 요청당 새 세션 1.00개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (product-detail)
    - 요청당 새 세션 1.03개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (order-race)
    - 요청당 새 세션 1.02개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄 (order-race-low-stock)
- 수정 방향: `CONN_MAX_AGE = 60` (+ `CONN_HEALTH_CHECKS = True`), or the psycopg pool (`OPTIONS: {"pool": True}`, Django 5.1+)

### 6. 🟡 중간 `orders-list` p95 2728 ms가 목표 500 ms 초과

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 388 | 1.0 | 16.343 | 6341.254 | `SELECT "orders"."id", "orders"."user_id", "orders"."status", "orders"."created_at" FROM "orders" WHERE "orders"."user_i…` |
| 7,760 | 20.0 | 0.04 | 307.871 | `SELECT "order_items"."id", "order_items"."order_id", "order_items"."product_id", "order_items"."quantity", "order_items…` |
| 16,410 | 42.3 | 0.005 | 88.92 | `SELECT "products"."id", "products"."name", "products"."price", "products"."stock" FROM "products" WHERE "products"."id"…` |
| 388 | 1.0 | 0.059 | 22.955 | `SELECT set_config($1, $2, $3)` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 2,518 | 1.0 | 0.055 | 137.336 | `SELECT set_config($1, $2, $3)` |
| 2,518 | 1.0 | 0.018 | 44.859 | `SELECT "products"."id", "products"."name", "products"."price", "products"."stock" FROM "products" WHERE "products"."id"…` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.164 | 16.363 | `INSERT INTO "orders" ("user_id", "status", "created_at") VALUES ($1, $2, $3::timestamptz) RETURNING "orders"."id"` |
| 100 | 1.0 | 0.154 | 15.449 | `INSERT INTO "order_items" ("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "order…` |
| 100 | 1.0 | 0.141 | 14.111 | `UPDATE "products" SET "name" = $1, "price" = $2, "stock" = $3 WHERE "products"."id" = $4` |
| 100 | 1.0 | 0.083 | 8.267 | `SELECT set_config($1, $2, $3)` |
| 100 | 1.0 | 0.038 | 3.841 | `SELECT "products"."id", "products"."name", "products"."price", "products"."stock" FROM "products" WHERE "products"."id"…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.039 | 3.926 | `SELECT set_config($1, $2, $3)` |
| 100 | 1.0 | 0.019 | 1.865 | `SELECT "products"."id", "products"."name", "products"."price", "products"."stock" FROM "products" WHERE "products"."id"…` |
| 20 | 0.2 | 0.088 | 1.754 | `INSERT INTO "order_items" ("order_id", "product_id", "quantity", "unit_price") VALUES ($1, $2, $3, $4) RETURNING "order…` |
| 20 | 0.2 | 0.088 | 1.751 | `INSERT INTO "orders" ("user_id", "status", "created_at") VALUES ($1, $2, $3::timestamptz) RETURNING "orders"."id"` |
| 20 | 0.2 | 0.063 | 1.259 | `UPDATE "products" SET "name" = $1, "price" = $2, "stock" = $3 WHERE "products"."id" = $4` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 44 / 67 | 91 / 1,024 |  |  |
| orders-list | db | 37 / 48 | 320 / 1,024 | 2 (2) | 0 |
| product-detail | app | 74 / 84 | 92 / 1,024 |  |  |
| product-detail | db | 18 / 23 | 317 / 1,024 | 2 (1) | 0 |
| order-race | app | 33 / 65 | 92 / 1,024 |  |  |
| order-race | db | 16 / 21 | 317 / 1,024 | 2 (0) | 0 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ 위반 | stock_after=99902, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ 위반 | stock_after=0, stock_before=10, sold_during_run=20 |

## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | JVM 등 런타임 설정은 사용자가 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | MVP 미지원 (v2) | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
