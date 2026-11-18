"""Real-student-error track. Fixtures are invented; no MathEDU text is stored in this repo."""
import io
import json
import zipfile

from stepthree import evaluate as ev
from stepthree import external as ex
from stepthree import report as rp
from stepthree.data import read_jsonl

PROC = r"Let $x$ be the price $$ \begin{aligned} & 3 x+2=11 \\ & 3 x=13 \\ & x=\frac{13}{3} \end{aligned} $$"


def _row(proc=PROC, errs=(r"3 x=13",), qid=0, verdict="wrong"):
    return {"id": qid, "student_id": 1, "student_answer": "13/3", "student_process": proc,
            "correct_or_not": verdict,
            "teacher_review": {"error_counts": len(errs),
                               "error": [{"error_type": "Arithmetical error", "error_equation": e} for e in errs]}}


MATHQA = [{"Problem": "three pens and a 2 dollar fee cost 11 dollars . price of a pen ?"}]


def test_segment_splits_latex_lines():
    assert ex.segment(PROC) == ["Let $x$ be the price", "3 x+2=11", "3 x=13", "x=\\frac{13}{3}"]


def test_locate_ignores_spacing_and_markup():
    steps = ex.segment(PROC)
    assert ex.locate(steps, "3x = 13") == 2
    assert ex.locate(steps, r"& 3 x=13 \\ & x=\frac{13}{3}") == 2  # multi-line mark -> its first line
    assert ex.locate(steps, "y=7") is None


def test_build_items_gold_is_earliest_marked_step():
    items, stats = ex.build_mathedu_items([_row(errs=(r"x=\frac{13}{3}", "3 x=13"))], MATHQA)
    assert stats["kept"] == 1 and items[0]["k"] == 3 and items[0]["statement"] == MATHQA[0]["Problem"]


def test_build_items_filters():
    rows = [_row(verdict="correct"), _row(errs=("9 y=1",)), _row(proc="x=4"), _row(errs=("",))]
    items, stats = ex.build_mathedu_items(rows, MATHQA)
    assert items == [] and stats["unlocated"] == 1 and stats["bad_length"] == 1 and stats["no_errors"] == 1


def test_fetch_and_load_with_fake_network(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for sp in ex.MATHQA_SPLITS:
            z.writestr(f"{sp}.json", json.dumps(MATHQA if sp == "train" else []))
        z.writestr("challenge_test.json", "[]")
    calls = []

    def get(url):
        calls.append(url)
        if url == ex.MATHQA_URL:
            return buf.getvalue()
        return json.dumps([_row()] if "train" in url else []).encode()

    items, stats = ex.load_mathedu(tmp_path, get=get)
    assert stats["kept"] == 1 and items[0]["k"] == 3
    assert all(ex.MATHEDU_COMMIT in u for u in calls if "MathEDU" in u)  # pinned version
    ex.load_mathedu(tmp_path, get=get)
    assert len(calls) == 4  # second load served from data/external/


def test_select_external_seeded_one_per_problem():
    items = [{"id": f"m-{i}", "problem_id": f"q{i % 5}"} for i in range(20)]
    a, b = ex.select_external(items, 4, 0), ex.select_external(items, 4, 0)
    assert a == b and len(a) == 4 and len({i["problem_id"] for i in a}) == 4


class Post:
    calls = 0

    def __call__(self, url, headers, payload):
        Post.calls += 1
        return 200, json.dumps({"choices": [{"message": {"content": '{"first_wrong_step": 3}'}}]})


def test_external_track_runs_scores_and_hides_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    cfg = ev.load_config(ev.CONFIG_PATH)
    cfg["providers"]["openrouter"].update(rpm=100000, rpd=1000)
    cfg["usage_log"] = "usage.jsonl"
    cache = ev.Cache(tmp_path / "cache.jsonl")
    client = ev.Client(cfg, "openrouter", cache, post=Post())
    client.key = "test"
    ext_items, _ = ex.build_mathedu_items([_row(), _row(errs=("3 x+2=11",))], MATHQA * 1)
    model = {"name": "fake", "provider": "openrouter", "id": "fake/m:free"}
    meta = ev.run_model(cfg, model, [], {}, cache, tasks=("external",), client=client,
                        log=lambda *a: None, ext_items=ext_items)
    assert meta["external_done"] == 2 and meta["external_n"] == 2
    rows = read_jsonl(tmp_path / "runs" / "fake" / "external.jsonl")
    assert [r["step_correct"] for r in rows] == [True, False]
    assert all(r["messages"] is None for r in read_jsonl(tmp_path / "cache.jsonl"))  # no dataset text cached
    assert "3 x+2" not in (tmp_path / "cache.jsonl").read_text()
    readme = tmp_path / "README.md"
    readme.write_text(f"{rp.START}\n{rp.END}\n")
    out = rp.report(tmp_path / "runs", tmp_path / "results", readme, log=lambda *a: None)
    assert out[0]["ext_n"] == 2 and out[0]["ext_step_correct"] == 1
    assert "50.0% (1/2)" in readme.read_text() and "constant-answer baseline" in readme.read_text()


def test_baseline_best_constant():
    assert rp.baseline([1, 1, 2, 3]) == (1, 2, 4)
    assert rp.baseline([2, 3]) == (2, 1, 2)  # ties -> smallest step
    assert rp.baseline([]) == (0, 0, 0)
