#!/usr/bin/env python3
"""F5 — turn plan.yaml into per-run k6 configs.

  plan.py prepare --label L [--quick]   writes runs/<L>/<run>/run.json and prints run names (one per line)
  plan.py invariants-before --names a,b SQL storing `before` snapshots
  plan.py invariants-check --names a,b  SQL returning one JSON array with each invariant's result
  plan.py mint-tokens ...               HS256 test tokens → runs/tokens.json (auth mode `token`)
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, info, pp_dir, read_yaml, sql_literal, write_json  # noqa: E402

SCRIPTS = {"read.js", "race.js", "auth.js"}


def load_plan():
    plan = read_yaml(pp_dir() / "plan.yaml")
    if not plan.get("runs"):
        die("plan.yaml has no runs")
    names = set()
    for r in plan["runs"]:
        if not r.get("name") or not re.match(r"^[\w.-]+$", str(r["name"])):
            die(f"every run needs a name of letters/digits/-/_: {r}")
        if r["name"] in names or r["name"].startswith("_"):
            die(f"duplicate or reserved run name: {r['name']}")
        names.add(r["name"])
        if not r.get("path"):
            die(f"run {r['name']}: path is required")
    return plan


def targets(plan):
    prof = read_yaml(pp_dir() / "profile.yaml", default={})
    t = dict(prof.get("targets") or {})
    t.update(plan.get("targets") or {})
    t.setdefault("p95_ms", 500)
    t.setdefault("error_rate", 0.01)
    return t


def auth_cfg(plan):
    a = dict(plan.get("auth") or {"mode": "none"})
    a.setdefault("mode", "none")
    if a["mode"] not in ("login", "token", "bypass", "none"):
        die("auth.mode must be login | token | bypass | none")
    if a["mode"] == "login":
        for k in ("login_path", "body"):
            if not a.get(k):
                die(f"auth.{k} is required for mode login")
    a.setdefault("users", 10)
    return a


def check_base_url(plan):
    """Catch the most common misconfiguration early: base_url port ≠ app container port."""
    from urllib.parse import urlsplit
    proj = pp_dir() / "project.json"
    if not proj.exists():
        return
    app_port = (json.loads(proj.read_text()).get("app") or {}).get("port")
    url = urlsplit(str(plan.get("base_url") or ""))
    port = url.port or (443 if url.scheme == "https" else 80)
    if url.hostname != "app":
        die(f"plan.yaml base_url must point at the compose service `app` (got {plan.get('base_url')}); "
            "catchme never sends load anywhere else")
    if app_port and int(app_port) != port:
        die(f"plan.yaml base_url uses port {port} but project.json app.port is {app_port} — fix one of them")


def run_config(plan, run, label, overrides=None):
    pp = pp_dir()
    a = auth_cfg(plan)
    cfg = {
        "name": run["name"],
        "base_url": str(plan.get("base_url") or "http://app:8080").rstrip("/"),
        "method": str(run.get("method") or "GET").upper(),
        "path": run["path"],
        "body": run.get("body"),
        "headers": run.get("headers") or {},
        "content_type": run.get("content_type"),
        "vus": run.get("vus"),
        "duration": run.get("duration"),
        "iterations": run.get("iterations"),
        "stages": run.get("stages"),
        "think_time": run.get("think_time"),
        "timeout": run.get("timeout"),
        "expected_status": [int(x) for x in (run.get("expected_status") or [])] or None,
        "seed": plan.get("seed", 42),
        "auth": {k: a[k] for k in ("mode", "users", "user_offset", "header", "scheme", "token_from", "cookie_name")
                 if a.get(k) is not None},
        "out": f"/out/{label}/{run['name']}/summary.json",
    }
    if a["mode"] in ("login", "token"):
        cfg["tokens_file"] = "/out/tokens.json"
    if (pp / "runs" / "exports.json").exists():
        cfg["exports_file"] = "/out/exports.json"
    cfg.update(overrides or {})
    return {k: v for k, v in cfg.items() if v is not None}


def script_of(run):
    s = run.get("script") or "read.js"
    if not (pp_dir() / "scenarios" / s).exists():
        die(f"scenario script {s} not found in .prod-parity/scenarios/")
    return s


def write_run(label, name, cfg, script, invariants=None, meta=None):
    d = pp_dir() / "runs" / label / name
    d.mkdir(parents=True, exist_ok=True)
    for f in ("warmup.json", "warmup_summary.json", "summary.json", "db_before.json", "db_after.json", "explain.json", "invariants.json",
              "activity.jsonl", "docker_stats.jsonl", "containers.txt"):
        try:
            (d / f).unlink()
        except FileNotFoundError:
            pass
    write_json(d / "run.json", cfg)
    (d / "script").write_text(script + "\n")
    (d / "invariants").write_text(",".join(invariants or []) + "\n")
    write_json(d / "meta.json", meta or {})


def default_warmup():
    """JVMs spend tens of seconds JIT-compiling at 0.5 vCPU; short runs would measure that, not the app."""
    proj = pp_dir() / "project.json"
    stack = json.loads(proj.read_text()).get("stack") if proj.exists() else None
    return "20s" if stack == "spring-jpa" else "5s"


def warmup_config(plan, run, cfg, label):
    w = run.get("warmup", plan.get("warmup", default_warmup()))
    if not w or str(w).strip() in ("0", "0s", "false", "none"):
        return None
    wc = dict(cfg)
    wc.update({"name": f"{run['name']}@warmup", "duration": str(w), "stages": None, "iterations": None,
               "vus": cfg.get("vus") or 10, "out": f"/out/{label}/{run['name']}/warmup_summary.json"})
    return {k: v for k, v in wc.items() if v is not None}


def prepare(label, quick=False):
    plan = load_plan()
    check_base_url(plan)
    a = auth_cfg(plan)
    tg = targets(plan)
    names = []
    if a["mode"] == "login":
        cfg = run_config(plan, {"name": "_auth", "path": a["login_path"], "method": a.get("method") or "POST"}, label)
        cfg.pop("tokens_file", None)
        cfg["auth"] = {k: v for k, v in a.items() if v is not None}
        if quick:  # 1 VU → one test account is enough; keeps the hook check fast
            cfg["auth"]["users"] = 1
        cfg["tokens_out"] = "/out/quick/tokens.json" if quick else "/out/tokens.json"
        write_run(label, "_auth", cfg, "auth.js", meta={"kind": "auth"})
        names.append("_auth")
    elif a["mode"] == "token" and not (pp_dir() / "runs" / "tokens.json").exists():
        die("auth.mode token needs runs/tokens.json — run `catchme mint-tokens` first")
    known_inv = {i["name"] for i in (read_yaml(pp_dir() / "invariants.yaml", default={}).get("invariants") or [])}
    for run in plan["runs"]:
        is_write = str(run.get("method") or "GET").upper() not in ("GET", "HEAD")
        if quick:
            if not run.get("quick", not is_write) or run.get("script") == "race.js":
                continue
            ov = {"vus": 1, "iterations": int(run.get("quick_iterations") or 20), "stages": None, "duration": None}
            cfg = {k: v for k, v in run_config(plan, run, label, ov).items() if v is not None}
            if "tokens_file" in cfg:  # quick mode keeps its own 1-user token file
                cfg["tokens_file"] = "/out/quick/tokens.json"
            write_run(label, run["name"], cfg, "read.js", meta={"kind": "quick"})
        else:
            invs = run.get("invariants") or []
            bad = [i for i in invs if i not in known_inv]
            if bad:
                die(f"run {run['name']}: unknown invariants {bad} (define them in invariants.yaml)")
            cfg = run_config(plan, run, label)
            is_race = run.get("script") == "race.js"
            wc = None if is_race else warmup_config(plan, run, cfg, label)  # races are one-shot by design
            if wc:
                cfg["warmup"] = wc["duration"]
            write_run(label, run["name"], cfg, script_of(run), invs,
                      meta={"kind": "race" if is_race else "load", "write": is_write})
            if wc:
                write_json(pp_dir() / "runs" / label / run["name"] / "warmup.json", wc)
        names.append(run["name"])
    write_json(pp_dir() / "runs" / label / "plan_meta.json",
               {"label": label, "quick": quick, "auth_mode": a["mode"], "targets": tg, "runs": names})
    print("\n".join(names))


# --------------------------------------------------------------------------- invariants

def load_invariants(names):
    allinv = {i["name"]: i for i in (read_yaml(pp_dir() / "invariants.yaml", default={}).get("invariants") or [])}
    out = []
    for n in [x for x in names.split(",") if x]:
        if n not in allinv:
            die(f"invariant {n} not defined in invariants.yaml")
        if not allinv[n].get("check"):
            die(f"invariant {n} needs a check query")
        out.append(allinv[n])
    return out


def snap_expr(name):
    return f"(SELECT value FROM catchme.snapshot WHERE name = {sql_literal(name)})"


def invariants_before(names):
    stmts = []
    for inv in load_invariants(names):
        n = inv["name"]
        stmts.append(f"DELETE FROM catchme.snapshot WHERE name = {sql_literal(n)};")
        if inv.get("before"):
            q = str(inv["before"]).strip().rstrip(";")
            stmts.append(f"INSERT INTO catchme.snapshot(name, value) SELECT {sql_literal(n)}, to_jsonb(q) FROM ({q}) q LIMIT 1;")
    print("\n".join(stmts))


def invariants_check(names):
    parts = []
    for inv in load_invariants(names):
        n = inv["name"]
        q = str(inv["check"]).strip().rstrip(";").replace("{{snap}}", snap_expr(n))
        parts.append(f"SELECT {sql_literal(n)} AS name, {sql_literal(inv.get('description') or '')} AS description, "
                     f"(SELECT to_jsonb(q) FROM ({q}) q LIMIT 1) AS result")
    if parts:
        print("SELECT COALESCE(json_agg(x), '[]'::json) FROM (\n" + "\nUNION ALL\n".join(parts) + "\n) x;")


# --------------------------------------------------------------------------- tokens

def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def mint_tokens(a):
    secret = os.environ.get(a.secret_env) if a.secret_env else None
    if not secret and a.secret_env:
        proj = json.loads((pp_dir() / "project.json").read_text())
        secret = (proj.get("app", {}).get("env") or {}).get(a.secret_env)
    if not secret:
        die(f"test secret {a.secret_env} not found in the environment or project.json app.env "
            "(it must be the TEST secret the local app uses — never a production secret)")
    now = int(time.time())
    try:
        claims_tpl = json.loads(a.claims)
    except json.JSONDecodeError as e:
        die(f"--claims must be JSON: {e}")
    tokens = []
    for n in range(1 + a.offset, a.count + 1 + a.offset):
        claims = json.loads(json.dumps(claims_tpl).replace("{n}", str(n)))
        for k, v in list(claims.items()):
            if isinstance(v, str) and v.isdigit() and k in ("sub_int", "user_id", "userId", "id"):
                claims[k] = int(v)
        claims.setdefault("iat", now)
        claims.setdefault("exp", now + a.exp_seconds)
        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = b64url(json.dumps(claims, separators=(",", ":")).encode())
        sig = b64url(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        tokens.append(f"{header}.{payload}.{sig}")
    write_json(pp_dir() / "runs" / "tokens.json", tokens)
    info(f"minted {len(tokens)} test tokens → .prod-parity/runs/tokens.json (not printed)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--label", required=True)
    p.add_argument("--quick", action="store_true")
    for c in ("invariants-before", "invariants-check"):
        q = sub.add_parser(c)
        q.add_argument("--names", required=True)
    m = sub.add_parser("mint-tokens")
    m.add_argument("--secret-env", required=True)
    m.add_argument("--count", type=int, default=50)
    m.add_argument("--offset", type=int, default=0)
    m.add_argument("--claims", default='{"sub": "{n}"}')
    m.add_argument("--exp-seconds", type=int, default=3600)
    a = ap.parse_args()
    if a.cmd == "prepare":
        prepare(a.label, a.quick)
    elif a.cmd == "invariants-before":
        invariants_before(a.names)
    elif a.cmd == "invariants-check":
        invariants_check(a.names)
    elif a.cmd == "mint-tokens":
        mint_tokens(a)


if __name__ == "__main__":
    main()
