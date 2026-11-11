#!/usr/bin/env python3
"""F6 — merge raw run artifacts into one metrics.json per label.

  collect.py finalize --label L      runs/<L>/*/{summary,db_before,db_after,explain,activity,docker_stats,invariants}
                                     → runs/<L>/metrics.json (+ query-baseline.json for full runs)
  collect.py quick-judge             compare runs/quick/metrics.json with query-baseline.json (exit 2 on regression)
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, info, pp_dir, read_json, read_yaml, write_json  # noqa: E402



def load_jsonl(p):
    out = []
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def metric(summary, name, key):
    m = (summary.get("metrics") or {}).get(name)
    if not m:
        return None
    return (m.get("values") or {}).get(key)


def http_stats(summary, tag="main"):
    d = f"http_req_duration{{catchme:{tag}}}"
    r = f"http_reqs{{catchme:{tag}}}"
    f = f"http_req_failed{{catchme:{tag}}}"
    count = metric(summary, r, "count") or 0
    out = {
        "requests": int(count),
        "rps": metric(summary, r, "rate"),
        "avg_ms": metric(summary, d, "avg"),
        "p50_ms": metric(summary, d, "p(50)") or metric(summary, d, "med"),
        "p95_ms": metric(summary, d, "p(95)"),
        "p99_ms": metric(summary, d, "p(99)"),
        "max_ms": metric(summary, d, "max"),
        "error_rate": metric(summary, f, "rate"),
    }
    out["status"] = {k: int(metric(summary, f"catchme_{k}", "count") or 0) for k in ("ok", "expected", "4xx", "5xx", "neterr")}
    if tag == "main" and out["error_rate"] is None and count:
        bad = out["status"]["5xx"] + out["status"]["neterr"] + out["status"]["4xx"]
        out["error_rate"] = bad / count
    return out


def parse_size_mb(s):
    m = re.match(r"^\s*([\d.]+)\s*([KMGT]?i?B)\s*$", s or "")
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2)
    mult = {"B": 1 / 1048576, "KiB": 1 / 1024, "KB": 1 / 1024, "kB": 1 / 1024, "MiB": 1, "MB": 1,
            "GiB": 1024, "GB": 1024, "TiB": 1048576, "TB": 1048576}.get(u, 1)
    return n * mult


def service_of(name):
    m = re.search(r"[-_](app|db|toxiproxy|mock-oauth2)[-_]\d+$", name or "")
    return m.group(1) if m else None


def resources(samples, limits):
    by = {}
    for s in samples:
        svc = service_of(s.get("Name", ""))
        if not svc:
            continue
        cpu = float(str(s.get("CPUPerc", "0")).rstrip("%") or 0)
        usage = str(s.get("MemUsage", "")).split("/")
        mem = parse_size_mb(usage[0]) if usage else None
        lim = parse_size_mb(usage[1]) if len(usage) > 1 else None
        e = by.setdefault(svc, {"cpu": [], "mem": [], "mem_limit_mb": lim})
        e["cpu"].append(cpu)
        if mem is not None:
            e["mem"].append(mem)
    out = {}
    for svc, e in by.items():
        cpus = limits.get(svc)
        cpu_avg = sum(e["cpu"]) / len(e["cpu"]) if e["cpu"] else None
        cpu_max = max(e["cpu"]) if e["cpu"] else None
        out[svc] = {
            "samples": len(e["cpu"]),
            "cpu_avg_pct": cpu_avg,
            "cpu_max_pct": cpu_max,
            "cpu_limit_cores": cpus,
            # share of the limit actually used (100 = pinned at the limit)
            "cpu_avg_of_limit_pct": (cpu_avg / cpus) if (cpu_avg is not None and cpus) else None,
            "cpu_max_of_limit_pct": (cpu_max / cpus) if (cpu_max is not None and cpus) else None,
            "mem_max_mb": max(e["mem"]) if e["mem"] else None,
            "mem_limit_mb": e["mem_limit_mb"],
        }
    return out


def walk_plan(node, acc):
    if isinstance(node, dict):
        if "Node Type" in node:
            acc.append(node)
        for k in ("Plan", "Plans"):
            if k in node:
                walk_plan(node[k], acc)
    elif isinstance(node, list):
        for x in node:
            walk_plan(x, acc)


def plan_summary(plan, table_rows):
    nodes = []
    walk_plan(plan, nodes)
    seq = []
    for n in nodes:
        if n.get("Node Type") == "Seq Scan":
            rel = n.get("Relation Name")
            seq.append({"table": rel, "filter": n.get("Filter"), "plan_rows": n.get("Plan Rows"),
                        "table_rows": table_rows.get(rel)})
    top = nodes[0] if nodes else {}
    return {"top_node": top.get("Node Type"), "total_cost": top.get("Total Cost"), "seq_scans": seq,
            "nodes": [n.get("Node Type") + (f" on {n['Relation Name']}" if n.get("Relation Name") else "")
                      + (f" using {n['Index Name']}" if n.get("Index Name") else "") for n in nodes][:15]}


def table_delta(before, after):
    b = {t["relname"]: t for t in (before.get("tables") or [])}
    out = {}
    for t in after.get("tables") or []:
        o = b.get(t["relname"], {})
        out[t["relname"]] = {
            "seq_scan": (t.get("seq_scan") or 0) - (o.get("seq_scan") or 0),
            "seq_tup_read": (t.get("seq_tup_read") or 0) - (o.get("seq_tup_read") or 0),
            "idx_scan": (t.get("idx_scan") or 0) - (o.get("idx_scan") or 0),
            "rows": max(t.get("reltuples") or 0, t.get("n_live_tup") or 0),
        }
    return out


def finalize_run(d, limits, pool_size):
    cfg = read_json(d / "run.json")
    meta = read_json(d / "meta.json", default={})
    summary = read_json(d / "summary.json", default={})
    if not summary:
        info(f"{d.name}: no k6 summary (did k6 fail?)")
    tag = "auth" if meta.get("kind") == "auth" else "main"
    http = http_stats(summary, tag)
    res = {"name": cfg["name"], "kind": meta.get("kind", "load"), "method": cfg.get("method"), "path": cfg.get("path"),
           "vus": cfg.get("vus"), "duration": cfg.get("duration"), "iterations": cfg.get("iterations"),
           "stages": cfg.get("stages"), "warmup": cfg.get("warmup"), "http": http}
    if tag == "auth":
        res["auth_users"] = (cfg.get("auth") or {}).get("users")
        return res

    before = read_json(d / "db_before.json", default={})
    after = read_json(d / "db_after.json", default={})
    reqs = http["requests"] or 0
    total_calls = (after.get("total_calls") or 0)
    stmts = []
    for s in after.get("statements") or []:
        calls = s.get("calls") or 0
        stmts.append({**s, "calls_per_request": (calls / reqs) if reqs else None})
    tables = table_delta(before, after)
    table_rows = {k: v["rows"] for k, v in tables.items()}
    explains = []
    for e in read_json(d / "explain.json", default=[]) or []:
        item = {k: e.get(k) for k in ("queryid", "query", "calls", "mean_ms", "error")}
        if e.get("plan"):
            item["plan"] = plan_summary(e["plan"], table_rows)
        explains.append(item)
    db_b, db_a = before.get("db") or {}, after.get("db") or {}
    acts = load_jsonl(d / "activity.jsonl")
    conn = {
        "samples": len(acts),
        "max_total": max((a.get("total", 0) for a in acts), default=None),
        "max_active": max((a.get("active", 0) for a in acts), default=None),
        "avg_active": (sum(a.get("active", 0) for a in acts) / len(acts)) if acts else None,
        "max_idle_in_tx": max((a.get("idle_in_tx", 0) for a in acts), default=None),
        "max_lock_wait": max((a.get("lock_wait", 0) for a in acts), default=None),
        "lock_wait_samples": sum(1 for a in acts if a.get("lock_wait", 0) > 0),
        "max_connections": acts[0].get("max_connections") if acts else None,
        "pool_size": pool_size,
        "lock_wait_events": int((d / "lock_waits.txt").read_text().strip() or 0) if (d / "lock_waits.txt").exists() else None,
    }
    containers = []
    ct = d / "containers.txt"
    if ct.exists():
        for line in ct.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                containers.append({"name": parts[0].lstrip("/"), "oom_killed": parts[1] == "true",
                                   "restarts": int(parts[2]) if parts[2].isdigit() else 0})
    res.update({
        "db": {
            "total_queries": total_calls,
            "queries_per_request": (total_calls / reqs) if reqs else None,
            "statements": stmts[:40],
            "deadlocks": (db_a.get("deadlocks") or 0) - (db_b.get("deadlocks") or 0),
            "rollbacks": (db_a.get("xact_rollback") or 0) - (db_b.get("xact_rollback") or 0),
            "temp_bytes": (db_a.get("temp_bytes") or 0) - (db_b.get("temp_bytes") or 0),
            "blks_read": (db_a.get("blks_read") or 0) - (db_b.get("blks_read") or 0),
            "blks_hit": (db_a.get("blks_hit") or 0) - (db_b.get("blks_hit") or 0),
            # new DB sessions opened during the run (PG14+); ≈ requests means no connection pooling
            "new_sessions": (db_a.get("sessions") or 0) - (db_b.get("sessions") or 0),
            "tables": tables,
            "settings": after.get("settings") or {},
        },
        "explain": explains,
        "connections": conn,
        "resources": resources(load_jsonl(d / "docker_stats.jsonl"), limits),
        "containers": containers,
        "expected_status": cfg.get("expected_status"),
        "invariants": [{"name": i.get("name"), "description": i.get("description"),
                        "ok": bool((i.get("result") or {}).get("ok")) if i.get("result") is not None else None,
                        "detail": i.get("result")} for i in (read_json(d / "invariants.json", default=[]) or [])],
    })
    return res


def finalize(label):
    pp = pp_dir()
    base = pp / "runs" / label
    if not base.exists():
        die(f"no runs for label {label}")
    meta = read_json(base / "plan_meta.json", default={})
    profile = read_yaml(pp / "profile.yaml", default={})
    project = read_json(pp / "project.json", default={})
    mode = (pp / "state" / "mode").read_text().strip() if (pp / "state" / "mode").exists() else "prod"
    if mode == "prod":
        limits = {"app": (profile.get("app") or {}).get("cpus"), "db": None}
        db = profile.get("db") or {}
        if db.get("cpus"):
            limits["db"] = (max(0.1, round(db["cpus"] * db["baseline_cpu_pct"] / 100, 2))
                            if db.get("cpu_mode") == "baseline" and db.get("baseline_cpu_pct") else db["cpus"])
    else:
        limits = {}
    pool = (profile.get("app") or {}).get("db_pool_size") or (project.get("app") or {}).get("default_pool")
    runs = []
    for name in meta.get("runs") or sorted(p.name for p in base.iterdir() if (p / "run.json").exists()):
        d = base / name
        if (d / "run.json").exists():
            runs.append(finalize_run(d, limits, pool))
    out = {
        "label": label,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stack": project.get("stack"),
        "profile": profile if mode == "prod" else {"name": "local baseline (no limits, no latency)"},
        "auth_mode": meta.get("auth_mode"),
        "targets": meta.get("targets"),
        "seed": (read_yaml(pp / "seed.yaml", default={}) or {}).get("seed"),
        "seed_tables": (read_yaml(pp / "seed.yaml", default={}) or {}).get("tables"),
        "runs": runs,
    }
    write_json(base / "metrics.json", out)
    if not meta.get("quick") and mode == "prod":
        qb = {r["name"]: r["db"]["queries_per_request"] for r in runs
              if r.get("db") and r["db"].get("queries_per_request") is not None and r["kind"] != "race"}
        if qb:
            write_json(pp / "query-baseline.json", {"label": label, "generated_at": out["generated_at"], "runs": qb})
    info(f"wrote {base.relative_to(pp.parent)}/metrics.json ({len(runs)} runs)")


def quick_judge():
    pp = pp_dir()
    base = read_json(pp / "query-baseline.json", default={})
    if not base:
        info("no query-baseline.json yet — run a full `catchme load` first")
        return 0
    cur = read_json(pp / "runs" / "quick" / "metrics.json")
    regress, lines = [], []
    for r in cur["runs"]:
        q = (r.get("db") or {}).get("queries_per_request")
        b = base["runs"].get(r["name"])
        if q is None or b is None:
            continue
        status = "ok"
        if q > b * 1.2 and q - b >= 1:
            status = "REGRESSION"
            top = sorted((r["db"].get("statements") or []), key=lambda s: -(s.get("calls_per_request") or 0))[:1]
            hint = f" — most repeated: {top[0]['calls_per_request']:.1f}×/req `{top[0]['query'][:140]}`" if top else ""
            regress.append(f"{r['name']}: queries/request {b:.1f} → {q:.1f}{hint}")
        lines.append(f"{r['name']}: {b:.1f} → {q:.1f} queries/request [{status}]")
    print("\n".join(lines) or "no comparable runs")
    if regress:
        print("catchme: queries/request regression detected:\n  " + "\n  ".join(regress), file=sys.stderr)
        return 2
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("finalize")
    f.add_argument("--label", required=True)
    sub.add_parser("quick-judge")
    a = ap.parse_args()
    if a.cmd == "finalize":
        finalize(a.label)
    else:
        sys.exit(quick_judge())


if __name__ == "__main__":
    main()
