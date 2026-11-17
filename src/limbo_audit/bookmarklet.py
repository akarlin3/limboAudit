"""1-click Overleaf Audit Bookmarklet generator and Chrome Web Store packager.

Compiles the client-side ``extensions/overleaf-chrome`` scanner (``scanner.js`` + ``bridge.js``
+ ``content.js`` + ``styles.css``) into a single ``javascript:(function(){...})();`` bookmarklet
URI, renders a drag-to-bookmarks-bar HTML install page, and packages the extension directory
into a deterministic, ready-to-upload Chrome Web Store ``.zip``.

Everything here is offline and deterministic: the bookmarklet and the extension make zero
network requests and never upload the manuscript buffer.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

BOOKMARKLET_PREFIX = "javascript:"
BOOKMARKLET_JS_ORDER: tuple[str, ...] = ("scanner.js", "bridge.js", "content.js")
EXTENSION_FILES: tuple[str, ...] = (
    "manifest.json",
    "scanner.js",
    "bridge.js",
    "content.js",
    "styles.css",
    "popup.html",
    "popup.js",
    "icons/icon16.png",
    "icons/icon48.png",
    "icons/icon128.png",
)
# Characters left unescaped so the URI stays readable (`javascript:(function(){...})();`)
# while everything that could break an href or a bookmark (spaces, quotes, %, #, &, <, >,
# newlines) is percent-encoded. javascript: URLs are percent-decoded before execution.
_URI_SAFE = "(){}[];,.:=!*+-_/'|~^$?@"
_FIXED_ZIP_DATE = (2026, 1, 1, 0, 0, 0)

SERVICES_URL = "https://averycorp.org/services.html"


@dataclass(frozen=True)
class BookmarkletBuild:
    uri: str
    source: str
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.uri.encode("utf-8"))


def default_extension_dir() -> Path:
    """Locate ``extensions/overleaf-chrome`` (installed wheel data first, then the repo checkout)."""
    here = Path(__file__).resolve().parent
    candidates = (
        here / "_overleaf_extension",
        here.parent.parent / "extensions" / "overleaf-chrome",
        Path.cwd() / "extensions" / "overleaf-chrome",
    )
    for cand in candidates:
        if (cand / "manifest.json").is_file():
            return cand
    raise FileNotFoundError(
        "Could not find extensions/overleaf-chrome/manifest.json; pass --extension-dir explicitly."
    )


def minify_js(source: str) -> str:
    """Conservative minifier: drops comment-only lines/blocks, indentation and blank lines.

    The extension sources follow a strict style (explicit semicolons, comments on their own
    lines, no multi-line string literals), so stripping is safe and newlines are kept for ASI
    robustness (they are percent-encoded as ``%0A`` inside the URI).
    """
    out: list[str] = []
    in_block = False
    for raw in source.splitlines():
        line = raw.strip()
        if in_block:
            if "*/" in line:
                in_block = False
                line = line.split("*/", 1)[1].strip()
            else:
                continue
        if line.startswith("/*"):
            if "*/" in line:
                line = line.split("*/", 1)[1].strip()
            else:
                in_block = True
                continue
        if not line or line.startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def minify_css(source: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};,>])\s*", r"\1", css)
    css = re.sub(r":\s+", ":", css)
    return css.replace(";}", "}").strip()


def build_bookmarklet_source(extension_dir: Path | None = None) -> str:
    ext = Path(extension_dir) if extension_dir else default_extension_dir()
    css = minify_css((ext / "styles.css").read_text(encoding="utf-8"))
    parts = [f"var __LIMBO_CSS__={json.dumps(css, ensure_ascii=True)};"]
    for name in BOOKMARKLET_JS_ORDER:
        parts.append(minify_js((ext / name).read_text(encoding="utf-8")))
    body = "\n".join(parts)
    return "(function(){\n" + body + "\n})();"


def build_bookmarklet(extension_dir: Path | None = None) -> BookmarkletBuild:
    source = build_bookmarklet_source(extension_dir)
    uri = BOOKMARKLET_PREFIX + quote(source, safe=_URI_SAFE)
    return BookmarkletBuild(
        uri=uri, source=source, sha256=hashlib.sha256(uri.encode("utf-8")).hexdigest()
    )


def render_bookmarklet_html(build: BookmarkletBuild) -> str:
    href = html.escape(build.uri, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>limboAudit Overleaf Bookmarklet</title>
<style>
:root {{ --navy:#121b2d; --navy2:#1b2740; --gold:#d4af37; --ink:#f4efe1; --muted:#a9b1c3; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--navy); color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif; }}
main {{ max-width:720px; margin:0 auto; padding:48px 16px; }}
.eyebrow {{ color:var(--gold); font-size:11px; letter-spacing:.2em; text-transform:uppercase; }}
h1 {{ margin:6px 0 12px; font:600 34px/1.15 Georgia,"Times New Roman",serif; }}
p, li {{ color:var(--muted); }}
.drag {{ display:inline-block; margin:22px 0; padding:14px 22px; border:1px solid var(--gold); border-radius:999px; background:var(--gold); color:var(--navy); font-weight:700; text-decoration:none; cursor:grab; }}
.card {{ margin-top:24px; padding:18px 20px; border:1px solid #24324f; border-radius:12px; background:var(--navy2); }}
code {{ color:var(--gold); }}
a.cta {{ color:var(--gold); }}
small {{ color:var(--muted); }}
</style>
</head>
<body>
<main>
<div class="eyebrow">AveryCorp &middot; limboAudit</div>
<h1>1-Click Overleaf Audit Bookmarklet</h1>
<p>Drag the gold button to your bookmarks bar. Open any Overleaf project, click the bookmark, and a
drawer lists untraced numbers, fragile p-values, GRIM triggers, citation/DOI gaps, unresolved
<code>\\ref</code>s, path leaks and abstract word counts for your active <code>.tex</code>/<code>.bib</code> buffer.</p>
<a class="drag" href="{href}" title="Drag me to your bookmarks bar">&#128737;&#65039; limboAudit Overleaf</a>
<div class="card">
<ol>
<li>Show the bookmarks bar (Ctrl/Cmd + Shift + B).</li>
<li>Drag <strong>&#128737;&#65039; limboAudit Overleaf</strong> onto it.</li>
<li>In Overleaf, open a <code>.tex</code> or <code>.bib</code> file (or select text) and click the bookmark.</li>
</ol>
<p><small>100% client-side &middot; zero server upload &middot; zero LLM training &middot;
deterministic. Build <code>{build.sha256[:12]}</code> &middot; {build.size_bytes:,} bytes.</small></p>
</div>
<p>Prefer an install? Load the <strong>limboAudit for Overleaf &amp; arXiv</strong> Chrome extension
(<code>overleaf_extension.zip</code>). Need fixes, not just findings?
<a class="cta" href="{SERVICES_URL}?from=overleaf#diagnostic-dropzone">$19 Self-Serve Fix-Pack</a> &middot;
<a class="cta" href="{SERVICES_URL}?tier=1a&amp;from=overleaf">$650&ndash;$2,450 Executive Audits</a></p>
</main>
</body>
</html>
"""


def package_extension_zip(out_zip: Path, extension_dir: Path | None = None) -> list[str]:
    """Write a deterministic Chrome Web Store zip with ``manifest.json`` at the archive root."""
    ext = Path(extension_dir) if extension_dir else default_extension_dir()
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3:
        raise ValueError("extensions/overleaf-chrome/manifest.json must declare manifest_version 3")
    names = sorted(
        p.relative_to(ext).as_posix()
        for p in ext.rglob("*")
        if p.is_file()
        and not any(part.startswith(".") for part in p.relative_to(ext).parts)
        and "__pycache__" not in p.parts
        and p.suffix not in {".zip", ".map"}
    )
    missing = [f for f in EXTENSION_FILES if f not in names]
    if missing:
        raise FileNotFoundError(f"Extension is missing required files: {', '.join(missing)}")
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, (ext / name).read_bytes())
    return names
