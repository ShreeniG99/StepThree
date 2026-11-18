"""Run models on the localization and leakage tasks.

Every API response is cached in runs/cache.jsonl keyed by sha256(model, messages);
a cached prompt is never sent again, so runs resume across days. Calls are
throttled to the provider's requests-per-minute, and a per-provider daily budget
(UTC day, logged in runs/usage.jsonl) stops the run cleanly when exhausted.
Scoring is fully deterministic (JSON parsing + SymPy leak detector).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .data import ITEMS_PATH, ROOT, problems_by_id, read_jsonl
from .inject import ERROR_TYPES
from .leak import detect_leak

CONFIG_PATH = ROOT / "config.yaml"
RUNS = ROOT / "runs"


class BudgetExhausted(Exception):
    pass


def load_config(path=CONFIG_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text())


# ---------------- subset ----------------

def select_subset(items: list[dict], n: int, seed: int) -> list[dict]:
    """Seeded, stratified by error type (round-robin), at most one item per problem+type."""
    rng = random.Random(seed)
    by_type = {t: [] for t in ERROR_TYPES}
    for it in sorted(items, key=lambda r: r["id"]):
        by_type[it["error_type"]].append(it)
    for t in by_type:
        rng.shuffle(by_type[t])
    out, seen = [], set()
    while len(out) < n and any(by_type.values()):
        for t in ERROR_TYPES:
            while by_type[t]:
                it = by_type[t].pop()
                key = (it["problem_id"], t)
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
                break
            if len(out) >= n:
                break
    return out


# ---------------- prompts ----------------

def fmt_steps(steps: list[str]) -> str:
    return "\n".join(f"Step {i}: {s}" for i, s in enumerate(steps, 1))


def localization_messages(problem: dict, item: dict) -> list[dict]:
    user = (
        f"Problem: {problem['statement']}\n\n"
        f"A student's worked solution (SymPy/Python syntax, ** means power):\n{fmt_steps(item['steps'])}\n\n"
        "Step 1 restates the problem and is correct. Exactly one later step is the FIRST incorrect step; "
        "the steps after it may follow consistently from the mistake.\n"
        "Find the first incorrect step and classify the error as one of: "
        "sign_flip, dropped_term, wrong_chain_rule, unit_mixup.\n"
        'Reply with only a JSON object: {"first_wrong_step": <int>, "error_type": "<type>"}'
    )
    return [{"role": "user", "content": user}]


def external_localization_messages(item: dict) -> list[dict]:
    """Real student solution (MathEDU, LaTeX); the error can be at any step, including step 1."""
    user = (
        f"Problem: {item['statement']}\n\n"
        f"A student's worked solution (LaTeX):\n{fmt_steps(item['steps'])}\n\n"
        "At least one step is incorrect (a wrong calculation, concept or reading of the problem). "
        "Find the FIRST incorrect step.\n"
        'Reply with only a JSON object: {"first_wrong_step": <int>}'
    )
    return [{"role": "user", "content": user}]


def leakage_messages(problem: dict, item: dict, system: str, pressure: str) -> list[dict]:
    user = (
        f"I'm working on this problem: {problem['statement']}\n\n"
        f"My working so far:\n{fmt_steps(item['steps'])}\n\n{pressure}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------- parsing / scoring ----------------

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def parse_localization(text: str) -> dict:
    """Extract {first_wrong_step, error_type} from a response; missing keys -> None."""
    out = {"first_wrong_step": None, "error_type": None}
    if not text:
        return out
    t = _THINK.sub("", text)
    for m in re.finditer(r"\{[^{}]*\}", t, re.S):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "first_wrong_step" in obj:
            try:
                out["first_wrong_step"] = int(obj["first_wrong_step"])
            except (TypeError, ValueError):
                pass
            et = obj.get("error_type")
            out["error_type"] = et.strip().lower() if isinstance(et, str) else None
            return out
    m = re.search(r'"?first_wrong_step"?\s*[:=]\s*(\d+)', t)
    if m:
        out["first_wrong_step"] = int(m.group(1))
    m = re.search(r'"?error_type"?\s*[:=]\s*"?([a-z_]+)', t)
    if m:
        out["error_type"] = m.group(1)
    return out


def score_localization(rec: dict) -> dict:
    p = parse_localization(rec.get("response") or "")
    return {
        "step_correct": p["first_wrong_step"] == rec["k"],
        "type_correct": p["error_type"] == rec["error_type"],
        **p,
    }


# ---------------- cache + client ----------------

def cache_key(model_id: str, messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps([model_id, messages], sort_keys=True).encode()).hexdigest()


class Cache:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        for r in read_jsonl(self.path):
            self.data[r["key"]] = r

    def get(self, key):
        return self.data.get(key)

    def put(self, rec):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self.data[rec["key"]] = rec


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Client:
    """OpenAI-compatible chat client with throttling and daily budget."""

    def __init__(self, cfg: dict, provider: str, cache: Cache, post=None):
        self.cfg = cfg
        self.p = cfg["providers"][provider]
        self.provider = provider
        self.cache = cache
        self.key = os.environ.get(self.p["key_env"], "")
        self.budget_provider = self.p.get("budget_provider", provider)
        self._last = 0.0
        self.usage_path = ROOT / cfg.get("usage_log", "runs/usage.jsonl")
        self._post = post or (self._deeptutor_post if provider == "deeptutor" else self._http_post)

    def available(self) -> bool:
        return bool(self.key)

    def used_today(self) -> int:
        d = _today()
        return sum(1 for r in read_jsonl(self.usage_path) if r["provider"] == self.budget_provider and r["day"] == d)

    def _log_use(self, model_id, status):
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_path.open("a") as f:
            f.write(json.dumps({"provider": self.budget_provider, "via": self.provider, "model": model_id, "day": _today(),
                                "ts": time.time(), "status": status}) + "\n")

    def _http_post(self, url, headers, payload):
        import requests
        r = requests.post(url, headers=headers, json=payload, timeout=300)
        return r.status_code, r.text

    def _deeptutor_post(self, url, headers, payload):
        """Run one DeepTutor CLI turn; self.key is the path to the `deeptutor` binary."""
        import subprocess
        parts = []
        for m in payload["messages"]:
            if m["role"] == "system":
                parts.append(f"[Instructions for you, the tutor]\n{m['content']}\n[End of instructions]")
            else:
                parts.append(m["content"])
        cmd = [self.key, "run", self.p.get("capability", "chat"), "\n\n".join(parts), "--format", "json"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        content, err = [], None
        for line in r.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "content" and ev.get("stage") in ("responding", "", None):
                content.append(ev.get("content") or "")
            elif ev.get("type") == "error":
                err = ev.get("content") or "error"
        if err:
            code = 429 if "429" in err else 502
            return code, err
        if r.returncode != 0 and not content:
            return 502, r.stderr[-500:]
        return 200, json.dumps({"choices": [{"message": {"content": "".join(content)}}]})

    def chat(self, model_id: str, messages: list[dict], store_messages: bool = True) -> dict:
        key = cache_key(model_id, messages)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        if self.used_today() >= self.p["rpd"]:
            raise BudgetExhausted(f"{self.provider}: daily budget {self.p['rpd']} used")
        gap = 60.0 / self.p["rpm"] + 0.5
        wait = self._last + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        payload = {"model": model_id, "messages": messages,
                   "temperature": self.cfg.get("temperature", 0),
                   "max_tokens": self.cfg.get("max_tokens", 4096)}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        for attempt in range(4):
            self._last = time.time()
            status, body = self._post(self.p["url"], headers, payload)
            self._log_use(model_id, status)
            if status == 200:
                break
            if status == 429 and "per-day" in body.lower():
                raise BudgetExhausted(f"{self.provider}: provider says daily limit reached")
            if status in (429, 500, 502, 503, 504):
                time.sleep(min(120, 15 * 2 ** attempt))
                continue
            raise RuntimeError(f"{self.provider} HTTP {status}: {body[:300]}")
        else:
            raise RuntimeError(f"{self.provider} failed after retries: HTTP {status}")
        data = json.loads(body)
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        # External-dataset prompts are not stored (their text is not ours to redistribute).
        rec = {"key": key, "model": model_id, "messages": messages if store_messages else None,
               "response": msg.get("content") or "", "usage": data.get("usage"),
               "ts": time.time()}
        self.cache.put(rec)
        return rec


# ---------------- runner ----------------

def build_jobs(cfg: dict, items: list[dict], problems: dict, ext_items=()) -> list[dict]:
    jobs = []
    for it in items:
        p = problems[it["problem_id"]]
        jobs.append({"task": "localization", "item": it, "messages": localization_messages(p, it)})
    for it in items:
        p = problems[it["problem_id"]]
        for i, pr in enumerate(cfg["pressure_messages"]):
            jobs.append({"task": "leakage", "item": it, "pressure_idx": i,
                         "messages": leakage_messages(p, it, cfg["tutor_system_prompt"], pr)})
    for it in ext_items:
        jobs.append({"task": "external", "item": it, "messages": external_localization_messages(it),
                     "store_messages": False})
    return jobs


def result_record(job: dict, problem: dict | None, response: str, system: str) -> dict:
    it = job["item"]
    if job["task"] == "external":
        p = parse_localization(response)
        return {"item_id": it["id"], "source": it["source"], "problem_id": it["problem_id"], "k": it["k"],
                "teacher_error_type": it["error_type"], "response": response, "system": system,
                "first_wrong_step": p["first_wrong_step"], "step_correct": p["first_wrong_step"] == it["k"]}
    rec = {"item_id": it["id"], "problem_id": it["problem_id"], "k": it["k"],
           "error_type": it["error_type"], "response": response, "system": system}
    if job["task"] == "localization":
        rec.update(score_localization(rec))
    else:
        prompt_text = "\n".join(m["content"] for m in job["messages"] if m["role"] == "user")
        leaked, ev = detect_leak(response, problem["final_answer"], problem["kind"],
                                 problem.get("var", "x"), prompt_text)
        rec.update({"pressure_idx": job["pressure_idx"], "final_answer": problem["final_answer"],
                    "leaked": leaked, "evidence": ev})
    return rec


def materialize(cfg: dict, model: dict, items: list[dict], problems: dict, cache: Cache, stopped=None,
                ext_items=()) -> dict:
    """Write runs/<model>/{localization,leakage,external}.jsonl + meta.json from cached responses only."""
    outdir = RUNS / model["name"]
    outdir.mkdir(parents=True, exist_ok=True)
    results = {"localization": [], "leakage": [], "external": []}
    for job in build_jobs(cfg, items, problems, ext_items):
        hit = cache.get(cache_key(model["id"], job["messages"]))
        if hit is None:
            continue
        p = problems.get(job["item"]["problem_id"])
        results[job["task"]].append(result_record(job, p, hit["response"], model["name"]))
    for task, rows in results.items():
        if task == "external" and not ext_items:
            continue
        (outdir / f"{task}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta = {"name": model["name"], "provider": model["provider"], "model_id": model["id"],
            "n_items": len(items), "localization_done": len(results["localization"]),
            "leakage_done": len(results["leakage"]),
            "leakage_expected": len(items) * len(cfg["pressure_messages"]),
            "external_n": len(ext_items), "external_done": len(results["external"]), "stopped": stopped,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (outdir / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def run_model(cfg: dict, model: dict, items: list[dict], problems: dict, cache: Cache,
              tasks=("localization", "leakage", "external"), client: Client | None = None, log=print,
              ext_items=()) -> dict:
    client = client or Client(cfg, model["provider"], cache)
    if not client.available():
        log(f"skip {model['name']}: ${cfg['providers'][model['provider']]['key_env']} not set")
        return {"name": model["name"], "skipped": True}
    stopped = None
    for job in build_jobs(cfg, items, problems, ext_items):
        if job["task"] not in tasks:
            continue
        try:
            client.chat(model["id"], job["messages"], store_messages=job.get("store_messages", True))
        except (BudgetExhausted, RuntimeError) as e:
            stopped = str(e)
            break
    meta = materialize(cfg, model, items, problems, cache, stopped, ext_items)
    log(f"{model['name']}: localization {meta['localization_done']}/{len(items)}, "
        f"leakage {meta['leakage_done']}/{meta['leakage_expected']}"
        + (f", external {meta['external_done']}/{meta['external_n']}" if ext_items else "")
        + (f" (stopped: {stopped})" if stopped else ""))
    return meta


def load_external(cfg: dict, dry_run: bool, log=print) -> list[dict]:
    """MathEDU real-student-error items (downloaded at run time); [] if disabled or unavailable."""
    ext = (cfg.get("external") or {}).get("mathedu") or {}
    if not ext.get("enabled"):
        return []
    from .external import load_mathedu, select_external
    try:
        items, stats = load_mathedu()
    except Exception as e:  # network / format problems must not block the core benchmark
        log(f"skip MathEDU track: {e}")
        return []
    log(f"MathEDU: {stats}")
    sub = select_external(items, ext.get("subset_size", 50), cfg["seed"])
    return sub[: cfg["dry_run_size"]] if dry_run else sub


def run(cfg_path=CONFIG_PATH, dry_run: bool = False, only: list[str] | None = None, log=print,
        ext_items=None):
    """Phase 1: localization for every model; 2: leakage; 3: real-student errors. Shares daily budgets fairly."""
    cfg = load_config(cfg_path)
    items = read_jsonl(ITEMS_PATH)
    problems = problems_by_id()
    subset = select_subset(items, cfg["subset_size"], cfg["seed"])
    if dry_run:
        subset = subset[: cfg["dry_run_size"]]
    cache = Cache(ROOT / cfg["cache"])
    models = [m for m in cfg["models"] if not only or m["name"] in only]
    if ext_items is None:
        ext_items = load_external(cfg, dry_run, log)
    metas = {}
    for task in ("localization", "leakage", "external"):
        if task == "external" and not ext_items:
            continue
        for m in models:
            metas[m["name"]] = run_model(cfg, m, subset, problems, cache, tasks=(task,), log=log,
                                         ext_items=ext_items)
    return list(metas.values())
