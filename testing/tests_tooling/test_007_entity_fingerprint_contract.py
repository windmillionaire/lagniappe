"""Repository contract for server-rendered durable entity anchors."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TAG_WITH_ENTITY = re.compile(r"<(?:(?!>).)*\blp-entity\b(?:(?!>).)*>", re.DOTALL)


def test_server_rendered_lp_entities_declare_fingerprints():
    missing = []
    templates = REPO_ROOT / "lagniappe" / "web" / "templates"
    for path in templates.rglob("*.html"):
        relative = path.relative_to(REPO_ROOT)
        for match in TAG_WITH_ENTITY.finditer(path.read_text()):
            if "data-fingerprint" not in match.group():
                line = path.read_text()[: match.start()].count("\n") + 1
                missing.append(f"{relative}:{line}")

    assert missing == [], "lp-entity tags missing data-fingerprint: " + ", ".join(missing)


def test_edited_form_markers_cover_update_forms_with_focused_routes():
    templates = REPO_ROOT / "lagniappe" / "web" / "templates"
    calls = []
    for path in templates.rglob("*.html"):
        for line in path.read_text().splitlines():
            if "controls.edited_marker(" not in line:
                continue
            argument = line.split("controls.edited_marker(", 1)[1].rsplit(")", 1)[0]
            calls.append((path.relative_to(templates).as_posix(), argument.strip()))

    assert len(calls) == 12
    assert all(argument for _, argument in calls)
    task_calls = [argument for path, argument in calls if path == "pages/tasks.html"]
    assert task_calls == [
        "url_for('tasks.get', key=t.urlsafe_key)",
        "url_for('tasks.settings', key=t.urlsafe_key)",
    ]
    assert (
        "categories/tools.html",
        "url_for('categories.info', key=category.urlsafe_key)",
    ) in calls

    controls = (templates / "controls.html").read_text()
    assert "{% macro edited_marker(route) %}" in controls
    assert 'data-edited-route="{{ route }}"' in controls
    assert 'data-role="edited-reset"' in controls
    assert "edited-reload" not in controls
