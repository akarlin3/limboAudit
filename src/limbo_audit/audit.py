"""Standardized AveryCorp ``AuditReport`` & ``AuditAttestation`` Contract.

Implements the Suite I / Suite II diagnostic contract for ``limbo-audit``:
- ``AuditAttestation``: Deterministic SHA-256 provenance digest of canonical inputs
  (``input_sha256``), canonical scientific report payload (``report_sha256``), and
  runtime ``platform_fingerprint``.
- ``AuditReport``: Typed frozen diagnostic report with JSON and GitHub Step Summary
  Markdown serialization.
- ``run_audit(seed=42)``: Evaluates the 59-entry verified reference taxonomy, 34/34
  traced manuscript numbers, CP0 distinctness release gate, and seeded adversarial
  epistemic fault-injection traps.
- ``write_baseline`` & ``assert_baseline``: Scientific regression ratchet enforcing zero
  drift against ``audit-baseline.json``.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from .fixtures import (
    CANONICAL_ARTIFACTS,
    CANONICAL_BIB_TEXT,
    CANONICAL_CLAIMS_MAP,
    CANONICAL_LEDGER_TEXT,
    CANONICAL_MANUSCRIPT_TEX,
    CANONICAL_RELEASE_CONFIG,
    evaluate_canonical_and_adversarial,
)

PACKAGE_NAME = "limbo-audit"
PACKAGE_VERSION = "2.0.0"

SUITE_I_NAME: Literal["Suite I: Clinical Quantitative-MRI Trust Spine"] = (
    "Suite I: Clinical Quantitative-MRI Trust Spine"
)
SUITE_II_NAME: Literal["Suite II: Scientific Identifiability & Null-Audit Suite"] = (
    "Suite II: Scientific Identifiability & Null-Audit Suite"
)
STAGE_ROLE = "Suite II: Zero-Phantom Citation, Numerical Traceability & Epistemic Null-Audit Gate"

SuiteLiteral = Literal[
    "Suite I: Clinical Quantitative-MRI Trust Spine",
    "Suite II: Scientific Identifiability & Null-Audit Suite",
]
StatusLiteral = Literal["PASS", "WARN", "HALT"]


def _to_builtin(val: Any) -> float | int | str | bool:
    if isinstance(val, (bool, np.bool_)):
        return bool(val)
    if isinstance(val, (int, np.integer)):
        return int(val)
    if isinstance(val, (float, np.floating)):
        return float(val)
    return str(val)


def compute_platform_fingerprint() -> str:
    """Return a concise runtime platform identifier (excluded from ``report_sha256`` for cross-Python invariance)."""
    sys_name = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    return f"{sys_name}-{machine}-py{py_ver}-numpy{np.__version__}"


def compute_canonical_input_sha256(seed: int) -> str:
    """Compute a deterministic SHA-256 digest over all canonical audit inputs and ``seed``."""
    canonical_bundle = {
        "seed": int(seed),
        "bib_text": CANONICAL_BIB_TEXT,
        "ledger_text": CANONICAL_LEDGER_TEXT,
        "manuscript_tex": CANONICAL_MANUSCRIPT_TEX,
        "claims_map": CANONICAL_CLAIMS_MAP,
        "artifacts": CANONICAL_ARTIFACTS,
        "release_config": CANONICAL_RELEASE_CONFIG,
    }
    encoded = json.dumps(
        canonical_bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_canonical_report_sha256(
    *,
    package: str,
    version: str,
    suite: str,
    stage_role: str,
    status: str,
    verdict: str,
    metrics: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    seed: int,
    input_sha256: str,
) -> str:
    """Compute a cross-platform, cross-Python-version deterministic SHA-256 over the report core."""
    core_payload = {
        "package": str(package),
        "version": str(version),
        "suite": str(suite),
        "stage_role": str(stage_role),
        "status": str(status),
        "verdict": str(verdict),
        "metrics": {str(k): _to_builtin(v) for k, v in metrics.items()},
        "thresholds": {str(k): _to_builtin(v) for k, v in thresholds.items()},
        "seed": int(seed),
        "input_sha256": str(input_sha256),
    }
    encoded = json.dumps(
        core_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AuditAttestation:
    """Cryptographic provenance attestation accompanying an ``AuditReport``."""

    input_sha256: str
    report_sha256: str
    platform_fingerprint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "input_sha256": str(self.input_sha256),
            "report_sha256": str(self.report_sha256),
            "platform_fingerprint": str(self.platform_fingerprint),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AuditAttestation:
        return cls(
            input_sha256=str(data["input_sha256"]),
            report_sha256=str(data["report_sha256"]),
            platform_fingerprint=str(data.get("platform_fingerprint", "unknown")),
        )


@dataclass(frozen=True)
class AuditReport:
    """Standardized AveryCorp scientific identifiability and epistemic null-audit report."""

    package: str
    version: str
    suite: SuiteLiteral
    stage_role: str
    status: StatusLiteral
    verdict: str
    metrics: dict[str, float | int | str | bool]
    thresholds: dict[str, float | int | str]
    seed: int
    attestation: AuditAttestation

    def to_dict(self) -> dict[str, Any]:
        """Serialize the audit report to a JSON-compatible Python dictionary."""
        return {
            "package": str(self.package),
            "version": str(self.version),
            "suite": str(self.suite),
            "stage_role": str(self.stage_role),
            "status": str(self.status),
            "verdict": str(self.verdict),
            "metrics": {str(k): _to_builtin(v) for k, v in self.metrics.items()},
            "thresholds": {str(k): _to_builtin(v) for k, v in self.thresholds.items()},
            "seed": int(self.seed),
            "attestation": self.attestation.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the audit report to a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AuditReport:
        """Reconstruct an ``AuditReport`` from a parsed JSON dictionary."""
        return cls(
            package=str(data["package"]),
            version=str(data["version"]),
            suite=data["suite"],
            stage_role=str(data["stage_role"]),
            status=data["status"],
            verdict=str(data["verdict"]),
            metrics={str(k): _to_builtin(v) for k, v in dict(data["metrics"]).items()},
            thresholds={str(k): _to_builtin(v) for k, v in dict(data["thresholds"]).items()},
            seed=int(data["seed"]),
            attestation=AuditAttestation.from_dict(data["attestation"]),
        )

    @classmethod
    def from_json(cls, text: str) -> AuditReport:
        """Deserialize an ``AuditReport`` from a JSON string."""
        return cls.from_dict(json.loads(text))

    def summary_line(self) -> str:
        """Return a concise one-line human-readable status summary."""
        return (
            f"[{self.status}] {self.package} v{self.version} "
            f"({self.suite} | {self.stage_role}) -> {self.verdict}"
        )

    def to_markdown(self) -> str:
        """Render a GitHub Flavored Markdown summary suitable for ``$GITHUB_STEP_SUMMARY``."""
        lines = [
            f"### `{self.package}` v{self.version} — Scientific Audit Summary",
            "",
            f"- **Suite**: {self.suite}",
            f"- **Role**: {self.stage_role}",
            f"- **Status**: **{self.status}** (`{self.verdict}`)",
            f"- **Seed**: `{self.seed}`",
            "",
            "| Metric | Value |",
            "|---|---|",
        ]
        for k, v in self.metrics.items():
            lines.append(f"| `{k}` | `{v}` |")
        lines.extend(
            [
                "",
                "#### Cryptographic Attestation",
                f"- `input_sha256`: `{self.attestation.input_sha256}`",
                f"- `report_sha256`: `{self.attestation.report_sha256}`",
                f"- `platform_fingerprint`: `{self.attestation.platform_fingerprint}`",
            ]
        )
        return "\n".join(lines) + "\n"


def run_audit(seed: int = 42) -> AuditReport:
    """Execute the full canonical 59-reference + 34-number + adversarial mutant audit."""
    eval_bundle = evaluate_canonical_and_adversarial(seed=int(seed))
    cit = eval_bundle.citations_result
    con = eval_bundle.consistency_result
    rel = eval_bundle.release_result

    verified_refs = sum(1 for e in cit.bib_entries.values() if e.identifier_valid)
    phantoms = len(cit.phantom_citations)
    id_cov = round(float(cit.identifier_coverage), 6)
    traced_ratio = round(float(con.traced_numbers_ratio), 6)
    fault_recall = round(float(eval_bundle.adversarial_fault_recall), 6)
    self_cite_frac = round(float(rel.self_citation_fraction), 3)
    statcheck_recall = round(float(eval_bundle.statcheck_trap_recall), 6)

    metrics: dict[str, float | int | str | bool] = {
        "verified_references": int(verified_refs),
        "phantom_citations": int(phantoms),
        "identifier_coverage": float(id_cov),
        "traced_numbers_ratio": float(traced_ratio),
        "adversarial_fault_recall": float(fault_recall),
        "self_citation_fraction": float(self_cite_frac),
        "statcheck_trap_recall": float(statcheck_recall),
    }
    thresholds: dict[str, float | int | str] = {
        "max_phantom_citations": 0,
        "min_identifier_coverage": 1.0,
        "min_traced_numbers_ratio": 1.0,
        "min_adversarial_fault_recall": 1.0,
        "max_self_citation_fraction": 0.15,
        "min_statcheck_trap_recall": 1.0,
        "consistency_rtol": 1e-4,
        "consistency_atol": 1e-4,
    }

    all_clean = (
        cit.passed
        and con.passed
        and rel.release_ready
        and phantoms == 0
        and id_cov >= 1.0
        and traced_ratio >= 1.0
        and fault_recall >= 1.0
        and statcheck_recall >= 1.0
    )
    if all_clean:
        status: StatusLiteral = "PASS"
        verdict = "ZERO_PHANTOM_CITATIONS_AND_NUMBERS_TRACED"
    elif cit.passed and con.passed:
        status = "WARN"
        verdict = "RELEASE_HELD_OR_PARTIAL_MUTANT_RECALL"
    else:
        status = "HALT"
        verdict = "EPISTEMIC_AUDIT_FAILURE"

    input_sha = compute_canonical_input_sha256(int(seed))
    report_sha = compute_canonical_report_sha256(
        package=PACKAGE_NAME,
        version=PACKAGE_VERSION,
        suite=SUITE_II_NAME,
        stage_role=STAGE_ROLE,
        status=status,
        verdict=verdict,
        metrics=metrics,
        thresholds=thresholds,
        seed=int(seed),
        input_sha256=input_sha,
    )
    attestation = AuditAttestation(
        input_sha256=input_sha,
        report_sha256=report_sha,
        platform_fingerprint=compute_platform_fingerprint(),
    )

    return AuditReport(
        package=PACKAGE_NAME,
        version=PACKAGE_VERSION,
        suite=SUITE_II_NAME,
        stage_role=STAGE_ROLE,
        status=status,
        verdict=verdict,
        metrics=metrics,
        thresholds=thresholds,
        seed=int(seed),
        attestation=attestation,
    )


def write_baseline(report: AuditReport, path: str | Path) -> Path:
    """Write ``report`` as a canonical JSON regression baseline at ``path``."""
    out = Path(path)
    out.write_text(report.to_json(indent=2) + "\n", encoding="utf-8")
    return out


def assert_baseline(
    report: AuditReport,
    baseline_path: str | Path,
    *,
    rtol: float = 1e-6,
    atol: float = 1e-6,
) -> tuple[bool, list[str]]:
    """Verify ``report`` against a locked ``audit-baseline.json`` scientific regression ratchet."""
    p = Path(baseline_path)
    if not p.exists():
        return (False, [f"Baseline file not found: {p}"])

    baseline = json.loads(p.read_text(encoding="utf-8"))
    drifts: list[str] = []

    for field in ("package", "version", "suite", "stage_role", "status", "verdict", "seed"):
        actual_val = getattr(report, field)
        expected_val = baseline.get(field)
        if actual_val != expected_val:
            drifts.append(f"Field '{field}' drifted: actual={actual_val!r} vs baseline={expected_val!r}")

    base_metrics = baseline.get("metrics", {})
    if set(report.metrics.keys()) != set(base_metrics.keys()):
        drifts.append(
            f"Metric keys mismatch: actual={sorted(report.metrics.keys())} vs baseline={sorted(base_metrics.keys())}"
        )

    for k, base_v in base_metrics.items():
        if k not in report.metrics:
            continue
        act_v = report.metrics[k]
        if isinstance(act_v, (int, float)) and isinstance(base_v, (int, float)) and not isinstance(act_v, bool):
            if not bool(np.isclose(float(act_v), float(base_v), rtol=rtol, atol=atol)):
                drifts.append(f"Metric '{k}' drifted: actual={act_v} vs baseline={base_v}")
        elif act_v != base_v:
            drifts.append(f"Metric '{k}' drifted: actual={act_v!r} vs baseline={base_v!r}")

    base_att = baseline.get("attestation", {})
    if report.seed == baseline.get("seed"):
        if report.attestation.input_sha256 != base_att.get("input_sha256"):
            drifts.append(
                f"Attestation input_sha256 mismatch: {report.attestation.input_sha256} vs {base_att.get('input_sha256')}"
            )
        if report.attestation.report_sha256 != base_att.get("report_sha256"):
            drifts.append(
                f"Attestation report_sha256 mismatch: {report.attestation.report_sha256} vs {base_att.get('report_sha256')}"
            )

    return (len(drifts) == 0, drifts)
