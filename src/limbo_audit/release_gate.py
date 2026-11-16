"""Engine 3 — Provisional Ledger & Distinctness / Release Gate.

Generalizes ``Augur/release_gate.py``, ``Augur/PROVISIONAL_LEDGER.md``,
``Matrix/release_gate.py``, and ``Limbo/ASSUMPTIONS.md``:
- Evaluates upstream anchor holds (``PROVISIONAL`` vs. ``LOCKED`` anchors and
  ``published=True`` + verified DOI anti-fabrication guards).
- Enforces the ``Limbo`` CP0 independent field-review distinctness gate (capping author
  self-citation fraction at e.g. ``<= 15%`` and optionally forbidding ``@unpublished``
  entries in standalone reviews).
- Integrates ``CitationAuditResult`` status and emits ``SUBMISSION_HOLD`` markers.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .citations import CitationAuditResult, is_valid_identifier


@dataclass(frozen=True)
class ReleaseGateResult:
    """Diagnostic decision from ``evaluate_release_gate``."""

    release_ready: bool
    state: Literal["RELEASE", "HELD"]
    blocking_reasons: tuple[str, ...]
    unmet_anchors: tuple[str, ...]
    locked_anchors: tuple[str, ...]
    self_citation_count: int
    total_references: int
    self_citation_fraction: float
    max_self_citation_fraction: float
    citation_gate_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_ready": self.release_ready,
            "state": self.state,
            "blocking_reasons": list(self.blocking_reasons),
            "unmet_anchors": list(self.unmet_anchors),
            "locked_anchors": list(self.locked_anchors),
            "self_citation_count": self.self_citation_count,
            "total_references": self.total_references,
            "self_citation_fraction": round(float(self.self_citation_fraction), 6),
            "max_self_citation_fraction": round(float(self.max_self_citation_fraction), 6),
            "citation_gate_passed": self.citation_gate_passed,
        }

    def format_hold_marker(self) -> str:
        """Render deterministic ``SUBMISSION_HOLD`` marker text matching Augur/Matrix conventions."""
        if self.release_ready:
            return (
                "SUBMISSION_HOLD: CLEAR\n"
                "All load-bearing upstream anchors are LOCKED/published, citation verification "
                "passed, and self-citation distinctness bounds hold.\n"
            )
        lines = [
            "SUBMISSION_HOLD: ACTIVE",
            "HELD -- release gate blocked by unmet epistemic or publication conditions.",
            f"Unmet anchors: {', '.join(self.unmet_anchors) if self.unmet_anchors else 'none'}.",
            "Blocking reasons:",
        ]
        for reason in self.blocking_reasons:
            lines.append(f"  - {reason}")
        return "\n".join(lines) + "\n"


def parse_provisional_ledger(ledger_markdown: str) -> dict[str, dict[str, Any]]:
    """Parse ``PROVISIONAL_LEDGER.md`` Markdown tables/checklists into an ``anchors`` dictionary."""
    anchors: dict[str, dict[str, Any]] = {}
    for raw_line in ledger_markdown.splitlines():
        line = raw_line.strip()
        # Checklist item e.g. "- [ ] **Fashion accepted** -> ..." or "- [x] **Gauge accepted**"
        cm = re.match(r"^-\s*\[([ xX])\]\s*\*\*([^*]+)\*\*(.*)$", line)
        if cm:
            checked = cm.group(1).lower() == "x"
            raw_title = cm.group(2).strip()
            rest = cm.group(3).strip()
            if "accepted" in raw_title.lower() or "published" in raw_title.lower():
                name = raw_title.split()[0].upper()
                recommended = "recommended" in rest.lower()
                doi_match = re.search(r"(10\.\d{4,9}/[^\s\)\]`]+)", rest)
                doi_val = doi_match.group(1) if doi_match else None
                anchors[name] = {
                    "status": "LOCKED" if checked else "PROVISIONAL",
                    "published": checked,
                    "doi": doi_val,
                    "load_bearing": not recommended,
                }
            continue

        # Markdown table row with explicit PROVISIONAL / LOCKED status column
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 3 and not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                upper_cells = [c.upper().strip("*` ") for c in cells]
                if "PROVISIONAL" in upper_cells or "LOCKED" in upper_cells:
                    anchor_name = re.sub(r"[*`]", "", cells[0]).strip()
                    if anchor_name and anchor_name.lower() not in {"#", "anchor", "id"}:
                        is_locked = "LOCKED" in upper_cells
                        is_lb = any(c in {"YES", "TRUE", "LOAD-BEARING"} for c in upper_cells)
                        doi_val = None
                        for c in cells:
                            dm = re.search(r"(10\.\d{4,9}/[^\s\)\]`]+)", c)
                            if dm:
                                doi_val = dm.group(1)
                                break
                        anchors[anchor_name] = {
                            "status": "LOCKED" if is_locked else "PROVISIONAL",
                            "published": is_locked,
                            "doi": doi_val,
                            "load_bearing": is_lb,
                        }
    return anchors


def _count_self_citations(
    citations_result: CitationAuditResult,
    release_config: Mapping[str, Any],
) -> tuple[int, int, float]:
    """Compute ``(self_cite_count, total_bib_entries, self_cite_fraction)``."""
    entries = citations_result.bib_entries
    total = len(entries)
    if total == 0:
        return (0, 0, 0.0)

    explicit_keys = {str(k) for k in release_config.get("self_citation_keys", [])}
    author_patterns = [
        str(p).strip().lower()
        for p in release_config.get("author_patterns", [])
        if str(p).strip()
    ]

    matched_keys: set[str] = set()
    for key, entry in entries.items():
        if key in explicit_keys:
            matched_keys.add(key)
            continue
        author_field = entry.author.lower()
        if any(pat in author_field for pat in author_patterns):
            matched_keys.add(key)
            continue
        keywords_field = entry.fields.get("keywords", "").lower()
        if "self-citation" in keywords_field or "in-portfolio" in keywords_field:
            matched_keys.add(key)

    count = len(matched_keys)
    return (count, total, count / total)


def evaluate_release_gate(
    release_config: Mapping[str, Any],
    citations_result: CitationAuditResult,
) -> ReleaseGateResult:
    """Evaluate upstream provisional/locked anchors, citation integrity, and CP0 distinctness.

    Supports both ``anchors`` (``Augur/release_config.json`` + ``PROVISIONAL``/``LOCKED`` states)
    and ``conditions`` (``Matrix/release.json``) schemas, plus ``provisional_ledger_md`` inline
    Markdown parsing.
    """
    blocking_reasons: list[str] = []
    unmet_anchors: list[str] = []
    locked_anchors: list[str] = []

    merged_anchors: dict[str, dict[str, Any]] = {}
    if "provisional_ledger_md" in release_config and isinstance(
        release_config["provisional_ledger_md"], str
    ):
        merged_anchors.update(parse_provisional_ledger(release_config["provisional_ledger_md"]))

    raw_anchors = release_config.get("anchors", {})
    if isinstance(raw_anchors, Mapping):
        for name, cfg in raw_anchors.items():
            if isinstance(cfg, Mapping):
                merged_anchors[str(name)] = dict(cfg)

    raw_conditions = release_config.get("conditions", {})
    if isinstance(raw_conditions, Mapping):
        for cond_name, cfg in raw_conditions.items():
            if isinstance(cfg, Mapping):
                satisfied = bool(cfg.get("satisfied", False))
                merged_anchors[str(cond_name)] = {
                    "status": "LOCKED" if satisfied else "PROVISIONAL",
                    "published": satisfied,
                    "doi": cfg.get("doi"),
                    "load_bearing": bool(cfg.get("blocks_release", True)),
                    "requires_doi": bool(cfg.get("requires_doi", satisfied and "doi" in cfg)),
                }

    # 1. Evaluate upstream anchor holds and anti-fabrication DOI rules
    for name, a in merged_anchors.items():
        load_bearing = bool(a.get("load_bearing", a.get("blocks_release", True)))
        status_str = str(a.get("status", "")).strip().upper()
        has_pub_flag = "published" in a
        published_flag = bool(a.get("published", False))
        doi_raw = a.get("doi")
        doi_str = str(doi_raw).strip() if doi_raw is not None else ""
        requires_doi = bool(a.get("requires_doi", has_pub_flag))

        # Anti-fabrication guard: published=True (or requires_doi when LOCKED) must carry a valid DOI
        if published_flag and (not doi_str or not is_valid_identifier("doi", doi_str)):
            unmet_anchors.append(name)
            blocking_reasons.append(
                f"[invalid-anchor-doi] {name}: marked published=True without a valid DOI (got {doi_raw!r})"
            )
            continue

        is_provisional = status_str == "PROVISIONAL" or (has_pub_flag and not published_flag)
        if not has_pub_flag and status_str not in {"LOCKED", "SOLID", "PUBLISHED"} and status_str:
            is_provisional = True

        if requires_doi and not is_provisional and (
            not doi_str or not is_valid_identifier("doi", doi_str)
        ):
            unmet_anchors.append(name)
            blocking_reasons.append(
                f"[invalid-anchor-doi] {name}: status={status_str or 'LOCKED'} requires a valid DOI"
            )
            continue

        if is_provisional:
            if load_bearing:
                unmet_anchors.append(name)
                blocking_reasons.append(
                    f"[provisional-hold] {name}: load-bearing upstream anchor is PROVISIONAL/unpublished"
                )
        else:
            locked_anchors.append(name)

        if bool(a.get("provisional_numbers_in_spine", False)):
            blocking_reasons.append(
                f"[provisional-spine] {name}: imports provisional numbers into load-bearing manuscript spine"
            )

    # 2. Enforce zero-phantom citation gate status
    if not citations_result.passed:
        blocking_reasons.append(
            f"[citation-gate-failed] Citation audit reported {len(citations_result.failures)} failure(s)"
        )

    # 3. Optional standalone review guard against @unpublished BibTeX entries
    if bool(release_config.get("forbid_unpublished_bib", False)):
        unpub = sorted(
            k for k, e in citations_result.bib_entries.items() if e.entry_type == "unpublished"
        )
        if unpub:
            blocking_reasons.append(
                f"[unpublished-bib-entry] Standalone release forbids @unpublished entries: {', '.join(unpub)}"
            )

    # 4. Enforce CP0 distinctness self-citation fraction cap (default <= 0.15)
    max_self_frac = float(release_config.get("max_self_citation_fraction", 0.15))
    self_count, total_refs, self_frac = _count_self_citations(citations_result, release_config)
    enforce_self_cap = bool(
        release_config.get(
            "enforce_self_citation_cap",
            (
                str(release_config.get("document_type", "")).lower()
                in {"field_review", "review", "survey"}
                or "max_self_citation_fraction" in release_config
                or "author_patterns" in release_config
                or "self_citation_keys" in release_config
            ),
        )
    )
    if enforce_self_cap and self_frac > max_self_frac + 1e-12:
        blocking_reasons.append(
            f"[self-citation-cap-exceeded] Author self-citation fraction "
            f"{self_frac:.3f} ({self_count}/{total_refs}) exceeds cap {max_self_frac:.3f}"
        )

    release_ready = len(blocking_reasons) == 0
    return ReleaseGateResult(
        release_ready=release_ready,
        state="RELEASE" if release_ready else "HELD",
        blocking_reasons=tuple(blocking_reasons),
        unmet_anchors=tuple(unmet_anchors),
        locked_anchors=tuple(locked_anchors),
        self_citation_count=self_count,
        total_references=total_refs,
        self_citation_fraction=float(self_frac),
        max_self_citation_fraction=max_self_frac,
        citation_gate_passed=bool(citations_result.passed),
    )
