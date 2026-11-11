# catchme 리포트 — prod · 2026-11-11T14:23:02+00:00

**이 사양은 `orders-list` 기준 동시 13요청까지** 버팁니다 (p95 ≤ 500 ms, 에러율 ≤ 1.0%).

> 로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.

## 요약

- 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 62.1개, 한 쿼리가 요청당 41.1번 실행
- 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 🟡 중간 `orders-list` p95 1175 ms가 목표 500 ms 초과
- 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 94% / 최대 106% (한도 0.5 vCPU 기준)

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
| orders-list | 30 VUs × 30s (+20s warm-up) | 879.5 | **1,174.8** | 1,295.0 | 32.8 | 0.00% | 62.1 |
| product-detail | 30 VUs × 20s (+20s warm-up) | 15.1 | **45.5** | 60.8 | 1,548.8 | 0.00% | 1.0 |
| order-race | 100 VUs × 1 (simultaneous) | 3,458.1 | **3,864.7** | 3,887.4 | 25.7 | 0.00% | 7.0 |
| order-race-low-stock | 100 VUs × 1 (simultaneous) | 1,139.0 | **1,546.7** | 1,552.8 | 63.5 | 0.00% | 6.8 |

**인증 비용**: 50 logins, p50 1,451.0 ms, p95 4,421.9 ms

| VUs | p95 (ms) | 에러율 | req/s | |
|---:|---:|---:|---:|---|
| 5 | 296.3 | 0.00% | 22.5 | ✅ |
| 10 | 321.4 | 0.00% | 39.1 | ✅ |
| 12 | 399.2 | 0.00% | 38.5 | ✅ |
| 13 | 429.0 | 0.00% | 38.2 | ✅ |
| 15 | 601.6 | 0.00% | 35.9 | ❌ |
| 20 | 629.4 | 0.00% | 38.5 | ❌ |

## 병목 원인 후보

### 1. 🔴 치명 레이스 확인: `order-race`에서 불변 조건 `stock_consistency` 위반
- 근거: 
    - final stock = initial stock - quantity sold during the run (product 1)
    - stock_after=99988, stock_before=100000, orders_created=100, sold_during_run=100
    - HTTP ok 100, expected 0, 4xx 0, 5xx 0
- 수정 방향: atomic `UPDATE ... SET stock = stock - :q WHERE stock >= :q`, `@Version`, or `PESSIMISTIC_WRITE`

### 2. 🔴 치명 레이스 확인: `order-race-low-stock`에서 불변 조건 `no_oversell` 위반
- 근거: 
    - units sold never exceed the starting stock (product 2, stock 10)
    - stock_after=0, stock_before=10, sold_during_run=97
    - HTTP ok 97, expected 3, 4xx 0, 5xx 0
- 수정 방향: atomic `UPDATE ... SET stock = stock - :q WHERE stock >= :q`, `@Version`, or `PESSIMISTIC_WRITE`

### 3. 🟠 높음 `orders-list`에서 N+1 의심: 요청당 쿼리 62.1개, 한 쿼리가 요청당 41.1번 실행
- 근거: `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` — 41,584 calls / 1,011 requests, mean 0.007 ms
- 수정 방향: fetch join / `@EntityGraph`, or `hibernate.default_batch_fetch_size`

### 4. 🟠 높음 인덱스 미사용 의심: `orders`(약 1,000,000행) Seq Scan, 필터 `(user_id = $1)`
- 근거: 
    - `select o1_0.id,o1_0.created_at,o1_0.status,o1_0.user_id from orders o1_0 where o1_0.user_id=$1 order by o1_0.created_at desc fetch first $2 rows only` — mean 21.66 ms × 1,011 calls
    - plan: Limit → Gather Merge → Sort → Seq Scan on orders
- 수정 방향: 필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)

### 5. 🟡 중간 `orders-list` p95 1175 ms가 목표 500 ms 초과

### 6. 🟡 중간 `product-detail`에서 app CPU가 한도에 붙음: 평균 94% / 최대 106% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

### 7. 🟡 중간 `order-race`에서 락 경합: 락 대기 세션 최대 5개 (5회 관측), 데드락 0
- 근거: 실행 중 PostgreSQL이 기록한 100 ms 이상 락 대기 5건
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 8. 🟡 중간 `order-race-low-stock`에서 락 경합: 락 대기 세션 최대 5개 (6회 관측), 데드락 0
- 근거: 실행 중 PostgreSQL이 기록한 100 ms 이상 락 대기 4건
- 수정 방향: 트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE

### 9. 🟡 중간 `order-race-low-stock`에서 app CPU가 한도에 붙음: 평균 102% / 최대 102% (한도 0.5 vCPU 기준)
- 수정 방향: 핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향

## 분석

_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._

## 비용이 큰 쿼리

**orders-list**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 1,011 | 1.0 | 21.659 | 21897.602 | `select o1_0.id,o1_0.created_at,o1_0.status,o1_0.user_id from orders o1_0 where o1_0.user_id=$1 order by o1_0.created_at…` |
| 20,220 | 20.0 | 0.02 | 396.315 | `select oi1_0.id,oi1_0.order_id,oi1_0.product_id,oi1_0.quantity,oi1_0.unit_price from order_items oi1_0 where oi1_0.orde…` |
| 41,584 | 41.1 | 0.007 | 294.655 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**product-detail**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 31,002 | 1.0 | 0.012 | 366.85 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 100 | 1.0 | 61.342 | 6134.214 | `update products set name=$1,price=$2,stock=$3 where id=$4` |
| 100 | 1.0 | 0.456 | 45.577 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 100 | 1.0 | 0.259 | 25.875 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 100 | 1.0 | 0.042 | 4.242 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

**order-race-low-stock**

| calls | /req | mean ms | total ms | query |
|---:|---:|---:|---:|---|
| 97 | 1.0 | 71.779 | 6962.55 | `update products set name=$1,price=$2,stock=$3 where id=$4` |
| 97 | 1.0 | 0.23 | 22.282 | `insert into orders (created_at,status,user_id) values ($1,$2,$3) returning id` |
| 97 | 1.0 | 0.114 | 11.013 | `insert into order_items (order_id,product_id,quantity,unit_price) values ($1,$2,$3,$4) returning id` |
| 100 | 1.0 | 0.033 | 3.315 | `select p1_0.id,p1_0.name,p1_0.price,p1_0.stock from products p1_0 where p1_0.id=$1` |

## 리소스

| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |
|---|---|---:|---:|---:|---:|
| orders-list | app | 63 / 101 | 347 / 1,024 |  |  |
| orders-list | db | 76 / 91 | 344 / 1,024 | 10 (5) | 0 |
| product-detail | app | 94 / 106 | 354 / 1,024 |  |  |
| product-detail | db | 15 / 17 | 340 / 1,024 | 10 (2) | 0 |
| order-race | app | 72 / 100 | 418 / 1,024 |  |  |
| order-race | db | 5 / 8 | 341 / 1,024 | 10 (6) | 5 |
| order-race-low-stock | app | 102 / 102 | 427 / 1,024 |  |  |
| order-race-low-stock | db | 9 / 9 | 342 / 1,024 | 10 (5) | 5 |

## 레이스 판정

| 시나리오 | invariant | | detail |
|---|---|---|---|
| order-race | stock_consistency — final stock = initial stock - quantity sold during the run (product 1) | ❌ 위반 | stock_after=99988, stock_before=100000, orders_created=100, sold_during_run=100 |
| order-race-low-stock | no_oversell — units sold never exceed the starting stock (product 2, stock 10) | ❌ 위반 | stock_after=0, stock_before=10, sold_during_run=97 |

## 한계

| 항목 | 재현 방식 | 한계 |
|---|---|---|
| CPU | Docker `cpus` 제한 | 클럭·세대 차이, Fargate 성능 편차 미반영 |
| 메모리 | `mem_limit` | JVM 등 런타임 설정은 사용자가 맞춰야 함 |
| 네트워크 지연 | Toxiproxy latency·jitter | AZ 간 변동, 패킷 손실 패턴은 근사 |
| 디스크 I/O | MVP 미지원 (v2) | EBS·RDS 스토리지 IOPS 미반영 |
| RDS 버스트 크레딧 | `cpu_mode` 전환만 지원 | t 계열 크레딧 소진 과정 미반영 |
| 데이터 | 합성 데이터 | 실제 분포, 핫 키 편향과 다를 수 있음 |
