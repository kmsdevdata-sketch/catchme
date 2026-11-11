# Spring Boot + JPA (Hibernate) reference

## Detection signals
- `build.gradle(.kts)` / `pom.xml` with `spring-boot`; `spring-boot-starter-data-jpa`; `org.postgresql:postgresql`.
- Endpoints: `@RestController` + `@GetMapping`/`@PostMapping`/... with class-level `@RequestMapping`.
- Port: `server.port` in `application.yml|properties`, default 8080.

## Dockerfile (if the project has none)
Use `templates/dockerfiles/spring.Dockerfile` (multi-stage Gradle or Maven). Builds take minutes;
keep the image between runs (teardown removes it — that's expected).

## DB wiring
`gen` sets:
```
SPRING_DATASOURCE_URL=jdbc:postgresql://toxiproxy:15432/app
SPRING_DATASOURCE_USERNAME=app_user
SPRING_DATASOURCE_PASSWORD=app_password
SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE=<pool>   # default 10 (Hikari default)
```
If the app uses a custom property for the URL or a profile, add it to `project.json → app.env`
(e.g. `SPRING_PROFILES_ACTIVE`). Flyway/Liquibase run at boot — good, the schema is ready for seeding.
If the app uses `ddl-auto=create`, set `SPRING_JPA_HIBERNATE_DDL_AUTO=update` so restarts keep seeded data.

## Memory — production gotcha
The JVM is container-aware but defaults the heap to 25% of the limit. Production usually sets
`-XX:MaxRAMPercentage=75`. Mirror production in `app.env`:
`JAVA_TOOL_OPTIONS=-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError`.
Also note `ActiveProcessorCount` follows `cpus` — with 0.5 vCPU, the JVM sees 1 CPU → small
common pool / Tomcat behavior differs from the laptop.

## Pool exhaustion
Hikari waits `connectionTimeout` (30 s default) → `SQLTransientConnectionException` → 5xx and
huge p99. If actuator is enabled, `hikaricp.connections.pending` confirms it.
Long transactions (`@Transactional` around remote calls) hold connections — check for that first.

## N+1 patterns and fixes
| Pattern | Evidence | Fix |
|---|---|---|
| `@OneToMany`/`@ManyToOne(fetch = LAZY)` accessed in a loop / during JSON serialization | `select ... from child where parent_id=?` with calls ≈ rows × requests | `JOIN FETCH` in JPQL, `@EntityGraph(attributePaths = ...)`, or DTO projection |
| `@ManyToOne` default EAGER | extra select per row | make it `LAZY` and fetch explicitly |
| Collections with paging + fetch join | in-memory paging warning (HHH90003004) | `hibernate.default_batch_fetch_size=100` or two-step (ids page → fetch) |
| OSIV serializing lazy relations | queries happen in the view layer | `spring.jpa.open-in-view=false` + explicit fetch |

## Race patterns and fixes
| Pattern | Fix |
|---|---|
| `findById` → `setStock(stock - qty)` → `save` | `@Modifying @Query("update ... set stock = stock - :q where id = :id and stock >= :q")`, or `@Version` optimistic lock + retry, or `@Lock(PESSIMISTIC_WRITE)` |
| `existsBy...` then `save` | unique constraint + handle `DataIntegrityViolationException` |
| `synchronized` method | does not work across instances; use DB locks |

## Missing index
JPA doesn't create indexes on FKs. Add via Flyway migration or `@Table(indexes = @Index(columnList = "user_id"))`.

## Measurement — production gotcha
At 0.5–1 vCPU the JIT compiler thread can take ~half the CPU for the first minute after start, so
short runs swing a lot between builds. catchme warms each run up for 20 s by default on Spring; for
before/after comparisons of small effects use `duration: 60s` and `warmup: 30s`. The same applies to
production right after a deploy — warm-up traffic before taking load helps.

## Hooks patterns
`*Repository.java|kt`, `*Mapper.xml` (MyBatis), entity files (add `*/domain/*.java` to `hooks.enabled` if needed).
