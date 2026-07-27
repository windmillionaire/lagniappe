"""Maintainer refresh workflow for the self-hosted Material Symbols subset."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

import yaml

from runner.context import NPM_CLI, REPOSITORY_ROOT
from runner.process import run_command


ICONS_PATH = REPOSITORY_ROOT / "src/style/icons.yaml"
FONT_PATH = REPOSITORY_ROOT / "src/fonts/material-symbols-rounded.woff2"
METADATA_PATH = REPOSITORY_ROOT / "src/fonts/material-symbols-rounded.json"
GOOGLE_FONTS_CSS_URL = "https://fonts.googleapis.com/css2"
FONT_FAMILY_QUERY = "Material Symbols Rounded:opsz,wght,FILL,GRAD@24,300..600,0..1,0"
USER_AGENT = "Mozilla/5.0 AppleWebKit/537.36 Chrome/126 Safari/537.36"
FONT_URL_RE = re.compile(r"src:\s*url\((https://fonts\.gstatic\.com/[^)]+)\)")


# @testable true
# @tests tests_tooling/test_icons.py::test_material_symbol_subset_request_uses_unique_sorted_registry_glyphs
def _registry_glyphs(value):
    if not isinstance(value, dict) or not value:
        raise TypeError("icon registry nodes must be non-empty mappings")
    if "glyph" in value:
        glyph = value["glyph"]
        if not isinstance(glyph, str) or not glyph:
            raise TypeError("icon registry glyphs must be non-empty strings")
        return [glyph]
    return [glyph for child in value.values() for glyph in _registry_glyphs(child)]


# @testable true
# @tests tests_tooling/test_icons.py::test_material_symbol_subset_request_uses_unique_sorted_registry_glyphs
def subset_request(icons_path=ICONS_PATH):
    registry = yaml.safe_load(Path(icons_path).read_text(encoding="utf-8")) or {}
    icon_names = sorted(set(_registry_glyphs(registry)))
    query = urlencode(
        {
            "family": FONT_FAMILY_QUERY,
            "icon_names": ",".join(icon_names),
            "display": "block",
        }
    )
    return f"{GOOGLE_FONTS_CSS_URL}?{query}", icon_names


# @testable false
# @covered-by runner/icons.py::update_icons
# @reason network transport is isolated behind tested response parsing
def _download(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read()


# @testable true
# @tests tests_tooling/test_icons.py::test_update_icons_writes_official_subset_metadata_and_rebuilds
def _font_url(css):
    match = FONT_URL_RE.search(css)
    if not match:
        raise ValueError(
            "Google Fonts CSS did not contain a Material Symbols WOFF2 URL"
        )
    return match.group(1)


# @testable true
# @tests tests_tooling/test_icons.py::test_update_icons_writes_official_subset_metadata_and_rebuilds
def _write_subset(font, css_url, font_url, icon_names, font_path, metadata_path):
    if not font.startswith(b"wOF2"):
        raise ValueError("Google Fonts response is not a WOFF2 font")

    font_path = Path(font_path)
    metadata_path = Path(metadata_path)
    font_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    font_path.write_bytes(font)

    version = parse_qs(urlparse(font_url).query).get("v", ["unknown"])[0]
    metadata = {
        "family": "Material Symbols Rounded",
        "source_css_url": css_url,
        "upstream_version": version,
        "axes": {
            "opsz": 24,
            "wght": "300..600",
            "FILL": "0..1",
            "GRAD": 0,
        },
        "icon_names": icon_names,
        "sha256": hashlib.sha256(font).hexdigest(),
    }
    payload = json.dumps(metadata, indent="\t")
    metadata_path.write_text(f"{payload}\n", encoding="utf-8")


# @testable true
# @tests tests_tooling/test_icons.py::test_update_icons_writes_official_subset_metadata_and_rebuilds
def update_icons(
    *,
    rebuild=True,
    icons_path=ICONS_PATH,
    font_path=FONT_PATH,
    metadata_path=METADATA_PATH,
):
    css_url, icon_names = subset_request(icons_path)
    css = _download(css_url).decode("utf-8")
    font_url = _font_url(css)
    font = _download(font_url)
    _write_subset(
        font,
        css_url,
        font_url,
        icon_names,
        font_path,
        metadata_path,
    )
    print(
        f"Updated Material Symbols Rounded with {len(icon_names)} glyphs "
        f"({len(font):,} bytes)"
    )
    if rebuild:
        run_command([NPM_CLI, "run", "dev"], check=True)
