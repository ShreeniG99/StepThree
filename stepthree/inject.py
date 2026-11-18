"""Inject one known error at step k of a clean solution and propagate it.

Mutations (all deterministic, SymPy-tree based):
  sign_flip         negate one term of a sum (or the whole side if no sum)
  dropped_term      delete one term of a sum (or one numeric factor / one "or" branch)
  wrong_chain_rule  evaluate a derivative of a composite but forget (or misuse) the
                    inner derivative g'(x)
  unit_mixup        use the wrong unit, e.g. km read as m, minutes read as seconds

After step k, later steps are rewritten to stay consistent with the wrong step:
first by re-applying the same edit to the original step, then by replaying the
original step's operation (evaluating the same derivatives/integrals), then by
a simplification in the style of the original step. The gate keeps an item only
if the checker finds exactly one break, at step k.
"""
from __future__ import annotations

import random
import re
from collections import Counter

import sympy as sp
from sympy import Derivative, Integral

from .check import UNITS, failing_steps, has_units, local_dict, parse_eq, step_ok, check
from sympy.parsing.sympy_parser import parse_expr
from sympy.physics.units import convert_to
from sympy.physics.units.quantities import Quantity

ERROR_TYPES = ["sign_flip", "dropped_term", "wrong_chain_rule", "unit_mixup"]
MAX_VARIANTS = 2  # per (problem, k, error_type)

U = UNITS
UNIT_SWAPS = [
    ("km_as_m", {U["kilometer"]: U["meter"]}),
    ("kmh_as_ms", {U["kilometer"]: U["meter"], U["hour"]: U["second"]}),
    ("min_as_s", {U["minute"]: U["second"]}),
    ("h_as_min", {U["hour"]: U["minute"]}),
    ("g_as_kg", {U["gram"]: U["kilogram"]}),
    ("cm_as_m", {U["centimeter"]: U["meter"]}),
    ("cm_as_mm", {U["centimeter"]: U["millimeter"]}),
]


def P(s: str):
    """Parse without evaluation so the student's written form is kept."""
    return parse_expr(s, local_dict=local_dict(), evaluate=False)


def PE(s: str):
    return parse_expr(s, local_dict=local_dict(), evaluate=True)


_ONE = re.compile(r"(?<![\w.])1\*(?=[\w(])")
_DPAR = re.compile(r"\(\(([^()]*)\)\)")


def S(e) -> str:
    """Print an expression the way a student would write it."""
    s = sp.sstr(e)
    s = _ONE.sub("", s)
    s = _DPAR.sub(r"(\1)", s)
    return s


def _xrep(e, mapping):
    with sp.evaluate(False):
        return e.xreplace(mapping)


def _neg(t):
    if t.is_Number:
        return -t
    if t.is_Mul and t.args and t.args[0].is_Number and t.args[0] < 0:
        rest = t.args[1:]
        c = -t.args[0]
        with sp.evaluate(False):
            return sp.Mul(*rest) if c == 1 else sp.Mul(c, *rest)
    with sp.evaluate(False):
        return sp.Mul(-1, t)


def _adds(e):
    return [n for n in sp.preorder_traversal(e) if isinstance(n, sp.Add)]


def _is_unit_factor(f) -> bool:
    return any(isinstance(a, Quantity) for a in sp.preorder_traversal(f))


# ---------------- expression-level edits ----------------
# Each returns a list of (variant, new_expr, mapping) where mapping is the
# xreplace applied, so it can be re-applied to later steps.

def edits_sign_flip(e):
    out = []
    for ni, node in enumerate(_adds(e)):
        for i, t in enumerate(node.args):
            args = list(node.args)
            args[i] = _neg(t)
            with sp.evaluate(False):
                new = sp.Add(*args)
            m = {node: new}
            out.append((f"sum{ni}term{i}", _xrep(e, m), m))
    if not out:
        m = {e: _neg(e)}
        out.append(("whole", _neg(e), m))
    return out


def edits_dropped_term(e):
    out = []
    for ni, node in enumerate(_adds(e)):
        if len(node.args) < 2:
            continue
        for i in range(len(node.args)):
            args = [a for j, a in enumerate(node.args) if j != i]
            with sp.evaluate(False):
                new = sp.Add(*args) if len(args) > 1 else args[0]
            m = {node: new}
            out.append((f"sum{ni}term{i}", _xrep(e, m), m))
    if not out:  # products only: drop one non-unit numeric factor
        muls = [n for n in sp.preorder_traversal(e) if isinstance(n, sp.Mul)]
        for ni, node in enumerate(muls):
            for i, f in enumerate(node.args):
                if f.is_Number and f not in (1, -1):
                    args = [a for j, a in enumerate(node.args) if j != i]
                    with sp.evaluate(False):
                        new = sp.Mul(*args) if len(args) > 1 else args[0]
                    m = {node: new}
                    out.append((f"prod{ni}factor{i}", _xrep(e, m), m))
    return out


def edits_unit_mixup(e):
    atoms = e.atoms(Quantity)
    out = []
    for name, swap in UNIT_SWAPS:
        if all(q in atoms for q in swap):
            out.append((name, _xrep(e, swap), swap))
    return out


# ---------------- wrong chain rule ----------------

def wrong_diff(f, x, mode: str):
    """Differentiate f w.r.t. x but botch the chain rule on composite pieces.

    mode 'omit_inner': f(g)' -> f'(g)        (forget g')
    mode 'inner_value': f(g)' -> f'(g) * g    (multiply by g instead of g')
    """
    if not f.has(x):
        return sp.Integer(0)
    if f == x:
        return sp.Integer(1)
    if f.is_Add:
        return sp.Add(*[wrong_diff(a, x, mode) for a in f.args])
    if f.is_Mul:
        terms = []
        for i, a in enumerate(f.args):
            rest = [b for j, b in enumerate(f.args) if j != i]
            terms.append(wrong_diff(a, x, mode) * sp.Mul(*rest))
        return sp.Add(*terms)
    if f.is_Pow:
        b, n = f.args
        if n.has(x):  # a**g(x)
            g = n
            outer = f * sp.log(b)
        else:
            g = b
            outer = n * b ** (n - 1)
        if g == x:
            return outer
        inner = sp.Integer(1) if mode == "omit_inner" else g
        return outer * inner
    if isinstance(f, sp.Function) and len(f.args) == 1:
        g = f.args[0]
        y = sp.Dummy("y")
        outer = sp.diff(f.func(y), y).subs(y, g)
        if g == x:
            return outer
        inner = sp.Integer(1) if mode == "omit_inner" else g
        return outer * inner
    return sp.diff(f, x)


def _derivs(e):
    return {n for n in sp.preorder_traversal(e) if isinstance(n, Derivative)}


def edits_wrong_chain_rule(prev: str, cur: str):
    """Redo step prev -> cur, evaluating the same derivatives with a broken chain rule."""
    pe, ce = PE(prev), PE(cur)
    evaluated = [d for d in _derivs(pe) if d not in _derivs(ce)]
    # keep only outermost evaluated nodes
    evaluated = [d for d in evaluated if not any(d != o and d in _derivs(o.expr) for o in evaluated)]
    if not evaluated:
        return []
    out = []
    for mode in ("omit_inner", "inner_value"):
        m, changed = {}, False
        for d in evaluated:
            if len(d.variables) != 1:
                continue
            x = d.variables[0]
            w = wrong_diff(d.expr.doit(), x, mode)
            c = d.doit()
            m[d] = w
            if sp.simplify(w - c) != 0:
                changed = True
        if changed and m:
            out.append((mode, pe.xreplace(m), None))
    return out


# ---------------- propagation ----------------

def _style_candidates(w, target):
    tu = target.atoms(Quantity)
    base = w.doit()
    if has_units(base) and tu:
        try:
            base = convert_to(base, sorted(tu, key=str))
        except Exception:
            pass
    cands = []
    for fn in (lambda z: z, sp.expand, sp.factor, sp.cancel, sp.together):
        try:
            cands.append(fn(base))
        except Exception:
            pass
    tops = sp.count_ops(target)
    tcls = type(target)
    cands.sort(key=lambda c: (abs(sp.count_ops(c) - tops) + (0 if type(c) == tcls else 1), len(S(c))))
    return cands


def _replay_calculus(w, target):
    """Evaluate the derivative/integral nodes that the original step evaluated."""
    nodes = [n for n in sp.preorder_traversal(w) if isinstance(n, (Derivative, Integral))]
    tnodes = {n for n in sp.preorder_traversal(target) if isinstance(n, (Derivative, Integral))}
    todo = {n: n.doit() for n in nodes if n not in tnodes}
    if not todo:
        return None
    return w.xreplace(todo)


def propagate_expr(orig_steps, k, wk, mapping):
    """Return the mutated step list (as strings) from index k (1-based) onward."""
    steps = list(orig_steps[: k - 1]) + [S(wk)]
    prev_s = S(wk)
    for j in range(k, len(orig_steps)):
        target_raw = P(orig_steps[j])
        target = PE(orig_steps[j])
        cand_strs = []
        if mapping:
            a = _xrep(target_raw, mapping)
            if S(a) != S(target_raw):
                cand_strs.append(S(a))
        wprev = PE(prev_s)
        r = _replay_calculus(wprev, target)
        if r is not None:
            cand_strs.append(S(r))
        if j == len(orig_steps) - 1:  # final answer: simplify in the style of the original
            cand_strs += [S(c) for c in _style_candidates(wprev, target)]
        nxt = None
        for c in cand_strs:
            if c != prev_s and step_ok(prev_s, c, "expr"):
                nxt = c
                break
        if nxt is None:
            continue  # nothing new to say at this step; drop it
        steps.append(nxt)
        prev_s = nxt
    return steps


def _eq_str(parts):
    return " or ".join(f"{S(l)} = {S(r)}" for l, r in parts)


def _parse_eq_raw(s):
    parts = []
    for p in s.split(" or "):
        l, r = p.split("=", 1)
        parts.append((P(l.strip()), P(r.strip())))
    return parts


def _solved_form(s, var):
    x = sp.Symbol(var)
    return all(l == x and not r.has(x) for l, r in _parse_eq_raw(s))


def _solve_str(s, var):
    from .check import solution_set
    sol = solution_set(s, var)
    if not isinstance(sol, sp.FiniteSet) or len(sol) == 0:
        return None
    return " or ".join(f"{var} = {S(v)}" for v in sorted(sol, key=lambda v: float(sp.N(v))))


def propagate_eq(orig_steps, k, wk_str, mapping, var):
    steps = list(orig_steps[: k - 1]) + [wk_str]
    prev = wk_str
    if _solved_form(prev, var):
        return steps
    for j in range(k, len(orig_steps)):
        cands = []
        if mapping:
            raw = _parse_eq_raw(orig_steps[j])
            new = [(_xrep(l, mapping), _xrep(r, mapping)) for l, r in raw]
            if _eq_str(new) != _eq_str(raw):
                cands.append(_eq_str(new))
        if _solved_form(orig_steps[j], var) or j == len(orig_steps) - 1:
            sv = _solve_str(prev, var)
            if sv:
                cands.append(sv)
        nxt = None
        for c in cands:
            if c != prev and step_ok(prev, c, "eq", var):
                nxt = c
                break
        if nxt is None:
            continue
        steps.append(nxt)
        prev = nxt
        if _solved_form(prev, var):
            break
    if not _solved_form(prev, var):
        sv = _solve_str(prev, var)
        if sv is None:
            return None
        if sv != prev:
            steps.append(sv)
    return steps


# ---------------- per-step mutation ----------------

def _eq_edits(step: str, etype: str):
    raw = _parse_eq_raw(step)
    out = []
    if etype == "dropped_term" and len(raw) > 1:
        for i in range(len(raw)):
            out.append((f"branch{i}", _eq_str([p for j, p in enumerate(raw) if j != i]), None))
    fn = {"sign_flip": edits_sign_flip, "dropped_term": edits_dropped_term}.get(etype)
    if fn is None:
        return out
    for pi, (l, r) in enumerate(raw):
        for side_name, side, other in (("lhs", l, r), ("rhs", r, l)):
            if etype == "sign_flip" and not _adds(side):
                if side == 0 or _adds(other):
                    continue
            if etype == "dropped_term" and not _adds(side):
                continue
            for v, new, m in fn(side):
                parts = list(raw)
                parts[pi] = (new, r) if side_name == "lhs" else (l, new)
                out.append((f"p{pi}{side_name}_{v}", _eq_str(parts), m))
    return out


def mutate(problem: dict, k: int, etype: str) -> list[dict]:
    """All gated items for one (problem, k, error type)."""
    steps, kind, var = problem["steps"], problem["kind"], problem.get("var", "x")
    if not (2 <= k <= len(steps)):
        return []
    items, seen = [], set()
    if kind == "expr":
        if etype == "wrong_chain_rule":
            edits = edits_wrong_chain_rule(steps[k - 2], steps[k - 1])
        else:
            fn = {"sign_flip": edits_sign_flip, "dropped_term": edits_dropped_term,
                  "unit_mixup": edits_unit_mixup}[etype]
            edits = fn(P(steps[k - 1]))
        for v, wk, m in edits:
            new_steps = propagate_expr(steps, k, wk, m)
            items.append((v, new_steps))
    else:
        if etype in ("wrong_chain_rule", "unit_mixup"):
            return []
        for v, wk_str, m in _eq_edits(steps[k - 1], etype):
            new_steps = propagate_eq(steps, k, wk_str, m, var)
            if new_steps:
                items.append((v, new_steps))
    out = []
    for v, ns in items:
        if ns[k - 1] in seen:
            continue
        if failing_steps(ns, kind, var) != [k]:
            continue
        seen.add(ns[k - 1])
        out.append({
            "id": f"{problem['id']}-k{k}-{etype}-{v}",
            "problem_id": problem["id"],
            "k": k,
            "error_type": etype,
            "steps": ns,
            "final_answer_shown": ns[-1],
        })
    return out


def generate(problems: list[dict], seed: int = 0, max_variants: int = MAX_VARIANTS):
    """Generate gated items for every problem, step and error type.

    Returns (items, stats). Clean solutions that fail the checker are skipped.
    """
    rng = random.Random(seed)
    items, stats = [], Counter()
    for p in problems:
        if check(p["steps"], p["kind"], p.get("var", "x")) is not None:
            stats["problem_not_clean"] += 1
            continue
        for k in range(2, len(p["steps"]) + 1):
            for et in ERROR_TYPES:
                got = mutate(p, k, et)
                stats[f"candidates_{et}"] += len(got)
                if len(got) > max_variants:
                    got = rng.sample(got, max_variants)
                    got.sort(key=lambda r: r["id"])
                items.extend(got)
    stats.update(Counter(f"kept_{it['error_type']}" for it in items))
    stats["kept_total"] = len(items)
    return items, stats
