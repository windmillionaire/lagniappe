"""Tooling tests for the public Material Symbols subset refresh."""

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]
TOGGLE_ICON_WRAPPER = re.compile(
    r"<span\b[^>]*styles\.toggle\.icon[^>]*>\s*{{\s*render_icon\(",
    re.DOTALL,
)


def test_material_icons_are_direct_children_of_icon_only_controls():
    templates = REPO_ROOT / "lagniappe" / "web" / "templates"
    wrappers = []
    for path in templates.rglob("*.html"):
        source = path.read_text()
        for match in TOGGLE_ICON_WRAPPER.finditer(source):
            line = source[: match.start()].count("\n") + 1
            wrappers.append(f"{path.relative_to(REPO_ROOT)}:{line}")

    styles = yaml.safe_load((REPO_ROOT / "src/style/styles.yaml").read_text())
    layout_classes = {
        token
        for definition in styles["toggle"]["icon"].values()
        for token in definition["classes"].split()
        if token in {"grid", "inline-grid", "place-items-center"}
    }

    assert wrappers == [], "redundant toggle icon wrappers: " + ", ".join(wrappers)
    assert layout_classes == set()


# @pair icons:subset-request
def test_material_symbol_subset_request_uses_unique_sorted_registry_glyphs(tmp_path):
    from runner import icons

    icons_path = tmp_path / "icons.yaml"
    icons_path.write_text(
        yaml.safe_dump(
            {
                "page": {"glyph": "draft", "fill": 1},
                "star": {
                    "active": {"glyph": "star", "fill": 1},
                    "inactive": {"glyph": "star", "fill": 0},
                },
                "plus": {"glyph": "add_2", "fill": 1, "weight": 600},
            },
            sort_keys=False,
        )
    )

    url, icon_names = icons.subset_request(icons_path)
    query = parse_qs(urlparse(url).query)

    assert icon_names == ["add_2", "draft", "star"]
    assert query["icon_names"] == ["add_2,draft,star"]
    assert query["family"] == [icons.FONT_FAMILY_QUERY]


# @pair icons:subset-update
def test_update_icons_writes_official_subset_metadata_and_rebuilds(
    tmp_path, monkeypatch
):
    from runner import icons

    icons_path = tmp_path / "icons.yaml"
    font_path = tmp_path / "material-symbols-rounded.woff2"
    metadata_path = tmp_path / "material-symbols-rounded.json"
    icons_path.write_text(
        "page:\n  glyph: draft\n  fill: 1\nproject:\n  glyph: list_alt\n  fill: 0\n"
    )
    font_url = (
        "https://fonts.gstatic.com/l/font?kit=official-subset&skey=rounded&v=v363"
    )
    downloads = []

    def download(url):
        downloads.append(url)
        if url.startswith(icons.GOOGLE_FONTS_CSS_URL):
            return (
                "@font-face { font-family: 'Material Symbols Rounded'; "
                f"src: url({font_url}) format('woff2'); }}"
            ).encode()
        return b"wOF2official-font"

    commands = []
    monkeypatch.setattr(icons, "_download", download)
    monkeypatch.setattr(
        icons,
        "run_command",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )

    icons.update_icons(
        icons_path=icons_path,
        font_path=font_path,
        metadata_path=metadata_path,
    )

    metadata = json.loads(metadata_path.read_text())
    assert font_path.read_bytes() == b"wOF2official-font"
    assert metadata["upstream_version"] == "v363"
    assert metadata["axes"]["wght"] == "300..600"
    assert metadata["axes"]["FILL"] == "0..1"
    assert metadata["icon_names"] == ["draft", "list_alt"]
    assert metadata["source_css_url"] == downloads[0]
    assert downloads[1] == font_url
    assert commands == [([icons.NPM_CLI, "run", "dev"], {"check": True})]
