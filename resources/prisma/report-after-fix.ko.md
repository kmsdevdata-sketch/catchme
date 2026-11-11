# catchme 리포트 — after · 2026-11-11T13:38:24+00:00

한계점 탐색은 실행하지 않았습니다 (`catchme breakpoint`).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 97% / 최대 101% (한도 0.5 vCPU 기준)
- 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 102% / 최대 106% (한도 0.5 vCPU 기준)
- 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 4개 (5회 관측), 데드락 0
- 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 4개 (1회 관측), 데드락 0

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 84.9 | **109.8** | 161.8 | 367.6 | 0.00% | 3.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 14.5 | **53.5** | 76.8 | 1,492.4 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 701.4 | **1,205.0** | 1,248.8 | 77.6 | 0.00% | 8.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 244.5 | **287.5** | 291.3 | 313.8 | 0.00% | 1.7 |

**인증 비용**: 50 logins, p50 265.4 ms, p95 412.3 ms

## 병목 원인 후보

### 1. 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 97% / 최대 101% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 2. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 102% / 최대 106% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 3. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 4개 (5회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 4. 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 4개 (1회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 11,051 | 1.0 | 0.12 | 1326.839 | `SELECT "public"."OrderItem"."id", "public"."OrderItem"."orderId", "public"."OrderItem"."productId", "public"."OrderItem…` |
| 11,051 | 1.0 | 0.036 | 400.59 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |
| 1,844 | 0.2 | 0.067 | 124.266 | `SELECT "public"."Product"."id", "public"."Product"."name" FROM "public"."Product" WHERE "public"."Product"."id" IN ($1,…` |
| 1,472 | 0.1 | 0.069 | 100.895 | `SELECT "public"."Product"."id", "public"."Product"."name" FROM "public"."Product" WHERE "public"."Product"."id" IN ($1,…` |
| 1,104 | 0.1 | 0.07 | 77.511 | `SELECT "public"."Product"."id", "public"."Product"."name" FROM "public"."Product" WHERE "public"."Product"."id" IN ($1,…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 29,900 | 1.0 | 0.008 | 237.299 | `SELECT "public"."Product"."id", "public"."Product"."name", "public"."Product"."price", "public"."Product"."stock" FROM …` |
| 5 | 0.0 | 0.003 | 0.016 | `SELECT $1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 44.596 | 4459.606 | `UPDATE "public"."Product" SET "stock" = ("public"."Product"."stock" - $1) WHERE ("public"."Product"."id" = $2 AND "publ…` |
| 100 | 1.0 | 0.119 | 11.887 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 100 | 1.0 | 0.069 | 6.913 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 100 | 1.0 | 0.011 | 1.063 | `SELECT "public"."Product"."id", "public"."Product"."price" FROM "public"."Product" WHERE ("public"."Product"."id" = $1 …` |
| 100 | 1.0 | 0.008 | 0.785 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 6.1 | 609.98 | `UPDATE "public"."Product" SET "stock" = ("public"."Product"."stock" - $1) WHERE ("public"."Product"."id" = $2 AND "publ…` |
| 10 | 0.1 | 0.087 | 0.873 | `INSERT INTO "public"."Order" ("userId","status","createdAt") VALUES ($1,$2,$3) RETURNING "public"."Order"."id"` |
| 10 | 0.1 | 0.061 | 0.612 | `INSERT INTO "public"."OrderItem" ("orderId","productId","quantity","unitPrice") VALUES ($1,$2,$3,$4) RETURNING "public"…` |
| 10 | 0.1 | 0.013 | 0.132 | `SELECT "public"."Product"."id", "public"."Product"."price" FROM "public"."Product" WHERE ("public"."Product"."id" = $1 …` |
| 10 | 0.1 | 0.012 | 0.119 | `SELECT "public"."Order"."id", "public"."Order"."userId", "public"."Order"."status", "public"."Order"."createdAt" FROM "…` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 97 / 101 | 62 / 1,024 |  |  |
| orders-list | db | 12 / 15 | 330 / 1,024 | 5 (1) | 0 |
| product-detail | app | 102 / 106 | 63 / 1,024 |  |  |
| product-detail | db | 12 / 15 | 328 / 1,024 | 5 (2) | 0 |
| order-race | app | 41 / 41 | 63 / 1,024 |  |  |
| order-race | db | 9 / 9 | 329 / 1,024 | 5 (4) | 4 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ 유지 | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ 유지 | stock_after=0, stock_before=10, sold_during_run=10 |

## 수정 전후 비교

| 시나리오 | 지표 | 수정 전 | 수정 후 | 변화 |
|---|---|---:|---:|---:|
| orders-list | 요청당 쿼리 수 | 61.0 | 3.0 | -95% |
| orders-list | p95 (ms) | 1,677.2 | 109.8 | -93% |
| orders-list | 에러율 | 0.00% | 0.00% |  |
| orders-list | 처리량 (req/s) | 28.4 | 367.6 | +1195% |
| product-detail | 요청당 쿼리 수 | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 48.9 | 53.5 | +9% |
| product-detail | 에러율 | 0.00% | 0.00% |  |
| product-detail | 처리량 (req/s) | 1,523.1 | 1,492.4 | -2% |
| order-race | 요청당 쿼리 수 | 8.0 | 8.0 | +0% |
| order-race | p95 (ms) | 488.6 | 1,205.0 | +147% |
| order-race | 에러율 | 0.00% | 0.00% |  |
| order-race | 처리량 (req/s) | 193.7 | 77.6 | -60% |
| order-race | 불변 조건: stock_consistency | ❌ 위반 | ✅ 유지 | |
| order-race-low-stock | 요청당 쿼리 수 | 8.0 | 1.7 | -79% |
| order-race-low-stock | p95 (ms) | 463.5 | 287.5 | -38% |
| order-race-low-stock | 에러율 | 0.00% | 0.00% |  |
| order-race-low-stock | 처리량 (req/s) | 197.6 | 313.8 | +59% |
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
