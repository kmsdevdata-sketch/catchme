# catchme 리포트 — prod · 2026-11-11T14:54:46+00:00

**이 사양은 `orders-list` 기준 동시 13요청까지** 버팁니다 (p95 ≤ 500 ms, 에러율 ≤ 1.0%).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 61.0개, 한 쿼리가 요청당 39.9번 실행
- 🟠 높음 인덱스 미사용 의심: `Order`(약 1,000,000행) Seq Scan, 필터 `("userId" = $1)`
- 🟡 중간 `orders-list` p95 1287 ms가 목표 500 ms 초과
- 🟡 중간 `orders-list`은 운영 사양에서 p95가 로컬보다 4.0배 느림 (323 → 1287 ms)

## 실행 조건

| | |
|---|---|
| 프로필 | app 0.5 vCPU/1024 MB + db.t3.micro (2 vCPU/1024 MB) |
| 앱 | 0.5 vCPU / 1024 MB |
| DB | db.t3.micro — 2 vCPU / 1024 MB, cpu_mode burst, max_connections 101 |
| 앱↔DB 지연 | 1.0 ms (jitter 0 ms) |
| DB 풀 크기 (앱 프로세스당) | None |
| 데이터 | User 1,000, Product 1,000, Order 1,000,000, OrderItem 2,000,000 (시드 42) |
| 인증 | 시딩한 테스트 계정 + 실제 로그인 API (인증 비용 포함) |
| 목표 | p95 ≤ 500 ms, errors ≤ 1.0% |

## 결과

| 시나리오 | 부하 | p50 (로컬 → 운영) | p95 (로컬 → 운영) | p99 (운영) | req/s (로컬 → 운영) | 에러율 | 요청당 쿼리 |
|---|---|---:|---:|---:|---:|---:|---:|
| orders-list | 30 VUs × 30s (+5s warm-up) | 255.9 → 985.3 | 322.7 → **1,287.1** | 2,169.6 | 114.6 → 29.0 | 0.00% | 61.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 1.8 → 15.9 | 3.4 → **45.1** | 62.6 | 14,275.6 → 1,573.9 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 84.8 → 384.5 | 112.6 → **486.1** | 495.7 | 804.7 → 193.9 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 68.8 → 331.5 | 92.4 → **429.6** | 438.2 | 927.5 → 217.4 | 0.00% | 8.0 |

**인증 비용**: 50 logins, p50 240.0 ms, p95 415.0 ms

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

### 2. 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 근거: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=6, stock_before=10, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0

### 3. 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 61.0개, 한 쿼리가 요청당 39.9번 실행
- 근거: `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM "public"."Product" WHERE ("public"."Prod…` — 35,275 calls / 883 requests, mean 0.005 ms

### 4. 🟠 높음 인덱스 미사용 의심: `Order`(약 1,000,000행) Seq Scan, 필터 `("userId" = $1)`
- 근거: 
    - `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "public"."Order" WHERE "public"."Order"."…` — mean 20.99 ms × 883 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on Order
- 수정 방향: 필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)

### 5. 🟡 중간 `orders-list` p95 1287 ms가 목표 500 ms 초과

### 6. 🟡 중간 `orders-list`은 운영 사양에서 p95가 로컬보다 4.0배 느림 (323 → 1287 ms)

### 7. 🟡 중간 `product-detail`은 운영 사양에서 p95가 로컬보다 13.1배 느림 (3 → 45 ms)

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 883 | 1.0 | 20.989 | 18532.96 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |
| 17,660 | 20.0 | 0.014 | 245.704 | `SELECT "public"."OrderItem"."id", "public"."OrderItem"."orderId", "public"."OrderItem"."productId", "public"."OrderItem…` |
| 35,275 | 39.9 | 0.005 | 172.259 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 10 | 0.0 | 0.001 | 0.015 | `SELECT $1` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 31,501 | 1.0 | 0.008 | 245.881 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 5 | 0.0 | 0.002 | 0.009 | `SELECT $1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.187 | 18.667 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND $3=$4) RETURNING "public"."Product".…` |
| 100 | 1.0 | 0.095 | 9.489 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.069 | 6.86 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.012 | 1.217 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.007 | 0.718 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 0.089 | 8.868 | `UPDATE "public"."Product" SET "stock" = $1 WHERE ("public"."Product"."id" = $2 AND 1=1) RETURNING "public"."Product"."i…` |
| 100 | 1.0 | 0.05 | 4.994 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.042 | 4.195 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.01 | 0.969 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 100 | 1.0 | 0.005 | 0.543 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 58 / 70 | 61 / 1,024 |  |  |
| orders-list | db | 62 / 75 | 331 / 1,024 | 5 (4) | 0 |
| product-detail | app | 88 / 103 | 63 / 1,024 |  |  |
| product-detail | db | 13 / 15 | 324 / 1,024 | 5 (2) | 0 |
| order-race | app | 39 / 39 | 63 / 1,024 |  |  |
| order-race | db | 9 / 9 | 324 / 1,024 | 5 (0) | 0 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ 위반 | stock_after=99996, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ 위반 | stock_after=6, stock_before=10, sold_during_run=100 |

## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | 런타임 설정(힙 크기, GC, 스레드·워커 수)은 운영과 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | 재현하지 않음 | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
