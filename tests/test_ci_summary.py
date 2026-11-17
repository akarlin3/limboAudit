"""Tests for action.yml, the publish workflow, and ``limbo-audit ci-summary``."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from limbo_audit.ci_summary import (
    AVERYCORP_SERVICES_URL,
    ENGINE_ORDER,
    SUMMARY_HEADER_PREFIX,
    compute_score,
    detect_scope,
    render_sarif,
    run_ci_summary,
)
from limbo_audit.cli import main

REPO = Path(__file__).resolve().parent.parent
VALID_COLORS = {"white", "black", "yellow", "blue", "green", "orange", "red", "purple", "gray-dark"}


def _write_flagged_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "refs.bib").write_text(
        "@article{lecun2015, author={LeCun, Yann}, title={Deep learning}, journal={Nature},"
        " year={2015}, doi={10.1038/nature14539}}\n"
        "@misc{vaswani2017, author={Vaswani}, title={Attention}, year={2017},"
        " eprint={1706.03762}, archivePrefix={arXiv}}\n",
        encoding="utf-8",
    )
    (root / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Cite \\cite{lecun2015,vaswani2017,ghost2099}. We found t(28) = 2.20, p = .45.\n"
        "\\includegraphics[width=1in]{figs/roc}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (root / "analysis.ipynb").write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "execution_count": 3, "outputs": []},
                    {
                        "cell_type": "code",
                        "execution_count": 1,
                        "outputs": [{"output_type": "error", "ename": "KeyError"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def _write_clean_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "figs").mkdir()
    (root / "figs" / "roc.png").write_bytes(b"\x89PNG")
    (root / "refs.bib").write_text(
        "@article{lecun2015, author={LeCun, Yann}, title={Deep learning}, journal={Nature},"
        " year={2015}, doi={10.1038/nature14539}}\n",
        encoding="utf-8",
    )
    (root / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Deep learning \\cite{lecun2015}.\n\\includegraphics{figs/roc}\n\\end{document}\n",
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------- action.yml


def test_action_yml_schema_is_marketplace_ready() -> None:
    meta = yaml.safe_load((REPO / "action.yml").read_text(encoding="utf-8"))
    assert meta["name"].startswith("limboAudit")
    assert meta["author"] == "AveryCorp Institute"
    assert meta["description"]
    assert meta["branding"] == {"icon": "shield", "color": "blue"}
    assert meta["branding"]["color"] in VALID_COLORS

    inputs = meta["inputs"]
    assert set(inputs) == {
        "target-dir", "tex-file", "bib-file", "artifacts-json",
        "profile", "fail-on-error", "sarif-output",
    }
    assert inputs["target-dir"]["default"] == "."
    assert inputs["profile"]["default"] == "default"
    assert inputs["fail-on-error"]["default"] == "false"
    assert inputs["sarif-output"]["default"] == "limbo-audit.sarif"
    assert all("description" in v for v in inputs.values())

    outputs = meta["outputs"]
    assert set(outputs) == {"readiness-score", "status", "total-findings", "sarif-path"}
    for name, spec in outputs.items():
        assert spec["value"] == f"${{{{ steps.audit.outputs.{name} }}}}"

    runs = meta["runs"]
    assert runs["using"] == "composite"
    steps = runs["steps"]
    assert steps[0]["uses"].startswith("actions/setup-python@")
    assert steps[0]["with"]["python-version"] == "3.11"
    run_steps = [s for s in steps if "run" in s]
    assert all(s.get("shell") == "bash" for s in run_steps)
    assert any("github.action_path" in json.dumps(s) for s in run_steps)
    audit_step = next(s for s in steps if s.get("id") == "audit")
    assert "limbo-audit" in audit_step["run"] and "ci-summary" in audit_step["run"]
    # Inputs reach the shell only via env vars (no ${{ }} expression injection in `run`).
    assert "${{" not in audit_step["run"]


def test_publish_pypi_workflow_uses_oidc_trusted_publishing() -> None:
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "publish-pypi.yml").read_text())
    triggers = wf[True] if True in wf else wf["on"]  # PyYAML parses bare `on` as True
    assert triggers["release"]["types"] == ["published"]
    assert "workflow_dispatch" in triggers

    build = wf["jobs"]["build"]
    build_runs = "\n".join(s.get("run", "") for s in build["steps"])
    assert "python -m build" in build_runs and "twine check" in build_runs
    assert any(str(s.get("uses", "")).startswith("actions/upload-artifact@") for s in build["steps"])

    pub = wf["jobs"]["publish-pypi"]
    assert pub["needs"] == "build"
    assert pub["permissions"] == {"id-token": "write"}
    env = pub["environment"]
    assert (env["name"] if isinstance(env, dict) else env) == "pypi"
    uses = [s.get("uses", "") for s in pub["steps"]]
    assert "pypa/gh-action-pypi-publish@release/v1" in uses
    assert "password" not in json.dumps(pub)


# ---------------------------------------------------------------- ci_summary


def test_detect_scope_modes(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    (a / "main.tex").write_text("hi", encoding="utf-8")
    assert detect_scope(a).mode == "A"
    (a / "refs.bib").write_text("", encoding="utf-8")
    assert detect_scope(a).mode == "B"
    (a / "results.csv").write_text("x\n1\n", encoding="utf-8")
    assert detect_scope(a).mode == "C"


def test_compute_score_is_clamped() -> None:
    assert compute_score(0, 0) == 100
    assert compute_score(1, 1) == 84
    assert compute_score(50, 50) == 0


def test_flagged_project_markdown_table_findings_and_footer(tmp_path: Path) -> None:
    proj = _write_flagged_project(tmp_path / "paper")
    report = run_ci_summary(proj)
    md = report.to_markdown()

    assert md.startswith(f"## {SUMMARY_HEADER_PREFIX} — Score: {report.score}/100 (ACTION NEEDED)")
    assert report.status == "ACTION NEEDED"
    assert 0 <= report.score < 100
    for engine in ENGINE_ORDER:
        assert f"| {engine} |" in md
    statuses = {e.name: e.status for e in report.engines}
    assert statuses["Citations & DOIs"] == "ACTION NEEDED"
    assert statuses["Statistical Consistency (GRIM/p-values)"] == "ACTION NEEDED"
    assert statuses["Number-to-Artifact Traceability"] == "WARN"
    assert statuses["Preprint/Retraction Upgrades"] == "WARN"
    assert statuses["Figure/Table Provenance"] == "ACTION NEEDED"

    bullets = [ln for ln in md.splitlines() if ln.startswith("- **")]
    assert 1 <= len(bullets) <= 5
    assert "`refs.bib` · `ghost2099`" in md
    assert "`main.tex:4`" in md  # missing \includegraphics line
    assert "Instant Self-Serve Browser Fix-Pack ($19)" in md
    assert "NOT-OD-21-013" in md
    assert f"[averycorp.org/services.html]({AVERYCORP_SERVICES_URL})" in md


def test_clean_project_passes_without_commercial_footer(tmp_path: Path) -> None:
    report = run_ci_summary(_write_clean_project(tmp_path / "clean"))
    md = report.to_markdown()
    assert report.status == "PASS" and report.score == 100
    assert "Score: 100/100 (PASS)" in md
    assert "Fix-Pack" not in md
    assert {e.name: e.status for e in report.engines}["Number-to-Artifact Traceability"] == "N/A"


def test_sarif_is_valid_2_1_0(tmp_path: Path) -> None:
    proj = _write_flagged_project(tmp_path / "paper")
    report = run_ci_summary(proj)
    sarif = render_sarif(report, uri_base=tmp_path)
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "limbo-audit"
    assert len(run["results"]) == report.total_findings
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    for res in run["results"]:
        assert res["ruleId"] in rule_ids
        assert res["level"] in {"error", "warning"}
        loc = res["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"].startswith("paper/")
        assert loc["region"]["startLine"] >= 1


def test_cli_writes_step_summary_outputs_and_sarif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    proj = _write_flagged_project(tmp_path / "paper")
    summary = tmp_path / "step_summary.md"
    summary.write_text("previous step\n", encoding="utf-8")
    outputs = tmp_path / "gh_output.txt"
    sarif = tmp_path / "limbo-audit.sarif"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.chdir(tmp_path)

    rc = main(["ci-summary", "--target-dir", str(proj), "--sarif-output", str(sarif)])
    capsys.readouterr()
    assert rc == 0  # fail-on-error defaults to false

    text = summary.read_text(encoding="utf-8")
    assert text.startswith("previous step\n")  # appended, not overwritten
    assert SUMMARY_HEADER_PREFIX in text

    kv = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
    assert kv["status"] == "ACTION NEEDED"
    assert 0 <= int(kv["readiness-score"]) < 100
    assert int(kv["total-findings"]) >= 5
    assert kv["sarif-path"] == str(sarif)
    assert json.loads(sarif.read_text())["version"] == "2.1.0"


def test_fail_on_error_and_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    flagged = _write_flagged_project(tmp_path / "paper")
    assert main(["ci-summary", str(flagged), "--fail-on-error", "true"]) == 1

    clean = _write_clean_project(tmp_path / "clean")
    assert main(["ci-summary", str(clean), "--fail-on-error", "true"]) == 0

    # strict: a warning-only project fails the gate; default does not.
    warn_only = tmp_path / "warn"
    warn_only.mkdir()
    (warn_only / "refs.bib").write_text(
        "@misc{v2017, title={Attention}, year={2017}, eprint={1706.03762}}\n", encoding="utf-8"
    )
    (warn_only / "main.tex").write_text("Text \\cite{v2017}.\n", encoding="utf-8")
    assert main(["ci-summary", str(warn_only), "--fail-on-error", "true"]) == 0
    assert (
        main(["ci-summary", str(warn_only), "--fail-on-error", "true", "--profile", "strict"]) == 1
    )
    assert run_ci_summary(warn_only, profile="lenient").status == "PASS"
    capsys.readouterr()


def test_explicit_tex_and_bib_inputs(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    proj = _write_clean_project(tmp_path / "clean")
    other_bib = tmp_path / "other.bib"
    other_bib.write_text(
        "@article{lecun2015, author={LeCun}, title={DL}, journal={Nature}, year={2015},"
        " doi={10.1038/nature14539}}\n",
        encoding="utf-8",
    )
    rc = main(
        ["ci-summary", "--tex-file", str(proj / "main.tex"), "--bib-file", str(other_bib), "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["status"] == "PASS"
    assert payload["cta_url"] == AVERYCORP_SERVICES_URL
