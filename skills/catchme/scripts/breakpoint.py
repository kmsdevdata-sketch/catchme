#!/usr/bin/env python3
"""F11 — find the maximum concurrency that still meets the targets.

  breakpoint.py next --label L     prepare the next stage (prints its directory name) or prints "done"
  breakpoint.py judge --label L    read the last stage's k6 summary and update the state

Strategy: start_vus, ×2 until p95 > target or error rate > target (or max_vus), then bisect
between the last passing and first failing level (up to 3 steps, or until within 10%).
Result: runs/<L>/breakpoint.json
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, info, pp_dir, read_json, write_json  # noqa: E402
from collect import http_stats  # noqa: E402
from plan import auth_cfg, load_plan, run_config, targets, write_run  # noqa: E402


def state_path(label):
    return pp_dir() / "runs" / label / "breakpoint" / "state.json"


def settings():
    plan = load_plan()
    bp = plan.get("breakpoint") or {}
    run_name = bp.get("run") or next((r["name"] for r in plan["runs"]
                                      if str(r.get("method") or "GET").upper() == "GET"), None)
    run = next((r for r in plan["runs"] if r["name"] == run_name), None)
    if not run:
        die("breakpoint.run must name a run in plan.yaml")
    return plan, run, {
        "start": int(bp.get("start_vus") or 10),
        "max": int(bp.get("max_vus") or 640),
        "stage": str(bp.get("stage_duration") or "20s"),
        "bisect_steps": int(bp.get("bisect_steps") or 3),
    }


def next_stage(label):
    plan, run, s = settings()
    sp = state_path(label)
    st = read_json(sp, default={}) if sp.exists() else {}
    if not st:
        st = {"run": run["name"], "settings": s, "targets": targets(plan), "phase": "grow",
              "lo": 0, "hi": None, "stages": [], "pending": s["start"], "bisects": 0}
    if st.get("pending") is None:
        print("done")
        return
    vus = st["pending"]
    name = f"vus-{vus:04d}"
    cfg = run_config(plan, run, f"{label}/breakpoint", {"vus": vus, "duration": s["stage"], "stages": None,
                                                        "iterations": None, "name": f"{run['name']}@{vus}"})
    cfg["out"] = f"/out/{label}/breakpoint/{name}/summary.json"
    cfg = {k: v for k, v in cfg.items() if v is not None}
    write_run(f"{label}/breakpoint", name, cfg, "read.js", meta={"kind": "breakpoint", "vus": vus})
    write_json(sp, st)
    auth_cfg(plan)
    print(name)


def judge(label):
    sp = state_path(label)
    st = read_json(sp)
    vus = st["pending"]
    d = pp_dir() / "runs" / label / "breakpoint" / f"vus-{vus:04d}"
    http = http_stats(read_json(d / "summary.json", default={}))
    t = st["targets"]
    p95, err = http.get("p95_ms"), http.get("error_rate") or 0
    ok = p95 is not None and http["requests"] > 0 and p95 <= t["p95_ms"] and err <= t["error_rate"]
    st["stages"].append({"vus": vus, "ok": ok, "p95_ms": p95, "error_rate": err, "rps": http.get("rps"),
                         "requests": http["requests"]})
    info(f"breakpoint {vus} VUs: p95 {p95 if p95 is None else round(p95, 1)} ms, errors {err:.2%} → {'pass' if ok else 'FAIL'}")
    s = st["settings"]
    if ok:
        st["lo"] = max(st["lo"], vus)
    else:
        st["hi"] = vus if st["hi"] is None else min(st["hi"], vus)

    nxt = None
    if st["phase"] == "grow":
        if ok and vus * 2 <= s["max"]:
            nxt = vus * 2
        elif ok:
            st["phase"] = "capped"
        else:
            st["phase"] = "bisect"
    if st["phase"] == "bisect" and nxt is None and st["lo"] > 0 and st["hi"]:
        gap = st["hi"] - st["lo"]
        if st["bisects"] < s["bisect_steps"] and gap > max(1, math.ceil(st["lo"] * 0.1)):
            nxt = (st["lo"] + st["hi"]) // 2
            st["bisects"] += 1
    st["pending"] = nxt
    if nxt is None:
        result = {"run": st["run"], "targets": t, "max_ok_vus": st["lo"], "first_fail_vus": st["hi"],
                  "capped": st["phase"] == "capped", "stages": sorted(st["stages"], key=lambda x: x["vus"])}
        write_json(pp_dir() / "runs" / label / "breakpoint.json", result)
        if st["lo"] == 0:
            info(f"breakpoint: even {s['start']} VUs miss the target")
        else:
            info(f"breakpoint: holds up to {st['lo']} concurrent requests" + (" (max_vus reached)" if result["capped"] else ""))
    write_json(sp, st)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("next", "judge", "reset"):
        p = sub.add_parser(c)
        p.add_argument("--label", default="prod")
    a = ap.parse_args()
    if a.cmd == "next":
        next_stage(a.label)
    elif a.cmd == "judge":
        judge(a.label)
    else:
        sp = state_path(a.label)
        if sp.exists():
            sp.unlink()


if __name__ == "__main__":
    main()
