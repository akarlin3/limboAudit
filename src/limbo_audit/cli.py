"""Command-line interface for ``limbo-audit`` (MIT Open-Core Edition)."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .audit import PACKAGE_VERSION, assert_baseline, run_audit, write_baseline
from .bookmarklet import build_bookmarklet, package_extension_zip, render_bookmarklet_html
from .citations import audit_citations, extract_prose_citations
from .consistency import (
    audit_numerical_consistency,
    parse_inline_trace_annotations,
    parse_latex_macros,
)
from .fixtures import evaluate_canonical_and_adversarial
from .release_gate import evaluate_release_gate, parse_provisional_ledger
from .statcheck import audit_stat_consistency

AVERYCORP_SERVICES_URL = "https://averycorp.org/services.html"

OPEN_CORE_CTA_FOOTER = (
    "Need automated macro refactoring, PDF/DOCX preprint auditing, or an AveryCorp "
    f"Pre-Submission Verification Dossier? Visit {AVERYCORP_SERVICES_URL}"
)

PRO_SUBCOMMANDS: dict[str, str] = {
    "export-dossier": "Executive Pre-Submission Verification Dossier & Print-Ready PDF Certificate",
    "studio": "Interactive Local Web Studio GUI",
    "autofix-numbers": "Automated LaTeX Macro Refactoring & Provenance Rewriting",
    "autofix-bib": "Automated BibTeX DOI/Crossref Resolution & Claims-Ledger Generation",
    "bundle-repro": "Automated Reproducibility Bundle Synthesis",
    "containerize": "Hermetic Docker, HPC Apptainer & CodeOcean Capsule Generation",
    "build-cards": "Automated GMLP Model Cards, Data Cards & Zenodo Archive Metadata",
    "simulate-referee": "Reviewer #2 Statistical Fragility & Desk-Reject Simulation",
    "build-revision": "Automated LaTeX Revision Diff & Point-by-Point Rebuttal Matrix",
    "rescue-notebooks": "Jupyter Notebook Determinism Rescue & Script Extraction",
    "submission-pack": "Journal Cover-Letter & Reporting-Checklist Submission Packet",
    "dag": "Artifact-to-Prose Provenance DAG & Blast-Radius Analysis",
    "check-blind": "Double-Blind Anonymization, Metadata Leak & Redaction Engine",
    "check-math": "Equation Symbol & Dimensional Consistency Engine",
    "check-code-sync": "Python AST-to-Prose Hyperparameter Synchronization Gate",
    "check-compliance": "EQUATOR/CLAIM/TRIPOD+AI/CONSORT Reporting Compliance Engine",
    "check-parity": "Abstract-Body-Table-Supplement Numerical Parity Engine",
    "check-figures": "Figure/Table Provenance & Axis/Caption Integrity Gate",
    "check-retractions": "Crossref/PubMed Retraction & Preprint-to-Journal Drift Gate",
    "check-rebuttal": "Reviewer Rebuttal Quote-Fidelity Verifier",
    "certify": "Journal Profile Reproducibility Certification",
    "verify-semantics": "Abstract-vs-Cited-Claim Semantic Drift Verifier",
    "check-portfolio": "Multi-Paper Lab Portfolio Contradiction & NIH RPPR Auditor",
    "traceability-matrix": "FDA GMLP / IEC 62304 Claim-to-Code Traceability Matrix",
    "install-hooks": "Pre-Commit & GitHub PR SARIF Bot Installer",
    "check-leakage": "Patient-Level Train/Val/Test Split-Leakage & AST Normalization Auditor",
    "check-models": "SafeTensors / PyTorch / ONNX Checkpoint Provenance Verifier",
    "monitor-org": "Lab-Organization Multi-Repo Compliance Monitor",
}

PRO_FILE_SUFFIXES: tuple[str, ...] = (
    ".pdf",
    ".docx",
    ".doc",
    ".zip",
    ".tar.gz",
    ".tgz",
)

_BOILERPLATE_MD_NAMES: frozenset[str] = frozenset(
    {
        "readme.md",
        "contributing.md",
        "changelog.md",
        "code_of_conduct.md",
        "security.md",
        "citations.md",
        "provisional_ledger.md",
        "license.md",
        "traceability_matrix.md",
        "model_card.md",
        "data_card.md",
    }
)

_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "build",
        "dist",
    }
)


def _safe_read_text(path: Path) -> str:
    """Read text with UTF-8-SIG -> CP1252 -> Latin-1 fallback for real-world LaTeX corpora."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _is_pro_document_arg(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    lower = token.lower()
    return any(lower.endswith(sfx) for sfx in PRO_FILE_SUFFIXES)


def _emit_pro_cta(
    *,
    feature_label: str,
    detail: str,
    as_json: bool = False,
) -> int:
    msg = (
        f"[AveryCorp Open-Core] {feature_label} is part of AveryCorp Executive Manuscript Audits.\n"
        f"  {detail}\n"
        f"  Public `limbo-audit` v{PACKAGE_VERSION} (MIT) provides deterministic read-only diagnostics "
        "for LaTeX (.tex), BibTeX (.bib), and Markdown (.md) manuscripts.\n"
        f"  Learn more or request an Executive Pre-Submission Verification Dossier at: {AVERYCORP_SERVICES_URL}"
    )
    if as_json:
        print(
            json.dumps(
                {
                    "package": "limbo-audit",
                    "version": PACKAGE_VERSION,
                    "edition": "open-core-mit",
                    "pro_feature_required": True,
                    "feature": feature_label,
                    "message": detail,
                    "service": "AveryCorp Executive Manuscript Audits",
                    "url": AVERYCORP_SERVICES_URL,
                },
                indent=2,
            )
        )
    else:
        print(msg)
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    report = run_audit(seed=int(args.seed))

    if args.write_baseline:
        write_baseline(report, args.write_baseline)

    baseline_ok = True
    drifts: list[str] = []
    if args.assert_baseline:
        baseline_ok, drifts = assert_baseline(report, args.assert_baseline)

    if args.json:
        print(report.to_json())
    elif args.markdown:
        print(report.to_markdown(), end="")
    else:
        print(report.summary_line())
        for k, v in report.metrics.items():
            print(f"  {k}: {v}")
        print(f"  input_sha256:  {report.attestation.input_sha256}")
        print(f"  report_sha256: {report.attestation.report_sha256}")
        if args.write_baseline:
            print(f"  wrote baseline -> {args.write_baseline}")
        if args.assert_baseline:
            print(
                f"  baseline ratchet ({args.assert_baseline}): {'PASS' if baseline_ok else 'FAIL'}"
            )

    if not baseline_ok:
        for d in drifts:
            print(f"BASELINE RATCHET FAIL: {d}", file=sys.stderr)
        return 1

    return 0 if report.status != "HALT" else 1


def _cmd_check_citations(args: argparse.Namespace) -> int:
    bib_path = Path(args.bib)
    if not bib_path.exists():
        print(f"ERROR: BibTeX file not found: {bib_path}", file=sys.stderr)
        return 2

    prose_chunks: list[str] = []
    for p_str in args.tex:
        if _is_pro_document_arg(p_str):
            return _emit_pro_cta(
                feature_label=f"Native {Path(p_str).suffix} Preprint & Reference-Section Ingestion",
                detail=(
                    f"Direct `{Path(p_str).name}` citation extraction without `.tex` source is delivered "
                    "through AveryCorp Executive Manuscript Audits."
                ),
                as_json=bool(args.json),
            )
        p = Path(p_str)
        if not p.exists():
            print(f"ERROR: Manuscript file not found: {p}", file=sys.stderr)
            return 2
        prose_chunks.append(_safe_read_text(p))

    ledger_text: str | None = None
    if args.ledger:
        lp = Path(args.ledger)
        if not lp.exists():
            print(f"ERROR: Claims ledger not found: {lp}", file=sys.stderr)
            return 2
        ledger_text = _safe_read_text(lp)

    result = audit_citations(
        bib_text=_safe_read_text(bib_path),
        prose_text="\n".join(prose_chunks),
        ledger_text=ledger_text,
        online=bool(args.online),
        check_unused=not bool(args.allow_unused),
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        ledger_info = " | ledger verified" if ledger_text is not None else ""
        online_info = " | online=ON" if args.online else ""
        print(
            f"{bib_path.name}: {len(result.bib_entries)} entries | "
            f"cited: {len(result.cited_keys)} | "
            f"id coverage: {100.0 * result.identifier_coverage:.1f}%{ledger_info}{online_info}"
        )
        if result.passed:
            print("PASS — zero phantom citations and 100% verified identifiers.")
        else:
            print(f"FAIL — {len(result.failures)} issue(s) detected:")
            for f in result.failures:
                print(f"  {f}")

    return 0 if result.passed else 1


def _load_artifacts_and_claims(
    tex_text: str,
    artifact_paths: Sequence[str],
    claims_path: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str] | None]:
    """Load artifact JSON files and infer/load claim mappings for ``check-numbers``."""
    artifacts: dict[str, Any] = {}
    bundled_claims: dict[str, Any] = {}
    bundled_digests: dict[str, str] | None = None

    for raw_p in artifact_paths:
        p = Path(raw_p)
        if p.is_dir():
            for child in sorted(p.glob("*.json")):
                if child.name in {"audit-baseline.json", "audit-lock.json", "claims.json", "release.json", "release_config.json"}:
                    continue
                loaded_child = json.loads(_safe_read_text(child))
                artifacts[child.name] = loaded_child
                artifacts[str(child)] = loaded_child
        else:
            loaded = json.loads(_safe_read_text(p))
            if (
                isinstance(loaded, dict)
                and "artifacts" in loaded
                and isinstance(loaded["artifacts"], dict)
                and ("claims" in loaded or "macros" in loaded)
            ):
                artifacts.update(loaded["artifacts"])
                bundled_claims.update(loaded.get("claims") or loaded.get("macros") or {})
                if isinstance(loaded.get("artifact_digests"), dict):
                    bundled_digests = dict(loaded["artifact_digests"])
            else:
                artifacts[p.name] = loaded
                if str(p) != p.name:
                    artifacts[str(p)] = loaded

    if claims_path:
        cp = Path(claims_path)
        claims_map: dict[str, Any] = json.loads(_safe_read_text(cp))
        return artifacts, claims_map, bundled_digests

    if bundled_claims:
        return artifacts, bundled_claims, bundled_digests

    inline_traces = parse_inline_trace_annotations(tex_text)
    if inline_traces:
        return artifacts, inline_traces, bundled_digests

    macros = parse_latex_macros(tex_text)
    inferred: dict[str, Any] = {}
    if len(artifact_paths) == 1:
        art_name = Path(artifact_paths[0]).name
        art_obj = artifacts.get(art_name, {})
        if isinstance(art_obj, dict):
            for m_name in macros:
                if m_name in art_obj:
                    inferred[m_name] = f"{art_name}:{m_name}"
                elif m_name.startswith("num") and m_name[3:] in art_obj:
                    inferred[m_name] = f"{art_name}:{m_name[3:]}"
            if not inferred:
                for k in art_obj:
                    inferred[k] = f"{art_name}:{k}"
    return artifacts, inferred, bundled_digests


def _cmd_check_numbers(args: argparse.Namespace) -> int:
    if _is_pro_document_arg(args.tex):
        return _emit_pro_cta(
            feature_label=f"Native {Path(args.tex).suffix} Numerical Claim Extraction",
            detail=(
                f"Direct numerical table/prose auditing on `{Path(args.tex).name}` is part of "
                "AveryCorp Executive Manuscript Audits."
            ),
            as_json=bool(args.json),
        )

    tex_chunks: list[str] = []
    if args.numbers_tex:
        np_path = Path(args.numbers_tex)
        if not np_path.exists():
            print(f"ERROR: numbers.tex file not found: {np_path}", file=sys.stderr)
            return 2
        tex_chunks.append(_safe_read_text(np_path))

    tex_path = Path(args.tex)
    if not tex_path.exists():
        print(f"ERROR: Manuscript file not found: {tex_path}", file=sys.stderr)
        return 2
    tex_chunks.append(_safe_read_text(tex_path))
    combined_tex = "\n".join(tex_chunks)

    for ap in args.artifacts:
        if not Path(ap).exists():
            print(f"ERROR: Artifact path not found: {ap}", file=sys.stderr)
            return 2
    if args.claims and not Path(args.claims).exists():
        print(f"ERROR: Claims mapping file not found: {args.claims}", file=sys.stderr)
        return 2

    artifacts, claims_map, digests = _load_artifacts_and_claims(
        combined_tex, args.artifacts, args.claims
    )
    result = audit_numerical_consistency(
        manuscript_text=combined_tex,
        macros_or_claims=claims_map,
        artifacts=artifacts,
        rtol=float(args.rtol),
        atol=float(args.atol),
        artifact_digests=digests,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(
            f"Consistency gate: verified {result.verified_claims}/{result.total_claims} claims "
            f"(traced ratio = {100.0 * result.traced_numbers_ratio:.1f}%)"
        )
        if result.passed:
            print("PASS — all manuscript numbers match locked artifacts within tolerance.")
        else:
            print(f"FAIL — {len(result.failures)} numerical consistency error(s):")
            for f in result.failures:
                print(f"  {f}")

    return 0 if result.passed else 1


def _cmd_check_stats(args: argparse.Namespace) -> int:
    raw_targets: list[str] = []
    if args.targets:
        raw_targets.extend(args.targets)
    if args.tex:
        raw_targets.extend(args.tex)
    if not raw_targets:
        print("ERROR: Supply at least one .tex or .md manuscript path.", file=sys.stderr)
        return 2

    chunks: list[str] = []
    for raw_t in raw_targets:
        if _is_pro_document_arg(raw_t):
            return _emit_pro_cta(
                feature_label=f"Native {Path(raw_t).suffix} Statistical & Table Extraction",
                detail=(
                    f"De-hyphenated PDF/DOCX statistical auditing for `{Path(raw_t).name}` is part of "
                    "AveryCorp Executive Manuscript Audits."
                ),
                as_json=bool(args.json),
            )
        p = Path(raw_t)
        if not p.exists():
            print(f"ERROR: Manuscript file not found: {p}", file=sys.stderr)
            return 2
        chunks.append(_safe_read_text(p))

    res = audit_stat_consistency("\n".join(chunks), alpha=float(args.alpha))
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(
            f"Statistical integrity gate: GRIM={res.grim_checks} | "
            f"test-stats={res.stat_tests_checked} | CIs={res.ci_checks}"
        )
        if res.passed:
            print("PASS — zero GRIM impossibilities, p-value mismatches, or inverted CIs.")
        else:
            print(f"FAIL — {len(res.failures)} statistical inconsistency issue(s):")
            for f in res.failures:
                print(f"  {f}")
    return 0 if res.passed else 1


def _cmd_check_release(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    bib_path = Path(args.bib)
    if not cfg_path.exists() or not bib_path.exists():
        missing = cfg_path if not cfg_path.exists() else bib_path
        print(f"ERROR: File not found: {missing}", file=sys.stderr)
        return 2

    if args.tex and _is_pro_document_arg(args.tex):
        return _emit_pro_cta(
            feature_label=f"Native {Path(args.tex).suffix} Release-Gate Ingestion",
            detail=(
                f"Direct `{Path(args.tex).name}` release-gate inspection is part of "
                "AveryCorp Executive Manuscript Audits."
            ),
            as_json=bool(args.json),
        )

    prose_text = _safe_read_text(Path(args.tex)) if args.tex else ""
    ledger_text = _safe_read_text(Path(args.ledger)) if args.ledger else None
    cit_res = audit_citations(
        _safe_read_text(bib_path),
        prose_text,
        ledger_text=ledger_text,
        check_unused=bool(args.tex),
    )
    rel_cfg = json.loads(_safe_read_text(cfg_path))
    rel_res = evaluate_release_gate(rel_cfg, cit_res)

    if args.write_marker:
        Path(args.write_marker).write_text(rel_res.format_hold_marker(), encoding="utf-8")

    if args.json:
        print(json.dumps(rel_res.to_dict(), indent=2))
    else:
        print(
            f"Release Gate: {rel_res.state} | self-citations: "
            f"{rel_res.self_citation_count}/{rel_res.total_references} "
            f"({100.0 * rel_res.self_citation_fraction:.1f}% <= {100.0 * rel_res.max_self_citation_fraction:.1f}%)"
        )
        if not rel_res.release_ready:
            for reason in rel_res.blocking_reasons:
                print(f"  {reason}")
    return 0 if rel_res.release_ready else 1


def _discover_open_core_files(root: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Return ``(manuscript_files, bib_files, pro_only_docs)`` under ``root``."""
    tex_files: list[Path] = []
    md_files: list[Path] = []
    bib_files: list[Path] = []
    pro_docs: list[Path] = []

    for p in sorted(root.rglob("*")):
        rel_parts = p.relative_to(root).parts
        if any(part in _EXCLUDED_DIRS or part.startswith(".") for part in rel_parts[:-1]):
            continue
        if not p.is_file():
            continue
        name_lc = p.name.lower()
        if any(name_lc.endswith(sfx) for sfx in PRO_FILE_SUFFIXES):
            pro_docs.append(p)
        elif name_lc.endswith(".tex"):
            tex_files.append(p)
        elif name_lc.endswith(".bib"):
            bib_files.append(p)
        elif name_lc.endswith(".md") and name_lc not in _BOILERPLATE_MD_NAMES:
            md_files.append(p)

    # Prefer prose .tex files over standalone numbers.tex if multiple .tex files exist
    prose_tex = [p for p in tex_files if p.name.lower() != "numbers.tex"]
    if prose_tex:
        manuscripts = tex_files
    elif tex_files:
        manuscripts = tex_files
    else:
        manuscripts = md_files

    return manuscripts, bib_files, pro_docs


def _emit_no_manuscript_error(target_resolved: Path, *, as_json: bool) -> int:
    msg = f"No .tex or .md manuscript found in {target_resolved}"
    diag = {
        "severity": "ERROR",
        "rule_id": "LIMBO-NO-MANUSCRIPT",
        "file": str(target_resolved),
        "line": 1,
        "message": msg,
    }
    if as_json:
        print(
            json.dumps(
                {
                    "passed": False,
                    "error_count": 1,
                    "warning_count": 0,
                    "diagnostics": [diag],
                    "cta_url": AVERYCORP_SERVICES_URL,
                },
                indent=2,
            )
        )
    else:
        print(f"FAIL — [ERROR] LIMBO-NO-MANUSCRIPT: {msg}")
        print(f"\n{OPEN_CORE_CTA_FOOTER}")
    return 2


def _cmd_check_all(args: argparse.Namespace) -> int:
    raw_target = args.file or args.target or args.dir or "."
    if _is_pro_document_arg(raw_target):
        return _emit_pro_cta(
            feature_label=f"Native {Path(raw_target).suffix} & Archive Preprint Auditing",
            detail=(
                f"Direct auditing of `{Path(raw_target).name}` (PDF/DOCX/Overleaf/arXiv archives, "
                "reference-section parsing, double-blind metadata inspection, and Executive Dossiers) "
                "is part of AveryCorp Executive Manuscript Audits."
            ),
            as_json=bool(args.json),
        )

    target_path = Path(raw_target).resolve()
    if not target_path.exists():
        return _emit_no_manuscript_error(target_path, as_json=bool(args.json))

    if target_path.is_file():
        if target_path.suffix.lower() not in {".tex", ".md"}:
            return _emit_no_manuscript_error(target_path, as_json=bool(args.json))
        project_dir = target_path.parent
        manuscript_files = [target_path]
        nums_candidate = project_dir / "numbers.tex"
        if nums_candidate.is_file() and nums_candidate != target_path:
            manuscript_files.append(nums_candidate)
        bib_files = sorted(project_dir.glob("*.bib"))
    else:
        project_dir = target_path
        manuscript_files, bib_files, pro_docs = _discover_open_core_files(project_dir)
        if not manuscript_files:
            if pro_docs:
                rel_names = ", ".join(p.name for p in pro_docs[:3])
                return _emit_pro_cta(
                    feature_label="Native PDF/DOCX & Archive Preprint Auditing",
                    detail=(
                        f"Detected `{rel_names}` in `{project_dir.name}`, with no `.tex` or `.md` source files. "
                        "Compiled PDF/DOCX preprint ingestion and Executive Verification Dossiers are "
                        "delivered through AveryCorp Executive Manuscript Audits."
                    ),
                    as_json=bool(args.json),
                )
            return _emit_no_manuscript_error(project_dir, as_json=bool(args.json))

    explicit_bibs = [Path(b) for b in (getattr(args, "bib", None) or []) if b]
    if explicit_bibs:
        bib_files = [b for b in explicit_bibs if b.is_file()]

    combined_prose = "\n".join(_safe_read_text(p) for p in manuscript_files)
    primary_file = manuscript_files[0].name
    diagnostics: list[dict[str, Any]] = []

    # 1. Citations Gate
    cit_summary: dict[str, Any] | None = None
    cited_in_prose = extract_prose_citations(combined_prose)
    if bib_files or cited_in_prose:
        bib_text = "\n".join(_safe_read_text(b) for b in bib_files)
        ledger_p = project_dir / "CITATIONS.md"
        ledger_text = _safe_read_text(ledger_p) if ledger_p.is_file() else None
        cit_res = audit_citations(
            bib_text=bib_text,
            prose_text=combined_prose,
            ledger_text=ledger_text,
            online=bool(args.online),
            check_unused=not bool(args.allow_unused),
        )
        cit_summary = cit_res.to_dict()
        for fail_msg in cit_res.failures:
            sev = "WARN" if fail_msg.startswith("[unused-bib-entry]") else "ERROR"
            diagnostics.append(
                {
                    "severity": sev,
                    "rule_id": "LIMBO-CITATION",
                    "file": bib_files[0].name if bib_files else primary_file,
                    "message": fail_msg,
                }
            )
    else:
        cit_res = None

    # 2. Numerical Consistency Gate
    con_summary: dict[str, Any] | None = None
    artifact_candidates: list[str] = []
    for sub_name in ("results", "artifacts", "outputs"):
        sub_p = project_dir / sub_name
        if sub_p.is_dir() and list(sub_p.glob("*.json")):
            artifact_candidates.append(str(sub_p))
    for top_json in sorted(project_dir.glob("*.json")):
        if top_json.name not in {
            "audit-baseline.json",
            "audit-lock.json",
            "claims.json",
            "release.json",
            "release_config.json",
            ".limbo-audit.json",
        }:
            artifact_candidates.append(str(top_json))
    for extra_art in getattr(args, "artifacts", None) or []:
        if extra_art and Path(extra_art).exists() and str(Path(extra_art)) not in artifact_candidates:
            artifact_candidates.append(str(Path(extra_art)))

    claims_p = project_dir / "claims.json"
    claims_arg = str(claims_p) if claims_p.is_file() else None
    inline_traces = parse_inline_trace_annotations(combined_prose)
    macros = parse_latex_macros(combined_prose)

    if (artifact_candidates and (claims_arg or inline_traces or macros)) or claims_arg or inline_traces:
        artifacts_map, claims_map, digests_map = _load_artifacts_and_claims(
            combined_prose, artifact_candidates, claims_arg
        )
        # Re-key relative subdir paths like `results/cp3.json`
        for sub_name in ("results", "artifacts", "outputs"):
            sub_p = project_dir / sub_name
            if sub_p.is_dir():
                for jf in sorted(sub_p.glob("*.json")):
                    rel_key = f"{sub_name}/{jf.name}"
                    if jf.name in artifacts_map and rel_key not in artifacts_map:
                        artifacts_map[rel_key] = artifacts_map[jf.name]

        if claims_map or any(k.startswith("num") for k in macros):
            con_res = audit_numerical_consistency(
                manuscript_text=combined_prose,
                macros_or_claims=claims_map,
                artifacts=artifacts_map,
                rtol=float(args.rtol),
                atol=float(args.atol),
                artifact_digests=digests_map,
            )
            con_summary = con_res.to_dict()
            for fail_msg in con_res.failures:
                diagnostics.append(
                    {
                        "severity": "ERROR",
                        "rule_id": "LIMBO-CONSISTENCY",
                        "file": primary_file,
                        "message": fail_msg,
                    }
                )

    # 3. Statistical Integrity Gate (GRIM, test-stat/p-value, CI bounds)
    stat_res = audit_stat_consistency(combined_prose, alpha=float(args.alpha))
    stat_summary = stat_res.to_dict()
    for finding in stat_res.findings:
        diagnostics.append(
            {
                "severity": finding.severity,
                "rule_id": f"LIMBO-STAT-{finding.code}",
                "file": primary_file,
                "line": finding.line_number,
                "message": finding.detail,
            }
        )

    # 4. Release & Self-Citation Gate
    rel_summary: dict[str, Any] | None = None
    rel_cfg_path = None
    for cand_name in ("release_config.json", "release.json"):
        cp = project_dir / cand_name
        if cp.is_file():
            rel_cfg_path = cp
            break
    prov_ledger_path = project_dir / "PROVISIONAL_LEDGER.md"
    if (rel_cfg_path is not None or prov_ledger_path.is_file()) and cit_res is not None:
        rel_cfg: dict[str, Any] = (
            json.loads(_safe_read_text(rel_cfg_path)) if rel_cfg_path is not None else {}
        )
        if prov_ledger_path.is_file() and "anchors" not in rel_cfg:
            rel_cfg["anchors"] = parse_provisional_ledger(_safe_read_text(prov_ledger_path))
        rel_res = evaluate_release_gate(rel_cfg, cit_res)
        rel_summary = rel_res.to_dict()
        if not rel_res.release_ready:
            for reason in rel_res.blocking_reasons:
                diagnostics.append(
                    {
                        "severity": "WARN",
                        "rule_id": "LIMBO-RELEASE-HOLD",
                        "file": rel_cfg_path.name if rel_cfg_path else "PROVISIONAL_LEDGER.md",
                        "message": reason,
                    }
                )

    error_count = sum(1 for d in diagnostics if d["severity"] == "ERROR")
    warning_count = sum(1 for d in diagnostics if d["severity"] == "WARN")
    passed = error_count == 0

    if args.json:
        payload: dict[str, Any] = {
            "passed": passed,
            "target": str(target_path),
            "manuscript_files": [str(p.relative_to(project_dir)) for p in manuscript_files],
            "error_count": error_count,
            "warning_count": warning_count,
            "diagnostics": diagnostics,
            "citations": cit_summary,
            "consistency": con_summary,
            "statcheck": stat_summary,
            "release_gate": rel_summary,
        }
        if error_count > 0 or warning_count > 0:
            payload["cta"] = OPEN_CORE_CTA_FOOTER
            payload["cta_url"] = AVERYCORP_SERVICES_URL
        print(json.dumps(payload, indent=2))
    else:
        verdict_label = "PASS" if (passed and warning_count == 0) else ("PASS (WITH WARNINGS)" if passed else "FAIL")
        print(
            f"limbo-audit check-all [{verdict_label}] | files={len(manuscript_files)} | "
            f"errors={error_count} | warnings={warning_count}"
        )
        for d in diagnostics:
            loc = f"{d['file']}:{d['line']}" if "line" in d else d["file"]
            print(f"  [{d['severity']}] {d['rule_id']} ({loc}): {d['message']}")
        if error_count > 0 or warning_count > 0:
            print(f"\n{OPEN_CORE_CTA_FOOTER}")

    return 0 if passed else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    seed = int(args.seed)
    report = run_audit(seed=seed)
    if args.json:
        print(report.to_json())
        return 0 if report.status != "HALT" else 1
    if args.markdown:
        print(report.to_markdown(), end="")
        return 0 if report.status != "HALT" else 1

    bundle = evaluate_canonical_and_adversarial(seed=seed)
    cit = bundle.citations_result
    con = bundle.consistency_result
    rel = bundle.release_result
    stat = bundle.statcheck_result

    print("=" * 88)
    print(
        f"limbo-audit v{PACKAGE_VERSION} (MIT Open-Core) | Citation, Traceability & Stat Diagnostic Gate (seed={seed})"
    )
    print("=" * 88)
    print(
        f"Engine 1 [Citations]    : {'PASS' if cit.passed else 'FAIL'} | "
        f"{len(cit.bib_entries)} verified refs | {len(cit.phantom_citations)} phantoms | "
        f"ID coverage = {100.0 * cit.identifier_coverage:.1f}%"
    )
    print(
        f"Engine 2 [Consistency]  : {'PASS' if con.passed else 'FAIL'} | "
        f"{con.verified_claims}/{con.total_claims} numbers traced | "
        f"{len(con.artifact_digests)} SHA-256 artifacts locked"
    )
    print(
        f"Engine 3 [StatCheck]    : {'PASS' if stat.passed else 'FAIL'} | "
        f"GRIM={stat.grim_checks} | test-stats={stat.stat_tests_checked} | CIs={stat.ci_checks}"
    )
    print(
        f"Engine 4 [Release Gate] : {rel.state} | "
        f"locked anchors = {len(rel.locked_anchors)} | "
        f"self-citations = {rel.self_citation_count}/{rel.total_references} "
        f"({100.0 * rel.self_citation_fraction:.1f}% <= {100.0 * rel.max_self_citation_fraction:.1f}%)"
    )
    print("-" * 88)
    print("Adversarial Epistemic Fault-Injection Traps:")
    for m in bundle.mutant_results:
        tag = "CAUGHT" if m.detected else "MISSED"
        print(f"  [{tag}] {m.mutant_id:<32} ({m.engine:<12}) -> {m.description}")
    print("-" * 88)
    print(f"Status & Verdict        : [{report.status}] {report.verdict}")
    print(f"Input SHA-256           : {report.attestation.input_sha256}")
    print(f"Report SHA-256          : {report.attestation.report_sha256}")
    print("=" * 88)
    return 0 if report.status != "HALT" else 1


def _cmd_export_bookmarklet(args: argparse.Namespace) -> int:
    ext_dir = Path(args.extension_dir) if args.extension_dir else None
    try:
        build = build_bookmarklet(ext_dir)
    except FileNotFoundError as exc:
        print(f"[ERROR] LIMBO-NO-EXTENSION: {exc}", file=sys.stderr)
        return 2
    summary: dict[str, Any] = {
        "bookmarklet_bytes": build.size_bytes,
        "bookmarklet_sha256": build.sha256,
        "out_html": None,
        "package_zip": None,
        "zip_files": [],
    }
    if args.out_html:
        out_html = Path(args.out_html)
        out_html.parent.mkdir(parents=True, exist_ok=True)
        out_html.write_text(render_bookmarklet_html(build), encoding="utf-8")
        summary["out_html"] = str(out_html)
    if args.package_zip:
        summary["zip_files"] = package_extension_zip(Path(args.package_zip), ext_dir)
        summary["package_zip"] = str(args.package_zip)
    if args.print_uri:
        summary["uri"] = build.uri

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    print("limbo-audit export-bookmarklet: 1-click Overleaf Audit Bookmarklet")
    print(f"  Bookmarklet: {build.size_bytes:,} bytes (sha256 {build.sha256[:16]})")
    if summary["out_html"]:
        print(f"  Install page: {summary['out_html']} (drag the gold button to your bookmarks bar)")
    if summary["package_zip"]:
        print(
            f"  Chrome Web Store bundle: {summary['package_zip']} ({len(summary['zip_files'])} files)"
        )
    if args.print_uri:
        print(build.uri)
    print(OPEN_CORE_CTA_FOOTER)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="limbo-audit",
        description=(
            "limbo-audit (MIT Open-Core): Deterministic LaTeX/BibTeX citation verification, "
            "manuscript number-to-artifact consistency, GRIM/p-value statistical checks, "
            "and provisional release-hold diagnostics."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PACKAGE_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser(
        "audit",
        help="Run the standardized Suite II epistemic hygiene audit and optional baseline ratchet.",
    )
    p_audit.add_argument("--seed", type=int, default=42, help="PCG64 seed (default: 42)")
    p_audit.add_argument(
        "--json", action="store_true", help="Emit machine-readable AuditReport JSON"
    )
    p_audit.add_argument(
        "--markdown",
        action="store_true",
        help="Emit GitHub Step Summary Markdown table",
    )
    p_audit.add_argument(
        "--write-baseline",
        type=str,
        default="",
        metavar="PATH",
        help="Write canonical AuditReport JSON baseline to PATH",
    )
    p_audit.add_argument(
        "--assert-baseline",
        type=str,
        default="",
        metavar="PATH",
        help="Verify non-regression against locked baseline JSON at PATH",
    )
    p_audit.set_defaults(func=_cmd_audit)

    p_cit = sub.add_parser(
        "check-citations",
        help="Verify .bib identifiers, prose citations (.tex/.md), and optional CITATIONS.md ledger.",
    )
    p_cit.add_argument("--bib", required=True, help="Path to BibTeX (.bib) file")
    p_cit.add_argument(
        "--tex",
        required=True,
        nargs="+",
        help="One or more LaTeX (.tex) or Markdown (.md) manuscript files",
    )
    p_cit.add_argument("--ledger", default="", help="Optional CITATIONS.md claims ledger")
    p_cit.add_argument(
        "--online",
        action="store_true",
        help="Probe doi.org / Crossref / export.arxiv.org over HTTP with backoff",
    )
    p_cit.add_argument(
        "--allow-unused",
        action="store_true",
        help="Allow .bib entries that are not cited in the supplied prose files",
    )
    p_cit.add_argument("--json", action="store_true", help="Emit JSON audit summary")
    p_cit.set_defaults(func=_cmd_check_citations)

    p_num = sub.add_parser(
        "check-numbers",
        help="Verify verbatim manuscript macros/numbers against seeded JSON artifacts.",
    )
    p_num.add_argument("--tex", required=True, help="Path to manuscript .tex/.md file")
    p_num.add_argument(
        "--artifacts",
        required=True,
        nargs="+",
        help="One or more JSON artifact files (or directory of JSON artifacts)",
    )
    p_num.add_argument("--claims", default="", help="Optional JSON claim-to-keypath mapping file")
    p_num.add_argument("--numbers-tex", default="", help="Optional separate numbers.tex macro file")
    p_num.add_argument(
        "--rtol", type=float, default=1e-4, help="Relative tolerance (default: 1e-4)"
    )
    p_num.add_argument(
        "--atol", type=float, default=1e-4, help="Absolute tolerance (default: 1e-4)"
    )
    p_num.add_argument("--json", action="store_true", help="Emit JSON consistency summary")
    p_num.set_defaults(func=_cmd_check_numbers)

    p_stat = sub.add_parser(
        "check-stats",
        help="Run read-only GRIM, test-statistic/p-value, and CI bound checks on .tex/.md files.",
    )
    p_stat.add_argument(
        "targets",
        nargs="*",
        help="LaTeX (.tex) or Markdown (.md) manuscript file(s)",
    )
    p_stat.add_argument(
        "--tex",
        "--file",
        dest="tex",
        nargs="+",
        default=[],
        help="LaTeX (.tex) or Markdown (.md) manuscript file(s)",
    )
    p_stat.add_argument(
        "--alpha", type=float, default=0.05, help="Decision threshold alpha (default: 0.05)"
    )
    p_stat.add_argument("--json", action="store_true", help="Emit JSON statcheck summary")
    p_stat.set_defaults(func=_cmd_check_stats)

    p_rel = sub.add_parser(
        "check-release",
        help="Evaluate provisional upstream anchor holds and CP0 self-citation distinctness bounds.",
    )
    p_rel.add_argument("--config", required=True, help="Path to release_config.json / release.json")
    p_rel.add_argument("--bib", required=True, help="Path to BibTeX (.bib) file")
    p_rel.add_argument("--tex", default="", help="Optional manuscript .tex/.md file")
    p_rel.add_argument("--ledger", default="", help="Optional CITATIONS.md file")
    p_rel.add_argument("--write-marker", default="", help="Optional path to write SUBMISSION_HOLD")
    p_rel.add_argument("--json", action="store_true", help="Emit JSON release-gate summary")
    p_rel.set_defaults(func=_cmd_check_release)

    p_all = sub.add_parser(
        "check-all",
        help="Run all Open-Core read-only gates (citations, numbers, statcheck, release) on a .tex/.md project.",
    )
    p_all.add_argument(
        "target",
        nargs="?",
        default="",
        help="Optional manuscript directory or .tex/.md file path",
    )
    p_all.add_argument("--dir", default="", help="Target manuscript directory (default: .)")
    p_all.add_argument("--file", default="", help="Direct .tex/.md manuscript file path")
    p_all.add_argument(
        "--online",
        action="store_true",
        help="Probe doi.org / Crossref / export.arxiv.org over HTTP",
    )
    p_all.add_argument(
        "--allow-unused",
        action="store_true",
        help="Allow uncited .bib entries without raising warnings",
    )
    p_all.add_argument(
        "--alpha", type=float, default=0.05, help="Significance threshold alpha (default: 0.05)"
    )
    p_all.add_argument("--rtol", type=float, default=1e-4, help="Relative numerical tolerance")
    p_all.add_argument("--atol", type=float, default=1e-4, help="Absolute numerical tolerance")
    p_all.add_argument(
        "--bib", nargs="+", default=[], help="Explicit .bib file(s) (overrides auto-discovery)"
    )
    p_all.add_argument(
        "--artifacts", nargs="+", default=[], help="Extra JSON artifact file(s) or directories"
    )
    p_all.add_argument("--json", action="store_true", help="Emit structured JSON summary")
    p_all.set_defaults(func=_cmd_check_all)

    from .ci_summary import register_ci_summary_parser

    register_ci_summary_parser(sub)

    p_demo = sub.add_parser(
        "demo",
        help="Run canonical 59-reference + 34-number benchmark and adversarial fault-trap demo.",
    )
    p_demo.add_argument("--seed", type=int, default=42, help="PCG64 seed (default: 42)")
    p_demo.add_argument("--json", action="store_true", help="Emit standardized AuditReport JSON")
    p_demo.add_argument("--markdown", action="store_true", help="Emit Markdown step summary")
    p_demo.set_defaults(func=_cmd_demo)

    p_bm = sub.add_parser(
        "export-bookmarklet",
        help="Compile the client-side Overleaf scanner into a 1-click bookmarklet and package the Chrome extension.",
    )
    p_bm.add_argument(
        "--out-html",
        default="overleaf_bookmarklet.html",
        help="Drag-to-bookmarks-bar install page (default: overleaf_bookmarklet.html; '' to skip)",
    )
    p_bm.add_argument(
        "--package-zip",
        default="overleaf_extension.zip",
        help="Chrome Web Store upload bundle (default: overleaf_extension.zip; '' to skip)",
    )
    p_bm.add_argument(
        "--extension-dir",
        default=None,
        help="Path to extensions/overleaf-chrome (default: auto-detected)",
    )
    p_bm.add_argument("--print-uri", action="store_true", help="Also print the javascript: URI")
    p_bm.add_argument("--json", action="store_true", help="Emit structured JSON summary")
    p_bm.set_defaults(func=_cmd_export_bookmarklet)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args_list

    if args_list:
        first = args_list[0]
        if first in PRO_SUBCOMMANDS:
            return _emit_pro_cta(
                feature_label=f"`limbo-audit {first}` ({PRO_SUBCOMMANDS[first]})",
                detail=(
                    f"`{first}` is an executive remediation and verification capability included in "
                    "AveryCorp Executive Manuscript Audits."
                ),
                as_json=as_json,
            )
        if "--dossier" in args_list:
            return _emit_pro_cta(
                feature_label="Executive Pre-Submission Verification Dossier (`--dossier`)",
                detail=(
                    "Interactive HTML & Print-Ready PDF Executive Verification Dossiers are delivered "
                    "through AveryCorp Executive Manuscript Audits."
                ),
                as_json=as_json,
            )
        # `export-bookmarklet --package-zip x.zip` writes (not ingests) a .zip archive.
        doc_args = [] if first == "export-bookmarklet" else args_list[1:]
        for tok in doc_args:
            if _is_pro_document_arg(tok):
                return _emit_pro_cta(
                    feature_label=f"Native `{Path(tok).suffix}` Preprint & Archive Ingestion",
                    detail=(
                        f"Direct auditing of `{Path(tok).name}` without `.tex` source is part of "
                        "AveryCorp Executive Manuscript Audits."
                    ),
                    as_json=as_json,
                )

    parser = build_parser()
    parsed = parser.parse_args(args_list)
    return int(parsed.func(parsed))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
