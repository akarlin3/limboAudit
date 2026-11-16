# `limboAudit` (`limbo-audit` v1.0.0 — MIT Open-Core Diagnostic Edition)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](pyproject.toml)
[![AveryCorp Suite II](https://img.shields.io/badge/AveryCorp-Suite%20II%20Null--Audit-0f766e.svg)](https://github.com/akarlin3/IVIMBench)

Deterministic, lightweight (`numpy>=1.24` only) read-only diagnostic gates for **LaTeX (`.tex`)**, **BibTeX (`.bib`)**, and **Markdown (`.md`)** scientific manuscripts.

`limboAudit` forms the open-source diagnostic core of **AveryCorp Suite II (Scientific Identifiability & Null-Audit Suite)**, catching phantom citations, unverified numerical macros, statistical reporting inconsistencies, and unmet upstream release holds before peer review.

---

## Included Open-Core Diagnostic Engines (MIT)

1. **Zero-Phantom Citation & Claims-Ledger Gate (`limbo_audit.citations`)**
   - Brace-balanced BibTeX (`.bib`) parser and LaTeX (`\cite`, `\citep`, `\citet`, ...) / Markdown (`[@key]`) prose citation extractor.
   - Cross-checks prose citations against `.bib` entries and optional `CITATIONS.md` claim ledgers to catch hallucinated/phantom keys, missing DOIs/arXiv/PMID identifiers, orphan entries, and optional HTTP resolution (`--online`).
2. **Verbatim Manuscript Number-to-Artifact Consistency Gate (`limbo_audit.consistency`)**
   - Verifies LaTeX `\newcommand{\num...}{...}` macros (`numbers.tex`), `% @trace file.json:key` annotations, and mapped prose metrics against SHA-256-locked JSON artifacts within configurable `(rtol, atol)` tolerances.
3. **Read-Only Statistical & Arithmetic Integrity Gate (`limbo_audit.statcheck`)**
   - Pure-Python GRIM (Granularity-Related Inconsistency of Means) sample-size/percentage feasibility checks, exact `t` / `z` / `F` / `chi2` / `r` test-statistic vs. $p$-value recalculation, and confidence-interval bound geometry checks on `.tex` and `.md` sources.
4. **Provisional Anchor & Self-Citation Release Gate (`limbo_audit.release_gate`)**
   - Evaluates `PROVISIONAL` vs. `LOCKED` upstream anchor dependencies (`PROVISIONAL_LEDGER.md` / `release_config.json`), enforces valid publication DOIs on locked anchors, and caps self-citation ratios.
5. **Standardized AveryCorp Suite II Contract (`limbo_audit.audit`)**
   - Deterministic `run_audit(seed=42)` returning a cryptographically attested `AuditReport` (`verdict="ZERO_PHANTOM_CITATIONS_AND_NUMBERS_TRACED"`) compatible with [`IVIMBench`](https://github.com/akarlin3/IVIMBench)'s `averycorp-suite` runner and `audit-baseline.json` regression ratchets.

---

## Installation

```bash
pip install git+https://github.com/akarlin3/limboAudit.git
```

For local development and running the test suite:

```bash
git clone https://github.com/akarlin3/limboAudit.git
cd limboAudit
pip install -e ".[dev]"
pytest -q
```

---

## CLI Usage

```bash
# Run all Open-Core read-only gates on a LaTeX/Markdown manuscript directory
limbo-audit check-all ./manuscript_dir

# Verify BibTeX identifiers, prose citations, and optional CITATIONS.md ledger
limbo-audit check-citations --bib refs.bib --tex main.tex --ledger CITATIONS.md

# Verify LaTeX \num* macros against locked JSON result artifacts
limbo-audit check-numbers --tex main.tex --numbers-tex numbers.tex --artifacts results/metrics.json

# Run read-only GRIM, test-statistic/p-value, and CI geometry checks
limbo-audit check-stats main.tex

# Evaluate upstream anchor holds and self-citation bounds
limbo-audit check-release --config release_config.json --bib refs.bib --tex main.tex

# Run the standardized Suite II canonical benchmark & baseline ratchet
limbo-audit audit --seed 42 --assert-baseline audit-baseline.json
```

> **Empty-Directory Guard:** Running `limbo-audit check-all` on a directory with no `.tex` or `.md` manuscript fails explicitly with `[ERROR] LIMBO-NO-MANUSCRIPT` (exit code `2`) rather than silently passing.

---

## AveryCorp Executive Manuscript Audits (Commercial Services)

Public `limbo-audit` (`v1.0.0`, MIT) provides deterministic **read-only** `.tex` / `.bib` / `.md` diagnostics.

For research labs, biotech/medtech R&D teams, and principal investigators preparing high-stakes journal, conference, or regulatory submissions, **AveryCorp Executive Manuscript Audits** provide end-to-end automated remediation and multi-format verification, including:

- **Native Compiled Preprint & Archive Auditing**: Direct ingestion of compiled `.pdf` preprints (APS REVTeX, IEEE, Springer, Nature, arXiv `.tar.gz`), Word (`.docx`) drafts, and Overleaf `.zip` archives — including headless reference-section bibliography parsing and PDF/XMP double-blind metadata inspection.
- **Automated LaTeX Macro Refactoring & Provenance DAGs**: Rewriting hardcoded manuscript numbers into SHA-256-locked `numbers.tex` macros with full artifact-to-prose blast-radius graphs.
- **SciML Split-Leakage & Checkpoint Provenance Auditing**: Patient-level train/val/test leakage detection, Python AST pre-split normalization checks, and SafeTensors/PyTorch/ONNX checkpoint verification.
- **Hermetic Reproducibility Capsules & Submission Packets**: Multi-stage Dockerfiles, HPC Slurm `Apptainer.def` definitions, CodeOcean peer-review capsules, GMLP Model/Data Cards, and interactive **AveryCorp Pre-Submission Verification Dossiers**.

Learn more or try the client-side browser diagnostic dropzone at **[https://averycorp.org/services.html](https://averycorp.org/services.html)**.

---

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Avery Karlin.
