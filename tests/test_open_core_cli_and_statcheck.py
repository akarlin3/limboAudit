"""Tests for Open-Core statcheck, check-all, LIMBO-NO-MANUSCRIPT guard, CTA routing, and clean tree boundary."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from limbo_audit import (
    audit_stat_consistency,
    pvalue_from_chi2,
    pvalue_from_f,
    pvalue_from_r,
    pvalue_from_t,
    pvalue_from_z,
)
from limbo_audit.cli import AVERYCORP_SERVICES_URL, OPEN_CORE_CTA_FOOTER, main

FORBIDDEN_PROPRIETARY_FILES = {
    "dossier.py",
    "studio.py",
    "autofix.py",
    "ingest.py",
    "pdf_refs.py",
    "referee_sim.py",
    "revision_pack.py",
    "notebook_rescue.py",
    "submission_pack.py",
    "containerize.py",
    "portfolio.py",
    "regulatory.py",
    "leakage.py",
    "checkpoint_audit.py",
    "archive_pack.py",
    "org_monitor.py",
}


def test_zero_proprietary_modules_present_in_source_tree() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src_dir = repo_root / "src" / "limbo_audit"
    present_files = {p.name for p in src_dir.iterdir() if p.is_file()}
    assert present_files.isdisjoint(FORBIDDEN_PROPRIETARY_FILES)
    assert present_files == {
        "__init__.py",
        "audit.py",
        "citations.py",
        "cli.py",
        "consistency.py",
        "fixtures.py",
        "py.typed",
        "release_gate.py",
        "statcheck.py",
    }


def test_statcheck_pure_python_kernels_and_cli(tmp_path: Path, capsys) -> None:
    assert abs(pvalue_from_z(1.959963984540054) - 0.05) < 1e-6
    assert abs(pvalue_from_t(2.0859634472658686, 20) - 0.05) < 1e-5
    assert abs(pvalue_from_f(4.351243503329275, 1, 20) - 0.05) < 1e-5
    assert abs(pvalue_from_chi2(3.841458820694124, 1) - 0.05) < 1e-5
    assert pvalue_from_r(0.5, 20) < 0.05

    clean_md = tmp_path / "clean.md"
    clean_md.write_text(
        "# Study Results\n\nIn cohort N = 20, 45.0% responded (t(18) = 2.55, p = 0.020; 95% CI [0.22, 0.68]).\n",
        encoding="utf-8",
    )
    assert main(["check-stats", str(clean_md)]) == 0
    assert "PASS" in capsys.readouterr().out

    trap_tex = tmp_path / "trap.tex"
    trap_tex.write_text(
        "In cohort N = 12, 31.0\\% responded (t(20) = 1.05, p = 0.010; 95\\% CI [0.90, 0.30]).\n",
        encoding="utf-8",
    )
    res = audit_stat_consistency(trap_tex.read_text(encoding="utf-8"))
    assert res.passed is False
    codes = {f.code for f in res.findings}
    assert {"GRIM_INCONSISTENCY", "DECISION_BOUNDARY_FLIP", "INVERTED_CI_BOUNDS"}.issubset(codes)

    rc_bad = main(["check-stats", "--tex", str(trap_tex), "--json"])
    assert rc_bad == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False


def test_check_all_empty_and_boilerplate_folder_guard(tmp_path: Path, capsys) -> None:
    empty_dir = tmp_path / "empty_ws"
    empty_dir.mkdir()

    rc = main(["check-all", str(empty_dir)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "LIMBO-NO-MANUSCRIPT" in out

    boilerplate_dir = tmp_path / "readme_only"
    boilerplate_dir.mkdir()
    (boilerplate_dir / "README.md").write_text("# Code only\n", encoding="utf-8")
    rc_json = main(["check-all", "--dir", str(boilerplate_dir), "--json"])
    assert rc_json == 2
    j_out = json.loads(capsys.readouterr().out)
    assert j_out["passed"] is False
    assert j_out["diagnostics"][0]["rule_id"] == "LIMBO-NO-MANUSCRIPT"


def test_check_all_clean_vs_flagged_cta_footer(tmp_path: Path, capsys) -> None:
    proj = tmp_path / "clean_paper"
    proj.mkdir()
    (proj / "refs.bib").write_text(
        "@article{lecun2015, author={LeCun, Yann}, title={Deep learning}, journal={Nature}, year={2015}, doi={10.1038/nature14539}}\n",
        encoding="utf-8",
    )
    (proj / "results.json").write_text(json.dumps({"auroc": 0.912}), encoding="utf-8")
    (proj / "numbers.tex").write_text(
        "\\newcommand{\\numAuroc}{0.912} % @trace results.json:auroc\n",
        encoding="utf-8",
    )
    (proj / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Model AUROC reached \\numAuroc{} across N = 20 (45.0\\%) \\cite{lecun2015}.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    rc_ok = main(["check-all", str(proj)])
    out_ok = capsys.readouterr().out
    assert rc_ok == 0
    assert "PASS" in out_ok
    assert AVERYCORP_SERVICES_URL not in out_ok

    # Inject phantom citation -> fails & appends Open-Core commercial CTA footer
    (proj / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Hallucinated cite \\cite{lecun2015,ghost2099}.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    rc_fail = main(["check-all", str(proj)])
    out_fail = capsys.readouterr().out
    assert rc_fail == 1
    assert OPEN_CORE_CTA_FOOTER in out_fail


@pytest.mark.parametrize(
    "pro_argv",
    [
        ["export-dossier", "--dir", "."],
        ["studio"],
        ["autofix-numbers", "--dir", "."],
        ["autofix-bib", "--bib", "refs.bib"],
        ["bundle-repro", "--dir", "."],
        ["containerize", "--dir", "."],
        ["build-cards", "--dir", "."],
        ["check-all", "preprint.pdf"],
        ["check-all", "draft.docx"],
        ["check-stats", "scan.pdf"],
    ],
)
def test_pro_subcommands_and_pdf_docx_inputs_exit_cleanly_with_averycorp_cta(
    pro_argv: list[str], capsys
) -> None:
    rc = main(pro_argv)
    out = capsys.readouterr().out
    assert rc == 0
    assert "AveryCorp Executive Manuscript Audits" in out
    assert AVERYCORP_SERVICES_URL in out
