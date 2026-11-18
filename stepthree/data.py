"""Load problems and items."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROBLEM_DIR = DATA_DIR / "problems"
ITEMS_PATH = DATA_DIR / "items.jsonl"


def load_problems(problem_dir: Path | str = PROBLEM_DIR) -> list[dict]:
    out = []
    for f in sorted(Path(problem_dir).glob("*.json")):
        out.extend(json.loads(f.read_text()))
    return out


def problems_by_id(problem_dir=PROBLEM_DIR) -> dict:
    return {p["id"]: p for p in load_problems(problem_dir)}


def read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def write_jsonl(path, rows) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
