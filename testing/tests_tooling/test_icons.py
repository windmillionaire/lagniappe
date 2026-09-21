"""Tooling tests for the public Material Symbols subset refresh."""

import hashlib
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
    assert metadata == {
        "family": "Material Symbols Rounded",
        "source_css_url": downloads[0],
        "upstream_version": "v363",
        "axes": {
            "opsz": 24,
            "wght": "300..600",
            "FILL": "0..1",
            "GRAD": 0,
        },
        "icon_names": ["draft", "list_alt"],
        "sha256": hashlib.sha256(b"wOF2official-font").hexdigest(),
    }
    assert downloads[1] == font_url
    assert commands == [([icons.NPM_CLI, "run", "dev"], {"check": True})]


@pytest.fixture
def icon_refresh(tmp_path, monkeypatch):
    from runner import icons

    paths = {
        "icons_path": tmp_path / "icons.yaml",
        "font_path": tmp_path / "symbols.woff2",
        "metadata_path": tmp_path / "symbols.json",
    }
    paths["icons_path"].write_text("page:\n  glyph: draft\n  fill: 1\n")
    paths["font_path"].write_bytes(b"previous-font")
    paths["metadata_path"].write_bytes(b"previous-metadata")
    downloads = []

    def download(url):
        downloads.append(url)
        if url.startswith(icons.GOOGLE_FONTS_CSS_URL):
            return b"src: url(https://fonts.gstatic.com/subset.woff2?v=v363)"
        return b"wOF2refreshed-font"

    monkeypatch.setattr(icons, "_download", download)
    monkeypatch.setattr(
        icons, "run_command", lambda *args, **kwargs: pytest.fail("unexpected build")
    )
    return icons, paths, downloads


# @source runner/icons.py::subset_request
# @source runner/icons.py::update_icons
# @pairs icons:subset-request icons:subset-update
@pytest.mark.parametrize("rebuild", [False, True])
@pytest.mark.parametrize(
    "registry",
    [
        {"page": {"glyph": "draft"}},
        {"bad-id": {"glyph": "draft", "fill": 1}},
        {"page": {"glyph": "Bad Glyph", "fill": 1}},
        {"page": {"glyph": "draft", "fill": True}},
        {"page": {"glyph": "draft", "fill": 1, "weight": 200}},
        {"page": {"glyph": "draft", "fill": 1, "spin": "yes"}},
        {"page": {"glyph": "draft", "fill": 1, "extra": "field"}},
    ],
    ids=["missing-fill", "invalid-id", "invalid-glyph", "invalid-fill",
         "invalid-weight", "invalid-spin", "unknown-field"],
)
def test_icon_refresh_rejects_invalid_registry_before_io(icon_refresh, registry, rebuild):
    icons, paths, downloads = icon_refresh
    paths["icons_path"].write_text(yaml.safe_dump(registry))
    before = {path: path.read_bytes() for path in paths.values()}

    with pytest.raises((TypeError, ValueError)):
        icons.update_icons(**paths, rebuild=rebuild)

    assert downloads == []
    assert {path: path.read_bytes() for path in paths.values()} == before
    assert set(paths["icons_path"].parent.iterdir()) == set(paths.values())


# @source runner/icons.py::_font_url
# @source runner/icons.py::_write_subset
# @source runner/icons.py::update_icons
# @pair icons:subset-update
@pytest.mark.parametrize("failure", ["css-download", "css-url", "font-download", "font-format"])
def test_icon_refresh_preserves_files_on_download_or_format_failure(
    icon_refresh, monkeypatch, failure
):
    icons, paths, _ = icon_refresh
    before = {path: path.read_bytes() for path in paths.values()}
    download = icons._download

    def failed_download(url):
        is_css = url.startswith(icons.GOOGLE_FONTS_CSS_URL)
        if failure == ("css-download" if is_css else "font-download"):
            raise OSError("download unavailable")
        if is_css and failure == "css-url":
            return b"@font-face {}"
        if not is_css and failure == "font-format":
            return b"not-a-font"
        return download(url)

    monkeypatch.setattr(icons, "_download", failed_download)
    with pytest.raises((OSError, ValueError)):
        icons.update_icons(**paths)

    assert {path: path.read_bytes() for path in paths.values()} == before
    assert set(paths["icons_path"].parent.iterdir()) == set(paths.values())


# @source runner/icons.py::_write_subset
# @source runner/icons.py::update_icons
# @pair icons:subset-update
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["stage-metadata", "publish-font", "publish-metadata"])
def test_icon_refresh_restores_pair_on_publication_failure(
    icon_refresh, monkeypatch, existing, failure
):
    icons, paths, _ = icon_refresh
    if not existing:
        paths["font_path"].unlink()
        paths["metadata_path"].unlink()
    root = paths["icons_path"].parent
    before = {path: path.read_bytes() for path in root.iterdir()}
    write_bytes, replace = Path.write_bytes, Path.replace

    def failed_write(path, content):
        if failure == "stage-metadata" and path.name == "new" and content.startswith(b"{"):
            raise OSError("injected publication failure")
        return write_bytes(path, content)

    def failed_replace(path, target):
        failed_target = (
            paths["font_path"] if failure == "publish-font" else paths["metadata_path"]
        )
        if failure.startswith("publish-") and path.name == "new" and target == failed_target:
            if failure == "publish-metadata":
                assert paths["font_path"].read_bytes() == b"wOF2refreshed-font"
            raise OSError("injected publication failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "write_bytes", failed_write)
    monkeypatch.setattr(Path, "replace", failed_replace)
    with pytest.raises(OSError, match="injected publication failure"):
        icons.update_icons(**paths)

    assert {path: path.read_bytes() for path in root.iterdir()} == before


# @source runner/icons.py::_write_subset
# @pair icons:subset-update
def test_icon_refresh_retains_recovery_files_if_restoration_fails(icon_refresh, monkeypatch):
    icons, paths, _ = icon_refresh
    replace = Path.replace

    def failed_replace(path, target):
        if target == paths["metadata_path"] or path.name == "previous":
            raise OSError("destination unavailable")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", failed_replace)
    with pytest.raises(RuntimeError, match="restoration was incomplete") as error:
        icons.update_icons(**paths)

    recovery_dirs = [path for path in paths["icons_path"].parent.iterdir() if path.is_dir()]
    assert recovery_dirs
    assert all(str(path) in str(error.value) for path in recovery_dirs)
    preserved = {path.read_bytes() for directory in recovery_dirs for path in directory.iterdir()}
    assert {b"previous-font", b"previous-metadata"} <= preserved
    assert paths["metadata_path"].read_bytes() == b"previous-metadata"


# @source runner/icons.py::update_icons
# @pair icons:subset-update
def test_icon_refresh_keeps_published_pair_when_rebuild_fails(icon_refresh, monkeypatch, capsys):
    icons, paths, _ = icon_refresh

    def failed_build(command, **kwargs):
        assert command == [icons.NPM_CLI, "run", "dev"]
        assert kwargs == {"check": True}
        assert paths["font_path"].read_bytes() == b"wOF2refreshed-font"
        metadata = json.loads(paths["metadata_path"].read_text())
        assert metadata["sha256"] == hashlib.sha256(b"wOF2refreshed-font").hexdigest()
        raise RuntimeError("frontend build failed")

    monkeypatch.setattr(icons, "run_command", failed_build)
    with pytest.raises(RuntimeError, match="frontend build failed"):
        icons.update_icons(**paths)

    assert paths["font_path"].read_bytes() == b"wOF2refreshed-font"
    assert json.loads(paths["metadata_path"].read_text())["icon_names"] == ["draft"]
    assert set(paths["icons_path"].parent.iterdir()) == set(paths.values())
    output = capsys.readouterr().out
    assert "retained" in output
    assert str(paths["font_path"]) in output
    assert str(paths["metadata_path"]) in output
