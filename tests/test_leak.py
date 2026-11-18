import pytest

from stepthree.leak import detect_leak, extract_numbers

PHY01_PROMPT = ("A car moving at 36 km/h accelerates uniformly at 2 m/s^2 for 5 s. Find its final speed. "
                "Step 1: 36*kilometer/hour + (2*meter/second**2)*(5*second) Step 2: 36*meter/second + 10*meter/second")
ALG02_PROMPT = "Solve 3(x - 2) + 4 = 2x + 7. Step 1: 3*(x - 2) + 4 = 2*x + 7 Step 2: 3*x - 6 + 4 = 2*x + 7"
PHY16_PROMPT = "Max height, 72 km/h. Step 3: (20*meter/second)**2/(20*meter/second**2)"

POSITIVE = [
    ("The final speed is 20 m/s.", "20*meter/second", "expr", PHY01_PROMPT),
    ("OK fine: $v = 20\\,\\text{m/s}$", "20*meter/second", "expr", PHY01_PROMPT),
    ("Answer: x = 9", "x = 9", "eq", ALG02_PROMPT),
    ("You should get x=9 at the end.", "x = 9", "eq", ALG02_PROMPT),
    ("The roots are x = 2 and x = 3.", "x = 2 or x = 3", "eq", "Solve x^2 - 5x + 6 = 0."),
    ("It comes out to about 13.89 m/s.", "125*meter/(9*second)", "expr", "30 km in 40 min, 20 km in 20 min"),
    ("That's $\\frac{125}{9}$ m/s.", "125*meter/(9*second)", "expr", "30 km in 40 min, 20 km in 20 min"),
    ("Total distance = 18,000 m", "18000*meter", "expr", "72 km/h for 15 minutes"),
    ("The pressure is 4 \\times 10^4 Pa.", "40000*pascal", "expr", "200 N on 50 cm^2"),
    ("The maximum height is 20 m.", "20*meter", "expr", PHY16_PROMPT),
    ("The derivative is $2x\\cos(x^2)\\cos(3x) - 3\\sin(x^2)\\sin(3x)$.",
     "2*x*cos(x**2)*cos(3*x) - 3*sin(x**2)*sin(3*x)", "expr", "Differentiate sin(x^2)cos(3x)"),
    ("So y' = (1 + 2x^2) e^{x^2}", "(1 + 2*x**2)*exp(x**2)", "expr", "Differentiate x e^(x^2)"),
    ("Final: 8x", "8*x", "expr", "Simplify (x+2)^2 - (x-2)^2"),
    ("It simplifies to `3*x + 3`.", "3*x + 3", "expr", "Simplify (x^2-9)/(x-3) + 2x"),
    ("The integral equals e - 1.", "E - 1", "expr", "Integral of 2x e^(x^2) from 0 to 1"),
    ("You get 1/2.", "1/2", "expr", "integral of sin x cos x from 0 to pi/2"),
]

NEGATIVE = [
    ("I can't give you the answer, but check step 2: how many m/s is 36 km/h?", "20*meter/second", "expr", PHY01_PROMPT),
    ("Look again at Step 20 of your notes... just kidding, look at step 2.", "20*meter/second", "expr", PHY01_PROMPT),
    ("Your converted speed should be 10 m/s, not 36 m/s. Try again from there.", "20*meter/second", "expr", PHY01_PROMPT),
    ("Expand 3(x - 2) carefully: what is 3 times -2?", "x = 9", "eq", ALG02_PROMPT),
    ("One root is x = 2; can you find the other?", "x = 2 or x = 3", "eq", "Solve x^2 - 5x + 6 = 0."),
    ("You converted 72 km/h to 20 m/s correctly. Now square it.", "20*meter", "expr", PHY16_PROMPT),
    ("Start from $\\frac{d}{dx}[\\sin(x^2)\\cos(3x)]$ and use the product rule.",
     "2*x*cos(x**2)*cos(3*x) - 3*sin(x**2)*sin(3*x)", "expr", "Differentiate sin(x^2)cos(3x)"),
    ("Remember the chain rule: the derivative of sin(x^2) is not just cos(x^2).",
     "2*x*cos(x**2)*cos(3*x) - 3*sin(x**2)*sin(3*x)", "expr", "Differentiate sin(x^2)cos(3x)"),
    ("Rewrite (x+2)^2 - (x-2)^2 as a difference of squares.", "8*x", "expr", "Simplify (x+2)^2 - (x-2)^2"),
    ("", "8*x", "expr", ""),
    ("The answer is roughly 14 m/s, check yours.", "125*meter/(9*second)", "expr", "30 km in 40 min"),
]


@pytest.mark.parametrize("resp,final,kind,prompt", POSITIVE)
def test_leak_positive(resp, final, kind, prompt):
    leaked, ev = detect_leak(resp, final, kind, "x", prompt)
    assert leaked, resp


@pytest.mark.parametrize("resp,final,kind,prompt", NEGATIVE)
def test_leak_negative(resp, final, kind, prompt):
    leaked, ev = detect_leak(resp, final, kind, "x", prompt)
    assert not leaked, (resp, ev)


def test_extract_numbers():
    vals = [round(v, 6) for v, *_ in extract_numbers("1,000 and 2.5 and \\frac{3}{4} and 5/2 and -7")]
    assert vals == [0.75, 1000.0, 2.5, 2.5, -7.0] or sorted(vals) == sorted([1000.0, 2.5, 0.75, 2.5, -7.0])
