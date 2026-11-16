"""Engine 2 — Verbatim Manuscript Number-to-Artifact Consistency Gate.

Generalizes ``Gauge/paper/consistency.py``, ``Augur/paper/consistency.py``, and
``Matrix/paper/consistency.py`` into a general traceability gate:
- Verifies every quantitative manuscript claim, LaTeX ``\\newcommand{\\num...}{...}`` macro
  (``numbers.tex``), or inline table/prose metric against a seeded JSON artifact key-path
  (e.g., ``"results/cp3.json:railing_rate_osipi" -> 0.542``).
- Computes and locks SHA-256 digests of every underlying JSON artifact.
- Catches both **Orphaned / Untraced Numbers** (undefined/unmapped ``\\num*`` macros or missing
  artifact key-paths) and **Mis-Quoted / Stale Numbers** (e.g., claiming ``r = 0.39`` when the
  locked artifact holds ``r = 0.24``).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

_LATEX_NEWCOMMAND_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{\\([A-Za-z][A-Za-z0-9]*)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
    r"(?:[^\n%]*%\s*(?:@trace|trace:|source:)\s*(\S+))?"
)
_LATEX_NUM_MACRO_USE_RE = re.compile(r"\\(num[A-Za-z0-9]+)\b")
_KEYPATH_STEP_RE = re.compile(r"([^\.\[\]/]+)|\[(\d+)\]")


def compute_artifact_sha256(artifact_obj: Any) -> str:
    """Compute a deterministic SHA-256 hex digest for a JSON-serializable object, str, or bytes."""
    if isinstance(artifact_obj, bytes):
        payload = artifact_obj
    elif isinstance(artifact_obj, str):
        payload = artifact_obj.encode("utf-8")
    else:
        canonical = json.dumps(
            artifact_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        payload = canonical.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_latex_macros(tex_text: str) -> dict[str, str]:
    """Extract ``{macro_name: value}`` from ``\\newcommand{\\macro}{value}`` definitions."""
    macros: dict[str, str] = {}
    for line in tex_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        for m in _LATEX_NEWCOMMAND_RE.finditer(line):
            macros[m.group(1)] = m.group(2).strip()
    return macros


def parse_inline_trace_annotations(tex_text: str) -> dict[str, str]:
    """Extract ``{macro_name: artifact_keypath}`` from ``% @trace path:key`` macro comments."""
    traces: dict[str, str] = {}
    for line in tex_text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        for m in _LATEX_NEWCOMMAND_RE.finditer(line):
            if m.group(3):
                traces[m.group(1)] = m.group(3).strip()
    return traces


def _normalize_numeric_token(raw: str) -> float | None:
    """Parse a LaTeX/Markdown numeric token (handling ``−``, ``--``, ``+``, ``\\%``) into a float."""
    s = raw.strip()
    s = s.strip("$")
    s = s.replace("−", "-").replace("–", "-").replace("--", "-")
    s = s.replace(r"\%", "").replace("%", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def resolve_artifact_keypath(
    artifacts: Mapping[str, Any], keypath: str
) -> tuple[bool, Any, str | None]:
    """Resolve ``"artifact_name:nested.path[0]"`` (or ``"nested.path"``) against ``artifacts``.

    Returns ``(found, value, artifact_key)``.
    """
    if ":" in keypath:
        art_name, inner_path = keypath.split(":", 1)
        if art_name not in artifacts:
            return (False, None, art_name)
        cur: Any = artifacts[art_name]
        art_key: str | None = art_name
    else:
        if keypath in artifacts and not isinstance(artifacts[keypath], Mapping):
            return (True, artifacts[keypath], None)
        if len(artifacts) == 1:
            only_key = next(iter(artifacts.keys()))
            only_val = artifacts[only_key]
            if isinstance(only_val, Mapping) and keypath not in artifacts:
                cur = only_val
                inner_path = keypath
                art_key = only_key
            else:
                cur = artifacts
                inner_path = keypath
                art_key = None
        else:
            cur = artifacts
            inner_path = keypath
            art_key = None

    if isinstance(cur, (str, bytes)):
        try:
            cur = json.loads(cur.decode("utf-8") if isinstance(cur, bytes) else cur)
        except Exception:
            return (False, None, art_key)

    if not inner_path:
        return (True, cur, art_key)

    for step in _KEYPATH_STEP_RE.finditer(inner_path):
        prop, idx_str = step.group(1), step.group(2)
        if prop is not None:
            if isinstance(cur, Mapping) and prop in cur:
                cur = cur[prop]
            else:
                return (False, None, art_key)
        elif idx_str is not None:
            idx = int(idx_str)
            if isinstance(cur, (list, tuple)) and -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return (False, None, art_key)
    return (True, cur, art_key)


@dataclass(frozen=True)
class ConsistencyAuditResult:
    """Comprehensive diagnostic output of ``audit_numerical_consistency``."""

    passed: bool
    total_claims: int
    verified_claims: int
    traced_numbers_ratio: float
    stale_or_misquoted: tuple[str, ...]
    untraced_or_orphaned: tuple[str, ...]
    unused_macros: tuple[str, ...]
    digest_mismatches: tuple[str, ...]
    artifact_digests: dict[str, str]
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total_claims": self.total_claims,
            "verified_claims": self.verified_claims,
            "traced_numbers_ratio": round(float(self.traced_numbers_ratio), 6),
            "stale_or_misquoted": list(self.stale_or_misquoted),
            "untraced_or_orphaned": list(self.untraced_or_orphaned),
            "unused_macros": list(self.unused_macros),
            "digest_mismatches": list(self.digest_mismatches),
            "artifact_digests": dict(self.artifact_digests),
            "failures": list(self.failures),
        }


def _strip_macro_definitions(text: str) -> str:
    """Return manuscript body with ``\\newcommand`` definition lines removed for usage scanning."""
    kept: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        if _LATEX_NEWCOMMAND_RE.search(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def audit_numerical_consistency(
    manuscript_text: str,
    macros_or_claims: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    rtol: float = 1e-4,
    atol: float = 1e-4,
    *,
    artifact_digests: Mapping[str, str] | None = None,
    check_unused_macros: bool = True,
) -> ConsistencyAuditResult:
    """Verify manuscript numbers, ``\\num*`` macros, and artifact SHA-256 digests.

    Parameters
    ----------
    manuscript_text:
        Combined or standalone LaTeX/Markdown manuscript text (may include ``\\newcommand``
        macro definitions from ``numbers.tex`` as well as prose/table body).
    macros_or_claims:
        Mapping from macro name (e.g. ``"numRailingRate"``) or claim identifier to either:
        - a key-path string ``"results/cp3.json:railing_rate_osipi"``, or
        - a spec dict with ``path`` (required) and optional ``fmt`` (e.g. ``"{:.3f}"``),
          ``scale`` (float multiplier, e.g. ``100.0`` for percentages), ``pattern`` (regex
          with 1 capture group to extract an inline prose value like ``r = 0.39``),
          ``value`` / ``manuscript_value`` (explicit claimed value), and ``sha256``
          (expected SHA-256 digest of the referenced artifact).
    artifacts:
        Mapping ``{artifact_name: json_dict_or_raw_str}`` (or a single flat artifact dict).
    rtol, atol:
        Relative and absolute tolerance passed to ``numpy.isclose`` for numeric comparisons.
    artifact_digests:
        Optional mapping ``{artifact_name: expected_sha256_hex}`` verified against computed
        SHA-256 digests.
    """
    computed_digests: dict[str, str] = {}
    for art_key, art_val in artifacts.items():
        computed_digests[str(art_key)] = compute_artifact_sha256(art_val)

    failures: list[str] = []
    digest_mismatches: list[str] = []

    if artifact_digests:
        for art_key, expected_hex in sorted(artifact_digests.items()):
            actual_hex = computed_digests.get(art_key)
            if actual_hex is None:
                digest_mismatches.append(art_key)
                failures.append(
                    f"[missing-artifact-digest] {art_key}: expected SHA-256 {expected_hex[:12]}... but artifact is missing"
                )
            elif actual_hex.lower() != expected_hex.strip().lower():
                digest_mismatches.append(art_key)
                failures.append(
                    f"[artifact-sha256-mismatch] {art_key}: expected {expected_hex[:12]}... vs actual {actual_hex[:12]}..."
                )

    defined_macros = parse_latex_macros(manuscript_text)
    prose_body = _strip_macro_definitions(manuscript_text)
    used_num_macros = set(_LATEX_NUM_MACRO_USE_RE.findall(prose_body))

    normalized_claims: dict[str, dict[str, Any]] = {}
    for raw_label, raw_spec in macros_or_claims.items():
        clean_label = raw_label.lstrip("\\")
        if isinstance(raw_spec, str):
            normalized_claims[clean_label] = {"path": raw_spec}
        elif isinstance(raw_spec, Mapping):
            normalized_claims[clean_label] = dict(raw_spec)
        else:
            normalized_claims[clean_label] = {"path": "", "_invalid_spec": raw_spec}

    stale_or_misquoted: list[str] = []
    untraced_or_orphaned: list[str] = []
    unused_macros: list[str] = []
    verified_claims = 0

    # 1. Check for \num* macros used in prose or defined in numbers.tex that lack a claim mapping
    traced_macro_names = set(normalized_claims.keys())
    for macro_name in sorted(used_num_macros - traced_macro_names):
        untraced_or_orphaned.append(macro_name)
        failures.append(
            f"[untraced-macro] \\{macro_name}: used in manuscript prose without artifact trace mapping"
        )

    for macro_name in sorted(set(defined_macros.keys()) - traced_macro_names):
        if macro_name.startswith("num") and macro_name not in untraced_or_orphaned:
            untraced_or_orphaned.append(macro_name)
            failures.append(
                f"[orphaned-macro-def] \\{macro_name}: defined in manuscript without artifact trace mapping"
            )

    # 2. Verify every claim in macros_or_claims
    checked_digest_pairs: set[tuple[str, str]] = set()
    for label, spec in normalized_claims.items():
        keypath = str(spec.get("path", "")).strip()
        if not keypath:
            untraced_or_orphaned.append(label)
            failures.append(f"[missing-keypath] {label}: empty artifact key-path")
            continue

        found, art_val, art_key = resolve_artifact_keypath(artifacts, keypath)
        if not found:
            untraced_or_orphaned.append(label)
            failures.append(
                f"[missing-artifact-path] {label}: key-path {keypath!r} could not be resolved"
            )
            continue

        # Per-claim optional SHA-256 pin
        spec_sha = spec.get("sha256")
        if spec_sha and art_key:
            pair = (art_key, str(spec_sha).lower())
            if pair not in checked_digest_pairs:
                checked_digest_pairs.add(pair)
                actual_sha = computed_digests.get(art_key, "").lower()
                if actual_sha != str(spec_sha).strip().lower():
                    if art_key not in digest_mismatches:
                        digest_mismatches.append(art_key)
                    failures.append(
                        f"[artifact-sha256-mismatch] {art_key} ({label}): expected {str(spec_sha)[:12]}... vs actual {actual_sha[:12]}..."
                    )
                    continue

        # Locate the claimed manuscript token:
        # Priority: (a) explicit pattern regex on prose, (b) defined \newcommand macro,
        # (c) explicit manuscript_value in spec, (d) inline `label = <num>` in prose.
        ms_raw: str | None = None
        pattern = spec.get("pattern")
        if pattern:
            pm = re.search(str(pattern), manuscript_text)
            if pm:
                ms_raw = pm.group(1) if pm.lastindex else pm.group(0)
            else:
                untraced_or_orphaned.append(label)
                failures.append(
                    f"[missing-inline-claim] {label}: pattern {pattern!r} not found in manuscript"
                )
                continue
        elif label in defined_macros:
            ms_raw = defined_macros[label]
            if check_unused_macros and prose_body.strip() and label.startswith("num"):
                # Verify macro is actually used in prose
                if not re.search(rf"\\{re.escape(label)}\b", prose_body):
                    unused_macros.append(label)
                    failures.append(
                        f"[unused-macro] \\{label}: defined and traced to {keypath} but unused in manuscript body"
                    )
                    continue
        elif "manuscript_value" in spec or "value" in spec:
            raw_v = spec.get("manuscript_value", spec.get("value"))
            ms_raw = str(raw_v)
        else:
            # Check inline assignment e.g. "r = 0.39" when label is "r" or search \label
            inline_re = re.compile(
                rf"(?<![A-Za-z0-9_\\]){re.escape(label)}\s*(?:=|≈|~)\s*([+\-−]?\d+(?:\.\d+)?)"
            )
            im = inline_re.search(prose_body)
            if im:
                ms_raw = im.group(1)
            else:
                untraced_or_orphaned.append(label)
                failures.append(
                    f"[missing-manuscript-value] {label}: neither \\newcommand{{\\{label}}} nor inline '{label} = ...' found"
                )
                continue

        scale = float(spec.get("scale", 1.0))
        fmt = spec.get("fmt")

        # Compare numeric or verbatim string
        art_num: float | None = None
        if isinstance(art_val, (int, float, np.number)) and not isinstance(art_val, bool):
            art_num = float(art_val) * scale
        elif isinstance(art_val, str):
            parsed_art = _normalize_numeric_token(art_val)
            if parsed_art is not None:
                art_num = parsed_art * scale

        ms_num = _normalize_numeric_token(ms_raw)

        if fmt is not None and art_num is not None:
            fmt_str = str(fmt)
            try:
                expected_formatted = fmt_str.format(art_num)
            except ValueError:
                expected_formatted = fmt_str.format(int(round(art_num)))
            expected_num = _normalize_numeric_token(expected_formatted)
            norm_ms_str = ms_raw.strip().replace("−", "-")
            norm_exp_str = expected_formatted.strip().replace("−", "-")
            if norm_ms_str == norm_exp_str or (
                ms_num is not None
                and expected_num is not None
                and bool(np.isclose(ms_num, expected_num, rtol=rtol, atol=atol))
            ):
                verified_claims += 1
            else:
                stale_or_misquoted.append(label)
                failures.append(
                    f"[stale-number] {label}: manuscript has {ms_raw!r} vs formatted artifact {expected_formatted!r} ({keypath}={art_val!r})"
                )
        elif art_num is not None and ms_num is not None:
            if bool(np.isclose(ms_num, art_num, rtol=rtol, atol=atol)):
                verified_claims += 1
            else:
                stale_or_misquoted.append(label)
                failures.append(
                    f"[stale-number] {label}: manuscript claims {ms_num} vs locked artifact {art_num} ({keypath})"
                )
        else:
            # Non-numeric verbatim string provenance (e.g., dataset ID, DOI, truncated blob SHA)
            norm_ms = ms_raw.replace(r"\_", "_").strip()
            norm_art = str(art_val).replace(r"\_", "_").strip()
            if norm_ms == norm_art:
                verified_claims += 1
            else:
                stale_or_misquoted.append(label)
                failures.append(
                    f"[stale-string] {label}: manuscript has {ms_raw!r} vs artifact {art_val!r} ({keypath})"
                )

    denominator = len(normalized_claims) + len(
        [u for u in untraced_or_orphaned if u not in normalized_claims]
    )
    ratio = (verified_claims / denominator) if denominator > 0 else 1.0
    passed = (len(failures) == 0)

    return ConsistencyAuditResult(
        passed=passed,
        total_claims=denominator,
        verified_claims=verified_claims,
        traced_numbers_ratio=float(ratio),
        stale_or_misquoted=tuple(stale_or_misquoted),
        untraced_or_orphaned=tuple(untraced_or_orphaned),
        unused_macros=tuple(unused_macros),
        digest_mismatches=tuple(digest_mismatches),
        artifact_digests=computed_digests,
        failures=tuple(failures),
    )
