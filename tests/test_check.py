import pytest

from stepthree.check import check, eq_equal, expr_equal, failing_steps, step_ok
from stepthree.data import load_problems

PROBLEMS = load_problems()


def test_fifty_problems_three_topics():
    assert len(PROBLEMS) == 50
    assert len({p["id"] for p in PROBLEMS}) == 50
    assert {p["topic"] for p in PROBLEMS} == {"algebra", "calculus", "physics"}


@pytest.mark.parametrize("p", PROBLEMS, ids=[p["id"] for p in PROBLEMS])
def test_clean_solution_accepted(p):
    var = p.get("var", "x")
    assert check(p["steps"], p["kind"], var) is None
    assert step_ok(p["steps"][-1], p["final_answer"], p["kind"], var)


def test_expr_equal_basic():
    assert expr_equal("(x+1)**2", "x**2 + 2*x + 1")
    assert not expr_equal("(x+1)**2", "x**2 + 1")


def test_units():
    assert expr_equal("36*kilometer/hour", "10*meter/second")
    assert not expr_equal("36*kilometer/hour", "36*meter/second")
    assert not expr_equal("10*meter + 10*meter/second", "20*meter/second")


def test_chain_rule_detected():
    assert expr_equal("Derivative(sin(x**2), x)", "2*x*cos(x**2)")
    assert not expr_equal("Derivative(sin(x**2), x)", "cos(x**2)")


def test_numeric_fallback_identity():
    # true identity that plain simplify may not close
    assert expr_equal("atan(x) + atan(1/x)", "pi/2")


def test_eq_solution_sets():
    assert eq_equal("x**2 - 5*x + 6 = 0", "x = 2 or x = 3")
    assert not eq_equal("x**2 - 5*x + 6 = 0", "x = 2")


def test_first_failing_step():
    steps = ["2*x + 3 = 11", "2*x = 14", "x = 7"]
    assert check(steps, "eq") == 2
    assert failing_steps(steps, "eq") == [2]
