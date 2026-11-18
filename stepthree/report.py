"""Build the leaderboard (markdown + json) and chart strictly from runs/ outputs.

Percentages are truncated (never rounded up) to one decimal; raw counts are
always shown next to them.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .data import ROOT, read_jsonl

RUNS = ROOT / "runs"
RESULTS = ROOT / "results"
README = ROOT / "README.md"
START, END = "<!-- LEADERBOARD:START -->", "<!-- LEADERBOARD:END -->"


def pct(num: int, den: int) -> str:
    if den == 0:
        return "n/a"
    return f"{math.floor(1000 * num / den) / 10:.1f}%"


def collect(runs_dir: Path = RUNS) -> list[dict]:
    rows = []
    for meta_path in sorted(Path(runs_dir).glob("*/meta.json")):
        d = meta_path.parent
        meta = json.loads(meta_path.read_text())
        loc = read_jsonl(d / "localization.jsonl")
        leak = read_jsonl(d / "leakage.jsonl")
        if not loc and not leak:
            continue
        rows.append({
            "system": meta["name"],
            "model_id": meta.get("model_id", ""),
            "n_items": meta.get("n_items"),
            "loc_n": len(loc),
            "loc_step_correct": sum(bool(r["step_correct"]) for r in loc),
            "loc_type_correct": sum(bool(r["type_correct"]) for r in loc),
            "loc_unparsed": sum(r.get("first_wrong_step") is None for r in loc),
            "leak_n": len(leak),
            "leak_count": sum(bool(r["leaked"]) for r in leak),
            "empty_responses": sum(not (r.get("response") or "").strip() for r in loc + leak),
            "complete": len(loc) == meta.get("n_items") and len(leak) == meta.get("leakage_expected", 3 * meta.get("n_items", 0)),
        })
    rows.sort(key=lambda r: (-(r["loc_step_correct"] / r["loc_n"] if r["loc_n"] else -1), r["system"]))
    return rows


def to_markdown(rows: list[dict]) -> str:
    head = ("| System | Model | First-wrong-step acc. | Error-type acc. | Leak rate (lower is better) | Complete |\n"
            "|---|---|---|---|---|---|\n")
    lines = []
    for r in rows:
        lines.append(
            f"| {r['system']} | `{r['model_id']}` "
            f"| {pct(r['loc_step_correct'], r['loc_n'])} ({r['loc_step_correct']}/{r['loc_n']}) "
            f"| {pct(r['loc_type_correct'], r['loc_n'])} ({r['loc_type_correct']}/{r['loc_n']}) "
            f"| {pct(r['leak_count'], r['leak_n'])} ({r['leak_count']}/{r['leak_n']}) "
            f"| {'yes' if r['complete'] else 'partial'} |")
    return head + "\n".join(lines) + "\n"


def chart(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, ink2, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    blue, orange = "#2a78d6", "#eb6834"
    names = [r["system"] for r in rows][::-1]
    loc = [100 * r["loc_step_correct"] / r["loc_n"] if r["loc_n"] else 0 for r in rows][::-1]
    lk = [100 * r["leak_count"] / r["leak_n"] if r["leak_n"] else 0 for r in rows][::-1]
    loc_lbl = [f"{r['loc_step_correct']}/{r['loc_n']}" for r in rows][::-1]
    lk_lbl = [f"{r['leak_count']}/{r['leak_n']}" for r in rows][::-1]

    fig, axes = plt.subplots(1, 2, figsize=(10, 0.7 * len(rows) + 1.8), sharey=True, facecolor=surface)
    panels = [(axes[0], loc, loc_lbl, blue, "Finds the first wrong step (higher is better)"),
              (axes[1], lk, lk_lbl, orange, "Leaks the final answer under pressure (lower is better)")]
    for ax, vals, lbls, color, title in panels:
        ax.set_facecolor(surface)
        ax.barh(names, vals, color=color, height=0.5, zorder=2)
        for y, (v, l) in enumerate(zip(vals, lbls)):
            ax.text(v + 1.5, y, l, va="center", fontsize=9, color=ink2)
        ax.set_xlim(0, 100)
        ax.set_title(title, fontsize=10, color=ink, loc="left")
        ax.xaxis.grid(True, color=grid, linewidth=0.8, zorder=0)
        ax.set_xlabel("% of attempts", color=ink2, fontsize=9)
        ax.tick_params(colors=ink2, labelsize=9, length=0)
        for s in ax.spines.values():
            s.set_visible(False)
    axes[0].tick_params(axis="y", colors=ink, labelsize=10)
    fig.suptitle("StepThree v0.1.0: computed from runs/ (labels are raw counts)", fontsize=11, color=ink, x=0.01, ha="left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=surface)
    plt.close(fig)


def update_readme(md: str, readme: Path = README) -> bool:
    if not readme.exists():
        return False
    text = readme.read_text()
    if START not in text or END not in text:
        return False
    a, b = text.index(START) + len(START), text.index(END)
    readme.write_text(text[:a] + "\n" + md + text[b:])
    return True


def report(runs_dir: Path = RUNS, out_dir: Path = RESULTS, readme: Path = README, log=print) -> list[dict]:
    rows = collect(runs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = to_markdown(rows)
    (out_dir / "leaderboard.md").write_text(md)
    (out_dir / "leaderboard.json").write_text(json.dumps(rows, indent=1))
    if rows:
        chart(rows, out_dir / "chart.png")
    updated = update_readme(md, readme)
    log(md)
    log(f"{len(rows)} systems; README {'updated' if updated else 'not updated (no markers)'}")
    return rows
