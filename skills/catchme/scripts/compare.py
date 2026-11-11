#!/usr/bin/env python3
"""F10 — before/after comparison table (queries/request, p95, error rate, throughput).

  compare.py --before prod --after after [--lang en|ko]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import pp_dir, read_json  # noqa: E402

T = {
    "en": {"title": "Before / after fix", "run": "Run", "metric": "Metric", "before": "Before", "after": "After",
           "change": "Change", "qpr": "queries/request", "p95": "p95 (ms)", "err": "error rate", "rps": "req/s",
           "inv": "invariant", "none": "No runs in common.", "ok": "✅ ok", "bad": "❌ violated"},
    "ko": {"title": "수정 전후 비교", "run": "시나리오", "metric": "지표", "before": "수정 전", "after": "수정 후",
           "change": "변화", "qpr": "요청당 쿼리 수", "p95": "p95 (ms)", "err": "에러율", "rps": "처리량 (req/s)",
           "inv": "불변 조건", "none": "공통 시나리오가 없습니다.", "ok": "✅ 유지", "bad": "❌ 위반"},
}


def _pct(b, a):
    if b in (None, 0) or a is None:
        return "—"
    d = (a - b) / b * 100
    return f"{d:+.0f}%"


def _f(v, kind):
    if v is None:
        return "—"
    if kind == "err":
        return f"{v * 100:.2f}%"
    return f"{v:,.1f}"


def render(before, after, lang="en"):
    t = T.get(lang, T["en"])
    bmap = {r["name"]: r for r in before.get("runs", [])}
    rows = []
    for r in after.get("runs", []):
        b = bmap.get(r["name"])
        if not b or r.get("kind") == "auth":
            continue
        pairs = [
            ("qpr", (b.get("db") or {}).get("queries_per_request"), (r.get("db") or {}).get("queries_per_request")),
            ("p95", b["http"].get("p95_ms"), r["http"].get("p95_ms")),
            ("err", b["http"].get("error_rate"), r["http"].get("error_rate")),
            ("rps", b["http"].get("rps"), r["http"].get("rps")),
        ]
        for key, bv, av in pairs:
            rows.append(f"| {r['name']} | {t[key]} | {_f(bv, key)} | {_f(av, key)} | {_pct(bv, av) if key != 'err' else ''} |")
        for inv in r.get("invariants") or []:
            bi = next((x for x in b.get("invariants") or [] if x["name"] == inv["name"]), {})
            mark = {True: t["ok"], False: t["bad"], None: "—"}
            rows.append(f"| {r['name']} | {t['inv']}: {inv['name']} | {mark[bi.get('ok')]} | {mark[inv.get('ok')]} | |")
    if not rows:
        return f"## {t['title']}\n\n{t['none']}\n"
    head = f"| {t['run']} | {t['metric']} | {t['before']} | {t['after']} | {t['change']} |\n|---|---|---:|---:|---:|\n"
    return f"## {t['title']}\n\n" + head + "\n".join(rows) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    runs = pp_dir() / "runs"
    print(render(read_json(runs / a.before / "metrics.json"), read_json(runs / a.after / "metrics.json"), a.lang))


if __name__ == "__main__":
    main()
