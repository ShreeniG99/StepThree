from collections import Counter

import pytest
import sympy as sp

from stepthree.check import check, failing_steps
from stepthree.data import ITEMS_PATH, problems_by_id, read_jsonl
from stepthree.inject import ERROR_TYPES, mutate, wrong_diff

PROBS = problems_by_id()
ITEMS = read_jsonl(ITEMS_PATH)


def _one(pid, k, et):
    out = mutate(PROBS[pid], k, et)
    assert out, f"no {et} item for {pid} at k={k}"
    for it in out:
        p = PROBS[pid]
        assert it["k"] == k and it["error_type"] == et
        assert it["steps"][: k - 1] == p["steps"][: k - 1]  # untouched before k
        assert failing_steps(it["steps"], p["kind"], p.get("var", "x")) == [k]  # only k breaks
        assert it["final_answer_shown"] == it["steps"][-1]
    return out


def test_sign_flip():
    out = _one("alg10", 3, "sign_flip")
    assert any("-" in it["steps"][2] for it in out)


def test_dropped_term():
    out = _one("alg01", 3, "dropped_term")
    assert all(len(it["steps"][2]) < len(PROBS["alg01"]["steps"][2]) for it in out)


def test_dropped_root_in_eq():
    out = _one("alg03", 4, "dropped_term")
    assert any(it["steps"][3] in ("x = 3", "x = 2") for it in out)


def test_wrong_chain_rule():
    out = _one("cal01", 3, "wrong_chain_rule")
    # the inner derivative 2*x of x**2 is missing
    assert any("cos(x**2)" in it["steps"][2] and "2*x" not in it["steps"][2] for it in out)


def test_wrong_diff_modes():
    x = sp.Symbol("x")
    assert wrong_diff(sp.sin(x**2), x, "omit_inner") == sp.cos(x**2)
    assert sp.simplify(wrong_diff(sp.sin(x**2), x, "inner_value") - x**2 * sp.cos(x**2)) == 0
    assert wrong_diff(sp.sin(x), x, "omit_inner") == sp.cos(x)  # no composite -> correct


def test_unit_mixup():
    out = _one("phy01", 2, "unit_mixup")
    assert any("36*meter" in it["steps"][1] for it in out)


def test_unit_mixup_not_applicable_without_units():
    assert mutate(PROBS["alg01"], 2, "unit_mixup") == []
    assert mutate(PROBS["alg02"], 2, "wrong_chain_rule") == []


def test_k1_never_mutated():
    for et in ERROR_TYPES:
        assert mutate(PROBS["alg01"], 1, et) == []


def test_dataset_size_and_balance():
    c = Counter(it["error_type"] for it in ITEMS)
    assert len(ITEMS) >= 200
    assert all(c[t] >= 40 for t in ERROR_TYPES), c
    assert len({it["id"] for it in ITEMS}) == len(ITEMS)


@pytest.mark.parametrize("it", ITEMS, ids=[i["id"] for i in ITEMS])
def test_checker_recovers_k(it):
    p = PROBS[it["problem_id"]]
    assert check(p["steps"], p["kind"], p.get("var", "x")) is None
    assert check(it["steps"], p["kind"], p.get("var", "x")) == it["k"]
