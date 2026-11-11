# catchme 리포트 — after · 2026-11-11T14:28:52+00:00

한계점 탐색은 실행하지 않았습니다 (`catchme breakpoint`).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 99% / 최대 102% (한도 0.5 vCPU 기준)
- 🟡 중간 `orders-list` p95 512 ms가 목표 500 ms 초과
- 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 95% / 최대 107% (한도 0.5 vCPU 기준)
- 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 9개 (11회 관측), 데드락 0
- 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 8개 (1회 관측), 데드락 0

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
| orders-list | 30 VUs × 30s (+20s warm-up) | 206.6 | **511.7** | 796.6 | 115.7 | 0.00% | 2.0 |
| product-detail | 30 VUs × 20s (+20s warm-up) | 15.3 | **88.2** | 98.1 | 1,126.5 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 3,235.5 | **3,980.2** | 4,011.1 | 24.8 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 435.6 | **628.6** | 721.6 | 134.1 | 0.00% | 1.6 |

**인증 비용**: 50 logins, p50 1,393.8 ms, p95 3,720.9 ms

## 병목 원인 후보

### 1. 🟡 중간 `orders-list`에서 app CPU가 한도에 붙음: 평균 99% / 최대 102% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 2. 🟡 중간 `orders-list` p95 512 ms가 목표 500 ms 초과

### 3. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 95% / 최대 107% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 4. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 9개 (11회 관측), 데드락 0
- 근거: 실행 중 PostgreSQL이 기록한 100 ms 이상 락 대기 18건
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 5. 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 8개 (1회 관측), 데드락 0
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 3,484 | 1.0 | 0.363 | 1263.581 | `select oi1_0.id,oi1_0.order_id,p1_0.id,p1_0.name,p1_0.price,p1_0.stock,oi1_0.product_id,oi1_0.quantity,oi1_0.unit_price…` |
| 3,484 | 1.0 | 0.077 | 266.759 | `select o1_0.id,o1_0.created_at,o1_0.status,o1_0.user_id from orders o1_0 where o1_0.user_id=$1 order by o1_0.created_at…` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 22,544 | 1.0 | 0.01 | 221.034 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 251.869 | 25186.947 | `update products p1_0 set stock=(p1_0.stock-$1) where p1_0.id=$2 and p1_0.stock>=$3` |
| 100 | 1.0 | 0.154 | 15.386 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 100 | 1.0 | 0.099 | 9.886 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 100 | 1.0 | 0.012 | 1.161 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 20.549 | 2054.911 | `update products p1_0 set stock=(p1_0.stock-$1) where p1_0.id=$2 and p1_0.stock>=$3` |
| 10 | 0.1 | 0.104 | 1.043 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 10 | 0.1 | 0.056 | 0.559 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 10 | 0.1 | 0.019 | 0.193 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 99 / 102 | 354 / 1,024 |  |  |
| orders-list | db | 10 / 13 | 347 / 1,024 | 10 (3) | 0 |
| product-detail | app | 95 / 107 | 377 / 1,024 |  |  |
| product-detail | db | 10 / 16 | 347 / 1,024 | 10 (2) | 0 |
| order-race | app | 63 / 95 | 441 / 1,024 |  |  |
| order-race | db | 7 / 8 | 350 / 1,024 | 10 (9) | 9 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ✅ 유지 | stock_after=99900, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ✅ 유지 | stock_after=0, stock_before=10, sold_during_run=10 |

## 수정 전후 비교

| 시나리오 | 지표 | 수정 전 | 수정 후 | 변화 |
|---|---|---:|---:|---:|
| orders-list | 요청당 쿼리 수 | 62.1 | 2.0 | -97% |
| orders-list | p95 (ms) | 1,174.8 | 511.7 | -56% |
| orders-list | 에러율 | 0.00% | 0.00% |  |
| orders-list | 처리량 (req/s) | 32.8 | 115.7 | +253% |
| product-detail | 요청당 쿼리 수 | 1.0 | 1.0 | +0% |
| product-detail | p95 (ms) | 45.5 | 88.2 | +94% |
| product-detail | 에러율 | 0.00% | 0.00% |  |
| product-detail | 처리량 (req/s) | 1,548.8 | 1,126.5 | -27% |
| order-race | 요청당 쿼리 수 | 7.0 | 7.0 | +0% |
| order-race | p95 (ms) | 3,864.7 | 3,980.2 | +3% |
| order-race | 에러율 | 0.00% | 0.00% |  |
| order-race | 처리량 (req/s) | 25.7 | 24.8 | -3% |
| order-race | 불변 조건: stock_consistency | ❌ 위반 | ✅ 유지 | |
| order-race-low-stock | 요청당 쿼리 수 | 6.8 | 1.6 | -77% |
| order-race-low-stock | p95 (ms) | 1,546.7 | 628.6 | -59% |
| order-race-low-stock | 에러율 | 0.00% | 0.00% |  |
| order-race-low-stock | 처리량 (req/s) | 63.5 | 134.1 | +111% |
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
