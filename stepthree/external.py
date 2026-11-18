"""Real-student-error track: MathEDU (Hsu et al., 2025) on MathQA problems.

MathEDU has authentic student solutions (LaTeX) where teachers marked each wrong
part (`error_equation`). We split a solution into steps and take the gold label
as the earliest step containing a teacher-marked error. Items are kept only if
every marked error is found verbatim (after whitespace/markup normalisation).

The MathEDU repo has no licence file, so its data is NOT copied into this repo:
it is downloaded at run time (pinned commit) into data/external/ (gitignored),
and cached prompts for this track are stored without their text.
MathQA (Amini et al., 2019) is Apache-2.0 and provides the problem statements.
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import urllib.request
import zipfile
from pathlib import Path

from .data import ROOT

MATHEDU_COMMIT = "acb1873f1569048d72c90855febc6f367b1e3356"
MATHEDU_URL = ("https://raw.githubusercontent.com/NYCU-NLP-Lab/MathEDU/"
               + MATHEDU_COMMIT + "/dataset/time_series_split/{}.json")
MATHEDU_SPLITS = ("train", "val", "test")
MATHQA_URL = "https://math-qa.github.io/math-QA/data/MathQA.zip"
MATHQA_SPLITS = ("train", "dev", "test")  # == HF math_qa train+validation+test, the order MathEDU ids index
MAX_STEPS = 20


def ext_dir() -> Path:
    return Path(os.environ.get("STEPTHREE_EXT_DIR", ROOT / "data" / "external"))


# ---------------- segmentation + gold label ----------------

_ENV = re.compile(r"\\(?:begin|end)\{[a-zA-Z*]+\}(?:\{[^{}]*\})?")


def segment(process: str) -> list[str]:
    """Split a LaTeX solution into steps: lines, \\\\ breaks, display-math boundaries."""
    s = _ENV.sub("\n", process.replace("\r", ""))
    s = s.replace("$$", "\n").replace("\\[", "\n").replace("\\]", "\n")
    steps = []
    for part in re.split(r"\\\\|\n", s):
        part = part.replace("&", " ").strip()
        part = re.sub(r"\s+", " ", part)
        if part in {"$", ""} or not re.search(r"[0-9A-Za-z]", part):
            continue
        steps.append(part)
    return steps


def _norm(s: str) -> str:
    s = s.replace("\\left", "").replace("\\right", "").replace("\\,", "").replace("\\!", "")
    s = re.sub(r"[\s$&]", "", s)
    return s.rstrip(".,;")


def locate(steps: list[str], error_equation: str) -> int | None:
    """0-based index of the first step containing the marked error, or None."""
    targets = [_norm(error_equation)] + [_norm(p) for p in segment(error_equation)]
    norm_steps = [_norm(s) for s in steps]
    for t in targets:
        if len(t) < 2:
            continue
        for i, ns in enumerate(norm_steps):
            if t in ns:
                return i
    return None


def build_mathedu_items(rows: list[dict], mathqa: list[dict]) -> tuple[list[dict], dict]:
    items, stats = [], {"wrong": 0, "no_errors": 0, "unlocated": 0, "bad_length": 0, "no_problem": 0}
    for idx, r in enumerate(rows):
        if r.get("correct_or_not") != "wrong":
            continue
        stats["wrong"] += 1
        errs = [e for e in (r.get("teacher_review") or {}).get("error") or [] if e.get("error_equation")]
        if not errs:
            stats["no_errors"] += 1
            continue
        qid = r.get("id")
        if not isinstance(qid, int) or not 0 <= qid < len(mathqa):
            stats["no_problem"] += 1
            continue
        steps = segment(r.get("student_process") or "")
        if not 2 <= len(steps) <= MAX_STEPS:
            stats["bad_length"] += 1
            continue
        locs = [locate(steps, e["error_equation"]) for e in errs]
        if any(l is None for l in locs):
            stats["unlocated"] += 1
            continue
        first = min(range(len(errs)), key=lambda j: locs[j])
        items.append({
            "id": f"mathedu-{idx}", "source": "mathedu", "problem_id": f"mathqa-{qid}",
            "statement": mathqa[qid]["Problem"].strip(), "steps": steps, "k": locs[first] + 1,
            "error_type": errs[first].get("error_type", ""), "student_id": r.get("student_id"),
        })
    stats["kept"] = len(items)
    return items, stats


# ---------------- download + load ----------------

def _get(url: str, timeout=120) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def fetch(dest: Path | None = None, get=_get) -> Path:
    dest = dest or ext_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for sp in MATHEDU_SPLITS:
        f = dest / f"mathedu_{sp}.json"
        if not f.exists():
            f.write_bytes(get(MATHEDU_URL.format(sp)))
    mq = dest / "mathqa.json"
    if not mq.exists():
        z = zipfile.ZipFile(io.BytesIO(get(MATHQA_URL)))
        rows = []
        for sp in MATHQA_SPLITS:
            name = next(n for n in z.namelist() if n.endswith(f"{sp}.json") and "MACOSX" not in n
                        and "challenge" not in n)
            rows += json.loads(z.read(name))
        mq.write_text(json.dumps([{"Problem": r["Problem"]} for r in rows]))
    return dest


def load_mathedu(dest: Path | None = None, get=_get) -> tuple[list[dict], dict]:
    dest = fetch(dest, get)
    rows = []
    for sp in MATHEDU_SPLITS:
        rows += json.loads((dest / f"mathedu_{sp}.json").read_text())
    mathqa = json.loads((dest / "mathqa.json").read_text())
    return build_mathedu_items(rows, mathqa)


def select_external(items: list[dict], n: int, seed: int) -> list[dict]:
    """Seeded sample, at most one item per MathQA problem."""
    rng = random.Random(seed)
    pool = sorted(items, key=lambda r: r["id"])
    rng.shuffle(pool)
    out, seen = [], set()
    for it in pool:
        if it["problem_id"] in seen:
            continue
        seen.add(it["problem_id"])
        out.append(it)
        if len(out) >= n:
            break
    return out
