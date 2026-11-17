# `limboAudit` (`limbo-audit` v2.0.0 — MIT Open-Core Diagnostic Edition)

[![PyPI](https://img.shields.io/pypi/v/limbo-audit.svg)](https://pypi.org/project/limbo-audit/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/limbo-audit.svg)](https://pypi.org/project/limbo-audit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](pyproject.toml)
[![AveryCorp Suite II](https://img.shields.io/badge/AveryCorp-Suite%20II%20Null--Audit-0f766e.svg)](https://github.com/akarlin3/IVIMBench)

Deterministic, lightweight (`numpy>=1.24` only) read-only diagnostic gates for **LaTeX (`.tex`)**, **BibTeX (`.bib`)**, and **Markdown (`.md`)** scientific manuscripts.

`limboAudit` forms the open-source diagnostic core of **AveryCorp Suite II (Scientific Identifiability & Null-Audit Suite)**, catching phantom citations, unverified numerical macros, statistical reporting inconsistencies, and unmet upstream release holds before peer review.

---

## Use as a 10-Second GitHub Action in Your Lab Repository

Add `.github/workflows/manuscript-audit.yml`:

```yaml
name: Manuscript Audit
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: akarlin3/limboAudit@v2
```

Every run writes a readiness score, an engine breakdown (citations & DOIs, GRIM/p-values, number-to-artifact traceability, preprint upgrades, figure provenance) and the top 5 findings to the **Job Summary**, plus a SARIF log (`limbo-audit.sarif`). By default it only reports and warns. Set `fail-on-error: 'true'` to block merges, and `profile: strict` to fail on warnings too. Other inputs: `target-dir`, `tex-file`, `bib-file`, `artifacts-json`, `sarif-output`. Outputs: `readiness-score`, `status`, `total-findings`, `sarif-path`.

The same report is available locally with `pip install limbo-audit && limbo-audit ci-summary .`

For full-turnaround audit sprints and University P-card retainers, see **[averycorp.org/services.html](https://averycorp.org/services.html)**.

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
pip install limbo-audit
# or the latest main branch:
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

# GitHub Job Summary Markdown + SARIF + step outputs (used by the GitHub Action)
limbo-audit ci-summary . --sarif-output limbo-audit.sarif

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

# Build the 1-click Overleaf bookmarklet + Chrome Web Store zip (see below)
limbo-audit export-bookmarklet
```

> **Empty-Directory Guard:** Running `limbo-audit check-all` on a directory with no `.tex` or `.md` manuscript fails explicitly with `[ERROR] LIMBO-NO-MANUSCRIPT` (exit code `2`) rather than silently passing.

---

## limboAudit for Overleaf & arXiv (Chrome Extension + 1-Click Bookmarklet)

Audit the `.tex` / `.bib` file you are editing in Overleaf in one click, with **zero install of Python, zero server upload and zero LLM training**: the scanner (`extensions/overleaf-chrome/scanner.js`) runs deterministically inside your own browser tab, typically in well under 50 ms.

| Check | What it flags |
| --- | --- |
| **Untraced Numbers & Fragile Stats** | Hardcoded `p = …`, `r = …`, `±` / `\pm`, `\%`, `N = …` outside `numbers.tex` macros; borderline `p = 0.04x`; thresholded `p < .05`; GRIM-impossible means (e.g. `M = 5.19` with `N = 28`) |
| **Citation & DOI Hygiene** | Empty `\cite{}`, `\cite{?}` / `TODO` keys, literal `[?]`; `.bib` `@article`/`@inproceedings` without `doi =`; duplicate keys; stale arXiv/bioRxiv/medRxiv preprints |
| **Figure/Table & Anonymization Leaks** | `\ref{…}` with no matching `\label`, literal `??`, `/Users/…`, `/home/…`, `C:\Users\…` path leaks (including inside `%` comments, which arXiv still ships), unpinned random seeds |
| **Target-Venue Word Count** | Live abstract word count against MRM (250), Nature (150) and PLOS ONE (300) defaults |

The `🛡️ limboAudit: [Score]/100` pill sits in the Overleaf toolbar; clicking it opens a navy/gold slide-over drawer with line-numbered findings (click to jump to the line) and three actions: the **⚡ $19 Instant Auto-Fix Macro & BibTeX Pack**, the **🏛️ $650 48h Executive Audit & Referee #2 Dossier**, and **📧 Copy P-Card Quote + NIH DMS Memo for My PI** (a pre-filled email citing 2 CFR § 200.320 and NIH NOT-OD-21-013, copied to your clipboard).

> Venue word limits are built-in defaults; always confirm against the journal's current author guidelines.

### Option A: Chrome Extension (Manifest V3)

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → select `extensions/overleaf-chrome/`.
2. Open an Overleaf project (or an arXiv abstract page). The pill appears in the toolbar; the popup also scans pasted text.

Permissions: `activeTab`, `scripting`, `storage` (venue preference only); hosts: `https://www.overleaf.com/*`, `https://arxiv.org/*`. A tiny MAIN-world bridge (`bridge.js`) reads the full CodeMirror 6 document, so findings cover the whole file rather than just the visible lines.

### Option B: 1-Click Overleaf Audit Bookmarklet (no Chrome Web Store needed)

```bash
# Compile the scanner into a javascript:(function(){...})(); bookmarklet + install page,
# and package the extension as a ready-to-upload Chrome Web Store bundle
limbo-audit export-bookmarklet --out-html overleaf_bookmarklet.html --package-zip overleaf_extension.zip

# Options: --print-uri (print the javascript: URI), --json, --extension-dir PATH,
#          --out-html "" / --package-zip "" to skip an output
```

Open `overleaf_bookmarklet.html`, drag the gold **🛡️ limboAudit Overleaf** button to your bookmarks bar, then click it in any Overleaf project. Both outputs are byte-for-byte deterministic. The same install page can be embedded on `averycorp.org/services.html`.

---

## AveryCorp Executive Manuscript Audits (Commercial Services)

Public `limbo-audit` (`v2.0.0`, MIT) provides deterministic **read-only** `.tex` / `.bib` / `.md` diagnostics.

For research labs, biotech/medtech R&D teams, and principal investigators preparing high-stakes journal, conference, or regulatory submissions, **AveryCorp Executive Manuscript Audits** provide end-to-end automated remediation and multi-format verification, including:

- **Native Compiled Preprint & Archive Auditing**: Direct ingestion of compiled `.pdf` preprints (APS REVTeX, IEEE, Springer, Nature, arXiv `.tar.gz`), Word (`.docx`) drafts, and Overleaf `.zip` archives — including headless reference-section bibliography parsing and PDF/XMP double-blind metadata inspection.
- **Automated LaTeX Macro Refactoring & Provenance DAGs**: Rewriting hardcoded manuscript numbers into SHA-256-locked `numbers.tex` macros with full artifact-to-prose blast-radius graphs.
- **SciML Split-Leakage & Checkpoint Provenance Auditing**: Patient-level train/val/test leakage detection, Python AST pre-split normalization checks, and SafeTensors/PyTorch/ONNX checkpoint verification.
- **Hermetic Reproducibility Capsules & Submission Packets**: Multi-stage Dockerfiles, HPC Slurm `Apptainer.def` definitions, CodeOcean peer-review capsules, GMLP Model/Data Cards, and interactive **AveryCorp Pre-Submission Verification Dossiers**.

Learn more or try the client-side browser diagnostic dropzone at **[https://averycorp.org/services.html](https://averycorp.org/services.html)**.

---

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Avery Karlin.
