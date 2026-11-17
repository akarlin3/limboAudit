"""GitHub Actions Job Summary, SARIF, and step-output generator (``limbo-audit ci-summary``).

Wraps the read-only ``check-all`` gates with three lightweight offline scans
(preprint-only references, ``\\includegraphics`` figure provenance, and Jupyter
notebook execution hygiene), then renders:

* a GitHub-flavoured Markdown block for ``$GITHUB_STEP_SUMMARY``,
* a SARIF 2.1.0 log for GitHub code scanning, and
* ``key=value`` step outputs for ``$GITHUB_OUTPUT``.

Everything here is deterministic and offline; nothing is written outside the
paths the caller names.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audit import PACKAGE_VERSION
from .citations import parse_bibtex

AVERYCORP_SERVICES_URL = "https://averycorp.org/services.html"
SARIF_SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/akarlin3/limboAudit"

SUMMARY_HEADER_PREFIX = "🛡️ AveryCorp limboAudit Epistemic & Reproducibility Gate"

ENGINE_CITATIONS = "Citations & DOIs"
ENGINE_STATS = "Statistical Consistency (GRIM/p-values)"
ENGINE_TRACE = "Number-to-Artifact Traceability"
ENGINE_PREPRINT = "Preprint/Retraction Upgrades"
ENGINE_FIGURES = "Figure/Table Provenance"
ENGINE_ORDER: tuple[str, ...] = (
    ENGINE_CITATIONS,
    ENGINE_STATS,
    ENGINE_TRACE,
    ENGINE_PREPRINT,
    ENGINE_FIGURES,
)

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_ACTION = "ACTION NEEDED"
STATUS_NA = "N/A"

PROFILES: tuple[str, ...] = ("default", "strict", "lenient")

ERROR_PENALTY = 12
WARN_PENALTY = 4
MAX_TOP_FINDINGS = 5

COMMERCIAL_FOOTER = (
    "> **Need automated `numbers.tex` macro refactoring, a Simulated Referee #2 Pre-Review Memo, "
    "or a signed NIH/Journal Reproducibility Dossier?**\n"
    "> • **Instant Self-Serve Browser Fix-Pack ($19)** or **48h Full Executive Audit & Notebook "
    "Rescue ($650–$2,450, `<$2,500` University P-Card & NIH DMS NOT-OD-21-013 Compliant)**: "
    f"[averycorp.org/services.html]({AVERYCORP_SERVICES_URL})"
)

_SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist", ".ipynb_checkpoints"}
)
_NON_ARTIFACT_JSON = frozenset(
    {"audit-baseline.json", "audit-lock.json", "package.json", "package-lock.json", "tsconfig.json"}
)
_INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_GRAPHICS_EXTS: tuple[str, ...] = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")
_PREPRINT_VENUE_RE = re.compile(
    r"arxiv|biorxiv|medrxiv|chemrxiv|psyarxiv|ssrn|research\s*square|preprints\.org|osf\s*preprints",
    re.IGNORECASE,
)
_PREPRINT_DOI_RE = re.compile(r"^10\.(48550/|1101/20\d\d\.|2139/ssrn|21203/rs\.|31234/osf\.io)", re.I)
_CITEKEY_MSG_RE = re.compile(r"^\[(?P<tag>[\w-]+)\]\s+(?P<key>[^:\s]+):")


# --------------------------------------------------------------------------- scope


@dataclass(frozen=True)
class RepoScope:
    """File inventory and the auto-detected audit mode for a repository."""

    root: Path
    tex_files: tuple[Path, ...]
    md_files: tuple[Path, ...]
    bib_files: tuple[Path, ...]
    notebooks: tuple[Path, ...]
    json_artifacts: tuple[Path, ...]
    csv_artifacts: tuple[Path, ...]

    @property
    def mode(self) -> str:
        """``A`` manuscript-only, ``B`` + bibliography, ``C`` + data/notebook artifacts."""
        if self.notebooks or self.json_artifacts or self.csv_artifacts:
            return "C"
        if self.bib_files:
            return "B"
        return "A"

    @property
    def mode_label(self) -> str:
        return {
            "A": "Mode A — Manuscript-only",
            "B": "Mode B — Manuscript + Bibliography",
            "C": "Mode C — Full Artifact-Traceable Repository",
        }[self.mode]

    def to_dict(self) -> dict[str, Any]:
        def rel(paths: Sequence[Path]) -> list[str]:
            return [_relpath(p, self.root) for p in paths]

        return {
            "mode": self.mode,
            "mode_label": self.mode_label,
            "tex_files": rel(self.tex_files),
            "md_files": rel(self.md_files),
            "bib_files": rel(self.bib_files),
            "notebooks": rel(self.notebooks),
            "json_artifacts": rel(self.json_artifacts),
            "csv_artifacts": rel(self.csv_artifacts),
        }


def _relpath(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def detect_scope(root: Path | str) -> RepoScope:
    """Inventory ``.tex``/``.md``/``.bib``/``.ipynb``/JSON/CSV files under ``root``."""
    root_p = Path(root)
    buckets: dict[str, list[Path]] = {k: [] for k in ("tex", "md", "bib", "ipynb", "json", "csv")}
    if root_p.is_file():
        candidates = [root_p]
        root_p = root_p.parent
    else:
        candidates = sorted(root_p.rglob("*")) if root_p.is_dir() else []
    for p in candidates:
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root_p).parts[:-1]
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel_parts):
            continue
        suffix = p.suffix.lower()
        if suffix == ".md" and p.name.lower() in {"readme.md", "changelog.md", "contributing.md", "license.md"}:
            continue
        if suffix == ".json" and (p.name in _NON_ARTIFACT_JSON or p.name.startswith(".")):
            continue
        key = suffix.lstrip(".")
        if key in buckets:
            buckets[key].append(p)
    return RepoScope(
        root=root_p,
        tex_files=tuple(buckets["tex"]),
        md_files=tuple(buckets["md"]),
        bib_files=tuple(buckets["bib"]),
        notebooks=tuple(buckets["ipynb"]),
        json_artifacts=tuple(buckets["json"]),
        csv_artifacts=tuple(buckets["csv"]),
    )


# ------------------------------------------------------------------ offline scans


def scan_preprints(bib_files: Sequence[Path], root: Path) -> list[dict[str, Any]]:
    """Flag references cited only as preprints (candidate journal-version upgrades)."""
    findings: list[dict[str, Any]] = []
    for bib in bib_files:
        try:
            entries = parse_bibtex(bib.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # pragma: no cover - defensive; parse_bibtex is tolerant
            continue
        for key, entry in sorted(entries.items()):
            venue = " ".join(
                entry.fields.get(f, "")
                for f in ("journal", "booktitle", "howpublished", "publisher", "archiveprefix", "note")
            )
            doi = entry.fields.get("doi", "").strip().lower().removeprefix("https://doi.org/")
            is_preprint = (
                entry.identifier_kind == "arxiv"
                or bool(_PREPRINT_VENUE_RE.search(venue))
                or bool(doi and _PREPRINT_DOI_RE.match(doi))
            )
            has_journal_doi = bool(doi) and not _PREPRINT_DOI_RE.match(doi)
            if is_preprint and not has_journal_doi:
                findings.append(
                    {
                        "severity": "WARN",
                        "rule_id": "LIMBO-PREPRINT-UPGRADE",
                        "file": _relpath(bib, root),
                        "citekey": key,
                        "message": (
                            f"[preprint-only] {key}: cited as a preprint with no journal DOI — "
                            "check whether a peer-reviewed version (or retraction notice) now exists"
                        ),
                    }
                )
    return findings


def scan_figures(tex_files: Sequence[Path], root: Path) -> tuple[int, list[dict[str, Any]]]:
    """Return ``(figure_count, findings)`` for ``\\includegraphics`` targets missing on disk."""
    total = 0
    findings: list[dict[str, Any]] = []
    for tex in tex_files:
        text = tex.read_text(encoding="utf-8", errors="replace")
        graphics_dirs = [tex.parent]
        gp = re.search(r"\\graphicspath\s*\{((?:\{[^}]*\})+)\}", text)
        if gp:
            graphics_dirs += [tex.parent / d for d in re.findall(r"\{([^}]*)\}", gp.group(1))]
        for lineno, line in enumerate(text.splitlines(), start=1):
            code = re.split(r"(?<!\\)%", line, maxsplit=1)[0]
            for m in _INCLUDEGRAPHICS_RE.finditer(code):
                total += 1
                target = m.group(1).strip()
                if _figure_exists(target, graphics_dirs, root):
                    continue
                findings.append(
                    {
                        "severity": "ERROR",
                        "rule_id": "LIMBO-FIGURE-MISSING",
                        "file": _relpath(tex, root),
                        "line": lineno,
                        "message": (
                            f"[missing-figure] \\includegraphics{{{target}}} has no matching file "
                            "in the repository — figure provenance cannot be traced"
                        ),
                    }
                )
    return total, findings


def _figure_exists(target: str, dirs: Sequence[Path], root: Path) -> bool:
    for base in [*dirs, root]:
        cand = base / target
        if cand.is_file():
            return True
        if not cand.suffix and any(cand.with_suffix(ext).is_file() for ext in _GRAPHICS_EXTS):
            return True
    return False


def scan_notebooks(notebooks: Sequence[Path], root: Path) -> list[dict[str, Any]]:
    """Flag notebooks with stored error outputs or out-of-order execution counts."""
    findings: list[dict[str, Any]] = []
    for nb_path in notebooks:
        rel = _relpath(nb_path, root)
        try:
            nb = json.loads(nb_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            findings.append(
                {
                    "severity": "WARN",
                    "rule_id": "LIMBO-NOTEBOOK-INVALID",
                    "file": rel,
                    "message": f"[invalid-notebook] {rel}: not valid notebook JSON",
                }
            )
            continue
        counts: list[int] = []
        for idx, cell in enumerate(nb.get("cells", []) if isinstance(nb, dict) else [], start=1):
            if not isinstance(cell, dict) or cell.get("cell_type") != "code":
                continue
            if isinstance(cell.get("execution_count"), int):
                counts.append(cell["execution_count"])
            for out in cell.get("outputs", []) or []:
                if isinstance(out, dict) and out.get("output_type") == "error":
                    findings.append(
                        {
                            "severity": "WARN",
                            "rule_id": "LIMBO-NOTEBOOK-ERROR-OUTPUT",
                            "file": rel,
                            "message": (
                                f"[notebook-error] {rel} cell {idx}: stored "
                                f"{out.get('ename', 'error')} output — results may not regenerate"
                            ),
                        }
                    )
        if counts and counts != sorted(counts):
            findings.append(
                {
                    "severity": "WARN",
                    "rule_id": "LIMBO-NOTEBOOK-OUT-OF-ORDER",
                    "file": rel,
                    "message": (
                        f"[out-of-order] {rel}: cells were executed out of order "
                        f"({counts[:6]}{'…' if len(counts) > 6 else ''}) — rerun top-to-bottom"
                    ),
                }
            )
    return findings


# --------------------------------------------------------------- core run


@dataclass
class EngineRow:
    name: str
    status: str
    findings: int
    detail: str = ""


@dataclass
class CISummaryReport:
    """Aggregate result of ``limbo-audit ci-summary``."""

    score: int
    status: str
    profile: str
    scope: RepoScope
    engines: list[EngineRow]
    diagnostics: list[dict[str, Any]]
    check_all: dict[str, Any] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.get("severity") == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.get("severity") == "WARN")

    @property
    def total_findings(self) -> int:
        return len(self.diagnostics)

    def gate_failed(self) -> bool:
        """Whether a strict ``fail-on-error`` gate should fail this run."""
        if self.profile == "strict":
            return self.total_findings > 0
        return self.error_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "limbo-audit",
            "version": PACKAGE_VERSION,
            "readiness_score": self.score,
            "status": self.status,
            "profile": self.profile,
            "total_findings": self.total_findings,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "scope": self.scope.to_dict(),
            "engines": [
                {"name": e.name, "status": e.status, "findings": e.findings, "detail": e.detail}
                for e in self.engines
            ],
            "diagnostics": self.diagnostics,
            "cta_url": AVERYCORP_SERVICES_URL,
        }

    def to_markdown(self) -> str:
        return render_markdown(self)


def _run_check_all_json(argv: list[str]) -> dict[str, Any]:
    """Invoke ``check-all --json`` in-process and parse its stdout."""
    from .cli import main as cli_main  # local import: cli registers this module

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli_main(["check-all", *argv, "--json"])
    try:
        parsed = json.loads(buf.getvalue())
    except json.JSONDecodeError:
        return {"diagnostics": []}
    return parsed if isinstance(parsed, dict) else {"diagnostics": []}


def _engine_status(diags: Sequence[dict[str, Any]], applicable: bool) -> str:
    if not applicable and not diags:
        return STATUS_NA
    if any(d.get("severity") == "ERROR" for d in diags):
        return STATUS_ACTION
    if diags:
        return STATUS_WARN
    return STATUS_PASS


def compute_score(error_count: int, warning_count: int) -> int:
    return max(0, min(100, 100 - ERROR_PENALTY * error_count - WARN_PENALTY * warning_count))


def run_ci_summary(
    target_dir: str | Path = ".",
    *,
    tex_file: str | None = None,
    bib_file: str | None = None,
    artifacts_json: Sequence[str] | None = None,
    profile: str = "default",
) -> CISummaryReport:
    """Run every Open-Core gate plus offline scans and build a :class:`CISummaryReport`."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    root = Path(target_dir)
    scope = detect_scope(root)
    root = scope.root

    argv: list[str] = ["--file", str(Path(tex_file))] if tex_file else [str(root)]
    bib_files = list(scope.bib_files)
    if bib_file:
        argv += ["--bib", str(Path(bib_file))]
        bib_files = [Path(bib_file)] if Path(bib_file).is_file() else []
    arts = [a for a in (artifacts_json or []) if a]
    if arts:
        argv += ["--artifacts", *arts]
    if profile == "lenient":
        argv.append("--allow-unused")

    check_all = _run_check_all_json(argv)
    base_root = Path(tex_file).parent if tex_file else root
    diagnostics: list[dict[str, Any]] = []
    for d in check_all.get("diagnostics", []) or []:
        d = dict(d)
        if d.get("file") and not Path(d["file"]).is_absolute():
            d["file"] = _relpath(base_root / d["file"], root)
        elif d.get("file"):
            d["file"] = _relpath(Path(d["file"]), root)
        m = _CITEKEY_MSG_RE.match(str(d.get("message", "")))
        if m and d.get("rule_id") == "LIMBO-CITATION":
            d["citekey"] = m.group("key")
        diagnostics.append(d)

    tex_for_figs = [Path(tex_file)] if tex_file else list(scope.tex_files)
    preprint_diags = scan_preprints(bib_files, root)
    fig_count, fig_diags = scan_figures(tex_for_figs, root)
    nb_diags = scan_notebooks(scope.notebooks, root)
    if profile == "lenient":
        preprint_diags = []
    diagnostics += preprint_diags + fig_diags + nb_diags

    def bucket(prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
        return [d for d in diagnostics if str(d.get("rule_id", "")).startswith(prefixes)]

    cit = check_all.get("citations") or None
    con = check_all.get("consistency") or None
    stat = check_all.get("statcheck") or {}
    stat_checks = sum(int(stat.get(k, 0) or 0) for k in ("grim_checks", "stat_tests_checked", "ci_checks"))

    cit_d = bucket(("LIMBO-CITATION", "LIMBO-RELEASE", "LIMBO-NO-MANUSCRIPT"))
    stat_d = bucket(("LIMBO-STAT",))
    trace_d = bucket(("LIMBO-CONSISTENCY", "LIMBO-NOTEBOOK"))
    engines = [
        EngineRow(ENGINE_CITATIONS, _engine_status(cit_d, cit is not None), len(cit_d),
                  f"{len(bib_files)} .bib file(s)"),
        EngineRow(ENGINE_STATS, _engine_status(stat_d, stat_checks > 0), len(stat_d),
                  f"{stat_checks} check(s)"),
        EngineRow(ENGINE_TRACE, _engine_status(trace_d, con is not None or bool(scope.notebooks)),
                  len(trace_d), f"{len(scope.notebooks)} notebook(s)"),
        EngineRow(ENGINE_PREPRINT, _engine_status(preprint_diags, bool(bib_files)),
                  len(preprint_diags), "offline scan; live retraction check in Pro"),
        EngineRow(ENGINE_FIGURES, _engine_status(fig_diags, fig_count > 0), len(fig_diags),
                  f"{fig_count} figure(s)"),
    ]

    errors = sum(1 for d in diagnostics if d.get("severity") == "ERROR")
    warns = sum(1 for d in diagnostics if d.get("severity") == "WARN")
    score = compute_score(errors, warns)
    status = STATUS_ACTION if errors else (STATUS_WARN if warns else STATUS_PASS)
    return CISummaryReport(
        score=score,
        status=status,
        profile=profile,
        scope=scope,
        engines=engines,
        diagnostics=diagnostics,
        check_all=check_all,
    )


# --------------------------------------------------------------- renderers


_STATUS_ICON = {STATUS_PASS: "✅", STATUS_WARN: "⚠️", STATUS_ACTION: "❌", STATUS_NA: "➖"}


def _finding_location(d: dict[str, Any]) -> str:
    loc = str(d.get("file", "")) or "repository"
    if d.get("line"):
        loc = f"{loc}:{d['line']}"
    if d.get("citekey"):
        return f"`{loc}` · `{d['citekey']}`"
    return f"`{loc}`"


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: CISummaryReport) -> str:
    """Render the GitHub Job Summary Markdown block."""
    lines = [
        f"## {SUMMARY_HEADER_PREFIX} — Score: {report.score}/100 ({report.status})",
        "",
        f"_limbo-audit v{PACKAGE_VERSION} · {report.scope.mode_label} · profile `{report.profile}` · "
        f"{report.error_count} error(s), {report.warning_count} warning(s)_",
        "",
        "| Engine | Status | Findings |",
        "| --- | --- | ---: |",
    ]
    for e in report.engines:
        lines.append(f"| {e.name} | {_STATUS_ICON[e.status]} {e.status} | {e.findings} |")
    lines.append("")

    ranked = sorted(report.diagnostics, key=lambda d: 0 if d.get("severity") == "ERROR" else 1)
    if ranked:
        lines.append(f"### Top Findings ({min(len(ranked), MAX_TOP_FINDINGS)} of {len(ranked)})")
        lines.append("")
        for d in ranked[:MAX_TOP_FINDINGS]:
            lines.append(
                f"- **{d.get('severity', 'WARN')}** {_finding_location(d)} — "
                f"{_escape_md(str(d.get('message', '')))}"
            )
        lines.append("")
        lines.append(COMMERCIAL_FOOTER)
    else:
        lines.append("No findings — every applicable gate passed. 🎉")
        lines.append("")
        lines.append(
            f"<sub>Deterministic open-core gate by AveryCorp · "
            f"[averycorp.org/services.html]({AVERYCORP_SERVICES_URL})</sub>"
        )
    lines.append("")
    return "\n".join(lines)


def render_sarif(report: CISummaryReport, *, uri_base: Path | None = None) -> dict[str, Any]:
    """Render a SARIF 2.1.0 log suitable for ``github/codeql-action/upload-sarif``."""
    base = (uri_base or Path.cwd()).resolve()
    root = report.scope.root.resolve()
    rule_ids = sorted({str(d.get("rule_id", "LIMBO")) for d in report.diagnostics})
    results = []
    for d in report.diagnostics:
        file_rel = str(d.get("file", "")) or "."
        abs_p = (root / file_rel).resolve()
        try:
            uri = abs_p.relative_to(base).as_posix()
        except ValueError:
            uri = abs_p.as_posix()
        region: dict[str, Any] = {"startLine": int(d["line"])} if d.get("line") else {"startLine": 1}
        results.append(
            {
                "ruleId": str(d.get("rule_id", "LIMBO")),
                "level": "error" if d.get("severity") == "ERROR" else "warning",
                "message": {"text": str(d.get("message", ""))},
                "locations": [
                    {"physicalLocation": {"artifactLocation": {"uri": uri}, "region": region}}
                ],
            }
        )
    return {
        "$schema": SARIF_SCHEMA_URL,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "limbo-audit",
                        "version": PACKAGE_VERSION,
                        "informationUri": INFORMATION_URI,
                        "rules": [
                            {"id": rid, "shortDescription": {"text": rid}, "helpUri": AVERYCORP_SERVICES_URL}
                            for rid in rule_ids
                        ],
                    }
                },
                "results": results,
            }
        ],
    }


def write_github_outputs(report: CISummaryReport, sarif_path: str, output_file: str) -> None:
    with open(output_file, "a", encoding="utf-8") as fh:
        fh.write(f"readiness-score={report.score}\n")
        fh.write(f"status={report.status}\n")
        fh.write(f"total-findings={report.total_findings}\n")
        fh.write(f"sarif-path={sarif_path}\n")


# --------------------------------------------------------------- CLI


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cmd_ci_summary(args: argparse.Namespace) -> int:
    report = run_ci_summary(
        args.target or args.target_dir or ".",
        tex_file=args.tex_file or None,
        bib_file=args.bib_file or None,
        artifacts_json=args.artifacts_json or None,
        profile=args.profile,
    )
    markdown = report.to_markdown()

    sarif_path = args.sarif_output or ""
    if sarif_path:
        Path(sarif_path).write_text(json.dumps(render_sarif(report), indent=2) + "\n", encoding="utf-8")
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

    summary_file = args.summary_file or os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        write_github_outputs(report, sarif_path, output_file)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(markdown)

    if _truthy(args.fail_on_error) and report.gate_failed():
        return 1
    return 0


def register_ci_summary_parser(sub: Any) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "ci-summary",
        help="Run all gates and write a GitHub Job Summary, SARIF log, and step outputs.",
    )
    p.add_argument("target", nargs="?", default="", help="Repository/manuscript directory")
    p.add_argument("--target-dir", default=".", help="Repository/manuscript directory (default: .)")
    p.add_argument("--tex-file", default="", help="Explicit primary .tex/.md manuscript")
    p.add_argument("--bib-file", default="", help="Explicit .bib bibliography")
    p.add_argument("--artifacts-json", nargs="*", default=[], help="Extra JSON artifact file(s)")
    p.add_argument("--profile", choices=PROFILES, default="default", help="Gate profile")
    p.add_argument(
        "--fail-on-error",
        nargs="?",
        const="true",
        default="false",
        help="Exit 1 when the gate fails (strict profile: any finding). Default: false",
    )
    p.add_argument("--sarif-output", default="", help="Write SARIF 2.1.0 log to this path")
    p.add_argument("--json-output", default="", help="Write the JSON report to this path")
    p.add_argument(
        "--summary-file",
        default="",
        help="Append Markdown here (default: $GITHUB_STEP_SUMMARY when set)",
    )
    p.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    p.set_defaults(func=_cmd_ci_summary)
    return p
