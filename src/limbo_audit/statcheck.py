"""Engine 5A — Statistical & Arithmetic Integrity Gate.

Deterministic, zero-heavy-dependency statistical consistency checks on ``.tex`` and
``.md`` manuscripts:
1. GRIM (Granularity-Related Inconsistency of Means) & integer-fraction gate for
   sample sizes (``N = ...``, ``n = ...``) paired with percentages or means.
2. Test-statistic vs. p-value recalculation gate (``t``, ``r``, ``z``, ``F``, ``chi2``)
   using pure-Python/stdlib special functions (``math.erfc``, ``math.lgamma``,
   continued-fraction incomplete beta & incomplete gamma).
3. Confidence interval & plus-minus geometry gate (inverted bounds, estimate
   outside ``[L, U]``, negative spread, and asymmetric normal intervals).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

# ---------------- Pure-Python Exact Distribution CDF / P-Value Kernels ----------------

_TINY = 1e-30
_EPS = 1e-14
_MAX_ITER = 300


def _betacf(a: float, b: float, x: float) -> float:
    """Evaluate continued fraction for incomplete beta function I_x(a, b)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _TINY:
        d = _TINY
    d = 1.0 / d
    h = d
    for m in range(1, _MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + aa / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + aa / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """Compute regularized incomplete beta function I_x(a, b) for 0 <= x <= 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    bt = math.exp(a * math.log(x) + b * math.log(1.0 - x) - ln_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def regularized_upper_gamma(a: float, x: float) -> float:
    """Compute regularized upper incomplete gamma Q(a, x) = 1 - P(a, x)."""
    if x <= 0.0:
        return 1.0
    if x < a + 1.0:
        # Series representation for P(a, x)
        ap = a
        term = 1.0 / a
        total = term
        for _ in range(1, _MAX_ITER + 1):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * _EPS:
                break
        p_val = total * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return max(0.0, min(1.0, 1.0 - p_val))
    # Lentz's continued fraction for Q(a, x)
    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b if abs(b) >= _TINY else 1.0 / _TINY
    h = d
    for i in range(1, _MAX_ITER + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _TINY:
            d = _TINY
        c = b + an / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    q_val = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return max(0.0, min(1.0, q_val))


def pvalue_from_z(z: float, *, two_tailed: bool = True) -> float:
    """Compute p-value from standard normal Z-statistic."""
    p_two = math.erfc(abs(z) / math.sqrt(2.0))
    return p_two if two_tailed else 0.5 * p_two


def pvalue_from_t(t_val: float, df: float, *, two_tailed: bool = True) -> float:
    """Compute p-value from Student's t-statistic with ``df`` degrees of freedom."""
    if df <= 0.0:
        raise ValueError(f"Degrees of freedom must be positive, got {df}")
    x = df / (df + t_val * t_val)
    p_two = regularized_incomplete_beta(0.5 * df, 0.5, x)
    p_two = max(0.0, min(1.0, p_two))
    return p_two if two_tailed else 0.5 * p_two


def pvalue_from_f(f_val: float, df1: float, df2: float) -> float:
    """Compute upper-tail p-value from F(df1, df2) statistic."""
    if df1 <= 0.0 or df2 <= 0.0:
        raise ValueError(f"F degrees of freedom must be positive, got ({df1}, {df2})")
    if f_val <= 0.0:
        return 1.0
    x = df2 / (df2 + df1 * f_val)
    return max(0.0, min(1.0, regularized_incomplete_beta(0.5 * df2, 0.5 * df1, x)))


def pvalue_from_chi2(chi2_val: float, df: float) -> float:
    """Compute upper-tail p-value from chi-square(df) statistic."""
    if df <= 0.0:
        raise ValueError(f"Chi-square degrees of freedom must be positive, got {df}")
    if chi2_val <= 0.0:
        return 1.0
    return regularized_upper_gamma(0.5 * df, 0.5 * chi2_val)


def pvalue_from_r(r_val: float, n: int, *, two_tailed: bool = True) -> float:
    """Compute p-value from Pearson correlation r and sample size n."""
    if n < 3:
        raise ValueError(f"Sample size n must be >= 3 for Pearson r, got {n}")
    if abs(r_val) >= 1.0:
        return 0.0
    df = float(n - 2)
    t_val = r_val * math.sqrt(df / (1.0 - r_val * r_val))
    return pvalue_from_t(t_val, df, two_tailed=two_tailed)


# ---------------- Findings & Result Dataclasses ----------------


@dataclass(frozen=True)
class StatCheckFinding:
    """Single statistical, GRIM, or confidence-interval integrity finding."""

    code: str
    severity: str
    line_number: int
    expression: str
    detail: str
    expected: str = ""
    reported: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "line_number": self.line_number,
            "expression": self.expression,
            "detail": self.detail,
            "expected": self.expected,
            "reported": self.reported,
        }


@dataclass(frozen=True)
class StatCheckResult:
    """Structured output from Engine 5A statistical & arithmetic integrity gate."""

    passed: bool
    grim_checks: int
    stat_tests_checked: int
    ci_checks: int
    findings: tuple[StatCheckFinding, ...]
    failures: tuple[str, ...]

    @property
    def p_value_inconsistencies(self) -> tuple[StatCheckFinding, ...]:
        return tuple(f for f in self.findings if f.code == "P_VALUE_INCONSISTENCY")

    @property
    def decision_boundary_flips(self) -> tuple[StatCheckFinding, ...]:
        return tuple(f for f in self.findings if f.code == "DECISION_BOUNDARY_FLIP")

    @property
    def grim_failures(self) -> tuple[StatCheckFinding, ...]:
        return tuple(f for f in self.findings if f.code == "GRIM_INCONSISTENCY")

    @property
    def ci_failures(self) -> tuple[StatCheckFinding, ...]:
        return tuple(
            f
            for f in self.findings
            if f.code in {
                "INVERTED_CI_BOUNDS",
                "ESTIMATE_OUTSIDE_CI",
                "ASYMMETRIC_NORMAL_CI",
                "NEGATIVE_SPREAD",
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "grim_checks": self.grim_checks,
            "stat_tests_checked": self.stat_tests_checked,
            "ci_checks": self.ci_checks,
            "findings": [f.to_dict() for f in self.findings],
            "failures": list(self.failures),
        }


# ---------------- Regex Patterns ----------------

_SAMPLE_SIZE_RE = re.compile(r"(?<![A-Za-z0-9_\\])([Nn])\s*=\s*(\d+)\b")
_PCT_RE = re.compile(r"(?<![A-Za-z0-9_.\\])(\d+(?:\.\d+)?)\s*(?:\\%|%)")
_MEAN_RE = re.compile(r"(?<![A-Za-z0-9_\\])(?:M|mean)\s*=\s*(-?\d+\.\d+)", re.IGNORECASE)

_P_CLAUSE = r"p\s*(<=|>=|\\le|\\ge|<|>|=)\s*(0?\.\d+(?:[eE][+-]?\d+)?|1\.0+|\d+(?:\.\d+)?[eE][+-]?\d+)"

_T_TEST_RE = re.compile(
    r"(?<![A-Za-z0-9_])t\s*\(\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*([+-]?\d+(?:\.\d+)?)\s*[,;]\s*"
    + _P_CLAUSE,
    re.IGNORECASE,
)
_F_TEST_RE = re.compile(
    r"(?<![A-Za-z0-9_])F\s*\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*([+-]?\d+(?:\.\d+)?)\s*[,;]\s*"
    + _P_CLAUSE,
)
_Z_TEST_RE = re.compile(
    r"(?<![A-Za-z0-9_])z\s*=\s*([+-]?\d+(?:\.\d+)?)\s*[,;]\s*" + _P_CLAUSE,
    re.IGNORECASE,
)
_CHI2_TEST_RE = re.compile(
    r"(?:\\chi\s*\^\s*2|chi2|chi\^2|χ²)\s*\(\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*([+-]?\d+(?:\.\d+)?)\s*[,;]\s*"
    + _P_CLAUSE,
    re.IGNORECASE,
)
_R_TEST_RE = re.compile(
    r"(?<![A-Za-z0-9_])r\s*=\s*([+-]?\d+(?:\.\d+)?)\s*[,;]\s*n\s*=\s*(\d+)\s*[,;]\s*"
    + _P_CLAUSE,
    re.IGNORECASE,
)

# Estimate + CI bracket: e.g. "0.45 [0.38, 0.52]" or "0.45 (95% CI [0.38, 0.52])" or "0.45 (95% CI: [0.38, 0.52])"
_CI_WITH_EST_RE = re.compile(
    r"([+-]?\d+\.\d+)\s*(?:\(\s*(?:[^()\[\]]{0,40}?\bCI\b[^()\[\]]{0,10})?)?"
    r"\[\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\]"
)
# Standalone CI bracket without preceding estimate
_CI_STANDALONE_RE = re.compile(
    r"(?:CI|interval)\s*[:=]?\s*\[\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\]",
    re.IGNORECASE,
)
_PM_RE = re.compile(
    r"([+-]?\d+(?:\.\d+)?)\s*(?:\\pm|±)\s*([+-]?\d+(?:\.\d+)?)"
)


def _strip_latex_comments(line: str) -> str:
    """Strip unescaped LaTeX % comments while preserving \\%."""
    i = 0
    while i < len(line):
        if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
            return line[:i]
        i += 1
    return line


def _decimal_places(num_str: str) -> int:
    s = num_str.strip()
    if "e" in s.lower():
        return 6
    if "." not in s:
        return 0
    return len(s.split(".", 1)[1])


def _can_express_percentage(pct: float, decimals: int, n: int) -> bool:
    """Return True iff some integer k in [0, n] rounds to ``pct`` at ``decimals`` places."""
    if n <= 0:
        return False
    if n >= 10 ** (decimals + 2):
        return True
    target = round(pct, decimals)
    tol = 0.5 * (10 ** (-decimals)) + 1e-9
    for k in range(0, n + 1):
        raw = 100.0 * k / n
        if abs(raw - target) <= tol:
            return True
    return False


def _can_express_mean(mean_val: float, decimals: int, n: int) -> bool:
    """GRIM test: return True iff some integer sum k yields ``mean_val`` at ``decimals``."""
    if n <= 0:
        return False
    if n >= 10**decimals:
        return True
    # Only test non-negative or signed integer sums near n * mean_val
    center = round(mean_val * n)
    tol = 0.5 * (10 ** (-decimals)) + 1e-9
    for k in range(center - 2, center + 3):
        if abs((k / n) - mean_val) <= tol:
            return True
    return False


def _split_segments_with_lines(text: str) -> list[tuple[int, str]]:
    """Split text into sentence/table-row segments paired with 1-indexed line numbers."""
    segments: list[tuple[int, str]] = []
    for line_idx, raw_line in enumerate(text.splitlines(), start=1):
        clean = _strip_latex_comments(raw_line).strip()
        if not clean:
            continue
        # Split long lines on sentence boundaries while keeping table rows intact
        if "\\\\" in clean or "|" in clean:
            segments.append((line_idx, clean))
        else:
            parts = re.split(r"(?<=[.;])\s+", clean)
            for part in parts:
                if part.strip():
                    segments.append((line_idx, part.strip()))
    return segments


def _evaluate_p_report(
    *,
    line_num: int,
    expr: str,
    op: str,
    p_str: str,
    p_two: float,
    p_one: float | None = None,
    alpha: float = 0.05,
    one_tailed: bool = False,
) -> list[StatCheckFinding]:
    """Compare reported p-value clause against recomputed p-value."""
    findings: list[StatCheckFinding] = []
    p_rep = float(p_str)
    norm_op = op.replace("\\le", "<=").replace("\\ge", ">=")
    p_calc = p_one if (one_tailed and p_one is not None) else p_two

    if norm_op in {"<", "<="}:
        # e.g. p < 0.05 or p < 0.001
        if p_calc >= p_rep + 1e-9:
            if p_rep <= alpha < p_calc:
                findings.append(
                    StatCheckFinding(
                        code="DECISION_BOUNDARY_FLIP",
                        severity="ERROR",
                        line_number=line_num,
                        expression=expr,
                        detail=f"Reported {expr}, but recomputed p = {p_calc:.6g} >= {p_rep}",
                        expected=f"p = {p_calc:.6g}",
                        reported=f"p {norm_op} {p_str}",
                    )
                )
            else:
                findings.append(
                    StatCheckFinding(
                        code="P_VALUE_INCONSISTENCY",
                        severity="ERROR",
                        line_number=line_num,
                        expression=expr,
                        detail=f"Reported p {norm_op} {p_str}, but recomputed p = {p_calc:.6g}",
                        expected=f"p = {p_calc:.6g}",
                        reported=f"p {norm_op} {p_str}",
                    )
                )
        return findings

    if norm_op in {">", ">="}:
        if p_calc <= p_rep - 1e-9:
            if p_calc < alpha <= p_rep:
                findings.append(
                    StatCheckFinding(
                        code="DECISION_BOUNDARY_FLIP",
                        severity="ERROR",
                        line_number=line_num,
                        expression=expr,
                        detail=f"Reported {expr}, but recomputed p = {p_calc:.6g} < {p_rep}",
                        expected=f"p = {p_calc:.6g}",
                        reported=f"p {norm_op} {p_str}",
                    )
                )
            else:
                findings.append(
                    StatCheckFinding(
                        code="P_VALUE_INCONSISTENCY",
                        severity="ERROR",
                        line_number=line_num,
                        expression=expr,
                        detail=f"Reported p {norm_op} {p_str}, but recomputed p = {p_calc:.6g}",
                        expected=f"p = {p_calc:.6g}",
                        reported=f"p {norm_op} {p_str}",
                    )
                )
        return findings

    # Exact equality: p = Y
    decimals = _decimal_places(p_str)
    tol = max(0.5 * (10 ** (-decimals)) + 1e-4, 0.002)
    diff_two = abs(p_rep - p_two)
    diff_one = abs(p_rep - p_one) if p_one is not None else float("inf")
    best_p = p_one if (one_tailed and p_one is not None) else p_two
    best_diff = diff_one if (one_tailed and p_one is not None) else diff_two

    # Also allow exact 1-tailed match if author didn't specify 2-tailed and 1-tailed matches closely
    if best_diff > tol and p_one is not None and diff_one <= tol:
        best_p = p_one
        best_diff = diff_one

    if best_diff > tol:
        rep_sig = p_rep < alpha
        calc_sig = best_p < alpha
        if rep_sig != calc_sig:
            findings.append(
                StatCheckFinding(
                    code="DECISION_BOUNDARY_FLIP",
                    severity="ERROR",
                    line_number=line_num,
                    expression=expr,
                    detail=(
                        f"Decision boundary flip at alpha={alpha}: reported p = {p_str} "
                        f"({'<' if rep_sig else '>='} {alpha}) vs recomputed p = {best_p:.6g}"
                    ),
                    expected=f"p = {best_p:.6g}",
                    reported=f"p = {p_str}",
                )
            )
        else:
            findings.append(
                StatCheckFinding(
                    code="P_VALUE_INCONSISTENCY",
                    severity="ERROR",
                    line_number=line_num,
                    expression=expr,
                    detail=f"Reported p = {p_str} differs from recomputed p = {best_p:.6g}",
                    expected=f"p = {best_p:.6g}",
                    reported=f"p = {p_str}",
                )
            )
    return findings


def audit_stat_consistency(
    manuscript_text: str,
    *,
    alpha: float = 0.05,
) -> StatCheckResult:
    """Run GRIM, test-statistic vs. p-value, and CI geometry checks on ``manuscript_text``."""
    findings: list[StatCheckFinding] = []
    grim_checks = 0
    stat_tests_checked = 0
    ci_checks = 0

    segments = _split_segments_with_lines(manuscript_text)

    for line_num, seg in segments:
        is_one_tailed = bool(re.search(r"\bone[- ]?(?:tailed|sided)\b", seg, re.IGNORECASE))

        # 1. GRIM / Integer-Fraction Gate
        n_matches = _SAMPLE_SIZE_RE.findall(seg)
        if n_matches:
            # Use the primary sample size in the segment
            n_val = int(n_matches[0][1])
            if 0 < n_val <= 10000:
                for pct_str in _PCT_RE.findall(seg):
                    pct_val = float(pct_str)
                    if 0.0 <= pct_val <= 100.0:
                        grim_checks += 1
                        dec = _decimal_places(pct_str)
                        if not _can_express_percentage(pct_val, dec, n_val):
                            findings.append(
                                StatCheckFinding(
                                    code="GRIM_INCONSISTENCY",
                                    severity="ERROR",
                                    line_number=line_num,
                                    expression=f"N={n_val}, {pct_str}%",
                                    detail=(
                                        f"Impossible percentage granularity {pct_str}% for sample size N={n_val}"
                                    ),
                                    expected=f"round(100*k/{n_val}, {dec})",
                                    reported=f"{pct_str}%",
                                )
                            )
                for mean_str in _MEAN_RE.findall(seg):
                    mean_val = float(mean_str)
                    dec = _decimal_places(mean_str)
                    if dec >= 2 and n_val < 10**dec:
                        grim_checks += 1
                        if not _can_express_mean(mean_val, dec, n_val):
                            findings.append(
                                StatCheckFinding(
                                    code="GRIM_INCONSISTENCY",
                                    severity="ERROR",
                                    line_number=line_num,
                                    expression=f"N={n_val}, M={mean_str}",
                                    detail=(
                                        f"GRIM failure: mean {mean_str} is impossible for integer-scale N={n_val}"
                                    ),
                                    expected=f"round(k/{n_val}, {dec})",
                                    reported=mean_str,
                                )
                            )

        # 2. Test-Statistic vs. p-Value Recalculation
        for m in _T_TEST_RE.finditer(seg):
            df_v, t_v, op, p_s = float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)
            if df_v > 0:
                stat_tests_checked += 1
                p2 = pvalue_from_t(t_v, df_v, two_tailed=True)
                findings.extend(
                    _evaluate_p_report(
                        line_num=line_num,
                        expr=m.group(0),
                        op=op,
                        p_str=p_s,
                        p_two=p2,
                        p_one=0.5 * p2,
                        alpha=alpha,
                        one_tailed=is_one_tailed,
                    )
                )

        for m in _F_TEST_RE.finditer(seg):
            d1, d2, f_v, op, p_s = (
                float(m.group(1)),
                float(m.group(2)),
                float(m.group(3)),
                m.group(4),
                m.group(5),
            )
            if d1 > 0 and d2 > 0:
                stat_tests_checked += 1
                pf = pvalue_from_f(f_v, d1, d2)
                findings.extend(
                    _evaluate_p_report(
                        line_num=line_num,
                        expr=m.group(0),
                        op=op,
                        p_str=p_s,
                        p_two=pf,
                        p_one=None,
                        alpha=alpha,
                        one_tailed=False,
                    )
                )

        for m in _Z_TEST_RE.finditer(seg):
            z_v, op, p_s = float(m.group(1)), m.group(2), m.group(3)
            stat_tests_checked += 1
            pz = pvalue_from_z(z_v, two_tailed=True)
            findings.extend(
                _evaluate_p_report(
                    line_num=line_num,
                    expr=m.group(0),
                    op=op,
                    p_str=p_s,
                    p_two=pz,
                    p_one=0.5 * pz,
                    alpha=alpha,
                    one_tailed=is_one_tailed,
                )
            )

        for m in _CHI2_TEST_RE.finditer(seg):
            df_v, c_v, op, p_s = float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)
            if df_v > 0:
                stat_tests_checked += 1
                pc = pvalue_from_chi2(c_v, df_v)
                findings.extend(
                    _evaluate_p_report(
                        line_num=line_num,
                        expr=m.group(0),
                        op=op,
                        p_str=p_s,
                        p_two=pc,
                        p_one=None,
                        alpha=alpha,
                        one_tailed=False,
                    )
                )

        for m in _R_TEST_RE.finditer(seg):
            r_v, n_v, op, p_s = float(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
            if -1.0 <= r_v <= 1.0 and n_v >= 3:
                stat_tests_checked += 1
                pr = pvalue_from_r(r_v, n_v, two_tailed=True)
                findings.extend(
                    _evaluate_p_report(
                        line_num=line_num,
                        expr=m.group(0),
                        op=op,
                        p_str=p_s,
                        p_two=pr,
                        p_one=0.5 * pr,
                        alpha=alpha,
                        one_tailed=is_one_tailed,
                    )
                )

        # 3. Confidence Interval & Plus-Minus Geometry Gate
        checked_spans: list[tuple[int, int]] = []
        claims_symmetric = bool(
            re.search(r"\b(?:normal|wald|symmetric)\s+(?:95%?\s*)?CI\b", seg, re.IGNORECASE)
        )
        for m in _CI_WITH_EST_RE.finditer(seg):
            ci_checks += 1
            checked_spans.append(m.span())
            est = float(m.group(1))
            lo = float(m.group(2))
            hi = float(m.group(3))
            if lo > hi:
                findings.append(
                    StatCheckFinding(
                        code="INVERTED_CI_BOUNDS",
                        severity="ERROR",
                        line_number=line_num,
                        expression=m.group(0),
                        detail=f"Inverted confidence interval bounds: [{lo}, {hi}]",
                        expected="L <= U",
                        reported=f"[{lo}, {hi}]",
                    )
                )
            elif est < lo - 1e-9 or est > hi + 1e-9:
                findings.append(
                    StatCheckFinding(
                        code="ESTIMATE_OUTSIDE_CI",
                        severity="ERROR",
                        line_number=line_num,
                        expression=m.group(0),
                        detail=f"Point estimate {est} lies outside interval [{lo}, {hi}]",
                        expected=f"{lo} <= {est} <= {hi}",
                        reported=m.group(0),
                    )
                )
            elif claims_symmetric:
                left_w = est - lo
                right_w = hi - est
                tol_sym = max(1e-3, 0.05 * (hi - lo))
                if abs(left_w - right_w) > tol_sym:
                    findings.append(
                        StatCheckFinding(
                            code="ASYMMETRIC_NORMAL_CI",
                            severity="ERROR",
                            line_number=line_num,
                            expression=m.group(0),
                            detail=(
                                f"Purportedly symmetric normal CI is asymmetric: "
                                f"left={left_w:.4g} vs right={right_w:.4g}"
                            ),
                            expected="est - L == U - est",
                            reported=m.group(0),
                        )
                    )

        for m in _CI_STANDALONE_RE.finditer(seg):
            if any(s <= m.start() < e for s, e in checked_spans):
                continue
            ci_checks += 1
            lo = float(m.group(1))
            hi = float(m.group(2))
            if lo > hi:
                findings.append(
                    StatCheckFinding(
                        code="INVERTED_CI_BOUNDS",
                        severity="ERROR",
                        line_number=line_num,
                        expression=m.group(0),
                        detail=f"Inverted confidence interval bounds: [{lo}, {hi}]",
                        expected="L <= U",
                        reported=f"[{lo}, {hi}]",
                    )
                )

        for m in _PM_RE.finditer(seg):
            ci_checks += 1
            spread = float(m.group(2))
            if spread < 0.0:
                findings.append(
                    StatCheckFinding(
                        code="NEGATIVE_SPREAD",
                        severity="ERROR",
                        line_number=line_num,
                        expression=m.group(0),
                        detail=f"Negative spread/SD in plus-minus expression: {m.group(0)}",
                        expected="SD >= 0",
                        reported=str(spread),
                    )
                )

    failures = tuple(f"[{f.code}] line {f.line_number}: {f.detail}" for f in findings)
    return StatCheckResult(
        passed=len(findings) == 0,
        grim_checks=grim_checks,
        stat_tests_checked=stat_tests_checked,
        ci_checks=ci_checks,
        findings=tuple(findings),
        failures=failures,
    )
