# catchme 리포트 — prod · 2026-11-11T13:33:33+00:00

**이 사양은 `orders-list` 기준 동시 13요청까지** 버팁니다 (p95 ≤ 500 ms, 에러율 ≤ 1.0%).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 61.0개, 한 쿼리가 요청당 40.0번 실행
- 🟠 높음 인덱스 미사용 의심: `Order`(약 1,000,000행) Seq Scan, 필터 `("userId" = $1)`
- 🟠 높음 `orders-list`에서 커넥션 풀 포화: 활성 커넥션 최대 5개, 풀 크기 5
- 🟡 중간 `orders-list` p95 1677 ms가 목표 500 ms 초과

## 실행 조건

| | |
|---|---|
| 프로필 | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| 앱 | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| 앱↔DB 지연 | 1.0 ms (jitter 0 ms) |
| DB 풀 크기 (앱 프로세스당) | 5 |
| 데이터 | User 1,000, Product 1,000, Order 1,000,000, OrderItem 2,000,000 (시드 42) |
| 인증 | 시딩한 테스트 계정 + 실제 로그인 API (인증 비용 포함) |
| 목표 | p95 ≤ 500 ms, errors ≤ 1.0% |

## 결과

| 시나리오 | 부하 | p50 | p95 | p99 | req/s | 에러율 | 요청당 쿼리 |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 965.8 | **1,677.2** | 2,469.9 | 28.4 | 0.00% | 61.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 14.8 | **48.9** | 71.2 | 1,523.1 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 394.1 | **488.6** | 492.1 | 193.7 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 371.5 | **463.5** | 470.3 | 197.6 | 0.00% | 8.0 |

**인증 비용**: 50 logins, p50 272.4 ms, p95 430.8 ms

| VUs | p95 (ms) | 에러율 | req/s | |
|---:|---:|---:|---:|---|
| 5 | 178.1 | 0.00% | 34.0 | ✅ |
| 10 | 349.3 | 0.00% | 35.2 | ✅ |
| 12 | 443.3 | 0.00% | 35.4 | ✅ |
| 13 | 443.9 | 0.00% | 36.3 | ✅ |
| 15 | 579.6 | 0.00% | 35.3 | ❌ |
| 20 | 824.9 | 0.00% | 33.0 | ❌ |

## 병목 원인 후보

### 1. 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 근거: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99996, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: `updateMany({ where: { id, stock: { gte: q } }, data: { stock: { decrement: q } } })` and check `count`

### 2. 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 근거: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=5, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: `updateMany({ where: { id, stock: { gte: q } }, data: { stock: { decrement: q } } })` and check `count`

### 3. 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 61.0개, 한 쿼리가 요청당 40.0번 실행
- 근거: `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM "public"."Product" WHERE ("public"."Prod…` — 34,604 calls / 866 requests, mean 0.006 ms
- 수정 방향: `include` / nested `select`, or one `findMany({ where: { id: { in: ids } } })`

### 4. 🟠 높음 인덱스 미사용 의심: `Order`(약 1,000,000행) Seq Scan, 필터 `("userId" = $1)`
- 근거: 
    - `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "public"."Order" WHERE "public"."Order"."…` — mean 25.06 ms × 866 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on Order
- 수정 방향: 필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)

### 5. 🟠 높음 `orders-list`에서 커넥션 풀 포화: 활성 커넥션 최대 5개, 풀 크기 5
- 근거: avg active 0.7, p95 1,677.2 ms, 5xx 0
- 수정 방향: 트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정

### 6. 🟡 중간 `orders-list` p95 1677 ms가 목표 500 ms 초과

### 7. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 104% / 최대 110% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 866 | 1.0 | 25.061 | 21703.206 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |
| 17,320 | 20.0 | 0.023 | 404.153 | `SELECT "public"."OrderItem"."id", "public"."OrderItem"."orderId", "public"."OrderItem"."productId", "public"."OrderItem…` |
| 34,604 | 40.0 | 0.006 | 206.584 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 10 | 0.0 | 0.003 | 0.033 | `SELECT $1` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 30,500 | 1.0 | 0.008 | 258.945 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 5 | 0.0 | 0.003 | 0.015 | `SELECT $1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.253 | 25.264 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND $3=$4) RETURNING "public"."Product".…` |
| 100 | 1.0 | 0.126 | 12.644 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.077 | 7.669 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.013 | 1.294 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.006 | 0.635 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.173 | 17.27 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND 1=1) RETURNING "public"."Product"."i…` |
| 100 | 1.0 | 0.073 | 7.303 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.05 | 4.978 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.012 | 1.203 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.007 | 0.739 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 70 / 98 | 62 / 1,024 |  |  |
| orders-list | db | 68 / 83 | 331 / 1,024 | 5 (5) | 0 |
| product-detail | app | 104 / 110 | 64 / 1,024 |  |  |
| product-detail | db | 13 / 14 | 327 / 1,024 | 5 (2) | 0 |
| order-race | app | 0 / 0 | 64 / 1,024 |  |  |
| order-race | db | 9 / 9 | 326 / 1,024 | 5 (0) | 0 |
| order-race-low-stock | app | 44 / 44 | 64 / 1,024 |  |  |
| order-race-low-stock | db | 10 / 10 | 326 / 1,024 | 5 (0) | 0 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ 위반 | stock_after=99996, stock_before=100000, orders_created=100, sold_during_run=100 |
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
