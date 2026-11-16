"""Engine 1 — Zero-Phantom Citation & Claims-Ledger Gate.

Generalizes ``Limbo/verify_citations.py`` into a reusable, pure-Python verification engine:
- Brace-balanced BibTeX (``.bib``) parser producing structured ``BibEntry`` records.
- LaTeX (``\\cite``, ``\\citep``, ``\\citet``, ...) and Pandoc/Markdown (``[@key]``) prose citation extractor.
- Markdown ``CITATIONS.md`` claims-ledger parser mapping each ``citekey`` to its verified
  one-line claim and resolvable identifier (DOI, arXiv, PMID, or stable URL).
- Offline structural/orphan/phantom verification plus optional ``online=True`` HTTP HEAD/GET
  resolution against ``doi.org`` / Crossref, ``export.arxiv.org``, and PubMed with exponential
  rate-limit backoff.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
ARXIV_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-zA-Z\-]+(?:\.[a-zA-Z]{2})?/\d{7})(?:v\d+)?$"
)
PMID_RE = re.compile(r"^\d{1,10}$")
URL_RE = re.compile(r"^https?://\S+$")

_LATEX_CITE_RE = re.compile(
    r"\\(?:cite[tp]?|citealt|citealp|citeauthor|citeyear|citenum|parencite|textcite|autocite|nocite)"
    r"\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}"
)
_MD_BRACKET_RE = re.compile(r"\[([^\[\]\n]+)\]")
_MD_CITEKEY_RE = re.compile(r"(?:^|[\s;\(\-,])@([A-Za-z0-9_][A-Za-z0-9_:\-\.]*)")


def normalize_identifier(kind: str, raw_value: str) -> str:
    """Strip common URI/prefix wrappers while preserving the canonical identifier value."""
    val = raw_value.strip()
    kind_lc = kind.lower()
    if kind_lc == "doi":
        for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
            if val.lower().startswith(prefix):
                val = val[len(prefix) :].strip()
                break
    elif kind_lc == "arxiv":
        for prefix in (
            "https://arxiv.org/abs/",
            "http://arxiv.org/abs/",
            "https://export.arxiv.org/abs/",
            "arxiv:",
        ):
            if val.lower().startswith(prefix):
                val = val[len(prefix) :].strip()
                break
    elif kind_lc == "pmid":
        if val.lower().startswith("pmid:"):
            val = val[5:].strip()
    elif kind_lc == "url":
        if val.lower().startswith("url:"):
            val = val[4:].strip()
    return val


def is_valid_identifier(kind: str, value: str) -> bool:
    """Return True iff ``(kind, value)`` matches a well-formed DOI, arXiv ID, PMID, or URL."""
    norm = normalize_identifier(kind, value)
    if not norm:
        return False
    kind_lc = kind.lower()
    if kind_lc == "doi":
        return bool(DOI_RE.match(norm))
    if kind_lc == "arxiv":
        return bool(ARXIV_RE.match(norm))
    if kind_lc == "pmid":
        return bool(PMID_RE.match(norm))
    if kind_lc == "url":
        return bool(URL_RE.match(norm))
    return False


def extract_identifier_from_fields(fields: dict[str, str]) -> tuple[str, str] | None:
    """Extract the highest-priority identifier ``(kind, normalized_value)`` from BibTeX fields."""
    if fields.get("doi", "").strip():
        return ("doi", normalize_identifier("doi", fields["doi"]))
    if fields.get("eprint", "").strip():
        return ("arxiv", normalize_identifier("arxiv", fields["eprint"]))
    if fields.get("arxiv", "").strip():
        return ("arxiv", normalize_identifier("arxiv", fields["arxiv"]))
    if fields.get("pmid", "").strip():
        return ("pmid", normalize_identifier("pmid", fields["pmid"]))
    if fields.get("url", "").strip():
        url_val = fields["url"].strip()
        # Recognize doi.org or arxiv.org URLs placed in the url field if dedicated fields are absent
        if url_val.lower().startswith(("https://doi.org/10.", "http://doi.org/10.")):
            return ("doi", normalize_identifier("doi", url_val))
        return ("url", normalize_identifier("url", url_val))
    return None


@dataclass(frozen=True)
class BibEntry:
    """Structured representation of a single BibTeX entry."""

    citekey: str
    entry_type: str
    fields: dict[str, str]
    identifier_kind: str | None
    identifier_value: str | None
    identifier_valid: bool

    @property
    def author(self) -> str:
        return self.fields.get("author", "")

    @property
    def title(self) -> str:
        return self.fields.get("title", "")

    @property
    def year(self) -> str:
        return self.fields.get("year", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "citekey": self.citekey,
            "entry_type": self.entry_type,
            "fields": dict(self.fields),
            "identifier_kind": self.identifier_kind,
            "identifier_value": self.identifier_value,
            "identifier_valid": self.identifier_valid,
        }


@dataclass(frozen=True)
class LedgerClaim:
    """Verified claim row parsed from a structured ``CITATIONS.md`` ledger."""

    citekey: str
    claim: str
    identifier_raw: str
    identifier_kind: str | None
    identifier_value: str | None
    identifier_valid: bool


@dataclass(frozen=True)
class CitationAuditResult:
    """Comprehensive diagnostic output of ``audit_citations``."""

    passed: bool
    bib_entries: dict[str, BibEntry]
    cited_keys: tuple[str, ...]
    phantom_citations: tuple[str, ...]
    missing_identifiers: tuple[str, ...]
    malformed_identifiers: tuple[str, ...]
    bib_without_ledger: tuple[str, ...]
    ledger_without_bib: tuple[str, ...]
    empty_ledger_claims: tuple[str, ...]
    ledger_identifier_mismatches: tuple[str, ...]
    unused_bib_entries: tuple[str, ...]
    unresolved_online: tuple[str, ...]
    identifier_coverage: float
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "verified_bib_count": len(self.bib_entries),
            "cited_key_count": len(self.cited_keys),
            "cited_keys": list(self.cited_keys),
            "phantom_citations": list(self.phantom_citations),
            "missing_identifiers": list(self.missing_identifiers),
            "malformed_identifiers": list(self.malformed_identifiers),
            "bib_without_ledger": list(self.bib_without_ledger),
            "ledger_without_bib": list(self.ledger_without_bib),
            "empty_ledger_claims": list(self.empty_ledger_claims),
            "ledger_identifier_mismatches": list(self.ledger_identifier_mismatches),
            "unused_bib_entries": list(self.unused_bib_entries),
            "unresolved_online": list(self.unresolved_online),
            "identifier_coverage": round(float(self.identifier_coverage), 6),
            "failures": list(self.failures),
        }


def _parse_bib_fields(body: str) -> dict[str, str]:
    """Parse brace-balanced or quoted ``name = value`` pairs inside a BibTeX entry body."""
    fields: dict[str, str] = {}
    n = len(body)
    i = 0
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if body[i] == "%":
            while i < n and body[i] != "\n":
                i += 1
            continue

        name_start = i
        while i < n and (body[i].isalnum() or body[i] in "_-.:"):
            i += 1
        field_name = body[name_start:i].strip().lower()
        while i < n and body[i] in " \t\r\n":
            i += 1
        if not field_name or i >= n or body[i] != "=":
            while i < n and body[i] not in ",\n":
                i += 1
            continue
        i += 1  # consume '='
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i >= n:
            break

        if body[i] == "{":
            depth = 0
            val_start = i + 1
            while i < n:
                ch = body[i]
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        raw_val = body[val_start:i]
                        i += 1
                        break
                i += 1
            else:
                raw_val = body[val_start:]
        elif body[i] == '"':
            val_start = i + 1
            i += 1
            while i < n:
                if body[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if body[i] == '"':
                    break
                i += 1
            raw_val = body[val_start:i]
            if i < n and body[i] == '"':
                i += 1
        else:
            val_start = i
            while i < n and body[i] not in ",\r\n}":
                i += 1
            raw_val = body[val_start:i]

        cleaned = re.sub(r"\s+", " ", raw_val).strip()
        fields[field_name] = cleaned

        while i < n and body[i] in " \t\r\n":
            i += 1
        if i < n and body[i] == ",":
            i += 1
    return fields


def parse_bibtex(bib_text: str) -> dict[str, BibEntry]:
    """Parse BibTeX text into an ordered mapping ``{citekey: BibEntry}``."""
    entries: dict[str, BibEntry] = {}
    header_re = re.compile(r"@([A-Za-z]+)\s*([\{\(])")
    pos = 0
    n = len(bib_text)

    while pos < n:
        # Skip % comment lines outside entries
        line_start = bib_text.rfind("\n", 0, pos) + 1
        m = header_re.search(bib_text, pos)
        if not m:
            break
        at_idx = m.start()
        line_start = bib_text.rfind("\n", 0, at_idx) + 1
        prefix_on_line = bib_text[line_start:at_idx].strip()
        if prefix_on_line.startswith("%"):
            next_nl = bib_text.find("\n", at_idx)
            pos = n if next_nl == -1 else next_nl + 1
            continue

        entry_type = m.group(1).strip().lower()
        open_delim = m.group(2)
        close_delim = "}" if open_delim == "{" else ")"
        i = m.end()
        depth = 1
        body_start = i
        while i < n and depth > 0:
            ch = bib_text[i]
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == open_delim:
                depth += 1
            elif ch == close_delim:
                depth -= 1
            i += 1

        full_inner = bib_text[body_start : i - 1 if depth == 0 else i]
        pos = i

        if entry_type in {"comment", "preamble", "string"}:
            continue

        comma_idx = full_inner.find(",")
        if comma_idx == -1:
            citekey = full_inner.strip()
            fields: dict[str, str] = {}
        else:
            citekey = full_inner[:comma_idx].strip()
            fields = _parse_bib_fields(full_inner[comma_idx + 1 :])

        if not citekey:
            continue

        ident = extract_identifier_from_fields(fields)
        if ident is None:
            id_kind, id_val, id_valid = None, None, False
        else:
            id_kind, id_val = ident
            id_valid = is_valid_identifier(id_kind, id_val)

        entries[citekey] = BibEntry(
            citekey=citekey,
            entry_type=entry_type,
            fields=fields,
            identifier_kind=id_kind,
            identifier_value=id_val,
            identifier_valid=id_valid,
        )
    return entries


def _strip_comments_from_prose(prose_text: str) -> str:
    """Remove HTML comments and unescaped LaTeX ``%`` comments from manuscript text."""
    text = re.sub(r"<!--.*?-->", "", prose_text, flags=re.DOTALL)
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        # Strip unescaped % in LaTeX lines (keep lines starting with > or | in Markdown intact unless % follows TeX command)
        idx = 0
        out_end = len(line)
        while idx < len(line):
            pct = line.find("%", idx)
            if pct == -1:
                break
            if pct > 0 and line[pct - 1] == "\\":
                idx = pct + 1
                continue
            # Avoid stripping markdown percentages like "15% cap" unless at start of line or preceded by whitespace + comment style
            if pct == 0 or (
                not (pct > 0 and line[pct - 1].isdigit())
                and ("\\" in line or line.lstrip().startswith("%"))
            ):
                out_end = pct
                break
            idx = pct + 1
        cleaned_lines.append(line[:out_end])
    return "\n".join(cleaned_lines)


def extract_prose_citations(prose_text: str) -> list[str]:
    """Extract unique citation keys referenced in LaTeX or Markdown prose (in first-seen order)."""
    cleaned = _strip_comments_from_prose(prose_text)
    seen: dict[str, None] = {}

    for m in _LATEX_CITE_RE.finditer(cleaned):
        for raw_key in m.group(1).split(","):
            key = raw_key.strip()
            if key and key != "*":
                seen.setdefault(key, None)

    for bm in _MD_BRACKET_RE.finditer(cleaned):
        bracket_body = bm.group(1)
        if "@" not in bracket_body:
            continue
        for km in _MD_CITEKEY_RE.finditer(bracket_body):
            key = km.group(1).rstrip(".,;:")
            if key:
                seen.setdefault(key, None)

    return list(seen.keys())


def _parse_ledger_identifier(raw_id: str) -> tuple[str | None, str | None, bool]:
    """Classify and validate a ``CITATIONS.md`` identifier cell."""
    cell = raw_id.strip().strip("`")
    if not cell or cell in {"-", "—", "none", "N/A", "n/a"}:
        return (None, None, False)

    lower = cell.lower()
    if lower.startswith("doi:") or lower.startswith("https://doi.org/") or lower.startswith("http://doi.org/"):
        val = normalize_identifier("doi", cell)
        return ("doi", val, is_valid_identifier("doi", val))
    if lower.startswith("arxiv:") or "arxiv.org/abs/" in lower:
        val = normalize_identifier("arxiv", cell)
        return ("arxiv", val, is_valid_identifier("arxiv", val))
    if lower.startswith("pmid:"):
        val = normalize_identifier("pmid", cell)
        return ("pmid", val, is_valid_identifier("pmid", val))
    if lower.startswith("url:") or lower.startswith("https://") or lower.startswith("http://"):
        val = normalize_identifier("url", cell)
        return ("url", val, is_valid_identifier("url", val))
    if DOI_RE.match(cell):
        return ("doi", cell, True)
    if ARXIV_RE.match(cell):
        return ("arxiv", cell, True)
    if PMID_RE.match(cell):
        return ("pmid", cell, True)
    return ("unknown", cell, False)


def parse_claims_ledger(ledger_text: str) -> dict[str, LedgerClaim]:
    """Parse a structured ``CITATIONS.md`` Markdown ledger into ``{citekey: LedgerClaim}``.

    Supports standard 3-column tables (``| `citekey` | identifier | verified claim |``) as well
    as header-labelled Markdown tables where ``identifier`` and ``claim`` columns appear in
    arbitrary order. Plain-text cross-reference rows without backtick-wrapped citekeys are
    skipped unless the current table header explicitly names ``citekey``.
    """
    claims: dict[str, LedgerClaim] = {}
    id_col = 1
    claim_col = 2
    key_col = 0
    explicit_citekey_table = False

    for raw_line in ledger_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            explicit_citekey_table = False
            key_col, id_col, claim_col = 0, 1, 2
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue

        # Separator row e.g. |---|---|---|
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue

        lower_cells = [c.lower().strip("`*") for c in cells]
        if any(h in {"key", "citekey", "citation key"} for h in lower_cells):
            for idx, h in enumerate(lower_cells):
                if h in {"key", "citekey", "citation key"}:
                    key_col = idx
                    explicit_citekey_table = h in {"citekey", "citation key"}
                elif "id" in h or "doi" in h or "url" in h:
                    id_col = idx
                elif "claim" in h or "summary" in h or "finding" in h:
                    claim_col = idx
            continue

        if key_col >= len(cells):
            continue

        key_cell = cells[key_col]
        km = re.fullmatch(r"`([^`]+)`", key_cell)
        if km:
            citekey = km.group(1).strip()
        elif explicit_citekey_table and re.fullmatch(r"[A-Za-z0-9_:\-\.]+", key_cell):
            citekey = key_cell
        else:
            continue

        raw_id = cells[id_col] if id_col < len(cells) else ""
        claim_val = cells[claim_col] if claim_col < len(cells) else ""
        id_kind, id_val, id_valid = _parse_ledger_identifier(raw_id)

        claims[citekey] = LedgerClaim(
            citekey=citekey,
            claim=claim_val.strip(),
            identifier_raw=raw_id.strip(),
            identifier_kind=id_kind,
            identifier_value=id_val,
            identifier_valid=id_valid,
        )
    return claims


def _http_probe(
    url: str,
    *,
    timeout: float = 10.0,
    max_retries: int = 3,
    base_backoff: float = 0.5,
    urlopen_fn: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Probe ``url`` with HEAD then GET, retrying transient 429/503 responses with backoff."""
    opener = urlopen_fn or urllib.request.urlopen
    headers = {"User-Agent": "limbo-audit/1.0 (+https://github.com/akarlin3/limboAudit)"}

    for method in ("HEAD", "GET"):
        for attempt in range(max_retries):
            req = urllib.request.Request(url, method=method, headers=headers)
            try:
                with opener(req, timeout=timeout) as resp:
                    status = int(getattr(resp, "status", 200))
                    if 200 <= status < 400:
                        return True
                    if status in {429, 503} and attempt + 1 < max_retries:
                        sleep_fn(base_backoff * (2**attempt))
                        continue
                    break
            except urllib.error.HTTPError as exc:
                if exc.code in {429, 503} and attempt + 1 < max_retries:
                    sleep_fn(base_backoff * (2**attempt))
                    continue
                # Try GET if HEAD returned 405 Method Not Allowed or 403
                break
            except Exception:
                if attempt + 1 < max_retries:
                    sleep_fn(base_backoff * (2**attempt))
                    continue
                break
    return False


def check_identifier_online(
    kind: str,
    value: str,
    *,
    timeout: float = 10.0,
    max_retries: int = 3,
    base_backoff: float = 0.5,
    urlopen_fn: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Verify network resolvability of an identifier against authoritative endpoints."""
    norm = normalize_identifier(kind, value)
    kind_lc = kind.lower()
    kwargs = {
        "timeout": timeout,
        "max_retries": max_retries,
        "base_backoff": base_backoff,
        "urlopen_fn": urlopen_fn,
        "sleep_fn": sleep_fn,
    }
    if kind_lc == "doi":
        enc = urllib.parse.quote(norm, safe="")
        if _http_probe(f"https://doi.org/{enc}", **kwargs):
            return True
        return _http_probe(f"https://api.crossref.org/works/{enc}", **kwargs)
    if kind_lc == "arxiv":
        enc = urllib.parse.quote(norm, safe="/.")
        if _http_probe(f"https://export.arxiv.org/api/query?id_list={enc}", **kwargs):
            return True
        return _http_probe(f"https://arxiv.org/abs/{enc}", **kwargs)
    if kind_lc == "pmid":
        return _http_probe(f"https://pubmed.ncbi.nlm.nih.gov/{norm}/", **kwargs)
    if kind_lc == "url":
        return _http_probe(norm, **kwargs)
    return False


def audit_citations(
    bib_text: str,
    prose_text: str,
    ledger_text: str | None = None,
    online: bool = False,
    *,
    check_unused: bool = True,
    online_checker: Callable[[str, str], bool] | None = None,
) -> CitationAuditResult:
    """Audit BibTeX bibliography, manuscript prose citations, and optional ``CITATIONS.md`` ledger.

    Flags:
    - Phantom citations in ``.tex`` / ``.md`` prose absent from ``.bib``.
    - Identifier-less or malformed-identifier ``.bib`` entries.
    - ``.bib`` <-> ``CITATIONS.md`` orphans, empty claims, and conflicting identifiers.
    - Unused ``.bib`` entries never cited in ``prose_text`` (when ``check_unused=True``).
    - Online non-resolving identifiers (when ``online=True``).
    """
    bib_entries = parse_bibtex(bib_text)
    cited_list = extract_prose_citations(prose_text)
    cited_set = set(cited_list)
    bib_keys = set(bib_entries.keys())

    failures: list[str] = []
    missing_ids: list[str] = []
    malformed_ids: list[str] = []
    valid_id_count = 0

    for key in sorted(bib_keys):
        entry = bib_entries[key]
        if entry.identifier_kind is None or entry.identifier_value is None:
            missing_ids.append(key)
            failures.append(f"[no-identifier] {key}: missing doi/eprint/pmid/url field in .bib")
        elif not entry.identifier_valid:
            malformed_ids.append(key)
            failures.append(
                f"[malformed-{entry.identifier_kind}] {key}: {entry.identifier_value!r}"
            )
        else:
            valid_id_count += 1

    phantoms = sorted(cited_set - bib_keys)
    for key in phantoms:
        failures.append(f"[phantom-prose-cite] {key}: cited in prose but absent from .bib")

    unused: list[str] = []
    if check_unused and prose_text.strip():
        unused = sorted(bib_keys - cited_set)
        for key in unused:
            failures.append(f"[unused-bib-entry] {key}: present in .bib but never cited in prose")

    bib_no_ledger: list[str] = []
    ledger_no_bib: list[str] = []
    empty_claims: list[str] = []
    id_mismatches: list[str] = []

    if ledger_text is not None:
        ledger = parse_claims_ledger(ledger_text)
        ledger_keys = set(ledger.keys())

        bib_no_ledger = sorted(bib_keys - ledger_keys)
        for key in bib_no_ledger:
            failures.append(f"[unverified] {key}: in .bib but missing verified claim in CITATIONS.md")

        ledger_no_bib = sorted(ledger_keys - bib_keys)
        for key in ledger_no_bib:
            failures.append(f"[orphan-claim] {key}: in CITATIONS.md but missing entry in .bib")

        for key in sorted(bib_keys & ledger_keys):
            row = ledger[key]
            if not row.claim.strip():
                empty_claims.append(key)
                failures.append(f"[empty-claim] {key}: verified claim in CITATIONS.md is blank")
            entry = bib_entries[key]
            if (
                row.identifier_raw
                and entry.identifier_valid
                and row.identifier_valid
                and (row.identifier_kind != entry.identifier_kind or row.identifier_value != entry.identifier_value)
            ):
                id_mismatches.append(key)
                failures.append(
                    f"[ledger-id-mismatch] {key}: .bib has {entry.identifier_kind}:{entry.identifier_value} "
                    f"vs CITATIONS.md {row.identifier_kind}:{row.identifier_value}"
                )

    unresolved: list[str] = []
    if online:
        probe = online_checker or check_identifier_online
        for key in sorted(bib_keys):
            entry = bib_entries[key]
            if entry.identifier_valid and entry.identifier_kind and entry.identifier_value:
                if not probe(entry.identifier_kind, entry.identifier_value):
                    unresolved.append(key)
                    failures.append(
                        f"[unresolved-online] {key}: {entry.identifier_kind}:{entry.identifier_value} did not resolve"
                    )

    id_cov = (valid_id_count / len(bib_entries)) if bib_entries else 0.0

    return CitationAuditResult(
        passed=(len(failures) == 0),
        bib_entries=bib_entries,
        cited_keys=tuple(cited_list),
        phantom_citations=tuple(phantoms),
        missing_identifiers=tuple(missing_ids),
        malformed_identifiers=tuple(malformed_ids),
        bib_without_ledger=tuple(bib_no_ledger),
        ledger_without_bib=tuple(ledger_no_bib),
        empty_ledger_claims=tuple(empty_claims),
        ledger_identifier_mismatches=tuple(id_mismatches),
        unused_bib_entries=tuple(unused),
        unresolved_online=tuple(unresolved),
        identifier_coverage=float(id_cov),
        failures=tuple(failures),
    )
