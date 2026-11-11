# catchme 리포트 — after · 2026-11-11T14:52:50+00:00

한계점 탐색은 실행하지 않았습니다 (`catchme breakpoint`).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 3개 (3회 관측), 데드락 0

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
| orders-list | 30 VUs × 30s (+5s warm-up) | 40.1 | **46.7** | 50.6 | 743.2 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+5s warm-up) | 0.4 | **1.3** | 61.7 | 20,862.4 | 0.00% | 0.0 |
| ramp-orders | ramp 20→80→160 VUs | 73.4 | **199.6** | 215.9 | 704.7 | 0.00% | 2.0 |
| order-race | 100 VUs × 1 (simultaneous) | 371.0 | **669.2** | 694.8 | 139.1 | 0.00% | 6.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 175.0 | **262.1** | 270.0 | 353.6 | 0.00% | 2.4 |

**인증 비용**: 50 logins, p50 691.8 ms, p95 965.5 ms

## 병목 원인 후보

### 1. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 3개 (3회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 22,321 | 1.0 | 0.427 | 9530.092 | `SELECT oi.order_id, p.name, oi.quantity, oi.unit_price FROM order_items oi JOIN products p ON p.id = oi.product_id WHER…` |
| 22,321 | 1.0 | 0.043 | 952.725 | `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` |

**ramp-orders**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 42,395 | 1.0 | 0.424 | 17981.091 | `SELECT oi.order_id, p.name, oi.quantity, oi.unit_price FROM order_items oi JOIN products p ON p.id = oi.product_id WHER…` |
| 42,395 | 1.0 | 0.043 | 1819.511 | `SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 16.634 | 1663.433 | `UPDATE products SET stock = stock - $1 WHERE id = $2 AND stock >= $1 RETURNING price` |
| 100 | 1.0 | 0.093 | 9.316 | `INSERT INTO orders (user_id, status) VALUES ($1, $2) RETURNING id` |
| 100 | 1.0 | 0.069 | 6.884 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 1.724 | 172.404 | `UPDATE products SET stock = stock - $1 WHERE id = $2 AND stock >= $1 RETURNING price` |
| 10 | 0.1 | 0.075 | 0.75 | `INSERT INTO orders (user_id, status) VALUES ($1, 'PAID') RETURNING id` |
| 10 | 0.1 | 0.057 | 0.574 | `INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)` |
| 90 | 0.9 | 0.006 | 0.537 | `SELECT EXISTS (SELECT $2 FROM products WHERE id = $1)` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 37 / 41 | 11 / 1,024 |  |  |
| orders-list | db | 28 / 30 | 327 / 1,024 | 4 (4) | 0 |
| product-detail | app | 101 / 104 | 12 / 1,024 |  |  |
| product-detail | db | 3 / 5 | 326 / 1,024 | 4 (0) | 0 |
| ramp-orders | app | 39 / 45 | 18 / 1,024 |  |  |
| ramp-orders | db | 28 / 34 | 328 / 1,024 | 4 (4) | 0 |
| order-race | app | 0 / 0 | 17 / 1,024 |  |  |
| order-race | db | 8 / 8 | 325 / 1,024 | 4 (3) | 3 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ 유지 | stock_after=99900, stock_before=100000, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2) | ✅ 유지 | stock_after=0, stock_before=10, sold_during_run=10 |

## 수정 전후 비교

| 시나리오 | 지표 | 수정 전 | 수정 후 | 변화 |
|---|---|---:|---:|---:|
| orders-list | 요청당 쿼리 수 | 81.4 | 2.0 | -98% |
| orders-list | p95 (ms) | 1,966.3 | 46.7 | -98% |
| orders-list | 에러율 | 0.00% | 0.00% |  |
| orders-list | 처리량 (req/s) | 20.0 | 743.2 | +3614% |
| product-detail | 요청당 쿼리 수 | 0.0 | 0.0 | — |
| product-detail | p95 (ms) | 1.4 | 1.3 | -8% |
| product-detail | 에러율 | 0.00% | 0.00% |  |
| product-detail | 처리량 (req/s) | 19,208.7 | 20,862.4 | +9% |
| ramp-orders | 요청당 쿼리 수 | 82.4 | 2.0 | -98% |
| ramp-orders | p95 (ms) | 6,982.0 | 199.6 | -97% |
| ramp-orders | 에러율 | 0.00% | 0.00% |  |
| ramp-orders | 처리량 (req/s) | 19.7 | 704.7 | +3474% |
| order-race | 요청당 쿼리 수 | 7.0 | 6.0 | -14% |
| order-race | p95 (ms) | 294.4 | 669.2 | +127% |
| order-race | 에러율 | 0.00% | 0.00% |  |
| order-race | 처리량 (req/s) | 319.3 | 139.1 | -56% |
| order-race | 불변 조건: stock_consistency | ❌ 위반 | ✅ 유지 | |
| order-race-low-stock | 요청당 쿼리 수 | 7.0 | 2.4 | -66% |
| order-race-low-stock | p95 (ms) | 246.0 | 262.1 | +7% |
| order-race-low-stock | 에러율 | 0.00% | 0.00% |  |
| order-race-low-stock | 처리량 (req/s) | 380.3 | 353.6 | -7% |
| order-race-low-stock | 불변 조건: no_oversell | ❌ 위반 | ✅ 유지 | |


## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | 런타임 설정(힙 크기, GC, 스레드·워커 수)은 운영과 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | 재현하지 않음 | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
