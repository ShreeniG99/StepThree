import json

import pytest

from stepthree import evaluate as ev
from stepthree import report as rp
from stepthree.data import ITEMS_PATH, problems_by_id, read_jsonl

CFG = ev.load_config(ev.CONFIG_PATH)
ITEMS = read_jsonl(ITEMS_PATH)
PROBS = problems_by_id()


def test_subset_fixed_seeded_and_stratified():
    a = ev.select_subset(ITEMS, 50, 0)
    b = ev.select_subset(ITEMS, 50, 0)
    assert [i["id"] for i in a] == [i["id"] for i in b]
    assert len(a) == 50
    types = {i["error_type"] for i in a}
    assert types == {"sign_flip", "dropped_term", "wrong_chain_rule", "unit_mixup"}


@pytest.mark.parametrize("text,step,etype", [
    ('{"first_wrong_step": 3, "error_type": "sign_flip"}', 3, "sign_flip"),
    ('Sure!\n```json\n{"first_wrong_step": 2, "error_type": "unit_mixup"}\n```', 2, "unit_mixup"),
    ('<think>maybe {"first_wrong_step": 9}</think>{"first_wrong_step": 4, "error_type": "Dropped_Term"}', 4, "dropped_term"),
    ("first_wrong_step: 5, error_type: wrong_chain_rule", 5, "wrong_chain_rule"),
    ("I am not sure.", None, None),
])
def test_parse_localization(text, step, etype):
    p = ev.parse_localization(text)
    assert p["first_wrong_step"] == step and p["error_type"] == etype


class FakePost:
    def __init__(self):
        self.calls = 0

    def __call__(self, url, headers, payload):
        self.calls += 1
        content = payload["messages"][-1]["content"]
        if "JSON" in content:
            return 200, json.dumps({"choices": [{"message": {"content": '{"first_wrong_step": 2, "error_type": "sign_flip"}'}}]})
        return 200, json.dumps({"choices": [{"message": {"content": "I won't tell you; check step 2."}}]})


def _setup(tmp_path, monkeypatch, rpd=1000):
    monkeypatch.setattr(ev, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    cfg = json.loads(json.dumps(CFG))
    cfg["providers"]["openrouter"]["rpm"] = 100000
    cfg["providers"]["openrouter"]["rpd"] = rpd
    cfg["usage_log"] = "usage.jsonl"
    cache = ev.Cache(tmp_path / "cache.jsonl")
    post = FakePost()
    client = ev.Client(cfg, "openrouter", cache, post=post)
    client.key = "test"
    return cfg, cache, client, post


def test_run_caches_and_never_recalls(tmp_path, monkeypatch):
    cfg, cache, client, post = _setup(tmp_path, monkeypatch)
    items = ev.select_subset(ITEMS, 4, 0)
    model = {"name": "fake", "provider": "openrouter", "id": "fake/model:free"}
    meta = ev.run_model(cfg, model, items, PROBS, cache, client=client, log=lambda *a: None)
    assert post.calls == 4 + 12
    assert meta["localization_done"] == 4 and meta["leakage_done"] == 12
    ev.run_model(cfg, model, items, PROBS, ev.Cache(tmp_path / "cache.jsonl"), client=client, log=lambda *a: None)
    assert post.calls == 16  # second run served entirely from cache
    loc = read_jsonl(tmp_path / "runs" / "fake" / "localization.jsonl")
    assert sum(r["step_correct"] for r in loc) == sum(i["k"] == 2 for i in items)
    leak = read_jsonl(tmp_path / "runs" / "fake" / "leakage.jsonl")
    assert not any(r["leaked"] for r in leak)


def test_daily_budget_stops_and_resumes(tmp_path, monkeypatch):
    cfg, cache, client, post = _setup(tmp_path, monkeypatch, rpd=5)
    items = ev.select_subset(ITEMS, 4, 0)
    model = {"name": "fake", "provider": "openrouter", "id": "fake/model:free"}
    meta = ev.run_model(cfg, model, items, PROBS, cache, client=client, log=lambda *a: None)
    assert post.calls == 5 and meta["stopped"]
    assert meta["localization_done"] == 4 and meta["leakage_done"] == 1


def test_missing_key_skips(tmp_path, monkeypatch):
    cfg, cache, client, post = _setup(tmp_path, monkeypatch)
    client.key = ""
    meta = ev.run_model(cfg, {"name": "x", "provider": "openrouter", "id": "x"}, ITEMS[:1], PROBS, cache,
                        client=client, log=lambda *a: None)
    assert meta["skipped"] and post.calls == 0


def test_report_matches_runs(tmp_path, monkeypatch):
    cfg, cache, client, post = _setup(tmp_path, monkeypatch)
    items = ev.select_subset(ITEMS, 4, 0)
    ev.run_model(cfg, {"name": "fake", "provider": "openrouter", "id": "fake/model:free"}, items, PROBS, cache,
                 client=client, log=lambda *a: None)
    readme = tmp_path / "README.md"
    readme.write_text(f"x\n{rp.START}\nold\n{rp.END}\ny\n")
    rows = rp.report(tmp_path / "runs", tmp_path / "results", readme, log=lambda *a: None)
    assert rows[0]["loc_n"] == 4 and rows[0]["leak_n"] == 12 and rows[0]["leak_count"] == 0
    assert (tmp_path / "results" / "chart.png").stat().st_size > 1000
    assert "(0/12)" in readme.read_text() and "old" not in readme.read_text()


def test_pct_truncates_never_rounds_up():
    assert rp.pct(2, 3) == "66.6%"
    assert rp.pct(1, 3) == "33.3%"
    assert rp.pct(0, 0) == "n/a"
