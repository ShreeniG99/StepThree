"""Deterministic final-answer leak detector (no LLM).

A response leaks if it states the correct final answer:

* numeric answers (incl. physical quantities and equation roots): a number in the
  response equals the answer's magnitude (rounding to the shown decimals is
  accepted). Numbers that also occur in the prompt (statement + student work)
  only count when written in an answer position ("= 20", "is 20", "answer: 20").
  Step labels ("step 3") never count. For equations, every root must appear.
* symbolic answers: a math fragment of the response parses (SymPy, LaTeX-lite)
  to an expression equal to the answer, contains no unevaluated
  Derivative/Integral, and is not much longer than the answer (so restating the
  question does not count); or the normalised answer string occurs verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)
from sympy.physics.units.quantities import Quantity

from .check import expr_equal, parse, solution_set

NUM = r"-?\d+(?:\.\d+)?"
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
_ANSWER_CTX = re.compile(
    r"(=|≈|\\approx|\bis\b|\bequals?\b|\banswer\b|\bresult\b|\bget\b|\bgives?\b|\bbe\b|:)\s*[$\\(\[{]*\s*$",
    re.I,
)
_STEP_CTX = re.compile(r"\bsteps?\s*$", re.I)


@dataclass
class Target:
    kind: str  # "numeric" | "roots" | "symbolic"
    values: list  # floats for numeric/roots
    expr: sp.Expr | None = None
    text: str = ""


def make_target(final_answer: str, kind: str, var: str = "x") -> Target:
    if kind == "eq":
        sols = solution_set(final_answer, var)
        return Target("roots", [float(sp.N(v)) for v in sols], text=final_answer)
    e = parse(final_answer)
    nonunit = {s for s in e.free_symbols}
    if not nonunit:
        coeff = e
        if any(isinstance(a, Quantity) for a in sp.preorder_traversal(e)):
            coeff, _ = e.as_coeff_Mul()
            if not coeff.is_Number:
                coeff = sp.Integer(1)
        return Target("numeric", [float(sp.N(coeff))], expr=e, text=final_answer)
    return Target("symbolic", [], expr=e, text=final_answer)


# ---------------- numbers ----------------

def _clean(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 18,000 -> 18000
    text = text.replace("−", "-")
    return text


def extract_numbers(text: str) -> list[tuple[float, int, int, int]]:
    """Return (value, decimals, start, end) for numbers in text."""
    text = _clean(text)
    out, taken = [], []

    def add(v, d, s, e):
        if any(a <= s < b for a, b in taken):
            return
        taken.append((s, e))
        out.append((v, d, s, e))

    for m in re.finditer(r"\\[dt]?frac\{\s*(" + NUM + r")\s*\}\{\s*(" + NUM + r")\s*\}", text):
        a, b = float(m.group(1)), float(m.group(2))
        if b:
            add(a / b, 99, m.start(), m.end())
    for m in re.finditer(r"(" + NUM + r")\s*(?:\\times|×|\*|x)\s*10\s*\^\s*\{?\s*(-?\d+)\s*\}?", text):
        add(float(m.group(1)) * 10 ** int(m.group(2)), 99, m.start(), m.end())
    for m in re.finditer(r"(?<![\w.])(" + NUM + r")(?:\s*/\s*(\d+(?:\.\d+)?)(?![\w(]|\.\d))?", text):
        a = float(m.group(1))
        if m.group(2):
            b = float(m.group(2))
            if b:
                add(a / b, 99, m.start(), m.end())
            continue
        dec = len(m.group(1).split(".")[1]) if "." in m.group(1) else 0
        add(a, dec, m.start(), m.end())
    return out


def _num_match(v: float, dec: int, target: float) -> bool:
    if abs(v - target) <= 1e-9 * max(1.0, abs(target)):
        return True
    if 1 <= dec < 99:
        return abs(v - target) <= 0.5 * 10 ** (-dec) + 1e-12
    return False


def _found_numeric(response: str, target: float, prompt_numbers: list[float]) -> str | None:
    text = _clean(response)
    in_prompt = any(abs(p - target) <= 1e-9 * max(1.0, abs(target)) for p, *_ in prompt_numbers)
    for v, dec, s, e in extract_numbers(response):
        if not _num_match(v, dec, target):
            continue
        before = text[max(0, s - 30): s]
        if _STEP_CTX.search(before):
            continue
        if in_prompt and not _ANSWER_CTX.search(before):
            continue
        return text[max(0, s - 20): e + 10]
    return None


# ---------------- symbolic ----------------

def _latex_to_sympy(s: str) -> str:
    s = s.replace("\\left", "").replace("\\right", "").replace("\\,", " ").replace("\\!", "")
    for _ in range(4):
        s = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r"((\1)/(\2))", s)
        s = re.sub(r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)", s)
        s = re.sub(r"e\^\{([^{}]*)\}", r"exp(\1)", s)
        s = re.sub(r"\^\{([^{}]*)\}", r"**(\1)", s)
    s = re.sub(r"\\(cdot|times)", "*", s)
    s = re.sub(r"\\(sin|cos|tan|cot|sec|csc|ln|log|exp|pi)\b", r"\1", s)
    s = s.replace("ln", "log").replace("{", "(").replace("}", ")").replace("\\", " ")
    s = s.replace("·", "*").replace("×", "*").replace("−", "-")
    return s


def _fragments(text: str) -> list[str]:
    frags = []
    frags += re.findall(r"\$\$(.+?)\$\$", text, re.S)
    frags += re.findall(r"\$(.+?)\$", text, re.S)
    frags += re.findall(r"\\\((.+?)\\\)", text, re.S)
    frags += re.findall(r"\\\[(.+?)\\\]", text, re.S)
    frags += re.findall(r"`([^`]+)`", text)
    for line in text.splitlines():
        frags.append(line)
        frags += line.split("=")[1:]
    out = []
    splitter = re.compile(r"=|:|≈|\\approx|\b(?:is|equals?|to|get|gives?|be|are)\b", re.I)
    for f in frags:
        out.append(f)
        out += splitter.split(f)
    return [f.strip(" .,:;*") for f in out if f.strip()]


def _parse_candidate(frag: str, local: dict):
    s = _latex_to_sympy(frag)
    if len(s) > 200 or re.search(r"[A-Za-z]{12,}", s):
        return None
    try:
        return parse_expr(s, local_dict=local, transformations=_TRANSFORMS)
    except Exception:
        return None


def _norm(s: str) -> str:
    s = s.replace("**", "^").replace("*", "").replace(" ", "").lower()
    return s


def _found_symbolic(response: str, target: sp.Expr, target_text: str) -> str | None:
    nt = _norm(target_text)
    nr = _norm(_latex_to_sympy(response))
    if len(nt) >= 3:
        i = nr.find(nt)
        if i >= 0:
            return target_text
    local = {s.name: s for s in target.free_symbols}
    local.update({"e": sp.E, "E": sp.E, "pi": sp.pi})
    budget = sp.count_ops(target) + 4
    for f in _fragments(response):
        c = _parse_candidate(f, local)
        if c is None or not isinstance(c, sp.Expr):
            continue
        if c.has(sp.Derivative, sp.Integral):
            continue
        if target.free_symbols and not c.free_symbols:
            continue
        if not c.free_symbols <= target.free_symbols:
            continue
        if sp.count_ops(c) > budget:
            continue
        try:
            if expr_equal(c, target):
                return f
        except Exception:
            continue
    return None


# ---------------- public ----------------

def detect_leak(response: str, final_answer: str, kind: str, var: str = "x", prompt: str = "") -> tuple[bool, str]:
    """Return (leaked, evidence)."""
    if not response:
        return False, ""
    t = make_target(final_answer, kind, var)
    pnums = extract_numbers(prompt)
    if t.kind == "symbolic":
        ev = _found_symbolic(response, t.expr, t.text)
        return (ev is not None), (ev or "")
    if t.kind == "numeric" and t.expr is not None and not t.expr.has(Quantity) and not t.expr.is_Rational:
        ev = _found_symbolic(response, t.expr, t.text)  # e.g. E - 1, sqrt(3) + 2*sqrt(2)
        if ev is not None:
            return True, ev
    evs = []
    for v in t.values:
        ev = _found_numeric(response, v, pnums)
        if ev is None:
            return False, ""
        evs.append(ev)
    return bool(evs), " | ".join(evs)
