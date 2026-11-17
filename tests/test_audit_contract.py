"""Tests for standardized AveryCorp AuditReport & AuditAttestation contract in limboAudit (v2.0.0 MIT Open-Core)."""
from __future__ import annotations

import json
from pathlib import Path

from limbo_audit import (
    AuditAttestation,
    AuditReport,
    __version__,
    assert_baseline,
    run_audit,
    write_baseline,
)
from limbo_audit.cli import main

REQUIRED_AUDIT_KEYS = {
    "package",
    "version",
    "suite",
    "stage_role",
    "status",
    "verdict",
    "metrics",
    "thresholds",
    "seed",
    "attestation",
}

REQUIRED_METRIC_KEYS = {
    "verified_references",
    "phantom_citations",
    "identifier_coverage",
    "traced_numbers_ratio",
    "adversarial_fault_recall",
    "self_citation_fraction",
    "statcheck_trap_recall",
}

REQUIRED_ATTESTATION_KEYS = {
    "input_sha256",
    "report_sha256",
    "platform_fingerprint",
}


def test_audit_report_contract_and_determinism() -> None:
    assert __version__ == "2.0.0"
    rep1 = run_audit(seed=42)
    rep2 = run_audit(seed=42)
    assert isinstance(rep1, AuditReport)
    assert isinstance(rep1.attestation, AuditAttestation)
    assert rep1 == rep2

    assert rep1.package == "limbo-audit"
    assert rep1.version == "2.0.0"
    assert rep1.suite == "Suite II: Scientific Identifiability & Null-Audit Suite"
    assert (
        rep1.stage_role
        == "Suite II: Zero-Phantom Citation, Numerical Traceability & Epistemic Null-Audit Gate"
    )
    assert rep1.status == "PASS"
    assert rep1.verdict == "ZERO_PHANTOM_CITATIONS_AND_NUMBERS_TRACED"

    parsed = json.loads(rep1.to_json())
    assert set(parsed.keys()) == REQUIRED_AUDIT_KEYS
    assert set(parsed["metrics"].keys()) == REQUIRED_METRIC_KEYS
    assert set(parsed["attestation"].keys()) == REQUIRED_ATTESTATION_KEYS

    assert parsed["metrics"] == {
        "verified_references": 59,
        "phantom_citations": 0,
        "identifier_coverage": 1.0,
        "traced_numbers_ratio": 1.0,
        "adversarial_fault_recall": 1.0,
        "self_citation_fraction": 0.051,
        "statcheck_trap_recall": 1.0,
    }
    assert len(rep1.attestation.input_sha256) == 64
    assert len(rep1.attestation.report_sha256) == 64
    assert AuditReport.from_json(rep1.to_json()) == rep1
    assert "limbo-audit" in rep1.summary_line()
    assert "Cryptographic Attestation" in rep1.to_markdown()


def test_baseline_ratchet_and_repo_baseline_lock(tmp_path: Path, capsys) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    repo_baseline = repo_root / "audit-baseline.json"
    assert repo_baseline.exists(), "Root audit-baseline.json must exist"

    rep = run_audit(seed=42)
    ok, drifts = assert_baseline(rep, repo_baseline)
    assert ok is True, f"Unexpected baseline drift: {drifts}"

    custom_base = tmp_path / "custom-baseline.json"
    rc_w = main(["audit", "--seed", "42", "--write-baseline", str(custom_base), "--json"])
    assert rc_w == 0
    _ = capsys.readouterr()

    rc_a = main(["audit", "--seed", "42", "--assert-baseline", str(custom_base), "--json"])
    assert rc_a == 0
    out_a = json.loads(capsys.readouterr().out)
    assert set(out_a.keys()) == REQUIRED_AUDIT_KEYS

    tampered = json.loads(custom_base.read_text(encoding="utf-8"))
    tampered["metrics"]["phantom_citations"] = 1
    write_path = tmp_path / "tampered.json"
    write_path.write_text(json.dumps(tampered), encoding="utf-8")

    rc_fail = main(["audit", "--seed", "42", "--assert-baseline", str(write_path)])
    assert rc_fail == 1
    err_out = capsys.readouterr().err
    assert "BASELINE RATCHET FAIL" in err_out

    direct_path = write_baseline(rep, tmp_path / "direct.json")
    assert direct_path.exists()


def test_cli_demo_json_and_markdown(capsys) -> None:
    rc_demo = main(["demo", "--seed", "42", "--json"])
    assert rc_demo == 0
    out_demo = json.loads(capsys.readouterr().out)
    assert set(out_demo.keys()) == REQUIRED_AUDIT_KEYS
    assert out_demo["package"] == "limbo-audit"
    assert out_demo["version"] == "2.0.0"

    rc_md = main(["audit", "--seed", "42", "--markdown"])
    assert rc_md == 0
    md_out = capsys.readouterr().out
    assert "| `verified_references` | `59` |" in md_out
