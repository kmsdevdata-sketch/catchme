#!/usr/bin/env python3
"""F7 — Markdown report from metrics.json.

  report.py [--label prod] [--baseline baseline] [--before prod] [--lang en|ko]

Writes .prod-parity/reports/<timestamp>-<label>.md and reports/latest.md.
Bottleneck candidates are heuristics with evidence; the agent adds its interpretation under "Analysis".
"""
import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import fnum, info, pp_dir, read_json  # noqa: E402
import compare  # noqa: E402

FIX = {
    "churn": {
        "django": "`CONN_MAX_AGE = 60` (+ `CONN_HEALTH_CHECKS = True`), or the psycopg pool (`OPTIONS: {\"pool\": True}`, Django 5.1+)",
        "fastapi": "create one engine at startup (module level) and reuse it; don't create engines or `NullPool` per request",
        "_": "reuse connections through a pool instead of connecting per request",
    },
    "n+1": {
        "spring-jpa": "fetch join / `@EntityGraph`, or `hibernate.default_batch_fetch_size`",
        "node-prisma": "`include` / nested `select`, or one `findMany({ where: { id: { in: ids } } })`",
        "django": "`select_related` (FK) / `prefetch_related` (reverse FK, M2M)",
        "node-typeorm": "`relations: { items: { product: true } }` or QueryBuilder `leftJoinAndSelect`",
        "fastapi": "`options(selectinload(Order.items).joinedload(OrderItem.product))`",
    },
    "race": {
        "spring-jpa": "atomic `UPDATE ... SET stock = stock - :q WHERE stock >= :q`, `@Version`, or `PESSIMISTIC_WRITE`",
        "node-prisma": "`updateMany({ where: { id, stock: { gte: q } }, data: { stock: { decrement: q } } })` and check `count`",
        "django": "`filter(stock__gte=q).update(stock=F('stock') - q)` or `select_for_update()` in `atomic()`",
        "node-typeorm": "QueryBuilder `update().set({ stock: () => 'stock - :q' }).where('id = :id AND stock >= :q')` and check `affected`",
        "fastapi": "`update(Product).where(Product.id == id, Product.stock >= q).values(stock=Product.stock - q)` and check `rowcount`",
    },
}

L = {
    "en": {
        "title": "catchme report", "approx": "Results are a production **approximation** in local Docker — see Limitations.",
        "verdict": "**This spec holds up to {n} concurrent requests** on `{run}` (p95 ≤ {p95} ms, errors ≤ {err}).",
        "verdict_capped": "**This spec holds at least {n} concurrent requests** on `{run}` (max tested; p95 ≤ {p95} ms, errors ≤ {err}).",
        "verdict_zero": "**This spec misses the target already at {n} concurrent requests** on `{run}` (p95 ≤ {p95} ms, errors ≤ {err}).",
        "verdict_none": "Breaking point not measured (run `catchme breakpoint`).",
        "summary": "Summary", "conditions": "Conditions", "results": "Results", "findings": "Bottleneck candidates",
        "queries": "Heaviest statements", "resources": "Resources", "race": "Race verdicts", "analysis": "Analysis",
        "limits": "Limitations", "auth_cost": "Auth cost",
        "no_findings": "No bottleneck candidates crossed the thresholds.",
        "analysis_todo": "_Agent: replace this with your interpretation — confirm or reject each candidate, point to code (file:line), rank by impact, and propose fixes._",
        "profile": "Profile", "app": "App", "db": "DB", "latency": "App↔DB latency", "data": "Data", "seed": "seed",
        "auth": "Auth", "targets": "Targets", "pool": "DB pool size (per app process)",
        "run": "Run", "load": "Load", "req": "Requests", "rps": "req/s", "err": "Errors", "qpr": "Queries/req",
        "baseline": "local", "prod": "prod",
        "auth_modes": {"login": "seeded test accounts + real login API (auth cost included)",
                       "token": "tokens minted with the test secret (login cost not included)",
                       "bypass": "⚠️ auth bypass profile — auth cost NOT included",
                       "none": "no auth"},
        "sev": {"critical": "🔴 critical", "high": "🟠 high", "medium": "🟡 medium"},
        "f_n1": "Possible N+1 on `{run}`: {qpr:.1f} queries/request; one statement runs {cpr:.1f}× per request",
        "f_index": "Possible missing index: Seq Scan on `{table}` (~{rows} rows) with filter `{flt}`",
        "f_pool": "Connection pool saturated on `{run}`: up to {active} active connections with pool size {pool}",
        "f_maxconn": "DB connections near max_connections on `{run}`: {total} of {max}",
        "ev_lock": "{e} lock waits of 100 ms or longer logged by PostgreSQL during the run",
        "f_churn": "New DB connection per request on `{run}`: up to {s} sessions opened for {r} requests (no connection pooling)",
        "ev_churn": "{x:.2f} new sessions per request — each pays TCP + auth + session setup over the app↔db latency",
        "f_lock": "Lock contention on `{run}`: up to {n} sessions waiting on locks ({s} samples), deadlocks {d}",
        "f_race": "Race condition: invariant `{name}` violated on `{run}`",
        "f_cpu": "{svc} CPU pinned at its limit on `{run}`: avg {avg:.0f}% / max {mx:.0f}% of {cores} vCPU",
        "f_mem": "{svc} memory near its limit on `{run}`: {used:.0f} MB of {lim:.0f} MB",
        "f_oom": "{svc} was OOM-killed or restarted during `{run}`",
        "f_err": "Error rate {rate:.2%} on `{run}` exceeds target {target:.2%} (5xx {s5}, network {ne}, 4xx {s4})",
        "f_p95": "p95 {p95:.0f} ms on `{run}` exceeds target {target:.0f} ms",
        "f_slowdown": "`{run}` is {x:.1f}× slower at p95 under the production profile than locally ({b:.0f} → {p:.0f} ms)",
        "ev": "Evidence", "fix": "Fix direction",
        "fix_index": "index on the filter columns (check the WHERE / ORDER BY of the statement)",
        "fix_pool": "shorten transactions, remove N+1, then size the pool against `max_connections`",
        "fix_lock": "shorter transactions, consistent lock order, atomic updates instead of read-modify-write",
        "fix_cpu": "profile the hot path (serialization, hashing, N+1 overhead) or size up",
        "fix_mem": "align runtime memory settings with the limit; bound result sets",
        "inv_ok": "✅ holds", "inv_bad": "❌ violated", "inv_none": "—",
        "lim_rows": [
            ("CPU", "Docker `cpus` limit", "clock/generation differences and Fargate variance not modeled"),
            ("Memory", "`mem_limit`", "runtime settings (JVM heap etc.) must match production"),
            ("Network latency", "Toxiproxy latency/jitter", "cross-AZ variance and packet loss only approximated"),
            ("Disk I/O", "not modeled (v2)", "EBS/RDS storage IOPS not reflected"),
            ("RDS burst credits", "`cpu_mode` switch only", "credit depletion over time not modeled"),
            ("Data", "synthetic data", "real distributions and hot keys may differ"),
        ],
        "lim_head": "| Item | Approach | Limitation |",
        "replicas": "Production runs {n} replicas; one replica was modeled.",
    },
    "ko": {
        "title": "catchme 리포트", "approx": "로컬 Docker에서 근사한 **운영 근사치**입니다 — 아래 한계를 함께 보세요.",
        "verdict": "**이 사양은 `{run}` 기준 동시 {n}요청까지** 버팁니다 (p95 ≤ {p95} ms, 에러율 ≤ {err}).",
        "verdict_capped": "**이 사양은 `{run}` 기준 최소 동시 {n}요청까지** 버팁니다 (테스트한 최대치, p95 ≤ {p95} ms, 에러율 ≤ {err}).",
        "verdict_zero": "**이 사양은 `{run}` 기준 동시 {n}요청에서 이미 목표를 넘깁니다** (p95 ≤ {p95} ms, 에러율 ≤ {err}).",
        "verdict_none": "한계점 탐색은 실행하지 않았습니다 (`catchme breakpoint`).",
        "summary": "요약", "conditions": "실행 조건", "results": "결과", "findings": "병목 원인 후보",
        "queries": "비용이 큰 쿼리", "resources": "리소스", "race": "레이스 판정", "analysis": "분석",
        "limits": "한계", "auth_cost": "인증 비용",
        "no_findings": "임계값을 넘은 병목 후보가 없습니다.",
        "analysis_todo": "_에이전트: 이 자리를 해석으로 바꾸세요 — 후보마다 사실인지 판단, 코드 위치(file:line) 연결, 영향 순 정렬, 수정 제안._",
        "profile": "프로필", "app": "앱", "db": "DB", "latency": "앱↔DB 지연", "data": "데이터", "seed": "시드",
        "auth": "인증", "targets": "목표", "pool": "DB 풀 크기 (앱 프로세스당)",
        "run": "시나리오", "load": "부하", "req": "요청 수", "rps": "req/s", "err": "에러율", "qpr": "요청당 쿼리",
        "baseline": "로컬", "prod": "운영",
        "auth_modes": {"login": "시딩한 테스트 계정 + 실제 로그인 API (인증 비용 포함)",
                       "token": "테스트 비밀키로 직접 발급한 토큰 (로그인 비용 미포함)",
                       "bypass": "⚠️ 인증 우회 프로파일 — 인증 비용 미포함",
                       "none": "인증 없음"},
        "sev": {"critical": "🔴 치명", "high": "🟠 높음", "medium": "🟡 중간"},
        "f_n1": "`{run}`에서 N+1 의심: 요청당 쿼리 {qpr:.1f}개, 한 쿼리가 요청당 {cpr:.1f}번 실행",
        "f_index": "인덱스 미사용 의심: `{table}`(약 {rows}행) Seq Scan, 필터 `{flt}`",
        "f_pool": "`{run}`에서 커넥션 풀 포화: 활성 커넥션 최대 {active}개, 풀 크기 {pool}",
        "f_maxconn": "`{run}`에서 DB 커넥션이 max_connections에 근접: {total} / {max}",
        "ev_lock": "실행 중 PostgreSQL이 기록한 100 ms 이상 락 대기 {e}건",
        "f_churn": "`{run}`에서 요청마다 DB 커넥션을 새로 엶: 요청 {r}건에 세션 {s}개 (커넥션 풀 없음)",
        "ev_churn": "요청당 새 세션 {x:.2f}개 — 매번 앱↔DB 지연 위에서 TCP·인증·세션 설정 비용을 냄",
        "f_lock": "`{run}`에서 락 경합: 락 대기 세션 최대 {n}개 ({s}회 관측), 데드락 {d}",
        "f_race": "레이스 확인: `{run}`에서 불변 조건 `{name}` 위반",
        "f_cpu": "`{run}`에서 {svc} CPU가 한도에 붙음: 평균 {avg:.0f}% / 최대 {mx:.0f}% (한도 {cores} vCPU 기준)",
        "f_mem": "`{run}`에서 {svc} 메모리가 한도에 근접: {used:.0f} MB / {lim:.0f} MB",
        "f_oom": "`{run}` 중 {svc}가 OOM으로 종료되었거나 재시작됨",
        "f_err": "`{run}` 에러율 {rate:.2%}가 목표 {target:.2%} 초과 (5xx {s5}, 네트워크 {ne}, 4xx {s4})",
        "f_p95": "`{run}` p95 {p95:.0f} ms가 목표 {target:.0f} ms 초과",
        "f_slowdown": "`{run}`은 운영 사양에서 p95가 로컬보다 {x:.1f}배 느림 ({b:.0f} → {p:.0f} ms)",
        "ev": "근거", "fix": "수정 방향",
        "fix_index": "필터 컬럼에 인덱스 (쿼리의 WHERE / ORDER BY 확인)",
        "fix_pool": "트랜잭션 단축, N+1 제거 후 `max_connections`에 맞춰 풀 크기 조정",
        "fix_lock": "트랜잭션 단축, 락 순서 통일, 읽고-쓰기 대신 원자적 UPDATE",
        "fix_cpu": "핫패스 프로파일링(직렬화, 해싱, N+1 오버헤드) 또는 사양 상향",
        "fix_mem": "런타임 메모리 설정을 한도에 맞추고 결과 집합 크기 제한",
        "inv_ok": "✅ 유지", "inv_bad": "❌ 위반", "inv_none": "—",
        "lim_rows": [
            ("CPU", "Docker `cpus` 제한", "클럭·세대 차이, Fargate 성능 편차 미반영"),
            ("메모리", "`mem_limit`", "JVM 등 런타임 설정은 사용자가 맞춰야 함"),
            ("네트워크 지연", "Toxiproxy latency·jitter", "AZ 간 변동, 패킷 손실 패턴은 근사"),
            ("디스크 I/O", "MVP 미지원 (v2)", "EBS·RDS 스토리지 IOPS 미반영"),
            ("RDS 버스트 크레딧", "`cpu_mode` 전환만 지원", "t 계열 크레딧 소진 과정 미반영"),
            ("데이터", "합성 데이터", "실제 분포, 핫 키 편향과 다를 수 있음"),
        ],
        "lim_head": "| 항목 | 재현 방식 | 한계 |",
        "replicas": "운영은 레플리카 {n}개지만 1개만 재현했습니다.",
    },
}


INTERNAL_SQL = re.compile(r"FOR KEY SHARE OF x|^SELECT \$\d+ FROM ONLY ", re.I)  # Postgres FK (RI trigger) checks


def app_statements(stmts):
    return [s for s in stmts or [] if not INTERNAL_SQL.search(s.get("query") or "")]


def short_sql(q, n=160):
    q = re.sub(r"\s+", " ", q or "").strip()
    return (q[: n - 1] + "…") if len(q) > n else q


def load_desc(r):
    if r.get("stages"):
        return "ramp " + "→".join(str(s.get("target")) for s in r["stages"]) + " VUs"
    if r.get("kind") == "race":
        return f"{r.get('vus') or '?'} VUs × {r.get('iterations') or 1} (simultaneous)"
    if r.get("iterations"):
        return f"{r.get('vus') or 1} VU × {r['iterations']}"
    base = f"{r.get('vus') or '?'} VUs × {r.get('duration') or '?'}"
    return base + (f" (+{r['warmup']} warm-up)" if r.get("warmup") else "")


def findings(m, base, stack, t):
    out = []
    targets = m.get("targets") or {"p95_ms": 500, "error_rate": 0.01}
    bmap = {r["name"]: r for r in (base or {}).get("runs", [])}
    seen_index = set()
    churn = []
    for r in m["runs"]:
        if r.get("kind") == "auth":
            continue
        name, http, db = r["name"], r["http"], r.get("db") or {}
        qpr = db.get("queries_per_request")
        stmts = app_statements(db.get("statements"))
        # N+1: many queries per request and one statement repeated per request
        rep = [s for s in stmts if (s.get("calls_per_request") or 0) >= 3 and re.match(r"^\s*select", s.get("query", ""), re.I)]
        if qpr and qpr >= 5 and rep:
            top = max(rep, key=lambda s: s["calls_per_request"])
            out.append(("high", t["f_n1"].format(run=name, qpr=qpr, cpr=top["calls_per_request"]),
                        [f"`{short_sql(top['query'])}` — {fnum(top['calls'])} calls / {fnum(http['requests'])} requests, mean {top.get('mean_ms')} ms"],
                        FIX["n+1"].get(stack, "")))
        # missing index
        for e in r.get("explain") or []:
            for sc in (e.get("plan") or {}).get("seq_scans") or []:
                rows = sc.get("table_rows") or 0
                if rows >= 10000 and sc.get("filter") and (sc["table"], sc["filter"]) not in seen_index:
                    seen_index.add((sc["table"], sc["filter"]))
                    out.append(("high", t["f_index"].format(table=sc["table"], rows=fnum(int(rows)), flt=short_sql(sc["filter"], 100)),
                                [f"`{short_sql(e['query'])}` — mean {e.get('mean_ms') and round(e['mean_ms'], 2)} ms × {fnum(e.get('calls'))} calls",
                                 "plan: " + " → ".join((e.get("plan") or {}).get("nodes") or [])[:300]],
                                t["fix_index"]))
        conn = r.get("connections") or {}
        pool = conn.get("pool_size")
        if pool and conn.get("max_active") is not None and conn["max_active"] >= pool and \
                ((http.get("p95_ms") or 0) > targets["p95_ms"] or http["status"]["5xx"] > 0):
            out.append(("high", t["f_pool"].format(run=name, active=conn["max_active"], pool=pool),
                        [f"avg active {conn.get('avg_active') and round(conn['avg_active'], 1)}, p95 {fnum(http.get('p95_ms'))} ms, 5xx {http['status']['5xx']}"],
                        t["fix_pool"]))
        if conn.get("max_connections") and conn.get("max_total") and conn["max_total"] >= 0.9 * conn["max_connections"]:
            out.append(("high", t["f_maxconn"].format(run=name, total=conn["max_total"], max=conn["max_connections"]), [], t["fix_pool"]))
        ns = db.get("new_sessions") or 0
        if http["requests"] >= 100 and ns >= 0.5 * http["requests"]:
            churn.append((name, ns, http["requests"]))
        lw_events = conn.get("lock_wait_events") or 0
        if (conn.get("max_lock_wait") or 0) > 0 or (db.get("deadlocks") or 0) > 0 or lw_events > 0:
            out.append(("medium", t["f_lock"].format(run=name, n=conn.get("max_lock_wait") or 0,
                                                     s=conn.get("lock_wait_samples") or 0, d=db.get("deadlocks") or 0),
                        [t["ev_lock"].format(e=lw_events)] if lw_events else [], t["fix_lock"]))
        for inv in r.get("invariants") or []:
            if inv.get("ok") is False:
                det = ", ".join(f"{k}={v}" for k, v in (inv.get("detail") or {}).items() if k != "ok")
                out.append(("critical", t["f_race"].format(name=inv["name"], run=name),
                            [inv.get("description") or "", det,
                             f"HTTP ok {http['status']['ok']}, expected {http['status'].get('expected', 0)}, 4xx {http['status']['4xx']}, 5xx {http['status']['5xx']}"],
                            FIX["race"].get(stack, "")))
        for svc, rs in (r.get("resources") or {}).items():
            if svc not in ("app", "db"):
                continue
            if (rs.get("cpu_avg_of_limit_pct") or 0) >= 85:
                out.append(("medium", t["f_cpu"].format(svc=svc, run=name, avg=rs["cpu_avg_of_limit_pct"],
                                                        mx=rs.get("cpu_max_of_limit_pct") or 0, cores=rs.get("cpu_limit_cores")), [], t["fix_cpu"]))
            if rs.get("mem_max_mb") and rs.get("mem_limit_mb") and rs["mem_max_mb"] >= 0.9 * rs["mem_limit_mb"]:
                out.append(("medium", t["f_mem"].format(svc=svc, run=name, used=rs["mem_max_mb"], lim=rs["mem_limit_mb"]), [], t["fix_mem"]))
        for c in r.get("containers") or []:
            if c.get("oom_killed") or c.get("restarts"):
                out.append(("critical", t["f_oom"].format(svc=c["name"], run=name), [], t["fix_mem"]))
        if r.get("kind") != "race":
            er = http.get("error_rate") or 0
            if er > targets["error_rate"]:
                s = http["status"]
                out.append(("high", t["f_err"].format(run=name, rate=er, target=targets["error_rate"], s5=s["5xx"], ne=s["neterr"], s4=s["4xx"]), [], ""))
            if (http.get("p95_ms") or 0) > targets["p95_ms"]:
                out.append(("medium", t["f_p95"].format(run=name, p95=http["p95_ms"], target=targets["p95_ms"]), [], ""))
            b = bmap.get(name)
            if b and b["http"].get("p95_ms") and http.get("p95_ms") and http["p95_ms"] >= 2 * b["http"]["p95_ms"]:
                out.append(("medium", t["f_slowdown"].format(run=name, x=http["p95_ms"] / b["http"]["p95_ms"],
                                                             b=b["http"]["p95_ms"], p=http["p95_ms"]), [], ""))
    if churn:  # one finding for all runs: it is an app-wide setting
        worst = max(churn, key=lambda c: c[1] / c[2])
        out.append(("high", t["f_churn"].format(run=", ".join(f"`{c[0]}`" for c in churn).strip("`"),
                                                 s=fnum(worst[1]), r=fnum(worst[2])),
                    [t["ev_churn"].format(x=c[1] / c[2]) + f" ({c[0]})" for c in churn],
                    FIX["churn"].get(stack, FIX["churn"]["_"])))
    order = {"critical": 0, "high": 1, "medium": 2}
    return sorted(out, key=lambda f: order[f[0]])


def verdict_line(bp, t, targets):
    if not bp:
        return t["verdict_none"]
    tg = bp.get("targets") or targets
    args = dict(run=bp["run"], p95=fnum(tg["p95_ms"], 0), err=f"{tg['error_rate']:.1%}")
    if not bp.get("max_ok_vus"):
        first = bp["stages"][0]["vus"] if bp.get("stages") else "?"
        return t["verdict_zero"].format(n=first, **args)
    key = "verdict_capped" if bp.get("capped") else "verdict"
    return t[key].format(n=bp["max_ok_vus"], **args)


def render(m, base, bp, before, lang):
    t = L[lang]
    prof = m.get("profile") or {}
    app, db, net = prof.get("app") or {}, prof.get("db") or {}, prof.get("network") or {}
    lines = [f"# {t['title']} — {m['label']} · {m['generated_at']}", "",
             verdict_line(bp, t, m.get("targets") or {"p95_ms": 500, "error_rate": 0.01}), "",
             f"> {t['approx']}", ""]
    fs = findings(m, base, m.get("stack"), t)

    lines += [f"## {t['summary']}", ""]
    if fs:
        for sev, title, _, _ in fs[:6]:
            lines.append(f"- {t['sev'][sev]} {title}")
    else:
        lines.append(t["no_findings"])
    lines.append("")

    lines += [f"## {t['conditions']}", "", "| | |", "|---|---|",
              f"| {t['profile']} | {prof.get('name', '—')} |",
              f"| {t['app']} | {app.get('cpus', '—')} vCPU / {app.get('memory_mb', '—')} MB |",
              f"| {t['db']} | {db.get('instance_class', '—')} — {db.get('cpus', '—')} vCPU / {db.get('memory_mb', '—')} MB, "
              f"cpu_mode {db.get('cpu_mode', '—')}, max_connections {db.get('max_connections', '—')} |",
              f"| {t['latency']} | {net.get('app_db_latency_ms', '—')} ms (jitter {net.get('jitter_ms', 0)} ms) |",
              f"| {t['pool']} | {next((r.get('connections', {}).get('pool_size') for r in m['runs'] if r.get('connections')), '—')} |",
              f"| {t['data']} | " + ", ".join(f"{k} {fnum(v if isinstance(v, int) else v.get('rows', 0))}" for k, v in (m.get("seed_tables") or {}).items()) + f" ({t['seed']} {m.get('seed')}) |",
              f"| {t['auth']} | {t['auth_modes'].get(m.get('auth_mode') or 'none', m.get('auth_mode'))} |",
              f"| {t['targets']} | p95 ≤ {fnum((m.get('targets') or {}).get('p95_ms'), 0)} ms, errors ≤ {((m.get('targets') or {}).get('error_rate') or 0):.1%} |",
              ""]
    if (app.get("replicas") or 1) > 1:
        lines += [t["replicas"].format(n=app["replicas"]), ""]

    bmap = {r["name"]: r for r in (base or {}).get("runs", [])}
    lines += [f"## {t['results']}", ""]
    if base:
        lines += [f"| {t['run']} | {t['load']} | p50 ({t['baseline']} → {t['prod']}) | p95 ({t['baseline']} → {t['prod']}) | "
                  f"p99 ({t['prod']}) | {t['rps']} ({t['baseline']} → {t['prod']}) | {t['err']} | {t['qpr']} |",
                  "|---|---|---:|---:|---:|---:|---:|---:|"]
    else:
        lines += [f"| {t['run']} | {t['load']} | p50 | p95 | p99 | {t['rps']} | {t['err']} | {t['qpr']} |",
                  "|---|---|---:|---:|---:|---:|---:|---:|"]
    auth_runs = []
    for r in m["runs"]:
        if r.get("kind") == "auth":
            auth_runs.append(r)
            continue
        h, b = r["http"], (bmap.get(r["name"]) or {}).get("http")
        err = f"{(h.get('error_rate') or 0) * 100:.2f}%"
        qpr = fnum((r.get("db") or {}).get("queries_per_request"))
        if base and b:
            lines.append(f"| {r['name']} | {load_desc(r)} | {fnum(b.get('p50_ms'))} → {fnum(h.get('p50_ms'))} | "
                         f"{fnum(b.get('p95_ms'))} → **{fnum(h.get('p95_ms'))}** | {fnum(h.get('p99_ms'))} | "
                         f"{fnum(b.get('rps'))} → {fnum(h.get('rps'))} | {err} | {qpr} |")
        else:
            lines.append(f"| {r['name']} | {load_desc(r)} | {fnum(h.get('p50_ms'))} | **{fnum(h.get('p95_ms'))}** | "
                         f"{fnum(h.get('p99_ms'))} | {fnum(h.get('rps'))} | {err} | {qpr} |")
    lines.append("")
    for a in auth_runs:
        h = a["http"]
        lines += [f"**{t['auth_cost']}**: {fnum(h['requests'])} logins, p50 {fnum(h.get('p50_ms'))} ms, p95 {fnum(h.get('p95_ms'))} ms", ""]

    if bp and bp.get("stages"):
        lines += ["| VUs | p95 (ms) | " + t["err"] + " | req/s | |", "|---:|---:|---:|---:|---|"]
        for s in bp["stages"]:
            lines.append(f"| {s['vus']} | {fnum(s.get('p95_ms'))} | {(s.get('error_rate') or 0) * 100:.2f}% | {fnum(s.get('rps'))} | {'✅' if s['ok'] else '❌'} |")
        lines.append("")

    lines += [f"## {t['findings']}", ""]
    if not fs:
        lines += [t["no_findings"], ""]
    for i, (sev, title, ev, fix) in enumerate(fs, 1):
        lines.append(f"### {i}. {t['sev'][sev]} {title}")
        ev = [e for e in ev if e]
        if ev:
            lines.append(f"- {t['ev']}: " + ("\n    - " + "\n    - ".join(ev) if len(ev) > 1 else ev[0]))
        if fix:
            lines.append(f"- {t['fix']}: {fix}")
        lines.append("")

    lines += [f"## {t['analysis']}", "", t["analysis_todo"], ""]

    lines += [f"## {t['queries']}", ""]
    for r in m["runs"]:
        st = app_statements((r.get("db") or {}).get("statements"))[:5]
        if not st:
            continue
        lines += [f"**{r['name']}**", "", "| calls | /req | mean ms | total ms | query |", "|---:|---:|---:|---:|---|"]
        for s in st:
            q = short_sql(s.get("query"), 120).replace("|", "\\|")
            lines.append(f"| {fnum(s.get('calls'))} | {fnum(s.get('calls_per_request'))} | {s.get('mean_ms')} | {s.get('total_ms')} | `{q}` |")
        lines.append("")

    lines += [f"## {t['resources']}", "",
              "| run | service | CPU avg / max (% of limit) | mem max / limit (MB) | DB conns max (active) | lock waits |",
              "|---|---|---:|---:|---:|---:|"]
    for r in m["runs"]:
        conn = r.get("connections") or {}
        for svc in ("app", "db"):
            rs = (r.get("resources") or {}).get(svc)
            if not rs:
                continue
            cpu = (f"{fnum(rs.get('cpu_avg_of_limit_pct'), 0)} / {fnum(rs.get('cpu_max_of_limit_pct'), 0)}"
                   if rs.get("cpu_limit_cores") else f"{fnum(rs.get('cpu_avg_pct'), 0)} / {fnum(rs.get('cpu_max_pct'), 0)} (of 1 core)")
            dbc = f"{conn.get('max_total', '—')} ({conn.get('max_active', '—')})" if svc == "db" else ""
            lw = str(conn.get("max_lock_wait", "—")) if svc == "db" else ""
            lines.append(f"| {r['name']} | {svc} | {cpu} | {fnum(rs.get('mem_max_mb'), 0)} / {fnum(rs.get('mem_limit_mb'), 0)} | {dbc} | {lw} |")
    lines.append("")

    invs = [(r["name"], i) for r in m["runs"] for i in (r.get("invariants") or [])]
    if invs:
        lines += [f"## {t['race']}", "", f"| {t['run']} | invariant | | detail |", "|---|---|---|---|"]
        for name, i in invs:
            mark = t["inv_ok"] if i.get("ok") else (t["inv_bad"] if i.get("ok") is False else t["inv_none"])
            det = ", ".join(f"{k}={v}" for k, v in (i.get("detail") or {}).items() if k != "ok")
            lines.append(f"| {name} | {i['name']} — {i.get('description') or ''} | {mark} | {det} |")
        lines.append("")

    if before:
        lines += [compare.render(before, m, lang), ""]

    lines += [f"## {t['limits']}", "", t["lim_head"], "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in t["lim_rows"]]
    if m.get("auth_mode") == "bypass":
        lines.append(f"| {t['auth']} | bypass | {t['auth_modes']['bypass']} |")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="prod")
    ap.add_argument("--baseline", default="baseline", help="label of the local baseline run (used if present)")
    ap.add_argument("--before", help="label to compare against (fix verification)")
    ap.add_argument("--lang", default="en", choices=sorted(L))
    a = ap.parse_args()
    runs = pp_dir() / "runs"
    m = read_json(runs / a.label / "metrics.json")
    base = read_json(runs / a.baseline / "metrics.json", default={}) if a.baseline != a.label else {}
    bp = read_json(runs / a.label / "breakpoint.json", default={})
    before = read_json(runs / a.before / "metrics.json") if a.before else None
    text = render(m, base or None, bp or None, before, a.lang)
    out_dir = pp_dir() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{a.label}.md"
    out.write_text(text)
    shutil.copyfile(out, out_dir / "latest.md")
    info(f"wrote {out.relative_to(pp_dir().parent)} (and reports/latest.md)")
    print(str(out.relative_to(pp_dir().parent)))


if __name__ == "__main__":
    main()
