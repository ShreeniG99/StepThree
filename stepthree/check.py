"""Deterministic step checker (no LLM).

A solution is a list of step strings. Step 1 restates the problem; every later
step must be equivalent to the step before it:

* kind "expr": each step is an expression equal to the previous one.
  Proven by simplify(a - b) == 0, falling back to a numeric check at 20 seeded
  random points. Physical units (meter, hour, newton, ...) are converted to SI
  base units first, so 36 km/h == 10 m/s but 36 km/h != 36 m/s.
* kind "eq": each step is an equation "lhs = rhs" (alternatives joined by
  " or ") with the same real solution set for the problem variable.
"""
from __future__ import annotations

import random
from functools import lru_cache

import sympy as sp
from sympy.parsing.sympy_parser import parse_expr
from sympy.physics import units as u
from sympy.physics.units import convert_to
from sympy.physics.units.quantities import Quantity

UNIT_NAMES = [
    "meter", "kilometer", "centimeter", "millimeter", "second", "minute", "hour",
    "gram", "kilogram", "newton", "joule", "watt", "pascal", "kelvin", "ampere",
    "ohm", "volt", "liter",
]
UNITS = {n: getattr(u, n) for n in UNIT_NAMES}
SI_BASE = [u.meter, u.kilogram, u.second, u.ampere, u.kelvin]
# SI base units become positive symbols so a dimension mismatch cannot cancel.
_BASE_SYMS = {q: sp.Symbol(f"_{q.name}", positive=True) for q in SI_BASE}

N_POINTS = 20
REL_TOL = 1e-8


def local_dict(extra: dict | None = None) -> dict:
    d = dict(UNITS)
    d.update({"E": sp.E, "pi": sp.pi})
    if extra:
        d.update(extra)
    return d


@lru_cache(maxsize=20000)
def parse(s: str, evaluate: bool = True) -> sp.Expr:
    return parse_expr(s, local_dict=local_dict(), evaluate=evaluate)


def has_units(e) -> bool:
    return any(isinstance(a, Quantity) for a in sp.preorder_traversal(e))


def to_si_symbols(e):
    """Convert units to SI base units, then replace those by positive symbols."""
    if not has_units(e):
        return e
    e = convert_to(sp.expand(e), SI_BASE)
    # convert_to leaves sums of mismatched dimensions as-is; map remaining
    # quantities (incl. derived ones inside such sums) term by term.
    reps = {}
    for q in e.atoms(Quantity):
        base = convert_to(q, SI_BASE)
        reps[q] = base
    e = e.xreplace(reps)
    return e.xreplace(_BASE_SYMS)


def _numeric_equal(d: sp.Expr, seed: int = 0) -> bool | None:
    """True if d == 0 at all sampled points, False if not, None if undecidable."""
    syms = sorted(d.free_symbols, key=lambda s: s.name)
    rng = random.Random(seed)
    f = sp.lambdify(syms, d, modules=["mpmath"]) if syms else None
    ok = 0
    for _ in range(N_POINTS):
        vals = [rng.uniform(0.3, 2.3) for _ in syms]
        try:
            v = complex(f(*vals)) if syms else complex(sp.N(d, 30))
        except (ZeroDivisionError, ValueError, TypeError, OverflowError):
            continue
        if v != v:  # nan
            continue
        if abs(v) > 1e-7:
            return False
        ok += 1
        if not syms:
            break
    return True if ok else None


def _scale(a, b) -> float:
    try:
        return max(1.0, abs(complex(sp.N(a.subs({s: 1.1 for s in a.free_symbols})))))
    except Exception:
        return 1.0


def expr_equal(a, b) -> bool:
    if isinstance(a, str):
        a = parse(a)
    if isinstance(b, str):
        b = parse(b)
    a = to_si_symbols(a.doit())
    b = to_si_symbols(b.doit())
    d = a - b
    try:
        if sp.simplify(d) == 0:
            return True
    except Exception:
        pass
    # numeric fallback, relative to magnitude of a
    s = _scale(a, b)
    res = _numeric_equal(d / s)
    return bool(res)


# ---------- equations ----------

def parse_eq(s: str):
    """'lhs = rhs or lhs2 = rhs2' -> list of sympy expressions lhs - rhs."""
    parts = []
    for p in s.split(" or "):
        if "=" not in p:
            raise ValueError(f"not an equation: {p!r}")
        lhs, rhs = p.split("=", 1)
        parts.append(parse(lhs.strip()) - parse(rhs.strip()))
    return parts


def solution_set(s: str, var: str = "x"):
    x = sp.Symbol(var)
    sols = sp.S.EmptySet
    for e in parse_eq(s):
        sols = sols.union(sp.solveset(sp.expand(e.doit()), x, domain=sp.S.Reals))
    return sols


def _set_key(S):
    if not isinstance(S, sp.FiniteSet):
        return ("nonfinite", str(S))
    vals = sorted(complex(sp.N(v, 30)).real for v in S)
    return tuple(round(v, 9) for v in vals)


def eq_equal(a: str, b: str, var: str = "x") -> bool:
    try:
        return _set_key(solution_set(a, var)) == _set_key(solution_set(b, var))
    except Exception:
        return False


# ---------- public API ----------

def step_ok(prev: str, cur: str, kind: str, var: str = "x") -> bool:
    try:
        if kind == "expr":
            return expr_equal(prev, cur)
        if kind == "eq":
            return eq_equal(prev, cur, var)
    except Exception:
        return False
    raise ValueError(f"unknown kind {kind!r}")


def failing_steps(steps: list[str], kind: str, var: str = "x") -> list[int]:
    """All 1-indexed steps that are NOT equivalent to their predecessor."""
    return [i + 1 for i in range(1, len(steps)) if not step_ok(steps[i - 1], steps[i], kind, var)]


def check(steps: list[str], kind: str, var: str = "x") -> int | None:
    """Return the first wrong step (1-indexed) or None if the solution is clean."""
    for i in range(1, len(steps)):
        if not step_ok(steps[i - 1], steps[i], kind, var):
            return i + 1
    return None
