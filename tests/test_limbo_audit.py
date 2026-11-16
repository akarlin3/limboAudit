"""Comprehensive deterministic unit tests for Engines 1, 2, 3, fixtures, and CLI."""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

from limbo_audit import (
    CANONICAL_ARTIFACT_DIGESTS,
    CANONICAL_ARTIFACTS,
    CANONICAL_BIB_TEXT,
    CANONICAL_CLAIMS_MAP,
    CANONICAL_LEDGER_TEXT,
    CANONICAL_MANUSCRIPT_TEX,
    CANONICAL_RELEASE_CONFIG,
    audit_citations,
    audit_numerical_consistency,
    check_identifier_online,
    compute_artifact_sha256,
    evaluate_canonical_and_adversarial,
    evaluate_release_gate,
    extract_prose_citations,
    is_valid_identifier,
    parse_bibtex,
    parse_claims_ledger,
    parse_provisional_ledger,
    resolve_artifact_keypath,
)
from limbo_audit.cli import main


# --------------------------------------------------------------------------- #
# Engine 1: Zero-Phantom Citation & Claims-Ledger Gate
# --------------------------------------------------------------------------- #
def test_canonical_59_reference_pass() -> None:
    res = audit_citations(
        CANONICAL_BIB_TEXT,
        CANONICAL_MANUSCRIPT_TEX,
        ledger_text=CANONICAL_LEDGER_TEXT,
        online=False,
    )
    assert res.passed is True
    assert len(res.bib_entries) == 59
    assert len(res.cited_keys) == 59
    assert res.phantom_citations == ()
    assert res.missing_identifiers == ()
    assert res.malformed_identifiers == ()
    assert res.bib_without_ledger == ()
    assert res.ledger_without_bib == ()
    assert res.unused_bib_entries == ()
    assert res.identifier_coverage == 1.0


def test_phantom_citation_trapping_latex_and_markdown() -> None:
    prose = (
        r"As shown in \cite{gudbjartsson1995} and \citep[see][p.~3]{sun2023phantom}, "
        "and confirmed in Markdown [@veraart2013; @hallucinated2025llm]."
    )
    keys = extract_prose_citations(prose)
    assert keys == [
        "gudbjartsson1995",
        "sun2023phantom",
        "veraart2013",
        "hallucinated2025llm",
    ]

    res = audit_citations(CANONICAL_BIB_TEXT, prose, check_unused=False)
    assert res.passed is False
    assert set(res.phantom_citations) == {"sun2023phantom", "hallucinated2025llm"}
    assert any("[phantom-prose-cite] sun2023phantom" in f for f in res.failures)


def test_bibtex_nested_braces_and_identifier_validation() -> None:
    assert is_valid_identifier("doi", "10.1002/mrm.21646")
    assert is_valid_identifier("doi", "10.1002/(SICI)1522-2586(199909)10:3<223::AID-JMRI2>3.0.CO;2-S")
    assert not is_valid_identifier("doi", "doi-pending-2026")
    assert is_valid_identifier("arxiv", "1905.03222")
    assert is_valid_identifier("arxiv", "1905.03222v2")
    assert is_valid_identifier("arxiv", "math/0501234")
    assert not is_valid_identifier("arxiv", "99.12")
    assert is_valid_identifier("pmid", "27330520")
    assert not is_valid_identifier("pmid", "PMID-abc")
    assert is_valid_identifier("url", "https://proceedings.mlr.press/v70/guo17a.html")
    assert not is_valid_identifier("url", "ftp://invalid.example.org/paper.pdf")

    bib = """
    @article{valid_pmid,
      author = {Koo, Terry K.},
      title = {Nested {Braces {Inside {$T_1$}} Title}},
      year = {2016},
      pmid = {27330520}
    }
    @article{missing_id,
      author = {NoId, Author},
      title = {Unanchored},
      year = {2024}
    }
    @article{bad_doi,
      author = {Bad, Doi},
      title = {Malformed DOI},
      year = {2024},
      doi = {not-a-doi}
    }
    """
    parsed = parse_bibtex(bib)
    assert len(parsed) == 3
    assert parsed["valid_pmid"].identifier_kind == "pmid"
    assert parsed["valid_pmid"].identifier_valid is True
    assert "Braces {Inside {$T_1$}}" in parsed["valid_pmid"].title

    res = audit_citations(bib, r"\cite{valid_pmid,missing_id,bad_doi}")
    assert res.passed is False
    assert res.missing_identifiers == ("missing_id",)
    assert res.malformed_identifiers == ("bad_doi",)
    assert abs(res.identifier_coverage - (1.0 / 3.0)) < 1e-9


def test_ledger_orphan_empty_claim_and_unused_bib_detection() -> None:
    bib = """
    @article{a2020, author={Alpha, A.}, title={A}, year={2020}, doi={10.1000/a2020}}
    @article{b2021, author={Beta, B.}, title={B}, year={2021}, eprint={2101.00001}}
    @article{c2022, author={Gamma, C.}, title={C}, year={2022}, doi={10.1000/c2022}}
    """
    ledger = """
| key | identifier | verified claim |
|---|---|---|
| `a2020` | doi:10.1000/a2020 |   |
| `d2023_orphan` | doi:10.1000/d2023 | Claim with no bib entry. |
| `c2022` | doi:10.1000/wrong_doi | Conflicting DOI in ledger. |
"""
    parsed_ledger = parse_claims_ledger(ledger)
    assert set(parsed_ledger.keys()) == {"a2020", "d2023_orphan", "c2022"}

    res = audit_citations(bib, r"Only citing \cite{a2020,b2021}.", ledger_text=ledger)
    assert res.passed is False
    assert res.bib_without_ledger == ("b2021",)
    assert res.ledger_without_bib == ("d2023_orphan",)
    assert res.empty_ledger_claims == ("a2020",)
    assert res.ledger_identifier_mismatches == ("c2022",)
    assert res.unused_bib_entries == ("c2022",)


def test_online_resolution_with_rate_limit_backoff() -> None:
    attempts: list[tuple[str, str]] = []
    sleeps: list[float] = []

    class _DummyResp:
        def __init__(self, status: int) -> None:
            self.status = status

        def __enter__(self) -> _DummyResp:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def fake_urlopen(req, timeout=10.0):  # noqa: ANN001
        attempts.append((req.get_method(), req.full_url))
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", hdrs=None, fp=io.BytesIO(b"")
            )
        return _DummyResp(200)

    ok = check_identifier_online(
        "doi",
        "10.1002/mrm.21646",
        max_retries=3,
        base_backoff=0.25,
        urlopen_fn=fake_urlopen,
        sleep_fn=sleeps.append,
    )
    assert ok is True
    assert len(attempts) == 2
    assert sleeps == [0.25]

    # Test online=True failure path in audit_citations
    bib = "@article{k1, author={A}, title={T}, year={2021}, eprint={2107.07511}}"
    res = audit_citations(
        bib,
        r"\cite{k1}",
        online=True,
        online_checker=lambda kind, val: False,
    )
    assert res.passed is False
    assert res.unresolved_online == ("k1",)


# --------------------------------------------------------------------------- #
# Engine 2: Verbatim Manuscript Number-to-Artifact Consistency Gate
# --------------------------------------------------------------------------- #
def test_canonical_34_numbers_consistency_pass() -> None:
    res = audit_numerical_consistency(
        CANONICAL_MANUSCRIPT_TEX,
        CANONICAL_CLAIMS_MAP,
        CANONICAL_ARTIFACTS,
        rtol=1e-4,
        atol=1e-4,
        artifact_digests=CANONICAL_ARTIFACT_DIGESTS,
    )
    assert res.passed is True
    assert res.total_claims == 34
    assert res.verified_claims == 34
    assert res.traced_numbers_ratio == 1.0
    assert res.stale_or_misquoted == ()
    assert res.untraced_or_orphaned == ()
    assert res.digest_mismatches == ()


def test_consistency_catches_stale_inline_and_macro_drift_and_sha256_tamper() -> None:
    artifacts = {
        "results/cp3.json": {
            "railing_rate_osipi": 0.542,
            "nested": {"ci": [0.12, 0.24, 0.36]},
        }
    }
    found, val, art_key = resolve_artifact_keypath(
        artifacts, "results/cp3.json:nested.ci[1]"
    )
    assert found is True and val == 0.24 and art_key == "results/cp3.json"

    manuscript = r"""
    \newcommand{\numRailing}{0.542}
    Railing rate was \numRailing{}, with untraceable \numGhostMacro{},
    while prose claimed r = 0.39 against the locked 0.24 benchmark.
    """
    claims = {
        "numRailing": {"path": "results/cp3.json:railing_rate_osipi", "fmt": "{:.3f}"},
        "r": {"path": "results/cp3.json:nested.ci[1]"},
        "missingClaim": {"path": "results/cp3.json:nonexistent_field"},
    }
    bad_digests = {"results/cp3.json": "0" * 64}

    res = audit_numerical_consistency(
        manuscript,
        claims,
        artifacts,
        rtol=1e-4,
        atol=1e-4,
        artifact_digests=bad_digests,
    )
    assert res.passed is False
    assert "r" in res.stale_or_misquoted
    assert "numGhostMacro" in res.untraced_or_orphaned
    assert "missingClaim" in res.untraced_or_orphaned
    assert "results/cp3.json" in res.digest_mismatches
    assert compute_artifact_sha256(artifacts["results/cp3.json"]) == res.artifact_digests["results/cp3.json"]


# --------------------------------------------------------------------------- #
# Engine 3: Provisional Ledger & Distinctness / Release Gate
# --------------------------------------------------------------------------- #
def test_release_gate_holds_and_self_citation_cap() -> None:
    cit = audit_citations(
        CANONICAL_BIB_TEXT, CANONICAL_MANUSCRIPT_TEX, ledger_text=CANONICAL_LEDGER_TEXT
    )
    clean_rel = evaluate_release_gate(CANONICAL_RELEASE_CONFIG, cit)
    assert clean_rel.release_ready is True
    assert clean_rel.state == "RELEASE"
    assert clean_rel.self_citation_count == 3
    assert clean_rel.total_references == 59
    assert abs(clean_rel.self_citation_fraction - (3.0 / 59.0)) < 1e-9
    assert "CLEAR" in clean_rel.format_hold_marker()

    # Fabricated published=True without a DOI must fail
    bad_doi_cfg = {
        "anchors": {
            "FASHION": {"published": True, "doi": None, "load_bearing": True},
        }
    }
    bad_doi_rel = evaluate_release_gate(bad_doi_cfg, cit)
    assert bad_doi_rel.release_ready is False
    assert "FASHION" in bad_doi_rel.unmet_anchors
    assert any("[invalid-anchor-doi]" in r for r in bad_doi_rel.blocking_reasons)

    # Tight self-citation cap (e.g., 2% < 5.1%) blocks release
    tight_cap_cfg = {
        **CANONICAL_RELEASE_CONFIG,
        "max_self_citation_fraction": 0.02,
    }
    tight_rel = evaluate_release_gate(tight_cap_cfg, cit)
    assert tight_rel.release_ready is False
    assert any("[self-citation-cap-exceeded]" in r for r in tight_rel.blocking_reasons)
    assert "ACTIVE" in tight_rel.format_hold_marker()

    # Parse PROVISIONAL_LEDGER.md checklist items
    md = """
    - [ ] **Fashion accepted** -> swap @unpublished{fashion}
    - [x] **Gauge accepted** (recommended) -> DOI 10.1002/mrm.29999
    """
    parsed_anchors = parse_provisional_ledger(md)
    assert parsed_anchors["FASHION"]["status"] == "PROVISIONAL"
    assert parsed_anchors["FASHION"]["load_bearing"] is True
    assert parsed_anchors["GAUGE"]["status"] == "LOCKED"
    assert parsed_anchors["GAUGE"]["doi"] == "10.1002/mrm.29999"


# --------------------------------------------------------------------------- #
# Engine 4 & CLI End-to-End File Commands
# --------------------------------------------------------------------------- #
def test_adversarial_mutant_suite_100pct_recall() -> None:
    bundle = evaluate_canonical_and_adversarial(seed=42)
    assert bundle.adversarial_fault_recall == 1.0
    assert bundle.statcheck_trap_recall == 1.0
    assert len(bundle.mutant_results) == 6
    assert all(m.detected for m in bundle.mutant_results)


def test_cli_check_citations_and_check_numbers(tmp_path: Path, capsys) -> None:
    bib_file = tmp_path / "refs.bib"
    tex_file = tmp_path / "paper.tex"
    ledger_file = tmp_path / "CITATIONS.md"
    art_dir = tmp_path / "results"
    art_dir.mkdir()

    bib_file.write_text(CANONICAL_BIB_TEXT, encoding="utf-8")
    tex_file.write_text(CANONICAL_MANUSCRIPT_TEX, encoding="utf-8")
    ledger_file.write_text(CANONICAL_LEDGER_TEXT, encoding="utf-8")

    for rel_name, payload in CANONICAL_ARTIFACTS.items():
        out_file = tmp_path / rel_name
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    claims_file = tmp_path / "claims.json"
    claims_file.write_text(json.dumps(CANONICAL_CLAIMS_MAP, indent=2), encoding="utf-8")

    rc_cit = main(
        [
            "check-citations",
            "--bib",
            str(bib_file),
            "--tex",
            str(tex_file),
            "--ledger",
            str(ledger_file),
            "--json",
        ]
    )
    assert rc_cit == 0
    cit_payload = json.loads(capsys.readouterr().out)
    assert cit_payload["passed"] is True
    assert cit_payload["verified_bib_count"] == 59

    artifact_args = [str(tmp_path / name) for name in CANONICAL_ARTIFACTS]
    # Note: claims_map references "results/trust_crlb.json:..." so write bundle JSON too
    bundle_json = tmp_path / "bundle.json"
    bundle_json.write_text(
        json.dumps(
            {
                "artifacts": CANONICAL_ARTIFACTS,
                "claims": CANONICAL_CLAIMS_MAP,
                "artifact_digests": CANONICAL_ARTIFACT_DIGESTS,
            }
        ),
        encoding="utf-8",
    )
    assert len(artifact_args) == 3

    rc_num = main(
        [
            "check-numbers",
            "--tex",
            str(tex_file),
            "--artifacts",
            str(bundle_json),
            "--json",
        ]
    )
    assert rc_num == 0
    num_payload = json.loads(capsys.readouterr().out)
    assert num_payload["passed"] is True
    assert num_payload["verified_claims"] == 34


def test_crossref_fallback_and_arxiv_online_probe() -> None:
    calls: list[str] = []

    class _Resp:
        def __init__(self, status: int) -> None:
            self.status = status

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def fake_urlopen(req, timeout=10.0):  # noqa: ANN001
        calls.append(req.full_url)
        if "doi.org" in req.full_url:
            raise urllib.error.HTTPError(
                req.full_url, 403, "Forbidden", hdrs=None, fp=io.BytesIO(b"")
            )
        return _Resp(200)

    assert check_identifier_online("doi", "10.1002/mrm.21646", urlopen_fn=fake_urlopen) is True
    assert any("api.crossref.org/works/" in u for u in calls)
    assert check_identifier_online("arxiv", "1905.03222", urlopen_fn=fake_urlopen) is True


def test_matrix_conditions_schema_and_cli_check_release(tmp_path: Path, capsys) -> None:
    bib_file = tmp_path / "refs.bib"
    bib_file.write_text(
        "@unpublished{draft2026, author={Karlin, Avery}, title={Draft}, year={2026}, url={https://example.org/draft}}\n",
        encoding="utf-8",
    )
    cfg_file = tmp_path / "release.json"
    cfg_file.write_text(
        json.dumps(
            {
                "forbid_unpublished_bib": True,
                "conditions": {
                    "FASHION_PUBLISHED": {"blocks_release": True, "satisfied": False},
                    "FORGE_BUILT": {"blocks_release": False, "satisfied": False},
                },
            }
        ),
        encoding="utf-8",
    )
    marker_file = tmp_path / "SUBMISSION_HOLD"

    rc = main(
        [
            "check-release",
            "--config",
            str(cfg_file),
            "--bib",
            str(bib_file),
            "--write-marker",
            str(marker_file),
            "--json",
        ]
    )
    assert rc == 1
    rel_out = json.loads(capsys.readouterr().out)
    assert rel_out["release_ready"] is False
    assert "FASHION_PUBLISHED" in rel_out["unmet_anchors"]
    assert "FORGE_BUILT" not in rel_out["unmet_anchors"]
    assert any("[unpublished-bib-entry]" in r for r in rel_out["blocking_reasons"])
    assert "SUBMISSION_HOLD: ACTIVE" in marker_file.read_text(encoding="utf-8")


def test_cli_check_numbers_inline_trace_comments(tmp_path: Path, capsys) -> None:
    art_file = tmp_path / "cp3.json"
    art_file.write_text(json.dumps({"railing_rate_osipi": 0.542}), encoding="utf-8")

    nums_file = tmp_path / "numbers.tex"
    nums_file.write_text(
        "\\newcommand{\\numRailing}{0.542}  % @trace cp3.json:railing_rate_osipi\n",
        encoding="utf-8",
    )
    tex_file = tmp_path / "ms.tex"
    tex_file.write_text("The railing rate is \\numRailing{}.\n", encoding="utf-8")

    rc = main(
        [
            "check-numbers",
            "--tex",
            str(tex_file),
            "--numbers-tex",
            str(nums_file),
            "--artifacts",
            str(art_file),
        ]
    )
    assert rc == 0
    assert "PASS" in capsys.readouterr().out
