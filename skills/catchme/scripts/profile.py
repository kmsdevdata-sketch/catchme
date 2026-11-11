#!/usr/bin/env python3
"""F2 — production profile → .prod-parity/profile.yaml

Sources, in order of preference:
  1. IaC in the repo (Terraform, CDK, ECS task definition JSON, k8s manifests)   --scan / --from-iac
  2. AWS read-only lookup (describe-*/list-* only, needs local AWS profile/SSO)  --aws
  3. Presets or manual values                                                     --app-preset/--db-preset/--app/--db
Explicit flags always override values found in IaC/AWS.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import HOME, die, info, pp_dir, project_root, read_yaml, write_yaml  # noqa: E402
from detect import SKIP_DIRS, read, rel  # noqa: E402

PRESETS = HOME / "presets"


# --------------------------------------------------------------------------- presets

def load_presets():
    return {
        "ecs-fargate": read_yaml(PRESETS / "ecs-fargate.yaml")["sizes"],
        "ec2": read_yaml(PRESETS / "ec2.yaml")["sizes"],
        "rds": read_yaml(PRESETS / "rds.yaml")["classes"],
    }


def rds_max_connections(memory_mb):
    return max(20, min(5000, int(memory_mb * 1024 * 1024 * 0.9 / 9531392)))


def db_from_class(cls, presets):
    c = presets["rds"].get(cls)
    if not c:
        die(f"unknown DB class '{cls}'. Known: {', '.join(presets['rds'])}. Use --db cpus=..,memory_mb=.. instead.")
    return {"instance_class": cls, "cpus": c["cpus"], "memory_mb": c["memory_mb"],
            "baseline_cpu_pct": c.get("baseline_cpu_pct")}


def app_from_preset(spec, presets):
    if ":" not in spec:
        die("--app-preset format: ecs-fargate:<size> or ec2:<type>")
    kind, size = spec.split(":", 1)
    table = presets.get(kind)
    if not table or size not in table:
        die(f"unknown app preset '{spec}'. Run --list-presets.")
    v = table[size]
    return {"cpus": v["cpus"], "memory_mb": v["memory_mb"], "baseline_cpu_pct": v.get("baseline_cpu_pct"),
            "instance": f"{kind}:{size}"}


def fargate_from_units(cpu_units, mem_mb):
    return {"cpus": round(int(cpu_units) / 1024, 3), "memory_mb": int(mem_mb)}


# --------------------------------------------------------------------------- IaC scan

def iter_files(root, exts):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(exts):
                yield Path(dirpath) / fn


def tf_vars(root):
    values = {}
    for p in iter_files(root, (".tf",)):
        for m in re.finditer(r'variable\s+"(\w+)"\s*\{(.*?)\n\}', read(p), re.S):
            d = re.search(r'default\s*=\s*"?([^"\n]+)"?', m.group(2))
            if d:
                values[m.group(1)] = d.group(1).strip()
    for p in iter_files(root, (".tfvars", ".auto.tfvars")):
        for m in re.finditer(r'^\s*(\w+)\s*=\s*"?([^"\n]+)"?', read(p), re.M):
            values[m.group(1)] = m.group(2).strip()
    return values


def resolve(v, variables):
    if v is None:
        return None
    v = v.strip().strip('"')
    m = re.match(r"^\$?\{?var\.(\w+)\}?$", v)
    if m:
        return variables.get(m.group(1), f"<unresolved var.{m.group(1)}>")
    return v


def tf_blocks(text, rtype):
    for m in re.finditer(r'resource\s+"' + rtype + r'"\s+"([\w-]+)"\s*\{', text):
        start, depth, i = m.end(), 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        yield m.group(1), text[start:i], m.start()


def k8s_cpu(v):
    v = str(v).strip().strip("'\"")
    return int(v[:-1]) / 1000 if v.endswith("m") else float(v)


def k8s_mem(v):
    v = str(v).strip().strip("'\"")
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024, "K": 1 / 1000, "M": 1, "G": 1000}
    for u, mult in units.items():
        if v.endswith(u):
            return int(float(v[: -len(u)]) * mult)
    return int(int(v) / 1024 / 1024)


def scan_iac(root):
    cands = []
    variables = tf_vars(root)
    for p in iter_files(root, (".tf",)):
        t = read(p)
        for name, body, pos in tf_blocks(t, "aws_ecs_task_definition"):
            cpu = re.search(r'^\s*cpu\s*=\s*"?([^"\n]+)"?', body, re.M)
            mem = re.search(r'^\s*memory\s*=\s*"?([^"\n]+)"?', body, re.M)
            cpu_v, mem_v = resolve(cpu.group(1) if cpu else None, variables), resolve(mem.group(1) if mem else None, variables)
            c = {"kind": "app", "source": f"{rel(root, p)}:{t.count(chr(10), 0, pos) + 1}", "name": name, "via": "terraform ecs task"}
            if cpu_v and cpu_v.isdigit() and mem_v and mem_v.isdigit():
                c.update(fargate_from_units(cpu_v, mem_v))
            else:
                c["unresolved"] = {"cpu": cpu_v, "memory": mem_v}
            cands.append(c)
        for rtype in ("aws_db_instance", "aws_rds_cluster_instance"):
            for name, body, pos in tf_blocks(t, rtype):
                ic = re.search(r'instance_class\s*=\s*"?([^"\n]+)"?', body)
                eng = re.search(r'engine\s*=\s*"?([^"\n]+)"?', body)
                c = {"kind": "db", "source": f"{rel(root, p)}:{t.count(chr(10), 0, pos) + 1}", "name": name,
                     "via": f"terraform {rtype}", "instance_class": resolve(ic.group(1), variables) if ic else None,
                     "engine": resolve(eng.group(1), variables) if eng else None}
                cands.append(c)
        for name, body, pos in tf_blocks(t, "aws_db_parameter_group"):
            m = re.search(r'name\s*=\s*"max_connections"\s*\n?\s*value\s*=\s*"?(\d+)"?', body)
            if m:
                cands.append({"kind": "db_param", "source": f"{rel(root, p)}:{t.count(chr(10), 0, pos) + 1}",
                              "max_connections": int(m.group(1))})
        for name, body, pos in tf_blocks(t, "aws_instance"):
            it = re.search(r'instance_type\s*=\s*"?([^"\n]+)"?', body)
            if it:
                cands.append({"kind": "app", "source": f"{rel(root, p)}:{t.count(chr(10), 0, pos) + 1}", "name": name,
                              "via": "terraform aws_instance", "ec2_type": resolve(it.group(1), variables)})

    for p in iter_files(root, (".json",)):
        t = read(p)
        if '"containerDefinitions"' not in t:
            continue
        try:
            d = json.loads(t)
        except json.JSONDecodeError:
            continue
        cpu, mem = d.get("cpu"), d.get("memory")
        if not (cpu and mem):
            cdefs = d.get("containerDefinitions") or []
            cpu = sum(int(c.get("cpu") or 0) for c in cdefs) or None
            mem = sum(int(c.get("memory") or c.get("memoryReservation") or 0) for c in cdefs) or None
        if cpu and mem:
            cands.append({"kind": "app", "source": rel(root, p), "via": "ecs task definition json",
                          **fargate_from_units(cpu, mem)})

    for p in iter_files(root, (".yaml", ".yml")):
        t = read(p)
        if not re.search(r"^kind:\s*(Deployment|StatefulSet)", t, re.M):
            continue
        for doc in re.split(r"^---\s*$", t, flags=re.M):
            if not re.search(r"^kind:\s*(Deployment|StatefulSet)", doc, re.M):
                continue
            lim = re.search(r"limits:\s*\n((?:\s+\w+:.*\n?)+)", doc) or re.search(r"requests:\s*\n((?:\s+\w+:.*\n?)+)", doc)
            if not lim:
                continue
            cpu = re.search(r"cpu:\s*['\"]?([\d.]+m?)", lim.group(1))
            mem = re.search(r"memory:\s*['\"]?([\d.]+[KMGT]i?)", lim.group(1))
            rep = re.search(r"replicas:\s*(\d+)", doc)
            name = re.search(r"^\s*name:\s*(\S+)", doc, re.M)
            if cpu or mem:
                cands.append({"kind": "app", "source": rel(root, p), "via": "k8s manifest",
                              "name": name.group(1) if name else None,
                              "cpus": k8s_cpu(cpu.group(1)) if cpu else None,
                              "memory_mb": k8s_mem(mem.group(1)) if mem else None,
                              "replicas": int(rep.group(1)) if rep else 1})

    for p in iter_files(root, (".ts", ".py")):
        t = read(p)
        if "aws-cdk" not in t and "aws_cdk" not in t:
            continue
        for m in re.finditer(r"(?:memoryLimitMiB|memory_limit_mib)\s*[:=]\s*(\d+)", t):
            window = t[max(0, m.start() - 400): m.end() + 400]
            cpu = re.search(r"\bcpu\s*[:=]\s*(\d+)", window)
            if cpu:
                cands.append({"kind": "app", "source": f"{rel(root, p)}:{t.count(chr(10), 0, m.start()) + 1}",
                              "via": "cdk fargate", **fargate_from_units(cpu.group(1), m.group(1))})
        for m in re.finditer(r"InstanceType\.of\(\s*(?:ec2\.)?InstanceClass\.(\w+)\s*,\s*(?:ec2\.)?InstanceSize\.(\w+)", t):
            window = t[max(0, m.start() - 600): m.start()]
            if re.search(r"DatabaseInstance|DatabaseCluster|rds\.", window):
                cls = f"db.{m.group(1).lower()}.{m.group(2).lower()}"
                cls = cls.replace("burstable3", "t3").replace("burstable4_graviton", "t4g").replace("memory5", "r5").replace("standard5", "m5")
                cands.append({"kind": "db", "source": f"{rel(root, p)}:{t.count(chr(10), 0, m.start()) + 1}",
                              "via": "cdk rds", "instance_class": cls})
    return cands


# --------------------------------------------------------------------------- AWS (read-only)

ALLOWED_AWS_OPS = {"describe-services", "describe-task-definition", "describe-db-instances",
                   "describe-db-parameters", "list-clusters", "list-services"}


def aws_ro(service, op, args, aws_profile=None, region=None):
    if op not in ALLOWED_AWS_OPS or not (op.startswith("describe-") or op.startswith("list-")):
        die(f"refusing non read-only AWS call: {service} {op}")
    if not shutil.which("aws"):
        die("aws CLI not found. Install it or use --from-iac / presets.")
    cmd = ["aws", service, op] + args + ["--output", "json"]
    if aws_profile:
        cmd += ["--profile", aws_profile]
    if region:
        cmd += ["--region", region]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        die(f"aws {service} {op} timed out")
    if out.returncode != 0:
        # stderr may mention the profile name but never credentials; keep it short
        die(f"aws {service} {op} failed: {out.stderr.strip().splitlines()[-1] if out.stderr.strip() else 'unknown error'}")
    return json.loads(out.stdout or "{}")


def from_aws(a):
    found = {}
    if a.cluster and a.service:
        svc = aws_ro("ecs", "describe-services", ["--cluster", a.cluster, "--services", a.service], a.aws_profile, a.region)
        services = svc.get("services") or []
        if not services:
            die("ECS service not found")
        td_arn = services[0]["taskDefinition"]
        td = aws_ro("ecs", "describe-task-definition", ["--task-definition", td_arn], a.aws_profile, a.region)["taskDefinition"]
        found["app"] = {**fargate_from_units(td.get("cpu") or 256, td.get("memory") or 512),
                        "replicas": services[0].get("desiredCount", 1), "source": f"aws:ecs:{a.cluster}/{a.service}"}
    if a.db_id:
        dbs = aws_ro("rds", "describe-db-instances", ["--db-instance-identifier", a.db_id], a.aws_profile, a.region)["DBInstances"]
        if not dbs:
            die("RDS instance not found")
        d = dbs[0]
        found["db"] = {"instance_class": d["DBInstanceClass"], "engine": d.get("Engine"), "source": f"aws:rds:{a.db_id}"}
        groups = d.get("DBParameterGroups") or []
        if groups:
            params = aws_ro("rds", "describe-db-parameters",
                            ["--db-parameter-group-name", groups[0]["DBParameterGroupName"], "--source", "user"],
                            a.aws_profile, a.region).get("Parameters", [])
            for prm in params:
                if prm.get("ParameterName") == "max_connections" and str(prm.get("ParameterValue", "")).isdigit():
                    found["db"]["max_connections"] = int(prm["ParameterValue"])
    if not found:
        die("--aws needs --cluster/--service and/or --db-id (use `aws ecs list-clusters` yourself to find them)")
    return found


# --------------------------------------------------------------------------- build

def parse_kv(s):
    out = {}
    for part in (s or "").split(","):
        if not part.strip():
            continue
        k, v = part.split("=", 1)
        v = v.strip()
        out[k.strip()] = float(v) if re.match(r"^\d+\.\d+$", v) else int(v) if v.isdigit() else v
    return out


def header(sources):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return ("# catchme production profile — generated " + ts + "\n"
            "# Edit freely; `catchme gen` reads this file. Values are approximations of production.\n"
            "# cpu_mode: burst = full vCPUs (T-class credits available) | baseline = credits exhausted\n"
            "# Sources: " + ", ".join(f"{k}={v}" for k, v in sources.items()) + "\n\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true", help="list IaC candidates and exit")
    ap.add_argument("--from-iac", nargs="?", const="auto", help="use IaC candidates (auto, or comma list of indexes from --scan)")
    ap.add_argument("--aws", action="store_true", help="read-only AWS lookup")
    ap.add_argument("--aws-profile")
    ap.add_argument("--region")
    ap.add_argument("--cluster")
    ap.add_argument("--service")
    ap.add_argument("--db-id")
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--app-preset", help="ecs-fargate:<size> | ec2:<type>")
    ap.add_argument("--db-preset", help="rds:<class>, e.g. rds:db.t3.micro")
    ap.add_argument("--db-class", help="alias for --db-preset rds:<class>")
    ap.add_argument("--app", help="manual: cpus=0.5,memory_mb=1024,replicas=1")
    ap.add_argument("--db", help="manual: cpus=2,memory_mb=1024,max_connections=100")
    ap.add_argument("--latency-ms", type=float)
    ap.add_argument("--jitter-ms", type=float)
    ap.add_argument("--p95-ms", type=float)
    ap.add_argument("--error-rate", type=float)
    ap.add_argument("--cpu-mode", choices=["burst", "baseline"])
    ap.add_argument("--pool-size", type=int, help="app DB pool size (default: stack default)")
    ap.add_argument("--name")
    a = ap.parse_args()

    presets = load_presets()
    if a.list_presets:
        print("App (--app-preset):")
        for kind in ("ecs-fargate", "ec2"):
            print(f"  {kind}: " + ", ".join(presets[kind]))
        print("DB (--db-preset rds:<class>):\n  " + ", ".join(presets["rds"]))
        return

    root = project_root()
    if a.scan:
        cands = scan_iac(root)
        print(json.dumps([{"index": i, **c} for i, c in enumerate(cands)], indent=2, ensure_ascii=False))
        if not cands:
            info("no IaC sizing found (Terraform / CDK / ECS task definition / k8s). Use --aws or presets.")
        return

    path = pp_dir() / "profile.yaml"
    prof = read_yaml(path, default={}) if path.exists() else {}
    app = dict(prof.get("app") or {})
    db = dict(prof.get("db") or {})
    sources = dict(prof.get("source") or {})

    if a.from_iac:
        cands = scan_iac(root)
        if a.from_iac != "auto":
            idx = [int(x) for x in a.from_iac.split(",")]
            cands = [cands[i] for i in idx]
        apps = [c for c in cands if c["kind"] == "app" and (c.get("cpus") or c.get("ec2_type"))]
        dbs = [c for c in cands if c["kind"] == "db" and c.get("instance_class")]
        params = [c for c in cands if c["kind"] == "db_param"]
        if a.from_iac == "auto" and (len(apps) > 1 or len(dbs) > 1):
            print(json.dumps([{"index": i, **c} for i, c in enumerate(scan_iac(root))], indent=2, ensure_ascii=False))
            die("multiple IaC candidates — ask the user which one, then pass --from-iac <i,j>", 3)
        if apps:
            c = apps[0]
            if c.get("ec2_type"):
                app.update(app_from_preset(f"ec2:{c['ec2_type']}", presets))
            else:
                app.update({k: c[k] for k in ("cpus", "memory_mb", "replicas") if c.get(k)})
            sources["app"] = f"iac:{c['source']}"
        if dbs:
            c = dbs[0]
            if str(c["instance_class"]).startswith("<unresolved"):
                die(f"DB instance class is {c['instance_class']} in {c['source']} — pass --db-preset explicitly")
            db.update(db_from_class(c["instance_class"], presets))
            sources["db"] = f"iac:{c['source']}"
        if params:
            db["max_connections"] = params[0]["max_connections"]
        if not apps and not dbs:
            die("no usable IaC sizing found — use --aws or presets", 3)

    if a.aws:
        found = from_aws(a)
        if "app" in found:
            src = found["app"].pop("source")
            app.update(found["app"])
            sources["app"] = src
        if "db" in found:
            src = found["db"].pop("source")
            mc = found["db"].pop("max_connections", None)
            found["db"].pop("engine", None)
            db.update(db_from_class(found["db"]["instance_class"], presets))
            if mc:
                db["max_connections"] = mc
            sources["db"] = src

    if a.app_preset:
        app.update(app_from_preset(a.app_preset, presets))
        sources["app"] = f"preset:{a.app_preset}"
    db_preset = a.db_preset or (f"rds:{a.db_class}" if a.db_class else None)
    if db_preset:
        if not db_preset.startswith("rds:"):
            die("--db-preset format: rds:<class>")
        db.update(db_from_class(db_preset.split(":", 1)[1], presets))
        sources["db"] = f"preset:{db_preset}"
    if a.app:
        app.update(parse_kv(a.app))
        sources["app"] = "manual"
    if a.db:
        db.update(parse_kv(a.db))
        sources["db"] = "manual"

    if not app.get("cpus") or not app.get("memory_mb"):
        die("app cpus/memory_mb unknown — pass --app-preset, --app, --from-iac or --aws", 3)
    if not db.get("cpus") or not db.get("memory_mb"):
        die("db cpus/memory_mb unknown — pass --db-preset, --db, --from-iac or --aws", 3)

    app.setdefault("replicas", 1)
    if a.pool_size is not None:
        app["db_pool_size"] = a.pool_size
    app.setdefault("db_pool_size", None)
    db["engine"] = "postgres"
    db.setdefault("cpu_mode", "burst")
    if a.cpu_mode:
        db["cpu_mode"] = a.cpu_mode
    db.setdefault("max_connections", rds_max_connections(db["memory_mb"]))
    db.setdefault("shared_buffers_mb", max(32, int(db["memory_mb"] * 0.25)))

    net = dict(prof.get("network") or {"app_db_latency_ms": 1, "jitter_ms": 0})
    if a.latency_ms is not None:
        net["app_db_latency_ms"] = a.latency_ms
    if a.jitter_ms is not None:
        net["jitter_ms"] = a.jitter_ms
    targets = dict(prof.get("targets") or {"p95_ms": 500, "error_rate": 0.01})
    if a.p95_ms is not None:
        targets["p95_ms"] = a.p95_ms
    if a.error_rate is not None:
        targets["error_rate"] = a.error_rate

    name = a.name or prof.get("name") or (
        f"app {app['cpus']} vCPU/{app['memory_mb']} MB + {db.get('instance_class', 'db')} ({db['cpus']} vCPU/{db['memory_mb']} MB)")
    out = {"name": name, "source": sources, "app": app, "db": db, "network": net, "targets": targets}
    if app.get("replicas", 1) > 1:
        info(f"production runs {app['replicas']} replicas; catchme models one replica with the per-task size "
             f"(pool and throughput numbers are per instance).")
    write_yaml(path, out, header(sources))
    info(f"wrote {path.relative_to(root)} — {name}")
    if db.get("baseline_cpu_pct"):
        eff = max(0.1, round(db["cpus"] * db["baseline_cpu_pct"] / 100, 2))
        info(f"DB is burstable: cpu_mode=burst uses {db['cpus']} vCPU; cpu_mode=baseline would use {eff} vCPU")


if __name__ == "__main__":
    main()
