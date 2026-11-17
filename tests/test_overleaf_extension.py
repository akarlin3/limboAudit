"""Deterministic tests for the Overleaf/arXiv MV3 extension, bookmarklet and Web Store packaging."""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import unquote

import pytest

from limbo_audit.bookmarklet import (
    EXTENSION_FILES,
    build_bookmarklet,
    default_extension_dir,
    minify_js,
    package_extension_zip,
    render_bookmarklet_html,
)
from limbo_audit.cli import main

EXT = Path(__file__).resolve().parent.parent / "extensions" / "overleaf-chrome"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node.js is required to execute scanner.js")

FIX_PACK_URL = "https://averycorp.org/services.html?from=overleaf#diagnostic-dropzone"
AUDIT_URL = "https://averycorp.org/services.html?tier=1a&from=overleaf"


# --------------------------------------------------------------------------- manifest


def _manifest() -> dict:
    return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_is_mv3_compliant() -> None:
    m = _manifest()
    assert m["manifest_version"] == 3
    assert m["name"] == "limboAudit for Overleaf & arXiv"
    assert len(m["description"]) <= 132
    assert all(part.isdigit() for part in m["version"].split("."))
    assert sorted(m["permissions"]) == ["activeTab", "scripting", "storage"]
    assert sorted(m["host_permissions"]) == ["https://arxiv.org/*", "https://www.overleaf.com/*"]
    assert m["action"]["default_popup"] == "popup.html"
    # MV2-only keys must be absent.
    for legacy in ("browser_action", "page_action", "background_page", "web_accessible_resources"):
        assert legacy not in m
    assert isinstance(m["content_security_policy"], dict)
    assert "unsafe-eval" not in json.dumps(m["content_security_policy"])
    # The MAIN-world bridge needs Chrome 111+.
    assert int(m["minimum_chrome_version"]) >= 111
    worlds = {tuple(cs["js"]): cs.get("world", "ISOLATED") for cs in m["content_scripts"]}
    assert worlds[("bridge.js",)] == "MAIN"
    assert worlds[("scanner.js", "content.js")] == "ISOLATED"
    for cs in m["content_scripts"]:
        for pattern in cs["matches"]:
            assert any(pattern.startswith(h[:-1]) for h in m["host_permissions"])


def test_manifest_references_existing_files_and_valid_icons() -> None:
    m = _manifest()
    referenced = {m["action"]["default_popup"], *m["icons"].values(), *m["action"]["default_icon"].values()}
    for cs in m["content_scripts"]:
        referenced.update(cs.get("js", []))
        referenced.update(cs.get("css", []))
    for rel in referenced | set(EXTENSION_FILES):
        assert (EXT / rel).is_file(), rel
    for size, rel in m["icons"].items():
        data = (EXT / rel).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        assert (width, height) == (int(size), int(size))


def test_extension_is_zero_network_and_zero_eval() -> None:
    forbidden = ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "importScripts", "eval(", "new Function", "innerHTML")
    for name in ("scanner.js", "content.js", "bridge.js", "popup.js"):
        src = (EXT / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in src, f"{token} found in {name}"
    popup = (EXT / "popup.html").read_text(encoding="utf-8")
    assert "<script>" not in popup  # MV3 forbids inline scripts
    assert '<script src="http' not in popup


def test_cta_urls_and_luxury_palette_present() -> None:
    scanner = (EXT / "scanner.js").read_text(encoding="utf-8")
    assert "SERVICES_URL + '?from=overleaf#diagnostic-dropzone'" in scanner
    assert "SERVICES_URL + '?tier=1a&from=overleaf'" in scanner
    assert "var SERVICES_URL = 'https://averycorp.org/services.html';" in scanner
    css = (EXT / "styles.css").read_text(encoding="utf-8")
    assert "#121b2d" in css and "#d4af37" in css


# --------------------------------------------------------------------------- bookmarklet


def test_bookmarklet_uri_shape_and_determinism() -> None:
    a = build_bookmarklet(EXT)
    b = build_bookmarklet(EXT)
    assert a.uri == b.uri and a.sha256 == b.sha256
    assert a.uri.startswith("javascript:(function(){")
    assert a.uri.endswith("})();")
    for bad in (" ", '"', "#", "<", ">", "\n", "&"):
        assert bad not in a.uri
    decoded = unquote(a.uri[len("javascript:"):])
    assert decoded == a.source
    assert "__LIMBO_CSS__" in decoded and "LimboScanner" in decoded
    assert "\n//" not in decoded and "\n/*" not in decoded and "\n * " not in decoded
    assert a.size_bytes < 2_000_000


@needs_node
def test_bookmarklet_source_is_valid_javascript(tmp_path: Path) -> None:
    js = tmp_path / "bm.js"
    js.write_text(build_bookmarklet(EXT).source, encoding="utf-8")
    proc = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_minify_js_strips_comments_but_keeps_urls() -> None:
    src = "/* header\n * more\n */\n// line comment\n  var u = 'https://x.org/a';\n\n  /* one */ var b = 1;\n"
    assert minify_js(src) == "var u = 'https://x.org/a';\nvar b = 1;"


def test_install_page_html_contains_draggable_link() -> None:
    build = build_bookmarklet(EXT)
    page = render_bookmarklet_html(build)
    assert '<a class="drag" href="javascript:(function(){' in page
    assert "bookmarks bar" in page
    assert "?tier=1a&amp;from=overleaf" in page


# --------------------------------------------------------------------------- packaging & CLI


def test_package_zip_is_deterministic_and_rooted(tmp_path: Path) -> None:
    z1, z2 = tmp_path / "a.zip", tmp_path / "b.zip"
    names = package_extension_zip(z1, EXT)
    package_extension_zip(z2, EXT)
    assert hashlib.sha256(z1.read_bytes()).digest() == hashlib.sha256(z2.read_bytes()).digest()
    with zipfile.ZipFile(z1) as zf:
        listed = zf.namelist()
        assert "manifest.json" in listed
        assert set(EXTENSION_FILES) <= set(listed)
        assert not any(n.startswith(".") or "/." in n for n in listed)
        assert json.loads(zf.read("manifest.json"))["manifest_version"] == 3
    assert names == sorted(listed)


def test_cli_export_bookmarklet_writes_html_and_zip(tmp_path: Path, capsys) -> None:
    html_out = tmp_path / "overleaf_bookmarklet.html"
    zip_out = tmp_path / "overleaf_extension.zip"
    rc = main(["export-bookmarklet", "--out-html", str(html_out), "--package-zip", str(zip_out), "--json", "--print-uri"])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["uri"].startswith("javascript:(function(){")
    assert summary["bookmarklet_sha256"] == build_bookmarklet(default_extension_dir()).sha256
    assert html_out.is_file() and zip_out.is_file()
    assert "manifest.json" in summary["zip_files"]


def test_cli_export_bookmarklet_skip_outputs_and_bad_dir(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["export-bookmarklet", "--out-html", "", "--package-zip", ""]) == 0
    out = capsys.readouterr().out
    assert "Bookmarklet:" in out and "averycorp.org/services.html" in out
    assert list(tmp_path.iterdir()) == []
    assert main(["export-bookmarklet", "--extension-dir", str(tmp_path / "nope")]) == 2
    assert "LIMBO-NO-EXTENSION" in capsys.readouterr().err


# --------------------------------------------------------------------------- JS scanner (via Node)

_HARNESS = """
const S = require(process.argv[1]);
let input = '';
process.stdin.on('data', d => input += d);
process.stdin.on('end', () => {
  const cases = JSON.parse(input);
  const out = cases.map(c => {
    if (c.memo) return { memo: S.buildPiMemo(S.scan(c.text, c.opts), { venue: 'MRM' }) };
    if (c.bench) {
      let best = Infinity, r;
      for (let i = 0; i < 5; i++) { const t0 = process.hrtime.bigint(); r = S.scan(c.text, c.opts); best = Math.min(best, Number(process.hrtime.bigint() - t0) / 1e6); }
      return { best, findings: r.findings.length };
    }
    const r = S.scan(c.text, c.opts); delete r.elapsedMs; return r;
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def _scan(*cases: dict) -> list[dict]:
    proc = subprocess.run(
        [NODE, "-e", _HARNESS, str(EXT / "scanner.js")],
        input=json.dumps(list(cases)),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _rules(result: dict) -> list[str]:
    return [f["rule"] for f in result["findings"]]


TEX = r"""\documentclass{article}
\newcommand{\numPmain}{0.031}
\begin{document}
\begin{abstract}
In N = 28 participants (M = 5.19), the effect held, p = 0.043, r = .41, 12.5\% and 3.2 $\pm$ 0.4.
\end{abstract}
See Fig.~\ref{fig:missing}, \cite{} and \cite{smith2020,?}. % /Users/jdoe/Dropbox
\section{Methods}\label{sec:methods}
We randomly split the data and used a random seed.
Exact value p = \numPmain{}; % p = 0.03 lives only in a comment
?? and p < .05 and p < 0.001.
\end{document}
"""


@needs_node
def test_scanner_tex_patterns() -> None:
    (r,) = _scan({"text": TEX, "opts": {"year": 2026}})
    rules = _rules(r)
    by_rule = {f["rule"]: f for f in r["findings"]}
    assert r["kind"] == "tex"
    assert by_rule["grim"]["severity"] == "high" and by_rule["grim"]["line"] == 5
    assert by_rule["p-borderline"]["severity"] == "high"
    assert {"r-hardcoded", "pct-hardcoded", "pm-hardcoded", "n-hardcoded"} <= set(rules)
    assert "p-threshold" in rules and rules.count("p-hardcoded") == 1  # p < 0.001 only
    assert by_rule["cite-empty"]["line"] == 7 and by_rule["cite-placeholder"]["line"] == 7
    assert "ref-unresolved" in rules and "ref-marker" in rules
    assert "comment" in by_rule["path-leak"]["message"]
    assert "seed-unpinned" in rules and "seed-missing" in rules
    # Macro definitions and commented-out numbers are not flagged.
    assert all(f["line"] not in (2, 10) or f["rule"] == "path-leak" for f in r["findings"])
    assert r["wordCount"]["words"] > 0 and r["wordCount"]["target"] == "MRM"
    assert 0 <= r["score"] < 60 and r["grade"] in {"D", "F"}


@needs_node
def test_scanner_grim_consistent_mean_not_flagged_and_clean_doc_scores_100() -> None:
    clean = "\\begin{document}\nWe report the result in Table~\\ref{tab:a}.\\label{tab:a}\n\\end{document}\n"
    ok_grim = "In N = 28 subjects (M = 5.18) the effect held.\n"
    r_clean, r_grim = _scan({"text": clean, "opts": {}}, {"text": ok_grim, "opts": {}})
    assert r_clean["findings"] == [] and r_clean["score"] == 100 and r_clean["grade"] == "A"
    assert "grim" not in _rules(r_grim)


@needs_node
def test_scanner_abstract_word_count_against_venues() -> None:
    body = " ".join(["word"] * 200)
    text = "\\begin{abstract}\n" + body + " \\cite{x}\n\\end{abstract}\n"
    mrm, nature = _scan({"text": text, "opts": {"venue": "MRM"}}, {"text": text, "opts": {"venue": "Nature"}})
    assert mrm["wordCount"]["words"] == 200
    assert mrm["wordCount"]["venues"]["MRM"] == {"label": "Magnetic Resonance in Medicine (MRM)", "limit": 250, "over": False}
    assert mrm["wordCount"]["venues"]["Nature"]["over"] is True
    assert mrm["wordCount"]["venues"]["PLOS"]["over"] is False
    assert "abstract-over" not in _rules(mrm)
    over = [f for f in nature["findings"] if f["rule"] == "abstract-over"]
    assert len(over) == 1 and over[0]["severity"] == "high" and "50 over" in over[0]["message"]


@needs_node
def test_scanner_bib_hygiene() -> None:
    bib = (
        "@article{smith2020,\n  title={A},\n  year={2020}\n}\n"
        "@misc{lee2021, title={B}, journal={arXiv preprint arXiv:2101.00001}, year = 2021, doi={10.48550/arXiv.2101.00001}}\n"
        "@article{ok2022, title={C}, year={2022}, doi={10.1000/xyz}}\n"
        "@misc{fresh2026, journal={bioRxiv}, year={2026}}\n"
        "@article{Smith2020, doi={10.1/x}}\n"
    )
    (r,) = _scan({"text": bib, "opts": {"year": 2026}})
    assert r["kind"] == "bib" and r["bibEntries"] == 5
    found = [(f["rule"], f["line"]) for f in r["findings"]]
    assert found == [
        ("bib-missing-doi", 1),
        ("bib-stale-preprint", 5),
        ("bib-duplicate-key", 8),
    ]


@needs_node
def test_scanner_is_deterministic_line_offset_and_fast() -> None:
    para = TEX.split("\\begin{document}")[1].split("\\end{document}")[0]
    big = "\\begin{document}\n" + para * 150 + "\\end{document}\n"
    a, b, off, bench = _scan(
        {"text": TEX, "opts": {"year": 2026}},
        {"text": TEX, "opts": {"year": 2026}},
        {"text": TEX, "opts": {"year": 2026, "lineOffset": 100}},
        {"text": big, "opts": {"year": 2026}, "bench": True},
    )
    assert a == b
    assert [f["line"] + 100 for f in a["findings"]] == [f["line"] for f in off["findings"]]
    assert bench["findings"] > 1000
    assert bench["best"] < 50.0, f"scan took {bench['best']:.1f} ms for {big.count(chr(10))} lines"


@needs_node
def test_pi_memo_contents() -> None:
    (r,) = _scan({"text": TEX, "opts": {"year": 2026}, "memo": True})
    memo = r["memo"]
    assert "2 CFR \u00a7 200.320" in memo
    assert "NOT-OD-21-013" in memo
    assert "$650" in memo and "$2,450" in memo and "P-Card" in memo
    assert "https://averycorp.org/services.html" in memo
