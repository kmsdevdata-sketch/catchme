#!/usr/bin/env python3
"""F3 — environment generation.

Reads .prod-parity/project.json + profile.yaml and writes:
  docker-compose.yml           production-like limits (cpus, mem_limit, DB settings) + Toxiproxy
  docker-compose.baseline.yml  same topology, no limits, default DB settings (local baseline)
  env.prod.sh / env.baseline.sh  values the wrapper needs (ports, toxics)
  toxiproxy.json, db-init/00-catchme.sql
"""
import argparse
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (HOME, die, info, is_local_host, pp_dir, project_root, read_json, read_yaml,  # noqa: E402
                     url_host, write_json, write_yaml)

# Not "catchme": a user named like the catchme schema would put app tables there via search_path ("$user", public)
DB_USER, DB_PASSWORD, DB_NAME = "app_user", "app_password", "app"
PROXY_PORT = 15432
IMAGES = {
    "postgres": "postgres:16",
    "toxiproxy": "ghcr.io/shopify/toxiproxy:2.9.0",
    "k6": "grafana/k6:0.54.0",
    "mock_oauth2": "ghcr.io/navikt/mock-oauth2-server:2.1.10",
}


def db_cpus(db):
    if db.get("cpu_mode") == "baseline" and db.get("baseline_cpu_pct"):
        return max(0.1, round(db["cpus"] * db["baseline_cpu_pct"] / 100, 2))
    return db["cpus"]


def fill(template, values):
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def build_compose(project, profile, mode, context, dockerfile):
    app_cfg, db = profile["app"], profile["db"]
    papp = project["app"]
    pool = app_cfg.get("db_pool_size") or papp.get("default_pool")
    values = {"host": "toxiproxy", "port": PROXY_PORT, "db": DB_NAME, "user": DB_USER,
              "password": DB_PASSWORD, "pool": pool if pool else ""}
    env = {}
    for k, v in (papp.get("db_env") or {}).items():
        val = fill(v, values)
        if not pool:  # stack without a pool (Django) — drop empty pool params
            val = val.replace("connection_limit=&", "").replace("?connection_limit=", "?")
        env[k] = val
    extra = {k: str(v) for k, v in (papp.get("env") or {}).items()}
    extra.update({k: str(v) for k, v in (app_cfg.get("env") or {}).items()})
    allowed = {h.strip() for h in os.environ.get("CATCHME_ALLOW_HOSTS", "").split(",") if h.strip()}
    override = pp_dir() / "compose.override.yml"
    if override.exists():  # services you add in compose.override.yml are local containers too
        allowed |= set((read_yaml(override, default={}).get("services") or {}).keys())
    for k, v in extra.items():  # safety rule 1: nothing in the app's env may point outside local Docker
        for m in re.finditer(r"[a-zA-Z][\w+.-]*://[^\s'\"]+", v):
            host = url_host(m.group(0))
            if host and not is_local_host(host) and host not in allowed:
                die(f"app env {k} points at non-local host '{host}'. catchme only talks to local containers — "
                    f"use a local value, or set CATCHME_ALLOW_HOSTS={host} if this is a harmless public endpoint "
                    f"(e.g. a JWKS URL) and the user agreed.")
    env.update(extra)
    port = int(papp.get("port") or 8080)
    env.setdefault("PORT", str(port))

    pg_cmd = ["postgres",
              "-c", "shared_preload_libraries=pg_stat_statements",
              "-c", "pg_stat_statements.track=all",
              "-c", "pg_stat_statements.track_utility=off",
              "-c", "pg_stat_statements.max=10000",
              "-c", "track_io_timing=on",
              "-c", "log_min_duration_statement=500",
              "-c", "log_lock_waits=on",
              "-c", "deadlock_timeout=100ms"]  # lock waits ≥100 ms get logged → counted per run
    if mode == "prod":
        mem = int(db["memory_mb"])
        pg_cmd += ["-c", f"max_connections={int(db['max_connections'])}",
                   "-c", f"shared_buffers={int(db.get('shared_buffers_mb') or mem // 4)}MB",
                   "-c", f"effective_cache_size={int(mem * 0.75)}MB",
                   "-c", "work_mem=4MB",
                   "-c", f"maintenance_work_mem={max(16, min(256, mem // 16))}MB"]

    db_svc = {
        "image": IMAGES["postgres"],
        "command": pg_cmd,
        "environment": {"POSTGRES_USER": DB_USER, "POSTGRES_PASSWORD": DB_PASSWORD, "POSTGRES_DB": DB_NAME},
        "volumes": ["dbdata:/var/lib/postgresql/data", "./db-init:/docker-entrypoint-initdb.d:ro"],
        "shm_size": "256m",
        "healthcheck": {"test": ["CMD-SHELL", f"pg_isready -U {DB_USER} -d {DB_NAME}"],
                        "interval": "2s", "timeout": "3s", "retries": 60},
        "labels": {"dev.catchme.role": "db"},
    }
    app_svc = {
        "build": {"context": context, "dockerfile": dockerfile},
        "environment": env,
        "ports": [f"127.0.0.1:{int(papp.get('host_port') or 18080)}:{port}"],
        "depends_on": {"db": {"condition": "service_healthy"}, "toxiproxy": {"condition": "service_started"}},
        "labels": {"dev.catchme.role": "app"},
    }
    if mode == "prod":
        db_svc.update({"cpus": db_cpus(db), "mem_limit": f"{int(db['memory_mb'])}m",
                       "memswap_limit": f"{int(db['memory_mb'])}m"})
        app_svc.update({"cpus": app_cfg["cpus"], "mem_limit": f"{int(app_cfg['memory_mb'])}m",
                        "memswap_limit": f"{int(app_cfg['memory_mb'])}m"})

    services = {
        "db": db_svc,
        "toxiproxy": {
            "image": IMAGES["toxiproxy"],
            "command": ["-host=0.0.0.0", "-config=/config/toxiproxy.json"],
            "volumes": ["./toxiproxy.json:/config/toxiproxy.json:ro"],
            "depends_on": {"db": {"condition": "service_healthy"}},
            "labels": {"dev.catchme.role": "proxy"},
        },
        "app": app_svc,
        "k6": {
            "image": IMAGES["k6"],
            "profiles": ["tools"],
            "user": "${CATCHME_UID:-0}:${CATCHME_GID:-0}",
            "volumes": ["./scenarios:/scripts:ro", "./runs:/out"],
            "labels": {"dev.catchme.role": "k6"},
        },
        "mock-oauth2": {
            "image": IMAGES["mock_oauth2"],
            "profiles": ["oauth"],
            "environment": {"SERVER_PORT": "8080"},
            "labels": {"dev.catchme.role": "mock-oauth2"},
        },
    }
    return {"services": services, "volumes": {"dbdata": {}}}


def env_sh(project, profile, mode, compose_file):
    papp, net = project["app"], profile.get("network") or {}
    latency = int(round(float(net.get("app_db_latency_ms") or 0))) if mode == "prod" else 0
    jitter = int(round(float(net.get("jitter_ms") or 0))) if mode == "prod" else 0
    vals = {
        "CM_MODE": mode,
        "CM_COMPOSE_FILE": compose_file,
        "CM_HOST_PORT": int(papp.get("host_port") or 18080),
        "CM_HEALTH_PATH": papp.get("health_path") or "/",
        "CM_LATENCY_MS": latency,
        "CM_JITTER_MS": jitter,
        "CM_APP_CPUS": profile["app"]["cpus"] if mode == "prod" else 0,
        "CM_APP_MEM_MB": profile["app"]["memory_mb"] if mode == "prod" else 0,
        "CM_DB_CPUS": db_cpus(profile["db"]) if mode == "prod" else 0,
        "CM_DB_MEM_MB": profile["db"]["memory_mb"] if mode == "prod" else 0,
    }
    return "# generated by catchme gen — do not edit, edit profile.yaml / project.json instead\n" + \
        "".join(f"{k}={shlex.quote(str(v))}\n" for k, v in vals.items())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context", help="build context (default: project root). Used by `verify` for a git worktree.")
    a = ap.parse_args()

    root, pp = project_root(), pp_dir()
    project = read_json(pp / "project.json")
    profile = read_yaml(pp / "profile.yaml")
    for k in ("app", "db"):
        if k not in profile:
            die(f"profile.yaml has no '{k}' section — run `catchme profile` first")

    papp = project.get("app") or {}
    dockerfile = papp.get("dockerfile")
    if not dockerfile:
        die("project.json app.dockerfile is null. Write .prod-parity/app.Dockerfile from "
            f"templates/dockerfiles/{project.get('stack')}.Dockerfile and set app.dockerfile.")

    if a.context:
        ctx_abs = Path(a.context).expanduser().resolve()
        if not ctx_abs.is_dir():
            die(f"context {a.context} is not a directory")
        context = str(ctx_abs)
        df_path = ctx_abs / dockerfile
        if not df_path.exists() and (root / dockerfile).exists():
            # e.g. .prod-parity/app.Dockerfile only exists in the original checkout
            context_dockerfile = str((root / dockerfile).resolve())
        else:
            context_dockerfile = dockerfile
    else:
        context = os.path.relpath(root, pp)
        context_dockerfile = dockerfile
        if not (root / dockerfile).exists():
            die(f"dockerfile {dockerfile} not found")

    ctx_dir = Path(context) if os.path.isabs(context) else root
    dockerignore = ctx_dir / ".dockerignore"
    ignore_text = dockerignore.read_text(errors="ignore") if dockerignore.exists() else ""
    if ".prod-parity" not in ignore_text:
        info("tip: add `.prod-parity` (and node_modules/build dirs) to .dockerignore to keep builds fast")
    # safety rule 1: an .env with real (non-local) endpoints must not be baked into the test image
    ignored = [ln.strip() for ln in ignore_text.splitlines() if ln.strip() and not ln.startswith("#")]
    for envf in sorted(ctx_dir.glob(".env*")):
        if not envf.is_file() or any(pat in (".env", ".env*", "*.env", envf.name) for pat in ignored):
            continue
        hosts = {url_host(m.group(0)) for m in re.finditer(r"[a-zA-Z][\w+.-]*://[^\s'\"]+", envf.read_text(errors="ignore"))}
        bad = sorted(h for h in hosts if h and not is_local_host(h))
        if bad:
            die(f"{envf.name} points at non-local hosts ({', '.join(bad)}) and is not in .dockerignore, so it would be "
                f"copied into the test image and the app could load it. Add `{envf.name}` to .dockerignore "
                f"(ask the user first — it is their file) and re-run gen.")

    pp.mkdir(parents=True, exist_ok=True)
    (pp / "db-init").mkdir(exist_ok=True)
    (pp / "runs").mkdir(exist_ok=True)
    (pp / "scenarios").mkdir(exist_ok=True)
    shutil.copyfile(HOME / "scripts" / "sql" / "init.sql", pp / "db-init" / "00-catchme.sql")
    write_json(pp / "toxiproxy.json", [{"name": "postgres", "listen": f"0.0.0.0:{PROXY_PORT}",
                                        "upstream": "db:5432", "enabled": True}])

    hdr = ("# generated by `catchme gen` from profile.yaml + project.json — regenerate instead of editing\n")
    for mode, fname in (("prod", "docker-compose.yml"), ("baseline", "docker-compose.baseline.yml")):
        write_yaml(pp / fname, build_compose(project, profile, mode, context, context_dockerfile), hdr)
        (pp / f"env.{mode}.sh").write_text(env_sh(project, profile, mode, fname))

    gi = pp / ".gitignore"
    if not gi.exists():
        gi.write_text("runs/\nstate/\nenv.*.sh\ndocker-compose*.yml\ntoxiproxy.json\ndb-init/\nhooks.enabled\n")

    app_cfg, db = profile["app"], profile["db"]
    info(f"prod: app {app_cfg['cpus']} vCPU / {app_cfg['memory_mb']} MB, db {db_cpus(db)} vCPU / {db['memory_mb']} MB, "
         f"max_connections {db['max_connections']}, app↔db latency {profile.get('network', {}).get('app_db_latency_ms', 0)} ms")
    info(f"wrote {pp.relative_to(root)}/docker-compose.yml (+ baseline)")


if __name__ == "__main__":
    main()
