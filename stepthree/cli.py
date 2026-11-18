"""Command-line interface: stepthree inject | check | eval | report."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from . import __version__


def cmd_inject(a):
    from .data import load_problems, write_jsonl, ITEMS_PATH
    from .inject import generate
    items, stats = generate(load_problems(a.problems) if a.problems else load_problems(), seed=a.seed)
    out = a.out or ITEMS_PATH
    write_jsonl(out, items)
    print(json.dumps({k: v for k, v in stats.items() if k.startswith("kept")}))
    print(f"wrote {len(items)} items to {out}")
    return 0


def cmd_check(a):
    from .check import check
    from .data import ITEMS_PATH, load_problems, problems_by_id, read_jsonl
    probs = problems_by_id()
    bad = [p["id"] for p in load_problems() if check(p["steps"], p["kind"], p.get("var", "x")) is not None]
    print(f"clean solutions: {len(probs) - len(bad)}/{len(probs)} pass" + (f"; failing: {bad}" if bad else ""))
    items = read_jsonl(a.items or ITEMS_PATH)
    miss = []
    for it in items:
        p = probs[it["problem_id"]]
        if check(it["steps"], p["kind"], p.get("var", "x")) != it["k"]:
            miss.append(it["id"])
    c = Counter(it["error_type"] for it in items)
    print(f"items: {len(items)}; k recovered for {len(items) - len(miss)}/{len(items)}; by type {dict(c)}")
    return 1 if (bad or miss) else 0


def cmd_eval(a):
    from .evaluate import run
    only = a.models.split(",") if a.models else None
    run(a.config, dry_run=a.dry_run, only=only)
    return 0


def cmd_report(a):
    from .report import report
    report()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stepthree", description="Benchmark AI tutors on first-wrong-step localization and answer leakage.")
    ap.add_argument("--version", action="version", version=f"stepthree {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inject", help="generate gated flawed solutions (data/items.jsonl)")
    p.add_argument("--problems", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_inject)
    p = sub.add_parser("check", help="verify clean solutions and that every item breaks exactly at k")
    p.add_argument("--items", default=None)
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("eval", help="run models from config.yaml (cached, throttled, resumable)")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--dry-run", action="store_true", help="only the first 10 subset items")
    p.add_argument("--models", default=None, help="comma-separated model names from config")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("report", help="leaderboard + chart from runs/")
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
